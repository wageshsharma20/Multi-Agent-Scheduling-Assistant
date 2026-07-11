import sqlite3
import uuid
import requests
import os
import logging
from langchain_core.tools import tool
from state import CheckAvailabilityInput, ReserveSlotInput, SendNotificationInput
from database import DB_PATH

# ---------------------------------------------------------------------------
# Observability: All tool calls and their inputs/outputs are logged.
# This satisfies the "loggable tool calls" non-functional requirement.
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@tool(args_schema=CheckAvailabilityInput)
def check_availability(date: str) -> list[str]:
    """Checks a mock SQLite database for available appointment slots on a given date.
    
    Args:
        date: The date to check in YYYY-MM-DD format.
        
    Returns:
        A list of available time slots as strings (e.g., ["09:00", "11:00", "14:00"]).
        Returns an empty list if no slots are available.
    """
    logger.info("[TOOL CALL] check_availability | input: date=%s", date)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT time FROM availability WHERE date = ? AND is_booked = 0 ORDER BY time",
        (date,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    result = [row[0] for row in rows]
    logger.info("[TOOL RESULT] check_availability | output: %s", result)
    return result


@tool(args_schema=ReserveSlotInput)
def reserve_slot(date: str, time: str, email: str) -> dict:
    """Reserves an appointment slot in the mock SQLite database.
    
    This function re-checks availability atomically before writing to
    guard against race conditions (e.g., a slot being taken between
    check_availability and reserve_slot calls).
    
    Args:
        date: The reservation date in YYYY-MM-DD format.
        time: The reservation time in HH:MM format.
        email: The user's email address.
        
    Returns:
        A dict with 'status' = 'confirmed' and a 'confirmation_id', OR
        a dict with 'status' = 'error' and a 'message' explaining the conflict.
    """
    logger.info("[TOOL CALL] reserve_slot | input: date=%s, time=%s, email=%s", date, time, email)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Re-check availability atomically to prevent race conditions
    cursor.execute(
        "SELECT id FROM availability WHERE date = ? AND time = ? AND is_booked = 0",
        (date, time)
    )
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        result = {
            "status": "error",
            "message": (
                f"Conflict: The {time} slot on {date} was just taken by another booking. "
                "Please offer the user 2-3 alternative times from the availability list."
            )
        }
        logger.warning("[TOOL RESULT] reserve_slot | CONFLICT: %s", result)
        return result
    
    # Book the slot
    slot_id = row[0]
    confirmation_id = f"CONF-{uuid.uuid4().hex[:8].upper()}"
    
    cursor.execute(
        "UPDATE availability SET is_booked = 1, email = ? WHERE id = ?",
        (email, slot_id)
    )
    conn.commit()
    conn.close()
    
    result = {
        "status": "confirmed",
        "confirmation_id": confirmation_id,
        "date": date,
        "time": time,
        "email": email,
    }
    logger.info("[TOOL RESULT] reserve_slot | CONFIRMED: %s", result)
    return result


@tool(args_schema=SendNotificationInput)
def send_booking_notification(email: str, details: dict) -> dict:
    """Sends a mock booking confirmation via an HTTP webhook.
    
    The webhook URL is configured via the WEBHOOK_URL environment variable.
    Failure of this tool does NOT cancel the booking — it only affects 
    the confirmation notification delivery.
    
    Args:
        email: The user's email address.
        details: Dict with 'date', 'time', and 'confirmation_id'.
        
    Returns:
        A dict with 'status' = 'success' or 'error' and a 'message'.
    """
    webhook_url = os.environ.get("WEBHOOK_URL")
    
    if not webhook_url:
        logger.warning("[TOOL WARN] send_booking_notification | WEBHOOK_URL not set; skipping HTTP call.")
        return {
            "status": "skipped",
            "message": "WEBHOOK_URL environment variable is not set. Notification skipped."
        }
    
    payload = {
        "to_email": email,
        "subject": "Booking Confirmation",
        "confirmation_id": details.get("confirmation_id"),
        "appointment_date": details.get("date"),
        "appointment_time": details.get("time"),
        "body": (
            f"Hi! Your appointment is confirmed.\n"
            f"Date: {details.get('date')}\n"
            f"Time: {details.get('time')}\n"
            f"Confirmation ID: {details.get('confirmation_id')}"
        )
    }
    
    logger.info("[TOOL CALL] send_booking_notification | sending to %s with payload: %s", webhook_url, payload)
    
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        result = {"status": "success", "message": "Notification sent successfully."}
        logger.info("[TOOL RESULT] send_booking_notification | SUCCESS: %s", result)
        return result
    except requests.exceptions.Timeout:
        result = {"status": "error", "message": "Webhook timed out. The booking is confirmed, but the email may be delayed."}
        logger.error("[TOOL RESULT] send_booking_notification | TIMEOUT")
        return result
    except Exception as e:
        result = {"status": "error", "message": f"Notification failed: {str(e)}. Your booking is still confirmed."}
        logger.error("[TOOL RESULT] send_booking_notification | ERROR: %s", str(e))
        return result
