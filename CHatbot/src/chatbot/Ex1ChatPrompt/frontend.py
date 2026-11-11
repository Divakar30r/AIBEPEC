"""Streamlit frontend: two parallel chat sessions, one per template strategy."""

from __future__ import annotations

import streamlit as st

from chatbot.Ex1ChatPrompt.backend import STRATEGIES, Session, make_sessions
from chatbot.config import get_settings
from chatbot.prompts import describe_templates

st.set_page_config(page_title="from_messages() vs from_template()", layout="wide")

SETTINGS = get_settings()

LABELS = {
    "from_messages": "ChatPromptTemplate.from_messages()",
    "from_template": "ChatPromptTemplate.from_template()",
}


def _init_state() -> None:
    if "sessions" not in st.session_state:
        st.session_state.sessions = make_sessions()
    # One transcript per strategy, so each column renders only its own messages.
    if "transcripts" not in st.session_state:
        st.session_state.transcripts = {strategy: [] for strategy in STRATEGIES}


def _render_sidebar() -> int:
    with st.sidebar:
        st.header("Settings")
        maxmum_sentences = st.slider("Max sentences in answer", 1, 10, 3)
        st.caption(f"Model: `{SETTINGS.model_id}`")
        st.caption(f"Provider: `{SETTINGS.provider}`")

        st.divider()
        st.subheader("Template introspection")
        for key, info in describe_templates().items():
            with st.expander(LABELS[key]):
                st.write(f"`input_variables`: {info['input_variables']}")
                st.write(f"`input_types`: {info['input_types']}")
                st.write(f"`message_count`: {info['message_count']}")
                st.write(f"`message_types`: {info['message_types']}")

        st.divider()
        if st.button("Reset both sessions", use_container_width=True):
            for session in st.session_state.sessions.values():
                session.reset()
            st.session_state.transcripts = {strategy: [] for strategy in STRATEGIES}
            st.rerun()

    return maxmum_sentences


def _render_column(session: Session, maxmum_sentences: int) -> None:
    """Draw one strategy's column: header, its own transcript, and its prompt."""
    st.subheader(LABELS[session.strategy])
    st.caption(f"{len(session.history) // 2} turn(s) in history")

    transcript = st.session_state.transcripts[session.strategy]
    if not transcript:
        st.info("No messages yet. Ask a question below to compare both templates.")

    for role, text in transcript:
        with st.chat_message(role):
            st.markdown(text)

    st.caption("Prompt actually sent (with placeholder question):")
    st.code(session.render_prompt("…your next question…", maxmum_sentences), language="text")


_init_state()
maxmum_sentences = _render_sidebar()

st.title("Prompt template comparison")
st.caption(
    "Both columns receive the identical question. Only the prompt template differs, "
    "so any behavioural difference is attributable to the template shape."
)

if not SETTINGS.is_configured:
    st.warning(
        "No Hugging Face token found. Copy `.env.example` to `.env`, add "
        "`HUGGINGFACEHUB_API_TOKEN`, then restart the app."
    )
    st.stop()

question = st.chat_input("Ask the same question to both templates")
if question:
    answers: dict[str, str] = {}
    for strategy in STRATEGIES:
        with st.spinner(f"{LABELS[strategy]} is thinking…"):
            try:
                answers[strategy] = st.session_state.sessions[strategy].ask(
                    question, maxmum_sentences=maxmum_sentences
                )
            except Exception as exc:  # surface provider/auth errors in the UI
                answers[strategy] = f"⚠️ Error: {exc}"

    # Each strategy's transcript gets the question and only its own answer.
    for strategy, answer in answers.items():
        transcript = st.session_state.transcripts[strategy]
        transcript.append(("user", question))
        transcript.append(("assistant", answer))

    st.rerun()

left, right = st.columns(2)
for column, strategy in zip((left, right), STRATEGIES):
    with column:
        _render_column(st.session_state.sessions[strategy], maxmum_sentences)
