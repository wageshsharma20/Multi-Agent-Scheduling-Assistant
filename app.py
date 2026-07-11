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

# Load static CSS from file
css_path = Path(__file__).parent / "style.css"
if css_path.exists():
    with open(css_path, "r") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Thread ID — persist via URL query params
# ---------------------------------------------------------------------------
if "thread_id" not in st.query_params:
    st.query_params["thread_id"] = str(uuid.uuid4())
thread_id = st.query_params["thread_id"]
config = {"configurable": {"thread_id": thread_id}}

# ---------------------------------------------------------------------------
# Header Dashboard
# ---------------------------------------------------------------------------
st.markdown("""
<div class="top-header">
    <div class="header-left">
        <svg class="header-logo" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
            <rect x="7" y="7" width="10" height="10" rx="1" ry="1"></rect>
        </svg>
        <span>ScheduleAI Agent</span>
    </div>
    <div class="header-right">
        <a href="/" target="_self">Home</a>
        <a href="https://github.com/wagesh" target="_blank">Docs</a>
        <a href="/" target="_self">Restart Session</a>
    </div>
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

# Show hero header and suggestion pills ONLY on empty conversations
suggestion_clicked = None
if not historical_messages:
    st.markdown("""
    <div class="hero">
        <h1 class="hero-title">Schedule appointments<br/>autonomously</h1>
        <p class="hero-sub">Design, deploy, and scale specialized AI agents that plan, execute, and optimize work across your tools.</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="suggestions">', unsafe_allow_html=True)
    cols = st.columns(3, gap="small")
    if cols[0].button("Deploy agent for tomorrow at 2pm", use_container_width=True):
        suggestion_clicked = "Deploy agent for tomorrow at 2pm"
    if cols[1].button("Audit available slots for Friday", use_container_width=True):
        suggestion_clicked = "Audit available slots for Friday"
    if cols[2].button("Run cross-tool booking workflow", use_container_width=True):
        suggestion_clicked = "Run cross-tool booking workflow"
    st.markdown('</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Render history
# ---------------------------------------------------------------------------
for msg in historical_messages:
    if msg.type in ("human", "ai") and msg.content:
        role = "user" if msg.type == "human" else "assistant"
        with st.chat_message(role):
            st.markdown(f'<span class="msg-{role}" style="display:none;"></span>\n\n{msg.content}', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Handle new input
# ---------------------------------------------------------------------------
prompt = st.chat_input("Type your message… e.g. 'Book me for tomorrow at 3pm'")
final_prompt = prompt or suggestion_clicked

if final_prompt:
    with st.chat_message("user"):
        st.markdown(f'<span class="msg-user" style="display:none;"></span>\n\n{final_prompt}', unsafe_allow_html=True)

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
                    st.markdown(f'<span class="msg-assistant" style="display:none;"></span>\n\n{final_content}', unsafe_allow_html=True)
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
