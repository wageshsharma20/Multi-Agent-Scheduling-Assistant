import sqlite3
from datetime import datetime, timedelta
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule.db")

# Standard mock slots available each working day
MOCK_SLOTS = ["09:00", "10:00", "11:00", "14:00", "15:00", "16:00"]
# Pre-seed window: generate slots for the next 30 days
SEED_DAYS = 30


def init_db():
    """Initializes the database schema and seeds mock availability.
    
    Also handles stale seed data: if the earliest date in the DB is in the past,
    it seeds fresh dates for the next SEED_DAYS from today.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create the availability table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS availability (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            is_booked BOOLEAN DEFAULT 0,
            email TEXT,
            UNIQUE(date, time)
        )
    ''')

    # Check if we need to (re)seed:
    # Seed if there are no future dates in the DB.
    today_str = datetime.now().strftime("%Y-%m-%d")
    cursor.execute(
        "SELECT COUNT(*) FROM availability WHERE date >= ? AND is_booked = 0",
        (today_str,)
    )
    future_count = cursor.fetchone()[0]

    if future_count == 0:
        seed_data(cursor)

    conn.commit()
    conn.close()


def seed_data(cursor):
    """Seeds mock availability for the next SEED_DAYS days starting from today.
    
    Uses INSERT OR IGNORE so re-seeding is safe and idempotent — it won't
    duplicate rows that already exist (e.g., future dates from a prior seed).
    
    Some slots are intentionally pre-booked to allow testing the negotiation flow:
    - 10:00 is pre-booked on every other day (even day offsets)
    """
    today = datetime.now()
    for i in range(SEED_DAYS):
        date_str = (today + timedelta(days=i)).strftime("%Y-%m-%d")
        for time_str in MOCK_SLOTS:
            # Pre-book 10:00 on even-offset days so negotiation flow is testable
            is_booked = 1 if time_str == "10:00" and i % 2 == 0 else 0
            cursor.execute(
                "INSERT OR IGNORE INTO availability (date, time, is_booked) VALUES (?, ?, ?)",
                (date_str, time_str, is_booked)
            )


if __name__ == "__main__":
    init_db()
    print(f"Database initialized. Path: {DB_PATH}")
