# app.py

import os
from copy import deepcopy

import streamlit as st
from dotenv import load_dotenv

from controller import run_pipeline
from config.settings import DEFAULTS, STYLE_PROFILES
from memory.manager import init_memory, memory_debug_view
from utils.logging_utils import debug_snapshot


load_dotenv()

st.set_page_config(page_title="SmartTutor", layout="wide")
st.title("SmartTutor")


# ---------- Sidebar ----------
st.sidebar.header("Configuration")

model_options = ["gpt-5-mini", "o3-mini", "o4-mini", "gpt-4o-mini", "gpt-4o"]
default_model = os.getenv("DEFAULT_MODEL", DEFAULTS["model"])
default_model_index = (
    model_options.index(default_model)
    if default_model in model_options
    else 0
)

model = st.sidebar.selectbox("Model", model_options, index=default_model_index)

style_keys = list(STYLE_PROFILES.keys())
default_style = DEFAULTS["style"]
default_style_index = style_keys.index(default_style) if default_style in style_keys else 0

style = st.sidebar.selectbox(
    "Tutoring style",
    options=style_keys,
    index=default_style_index,
)
st.sidebar.caption(STYLE_PROFILES[style]["description"])

debug = st.sidebar.checkbox("Debug mode", value=DEFAULTS["debug"])
enable_llm_verify = st.sidebar.checkbox(
    "Enable LLM verify",
    value=DEFAULTS["enable_llm_verify"],
)
max_retries = st.sidebar.selectbox("Max retries", options=[0, 1, 2], index=1)

api_key_override = st.sidebar.text_input("API key override (optional)", type="password")

if not os.getenv("AZURE_OPENAI_API_KEY") and not api_key_override:
    st.sidebar.warning("No Azure API key found in .env and no override provided.")


# ---------- Session state ----------
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "memory" not in st.session_state:
    st.session_state.memory = init_memory()


if st.sidebar.button("Clear chat"):
    st.session_state.chat_history = []
    st.session_state.memory = init_memory()
    st.rerun()


# ---------- Chat history ----------
for role, content in st.session_state.chat_history:
    with st.chat_message(role):
        st.markdown(content)


# ---------- User input ----------
user_input = st.chat_input("Ask a math, history, or conversation-summary question...")

if user_input:
    st.session_state.chat_history.append(("user", user_input))

    with st.chat_message("user"):
        st.markdown(user_input)

    config = {
        "model": model,
        "style": style,
        "debug": debug,
        "max_retries": max_retries,
        "enable_llm_verify": enable_llm_verify,
    }

    if api_key_override:
        config["api_key"] = api_key_override

    memory_before = deepcopy(st.session_state.memory)

    with st.spinner("Thinking..."):
        try:
            state = run_pipeline(
                raw_input=user_input,
                config=config,
                memory=deepcopy(st.session_state.memory),
            )

        except Exception as e:
            # Final UI-level safety net. Ideally controller already catches this.
            class _FallbackState:
                final_response = (
                    "The tutoring system encountered an internal error. Please "
                    "rephrase the question as a direct math, history, or "
                    "conversation-summary task."
                )
                memory = memory_before

            state = _FallbackState()

            if debug:
                st.sidebar.error(f"Unhandled app error: {type(e).__name__}: {e}")

    # Persist updated memory for the next turn.
    st.session_state.memory = state.memory

    st.session_state.chat_history.append(("assistant", state.final_response))

    with st.chat_message("assistant"):
        st.markdown(state.final_response)

    if debug:
        st.sidebar.subheader("Debug snapshot")
        st.sidebar.subheader("Context resolution")
        try:
            if getattr(state, "context_resolution", None):
                st.sidebar.json(state.context_resolution.model_dump())
            else:
                st.sidebar.write("No context resolution.")
        except Exception as e:
            st.sidebar.write(
                f"Context-resolution debug unavailable: {type(e).__name__}: {e}"
            )

        st.sidebar.subheader("Resolved input")
        try:
            st.sidebar.write(getattr(state, "resolved_input", None) or "")
        except Exception as e:
            st.sidebar.write(
                f"Resolved-input debug unavailable: {type(e).__name__}: {e}"
            )
        try:
            st.sidebar.json(debug_snapshot(state))
        except Exception:
            st.sidebar.write("Debug snapshot unavailable for fallback state.")

        st.sidebar.subheader("Memory before")
        try:
            st.sidebar.json(memory_debug_view(memory_before))
        except Exception as e:
            st.sidebar.write(
                f"Memory-before debug unavailable: {type(e).__name__}: {e}"
            )

        st.sidebar.subheader("Memory after")
        try:
            st.sidebar.json(memory_debug_view(st.session_state.memory))
        except Exception as e:
            st.sidebar.write(
                f"Memory-after debug unavailable: {type(e).__name__}: {e}"
            )