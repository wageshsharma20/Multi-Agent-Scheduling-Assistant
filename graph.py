"""graph.py — LangGraph State Machine Definition

This module defines the two-agent workflow:
  triage_node        → Classifies intent (general vs. scheduling)
  booking_specialist → Manages the booking flow with tool access
  tools              → LangGraph ToolNode that executes tool calls

Routing:
  triage → (general) → END
  triage → (scheduling) → booking_specialist
  booking_specialist → (tool_calls present) → tools → booking_specialist
  booking_specialist → (no tool_calls) → END

State is persisted via SqliteSaver (LangGraph checkpointer) keyed by thread_id.
"""

import os
import ast
import json
import sqlite3
import logging
from datetime import datetime

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_groq import ChatGroq
from langchain_core.messages import AIMessage

from state import GraphState, default_slot
from agents import triage_prompt, get_booking_prompt
from tools import check_availability, reserve_slot, send_booking_notification

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tools list (used by ToolNode and LLM binding)
# ---------------------------------------------------------------------------
tools_list = [check_availability, reserve_slot, send_booking_notification]

# ---------------------------------------------------------------------------
# LLM Setup — Lazy-initialized to ensure load_dotenv() in app.py runs first.
# The _llm, triage_llm, and booking_llm objects are created on first use
# inside _get_llms(), not at module import time, so GROQ_API_KEY is always
# available when these are first called.
# ---------------------------------------------------------------------------
_triage_llm = None
_booking_llm = None

def _get_llms():
    """Lazy-initialize LLMs on first call to ensure env vars are loaded."""
    global _triage_llm, _booking_llm
    if _triage_llm is None or _booking_llm is None:
        _llm = ChatGroq(
            temperature=0,
            model_name="llama-3.3-70b-versatile",  # llama3-8b-8192 was decommissioned
            max_tokens=1024,
        )
        _triage_llm = _llm.bind(response_format={"type": "json_object"})
        _booking_llm = _llm.bind_tools(tools_list)
    return _triage_llm, _booking_llm


# ---------------------------------------------------------------------------
# Node Definitions
# ---------------------------------------------------------------------------

def triage_node(state: GraphState) -> dict:
    """Classifies the user's intent and either responds directly (general)
    or signals the graph to route to the Booking Specialist (scheduling).
    """
    triage_llm, _ = _get_llms()
    chain = triage_prompt | triage_llm
    response = chain.invoke({"messages": state["messages"]})

    try:
        result = json.loads(response.content)
        intent = result.get("intent", "unclassified")
        bot_response = result.get("response", "").strip()
    except (json.JSONDecodeError, AttributeError):
        logger.warning("Triage LLM returned non-JSON output; defaulting to general.")
        intent = "general"
        bot_response = "I'm here to help you schedule appointments. What would you like to do?"

    logger.info("[TRIAGE] classified intent = '%s'", intent)

    new_messages = []
    if intent == "general" and bot_response:
        new_messages.append(AIMessage(content=bot_response))

    return {
        "intent": intent,
        "messages": new_messages,
        # Initialize slot to collecting status on every new triage if not already set
        "slot": state.get("slot") or default_slot(),
    }


def booking_specialist_node(state: GraphState) -> dict:
    """Manages the full booking workflow: date normalization, missing-field prompting,
    tool calls, negotiation, and confirmation.
    
    The current datetime is injected dynamically so the LLM can always resolve
    relative dates correctly.
    """
    _, booking_llm = _get_llms()
    prompt = get_booking_prompt()
    chain = prompt | booking_llm

    current_datetime = datetime.now().strftime("%A, %B %d %Y, %I:%M %p (IST)")
    logger.info("[BOOKING] invoking specialist | current_datetime=%s", current_datetime)

    response = chain.invoke({
        "messages": state["messages"],
        "current_datetime": current_datetime,
    })

    logger.info(
        "[BOOKING] specialist response | has_tool_calls=%s",
        bool(getattr(response, "tool_calls", None))
    )

    # Update slot status based on tool call intent
    updated_slot = dict(state.get("slot") or default_slot())
    if getattr(response, "tool_calls", None):
        updated_slot["status"] = "checking"

    return {
        "messages": [response],
        "slot": updated_slot,
    }


