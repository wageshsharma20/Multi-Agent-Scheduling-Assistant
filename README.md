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
├── render.yaml              # Render deployment blueprint
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

> ⚠️ **Known Limitation (Render Free Tier):** Render's free tier resets the disk on each new *deploy*. The SQLite files (`schedule.db`, `checkpoints.sqlite`) persist across requests during a running deployment session but are wiped if you push a new version. This is documented in the PRD as an acceptable known limitation. For production, replace `SqliteSaver` with a managed DB adapter (e.g., Supabase Postgres).

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

## 🔑 Getting Test Credentials (for Evaluators)

### GROQ_API_KEY
1. Visit [https://console.groq.com](https://console.groq.com)
2. Sign up for a free account (no credit card required)
3. Navigate to **API Keys → Create API Key**
4. Copy the key (starts with `gsk_...`) and paste it into `.env`:
   ```
   GROQ_API_KEY=gsk_your_key_here
   ```
The free tier provides ample request quota to evaluate the application end-to-end.

### WEBHOOK_URL (Mock Notification Endpoint)
1. Visit [https://webhook.site](https://webhook.site)
2. The page immediately generates a unique URL for you (e.g., `https://webhook.site/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)
3. Copy that URL and paste it into `.env`:
   ```
   WEBHOOK_URL=https://webhook.site/your-uuid-here
   ```
4. Keep the webhook.site tab open — you will see the HTTP POST request arrive in real time when a booking is confirmed.

> **Note:** The `WEBHOOK_URL` env var is optional for basic testing. If it is not set, `send_booking_notification` returns `status: "skipped"` gracefully and the booking is still fully confirmed. The agent will inform the user accordingly.

---

## ☁️ Deployment

### Render (Recommended)

Render provides containerized Python web services where the SQLite files persist for the lifetime of a deployment.

1. Push your code to a **public GitHub repository**
2. Go to [render.com](https://render.com) → **New → Web Service**
3. Connect your GitHub repo — Render will auto-detect `render.yaml`
4. Click **Apply** / **Deploy**
5. In the Render dashboard, go to **Environment** and set:
   - `GROQ_API_KEY` → your Groq key
   - `WEBHOOK_URL` → your webhook.site URL
6. Wait for deployment to complete, then visit the provided `.onrender.com` URL

> **Memory:** The app is designed to stay well under Render's **512MB free-tier limit**. LLM inference runs entirely on Groq's servers — the container only handles Streamlit requests, SQLite I/O, and lightweight HTTP calls.

### Vercel (Alternative — with Caveats)

> ⚠️ **Important:** Vercel is a serverless platform. Its filesystem is ephemeral between function invocations, meaning `checkpoints.sqlite` and `schedule.db` will reset frequently. The conversation persistence feature (FR-12) will not work reliably on Vercel without an external database. Vercel is acceptable for a quick demo but **Render is strongly recommended** for the full feature set.

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
| Deployment | Render (recommended) / Vercel (limited) |
| Python | 3.11+ |
