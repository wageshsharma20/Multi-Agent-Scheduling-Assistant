from typing import TypedDict, Literal, Annotated, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class SlotDetails(TypedDict, total=False):
    """Tracks the extracted entities required for a booking.
    
    All fields are optional (total=False) because they are filled in
    progressively as the Booking Specialist gathers information from the user.
    """
    date: str               # Must be normalized to YYYY-MM-DD
    time: str               # Format HH:MM (24-hour)
    email: str              # User's email address
    status: str             # "collecting" | "checking" | "reserved" | "failed"
    confirmation_id: Optional[str]  # Set after successful reserve_slot


def default_slot() -> SlotDetails:
    """Returns a fresh, empty SlotDetails dict."""
    return SlotDetails(status="collecting")


class GraphState(TypedDict):
    """The core state object for the LangGraph workflow.
    
    This is passed between every node in the graph. Each node returns
    a partial dict with only the keys it modifies; LangGraph merges
    the returned dict back into the full state.
    """
    # add_messages is a reducer that APPENDS new messages rather than overwriting.
    # This is critical: returning {"messages": [new_msg]} will ADD to the list,
    # not replace it.
    messages: Annotated[list[BaseMessage], add_messages]

    # Routing signal set by the Triage node
    intent: Literal["general", "scheduling", "unclassified"]

    # Structured booking details, progressively filled in
    slot: SlotDetails


# ---------------------------------------------------------------------------
# Pydantic Schemas for Tool Inputs
# ---------------------------------------------------------------------------
# These schemas are attached to each @tool via args_schema=...
# They force the LLM to provide correctly-typed arguments and give the model
# a clear description of what each field must look like.

class CheckAvailabilityInput(BaseModel):
    date: str = Field(
        description=(
            "The date to check for available slots, strictly in YYYY-MM-DD format. "
            "NEVER pass relative dates like 'tomorrow' or 'next week'. "
            "You must resolve any relative date to an absolute date first."
        )
    )


class ReserveSlotInput(BaseModel):
    date: str = Field(description="The reservation date in YYYY-MM-DD format.")
    time: str = Field(description="The reservation time in HH:MM format (24-hour clock).")
    email: str = Field(description="The user's email address for the booking confirmation.")


class SendNotificationInput(BaseModel):
    email: str = Field(description="The user's email address.")
    details: dict = Field(
        description=(
            "A dictionary containing booking confirmation details. "
            "Must include 'date' (YYYY-MM-DD), 'time' (HH:MM), and 'confirmation_id'."
        )
    )