def _parse_tool_content(content) -> dict:
    """Safely parse a ToolMessage content string into a dict.
    
    LangGraph's ToolNode serialises tool return values using Python's repr()
    (single-quoted strings), NOT json.dumps(). We therefore try json.loads
    first (handles double-quoted JSON) and fall back to ast.literal_eval
    (handles Python dict literals with single quotes).
    """
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return {}
    # Try strict JSON first
    try:
        result = json.loads(content)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass
    # Fall back to Python literal eval (handles repr output)
    try:
        result = ast.literal_eval(content)
        if isinstance(result, dict):
            return result
    except (ValueError, SyntaxError):
        pass
    return {}


def update_slot_after_tools(state: GraphState) -> dict:
    """Runs after the ToolNode to inspect tool results and update the slot state.
    
    This is a lightweight pass-through node that reads the last ToolMessage(s)
    and updates slot.status / slot.confirmation_id accordingly.
    
    IMPORTANT: LangGraph's ToolNode serialises tool return dicts via repr(),
    not json.dumps(). _parse_tool_content() handles both formats safely.
    """
    updated_slot = dict(state.get("slot") or default_slot())

    # Walk messages in reverse to find the most recent tool result messages
    for msg in reversed(state["messages"]):
        if msg.type == "tool":
            result = _parse_tool_content(msg.content)
            if result.get("status") == "confirmed":
                updated_slot["status"] = "reserved"
                updated_slot["confirmation_id"] = result.get("confirmation_id")
                updated_slot["date"] = result.get("date", updated_slot.get("date"))
                updated_slot["time"] = result.get("time", updated_slot.get("time"))
                logger.info(
                    "[SLOT] updated to 'reserved' | confirmation_id=%s",
                    updated_slot["confirmation_id"]
                )
            elif result.get("status") == "error":
                updated_slot["status"] = "failed"
                logger.warning(
                    "[SLOT] tool returned error | message=%s",
                    result.get("message")
                )
            break  # Only process the most recent tool message

    return {"slot": updated_slot}


# ---------------------------------------------------------------------------
# Graph Assembly
# ---------------------------------------------------------------------------

# 1. Initialize the graph with our state schema
workflow = StateGraph(GraphState)

# 2. Register nodes
workflow.add_node("triage", triage_node)
workflow.add_node("booking_specialist", booking_specialist_node)
workflow.add_node("tools", ToolNode(tools_list))
workflow.add_node("update_slot", update_slot_after_tools)

# 3. Entry point
workflow.set_entry_point("triage")

# 4. Conditional routing from Triage
def route_from_triage(state: GraphState) -> str:
    """Routes to booking_specialist for scheduling intent; ends turn for general."""
    if state.get("intent") == "scheduling":
        return "booking_specialist"
    return END

workflow.add_conditional_edges("triage", route_from_triage)

# 5. Conditional routing from Booking Specialist
def route_from_booking(state: GraphState) -> str:
    """Routes to tools node if LLM generated tool calls; otherwise ends turn."""
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "tools"
    return END

workflow.add_conditional_edges("booking_specialist", route_from_booking)

# 6. After tools execute, update slot state, then return to specialist for follow-up
workflow.add_edge("tools", "update_slot")
workflow.add_edge("update_slot", "booking_specialist")

# ---------------------------------------------------------------------------
# Compile with SQLite Checkpointer for Persistent State
# ---------------------------------------------------------------------------
_CHECKPOINT_DB = os.path.join(os.path.dirname(__file__), "checkpoints.sqlite")
_checkpoint_conn = sqlite3.connect(_CHECKPOINT_DB, check_same_thread=False)
memory = SqliteSaver(_checkpoint_conn)

# The compiled app is what app.py imports and invokes
app = workflow.compile(checkpointer=memory)

logger.info("LangGraph compiled successfully | checkpoint_db=%s", _CHECKPOINT_DB)
