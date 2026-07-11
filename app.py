import streamlit as st
import uuid
import logging
import base64
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

# Load .env FIRST before any other imports that read env vars
load_dotenv()

from database import init_db
init_db()

from graph import app as compiled_graph

# ---------------------------------------------------------------------------
# Page Config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="ScheduleAI — Smart Booking Assistant",
    page_icon="📅",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Background Image Helper
# ---------------------------------------------------------------------------
@st.cache_data
def get_base64_image(image_path):
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()

bg_base64 = get_base64_image("bg.png")

# ---------------------------------------------------------------------------
# Custom CSS — Evolv AI Aesthetic (Minimalist Dark, Sharp Corners, Emerald)
# ---------------------------------------------------------------------------
# Background image is injected in a separate style block to avoid f-string curly brace conflicts
st.markdown(f"""
<style>
.stApp {{
    background-color: #000000;
    background-image: linear-gradient(rgba(0, 0, 0, 0.7), rgba(0, 0, 0, 0.8)), url("data:image/png;base64,{bg_base64}");
    background-size: cover;
    background-position: center;
    background-attachment: fixed;
    min-height: 100vh;
}}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<style>
/* ── Global Reset ── */
html, body, [class*="css"], h1, h2, h3, h4, h5, h6, p, span, div, button, input, textarea {
    font-family: 'Arial', sans-serif !important;
}

/* ── Hide Streamlit chrome ── */
#MainMenu, footer, header { visibility: hidden; }
.stDeployButton { display: none; }
[data-testid="stToolbar"] { display: none; }

/* ── Page background ── */
/* Handled in the dynamic style block above */

/* ── Hero header ── */
.hero {
    text-align: center;
    padding: 3rem 1rem 1rem;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    margin-bottom: 2rem;
}
.hero-title {
    font-family: 'Georgia', serif !important;
    font-size: 3.5rem !important;
    font-weight: 300;
    color: #ffffff;
    margin: 0;
    line-height: 1.1;
    letter-spacing: -0.02em;
}
.hero-sub {
    color: #a1a1aa;
    font-size: 1.25rem !important;
    margin-top: 1rem;
    font-weight: 400;
    max-width: 700px;
    margin-left: auto;
    margin-right: auto;
}

/* ── Chat container ── */
.suggestions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    justify-content: center;
    margin: 2rem 0;
}
/* ── Main Area Buttons (Suggestion Pills) ── */
section.main .stButton button {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    color: #d4d4d8 !important;
    font-size: 0.85rem !important;
    border-radius: 0px !important;
    padding: 0.5rem 1rem !important;
    transition: all 0.2s !important;
}
section.main .stButton button:hover {
    background: rgba(255,255,255,0.08) !important;
    border-color: rgba(255,255,255,0.2) !important;
    color: #ffffff !important;
}
section.main .stButton button p {
    font-size: 0.85rem !important;
}

/* ── Chat container ── */
[data-testid="stChatMessageContainer"] {
    padding: 0 0.5rem;
}

/* ── User message bubble ── */
[data-testid="stChatMessage"][data-testid*="human"] .stChatMessageContent,
div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stMarkdownContainer"] {
    background: rgba(255,255,255,0.08) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 0px !important;
    padding: 1rem 1.25rem !important;
    color: #ffffff !important;
    border-left: 3px solid #ffffff !important;
}

/* ── AI message bubble ── */
div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) [data-testid="stMarkdownContainer"] {
    background: rgba(255,255,255,0.02) !important;
    border: 1px solid rgba(255,255,255,0.05) !important;
    border-radius: 0px !important;
    padding: 1rem 1.25rem !important;
    color: #d4d4d8 !important;
    border-left: 3px solid #00BC7D !important;
}

/* ── Chat Avatars (Green Squares) ── */
[data-testid="stChatMessageAvatar"] {
    background-color: #00BC7D !important;
    border-radius: 0px !important;
    width: 12px !important;
    height: 12px !important;
    min-width: 12px !important;
    min-height: 12px !important;
    margin-top: 1.4rem !important; /* Align with the padded message bubble */
}
[data-testid="stChatMessageAvatar"] svg, [data-testid="stChatMessageAvatar"] img {
    display: none !important;
}

/* Make chat text bigger */
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {
    font-size: 1.1rem !important;
    line-height: 1.6 !important;
}

/* ── Chat input bar (PromptBox Style) ── */
/* Remove Streamlit's default solid background from the bottom container */
[data-testid="stBottomBlockContainer"], .stAppBottomBlock, [data-testid="stBottom"] {
    background: transparent !important;
    background-color: transparent !important;
}

[data-testid="stChatInput"] {
    background: #2f2f2f !important; /* ChatGPT true dark mode input color */
    border: 1px solid rgba(255,255,255,0.15) !important;
    border-radius: 1.5rem !important;
    color: #ffffff !important;
    padding: 0.25rem 0.5rem !important;
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.5), 0 4px 6px -2px rgba(0, 0, 0, 0.3) !important;
}
[data-testid="stChatInput"]:focus-within {
    border-color: rgba(255,255,255,0.4) !important;
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.5), 0 4px 6px -2px rgba(0, 0, 0, 0.3) !important;
}
[data-testid="stChatInput"] textarea {
    color: #ffffff !important;
}
[data-testid="stChatInput"] textarea::placeholder {
    color: #a1a1aa !important;
}

/* ── Send button ── */
[data-testid="stChatInputSubmitButton"] button {
    background: #ffffff !important;
    color: #212121 !important;
    border: none !important;
    border-radius: 50% !important;
    height: 2.2rem !important;
    width: 2.2rem !important;
    margin-right: 0.25rem !important;
    transition: all 0.2s;
}
[data-testid="stChatInputSubmitButton"] button:hover {
    background: #e4e4e7 !important;
}
[data-testid="stChatInputSubmitButton"] svg {
    fill: #212121 !important;
}

/* ── Success box ── */
[data-testid="stSuccess"] {
    background: rgba(0, 188, 125, 0.05) !important;
    border: 1px solid rgba(0, 188, 125, 0.2) !important;
    border-radius: 0px !important;
    border-left: 3px solid #00BC7D !important;
    color: #00BC7D !important;
}

/* ── Error box ── */
[data-testid="stError"] {
    background: rgba(239,68,68,0.05) !important;
    border: 1px solid rgba(239,68,68,0.2) !important;
    border-radius: 0px !important;
    border-left: 3px solid #ef4444 !important;
}

/* ── Spinner ── */
[data-testid="stSpinner"] {
    color: #00BC7D !important;
}

/* ── Thread badge ── */
.thread-badge {
    display: inline-flex;
    align-items: center;
    background: transparent;
    border: 1px solid rgba(255,255,255,0.1);
    color: #71717a;
    font-size: 0.65rem;
    font-family: monospace;
    padding: 0.25rem 0.75rem;
    margin-bottom: 1rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

/* ── Divider ── */
hr {
    border-color: rgba(255,255,255,0.1) !important;
    margin: 1.5rem 0 !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #181818 !important;
    border-right: 1px solid rgba(255,255,255,0.1) !important;
}
[data-testid="stSidebar"] * {
    color: #a1a1aa !important;
}
[data-testid="stSidebar"] h3 {
    color: #ffffff !important;
    font-weight: 400;
    letter-spacing: -0.02em;
}
[data-testid="stSidebar"] .stButton button {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
    color: #ffffff !important;
    border-radius: 0px !important;
    font-weight: 500;
    transition: all 0.2s;
}
[data-testid="stSidebar"] .stButton button:hover {
    background: rgba(255,255,255,0.1) !important;
    border-color: rgba(255,255,255,0.3) !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); }

/* ── Fade-in animation ── */
@keyframes fadeUp {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
}
[data-testid="stChatMessage"] {
    animation: fadeUp 0.3s ease both;
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Thread ID — persist via URL query params
# ---------------------------------------------------------------------------
if "thread_id" not in st.query_params:
    st.query_params["thread_id"] = str(uuid.uuid4())
thread_id = st.query_params["thread_id"]
config = {"configurable": {"thread_id": thread_id}}

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Evolv AI Agent")
    st.markdown("Automate workflows with an agent that plans, executes, and optimizes operations.")
    st.divider()
    st.markdown("""
<div style="font-size: 0.8rem; line-height: 1.6;">
<div style="display: flex; align-items: center; margin-bottom: 0.5rem;">
<span style="height: 4px; width: 4px; background-color: #00BC7D; display: inline-block; margin-right: 8px;"></span>
<strong>Triage Agent:</strong> Classifies intent
</div>
<div style="display: flex; align-items: center;">
<span style="height: 4px; width: 4px; background-color: #00BC7D; display: inline-block; margin-right: 8px;"></span>
<strong>Booking Specialist:</strong> Executes workflow
</div>
</div>
    """, unsafe_allow_html=True)
    st.divider()
    if st.button("Initialize New Session", use_container_width=True):
        st.query_params["thread_id"] = str(uuid.uuid4())
        st.rerun()
    st.markdown(f'<div class="thread-badge">SESSION ID: {thread_id[:8]}</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Hero Header
# ---------------------------------------------------------------------------
st.markdown("""
<div class="hero">
    <h1 class="hero-title">Schedule appointments<br/>autonomously</h1>
    <p class="hero-sub">Design, deploy, and scale specialized AI agents that plan, execute, and optimize work across your tools.</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Restore conversation history from LangGraph SQLite checkpointer
# ---------------------------------------------------------------------------
try:
    saved_state = compiled_graph.get_state(config)
    historical_messages = (
        saved_state.values.get("messages", [])
        if saved_state and saved_state.values else []
    )
except Exception:
    historical_messages = []

# Show suggestion pills only on empty conversations
suggestion_clicked = None
if not historical_messages:

    st.markdown('<div class="suggestions">', unsafe_allow_html=True)
    cols = st.columns(3, gap="small")
    if cols[0].button("Deploy agent for tomorrow at 2pm", use_container_width=True):
        suggestion_clicked = "Deploy agent for tomorrow at 2pm"
    if cols[1].button("Audit available slots for Friday", use_container_width=True):
        suggestion_clicked = "Audit available slots for Friday"
    if cols[2].button("Run cross-tool booking workflow", use_container_width=True):
        suggestion_clicked = "Run cross-tool booking workflow"
    st.markdown('</div>', unsafe_allow_html=True)

# Render history
for msg in historical_messages:
    if msg.type in ("human", "ai") and msg.content:
        role = "user" if msg.type == "human" else "assistant"
        with st.chat_message(role):
            st.markdown(msg.content)

# ---------------------------------------------------------------------------
# Handle new input
# ---------------------------------------------------------------------------
prompt = st.chat_input("Type your message… e.g. 'Book me for tomorrow at 3pm'")
final_prompt = prompt or suggestion_clicked

if final_prompt:
    with st.chat_message("user"):
        st.markdown(final_prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                response_state = compiled_graph.invoke(
                    {"messages": [HumanMessage(content=final_prompt)]},
                    config=config,
                )

                final_content = ""
                for msg in reversed(response_state.get("messages", [])):
                    if msg.type == "ai" and msg.content:
                        final_content = msg.content
                        break

                if final_content:
                    st.markdown(final_content)
                else:
                    st.warning("No response generated. Please try again.")

                # Booking confirmation banner
                slot = response_state.get("slot", {})
                if slot.get("status") == "reserved" and slot.get("confirmation_id"):
                    st.success(
                        f"✅ **Booking Confirmed!**  \n"
                        f"📅 **{slot.get('date')}** at **{slot.get('time')}**  \n"
                        f"🔖 Confirmation ID: `{slot.get('confirmation_id')}`"
                    )

            except Exception as e:
                err = str(e)
                if "decommissioned" in err or "model" in err.lower():
                    st.error("⚠️ The selected Groq model is no longer available. The model has been updated — please restart the app.")
                else:
                    st.error(f"⚠️ Error: {err}\n\nCheck that `GROQ_API_KEY` is set correctly.")
                logging.exception("Graph invocation error")
