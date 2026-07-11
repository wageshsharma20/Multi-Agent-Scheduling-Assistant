# 📅 Multi-Agent Scheduling Assistant

A conversational appointment-booking assistant built with **LangGraph**, **Groq (Llama 3 8B)**, and **Streamlit**. It demonstrates a clean multi-agent architecture where a **Triage Agent** handles intent classification and a **Booking Specialist** manages the full transactional booking workflow — including date normalization, tool calling, conflict negotiation, and mock webhook notifications. The application features a sleek dark-mode UI with a top-level status dashboard for real-time observability.

> **Live Demo:** *(https://multi-agent-scheduling-assistant.streamlit.app/)*

---

## 🗺️ Graph Topology

```
User Message
     │
     ▼
┌──────────────────┐
│   Triage Agent   │  ← No tools. Classifies intent only.
│  (triage_node)   │
└────────┬─────────┘
         │
         ├── "general" ──────────────────────► END (responds directly)
         │
         └── "scheduling" ──────────────────► ┌────────────────────────────┐
                                               │    Booking Specialist      │
                                               │  (booking_specialist_node) │
                                               │                            │
                                               │  • Injects current date    │
                                               │  • Enforces 5 rules:       │
                                               │    1. Date normalization    │
                                               │    2. Collect all fields   │
                                               │    3. Check before reserve │
                                               │    4. Negotiate conflicts  │
                                               │    5. Notify after booking │
                                               └────────────┬───────────────┘
                                                            │
                                          tool_calls?  yes  │
                                                            ▼
                                               ┌────────────────────────────┐
                                               │   ToolNode (tools)         │
                                               │  Executes one of:          │
                                               │  • check_availability()    │
                                               │  • reserve_slot()          │
                                               │  • send_booking_notif...() │
                                               └────────────┬───────────────┘
                                                            │
                                                            ▼
                                               ┌────────────────────────────┐
                                               │   update_slot              │
                                               │  (update_slot_after_tools) │
                                               │  Parses ToolMessage output │
                                               │  Updates slot.status,      │
                                               │  confirmation_id, etc.     │
                                               └────────────┬───────────────┘
                                                            │
                                                            └──── loops back ──► Booking Specialist
                                                                                      │
                                                                              no tool_calls
                                                                                      │
                                                                                      ▼
                                                                                    END

Every node read/writes GraphState. After every turn, the FULL state
(messages + slot) is checkpointed to checkpoints.sqlite via SqliteSaver,
keyed by thread_id — so conversations survive browser refreshes.
```

---

## 🤖 Agent Architecture

### Triage Agent (`triage_node`)
- Receives the user's raw message
- Uses the Groq LLM to classify intent as `"general"` or `"scheduling"`  
- **If general:** responds directly in natural language, graph ends the turn (`→ END`)
- **If scheduling:** sets `intent = "scheduling"`, graph routes to Booking Specialist
- Has **no tool access** — cannot call `check_availability`, `reserve_slot`, or `send_booking_notification`
- Uses structured JSON output (`{"intent": ..., "response": ...}`) so routing decisions are code-level, not free-text guessing

### Booking Specialist (`booking_specialist_node`)
- Owns all three tools
- **Date Normalization:** The current date/time is injected into its system prompt on every call. The LLM is explicitly forbidden from passing relative expressions like "tomorrow" or "Friday" to any tool. It must compute the absolute `YYYY-MM-DD` from the injected date.
- **Missing Field Prompting:** Before calling `reserve_slot`, it must have all three of: `date`, `time`, `email`. If any are missing, it asks for specifically the missing one — not a generic "please provide more details".
- **Negotiation Loop:** If `check_availability` returns the requested time as unavailable, it offers 2–3 concrete alternatives. If `reserve_slot` returns a conflict, it re-queries availability and re-offers alternatives.
- **Notification Decoupling:** `send_booking_notification` failure does not cancel the booking. The agent informs the user the booking is confirmed but the email may be delayed.

---

## 🔧 Tool Contracts

### `check_availability(date: str) → list[str]`
| Field | Detail |
|---|---|
| Input | `date` in `YYYY-MM-DD` format |
| Output | List of open time strings, e.g. `["09:00", "11:00", "14:00"]`. Empty list if fully booked. |
| Data source | `schedule.db` SQLite (shared with `reserve_slot`) |
| Side effects | None — read-only |

### `reserve_slot(date: str, time: str, email: str) → dict`
| Field | Detail |
|---|---|
| Input | `date` (YYYY-MM-DD), `time` (HH:MM), `email` |
| Success output | `{"status": "confirmed", "confirmation_id": "CONF-XXXXXXXX", "date": ..., "time": ..., "email": ...}` |
| Conflict output | `{"status": "error", "message": "Conflict: slot was just taken..."}` |
| Race condition guard | Re-checks `is_booked = 0` atomically before the `UPDATE` write |
| Data source | `schedule.db` SQLite |

### `send_booking_notification(email: str, details: dict) → dict`
| Field | Detail |
|---|---|
| Input | `email`, `details` dict with `date`, `time`, `confirmation_id` |
| Success output | `{"status": "success", "message": "Notification sent successfully."}` |
| Failure output | `{"status": "error", "message": "...reason..."}` |
| No-URL output | `{"status": "skipped", "message": "WEBHOOK_URL not set..."}` |
| Endpoint | Configured via `WEBHOOK_URL` env var (see setup below) |
| Timeout | 10 seconds; timeout errors are caught and returned gracefully |

> **Observability:** Every tool call and its result is logged to stdout:
> ```
> 2026-07-11 [INFO] tools: [TOOL CALL] check_availability | input: date=2026-07-12
> 2026-07-11 [INFO] tools: [TOOL RESULT] check_availability | output: ['09:00', '11:00', '14:00', '15:00']
> ```

---

## 📂 Project Structure

```
scheduling_assistant/
├── app.py                   # Streamlit UI — application entry point
├── graph.py                 # LangGraph state machine: nodes, edges, SqliteSaver
├── agents.py                # System prompts for Triage Agent & Booking Specialist
├── tools.py                 # @tool definitions: check_availability, reserve_slot, send_booking_notification
├── state.py                 # GraphState TypedDict, SlotDetails TypedDict, Pydantic tool schemas
├── database.py              # SQLite schema, mock data seeder, stale-date refresh logic
├── .streamlit/
│   └── config.toml          # Headless server config for cloud deployment
├── requirements.txt         # Pinned Python dependencies
├── .env.example             # Template for required environment variables
└── .gitignore               # Excludes .env, *.db, *.sqlite, __pycache__, etc.
```

---

## 🗃️ State Persistence Design

State persistence is powered by LangGraph's **`SqliteSaver`** checkpointer backed by `checkpoints.sqlite`.

**Flow:**
1. On first page load, `app.py` generates a UUID and writes it to the URL as `?thread_id=<uuid>`
2. Every subsequent page load (including refreshes) reads `thread_id` from the URL
3. `compiled_graph.get_state(config)` fetches the full serialized state from `checkpoints.sqlite`
4. The Streamlit UI replays all historical messages before rendering the chat input box

**Why URL params instead of `st.session_state`?** Streamlit's `session_state` is cleared on browser refresh. URL query parameters survive refreshes, making them the correct mechanism for client-side thread retention.

---

## 🚀 Local Setup

**Prerequisites:** Python 3.11+

```bash
# 1. Clone the repository
git clone <your-github-repo-url>
cd scheduling_assistant

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# .\venv\Scripts\activate       # Windows PowerShell

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables (see section below for how to get these)
cp .env.example .env
# Edit .env and fill in GROQ_API_KEY and WEBHOOK_URL

# 5. Run the application
streamlit run app.py
```

The app opens at `http://localhost:8501`.

---


---



## 🧪 Testing Scenarios

| Scenario | Test Input | Expected Behaviour |
|---|---|---|
| **General query** | "Hello, what can you do?" | Triage Agent responds directly. No tools called. |
| **Happy path** | "Book me for tomorrow at 9am, my email is test@example.com" | Agent resolves date → `check_availability` → `reserve_slot` → `send_booking_notification` → confirms with ID |
| **Missing info** | "Book me for tomorrow" | Agent asks specifically for time AND email (not a generic prompt) |
| **Unavailable time** | Request 10:00 on an even-offset day (pre-booked) | Agent offers 2–3 alternatives from the available list |
| **Race condition** | Book the same slot in two browser tabs | Second `reserve_slot` returns conflict; agent negotiates alternatives |
| **Webhook failure** | Set `WEBHOOK_URL` to an invalid URL | Booking still confirmed; agent says email may be delayed |
| **Refresh persistence** | Start a booking, refresh the browser tab | Full chat history reloads from SQLite checkpointer |

---

## 🔐 Security

- No API keys committed to the repository
- `.gitignore` excludes `.env`, `*.sqlite`, `*.db`, and `__pycache__`
- `.env.example` contains only placeholder values
- All secrets are configured via environment variables / hosting platform secrets manager

---

## 🛠️ Tech Stack

| Component | Technology |
|---|---|
| Multi-agent orchestration | LangGraph 0.2.x (`StateGraph`, `ToolNode`, conditional edges) |
| LLM | Groq API — Llama 3 8B (`langchain-groq`) |
| State persistence | LangGraph `SqliteSaver` → `checkpoints.sqlite` |
| Mock availability store | SQLite (`schedule.db`) — shared by `check_availability` & `reserve_slot` |
| Mock notification | HTTP POST webhook (webhook.site) |
| UI | Streamlit 1.44 |
| Deployment | Streamlit |
| Python | 3.11+ |
