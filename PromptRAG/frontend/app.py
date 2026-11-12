"""Basic Streamlit chatbot UI.

Run from the project folder:  uv run streamlit run frontend/app.py
"""

import sys
from pathlib import Path

import streamlit as st

# Streamlit puts this script's folder on sys.path, not the project root where `backend` lives.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.prompt import list_patterns  # noqa: E402
from backend.search import chat  # noqa: E402

st.set_page_config(page_title="PromptRAG", page_icon="💬")
st.title("PromptRAG")
st.caption("Ask about prompt engineering. Answers come from the indexed repo and PDFs.")

if "messages" not in st.session_state:
    st.session_state.messages = []  # {"role", "content", "sources"}

with st.sidebar:
    st.header("Prompt patterns")
    patterns = st.multiselect(
        "Embedded together with your question",
        options=list_patterns(),
        help="Selected patterns are added to the question before the semantic search.",
    )
    if st.button("Clear chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()


def show_sources(sources: list[dict]) -> None:
    if not sources:
        return
    with st.expander(f"Sources ({len(sources)})"):
        for s in sources:
            st.markdown(f"**{s['source']}** ({s['type']}, match {s['score']:.2f})")


for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        show_sources(m.get("sources", []))

if prompt := st.chat_input("Ask a question"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Searching..."):
                resp = chat(prompt, patterns)
            answer = resp.answer
            sources = [
                {"source": h.source, "type": h.source_type, "score": h.score} for h in resp.hits
            ]
        except Exception as exc:  # missing API key, DB down, etc.: show it instead of crashing
            answer, sources = f"Sorry, the backend call failed: `{exc}`", []
        st.markdown(answer)
        show_sources(sources)

    st.session_state.messages.append({"role": "assistant", "content": answer, "sources": sources})
