"""Streamlit UI: one-time query -> RAG over all files + LLM eval score, then chat with the LLM.

Run from the project folder:  uv run streamlit run frontend/app.py
"""

import sys
from pathlib import Path

import streamlit as st

# Streamlit puts this script's folder on sys.path, not the project root where `backend` lives.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.prompt import list_patterns  # noqa: E402
from backend.search import chat, list_files, run_rag  # noqa: E402

st.set_page_config(page_title="PromptRAG", page_icon="💬")
st.title("PromptRAG")
st.caption("Enter a query once to search every indexed file, then chat with the LLM about it.")

# Long file names: let the open dropdown list scroll horizontally instead of cutting them off.
st.markdown(
    """
    <style>
    div[data-baseweb="popover"] ul { overflow-x: auto; }
    div[data-baseweb="popover"] li, div[data-baseweb="popover"] li * {
        white-space: nowrap; overflow: visible; text-overflow: clip;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.session_state.setdefault("messages", [])
st.session_state.setdefault("rag", None)  # RAGResult once search + evaluation are complete
st.session_state.setdefault("files", [])
st.session_state.setdefault("query_in", "")


def reset() -> None:
    """New query: forget the RAG result, the file list and the whole chat with the LLM."""
    st.session_state.messages = []
    st.session_state.rag = None
    st.session_state.files = []
    st.session_state.query_in = ""


# --- Step 1: the one-time query (locked after submit until Reset) ---------------------------
locked = st.session_state.rag is not None
col_query, col_search, col_reset = st.columns([6, 1.2, 1.2], vertical_alignment="bottom")
query_in = col_query.text_input("Query (can be entered only once)", key="query_in", disabled=locked)
searched = col_search.button("Search", key="search_btn", disabled=locked, use_container_width=True)
col_reset.button("Reset", key="reset_btn", on_click=reset, use_container_width=True)

if searched and query_in.strip():
    try:
        with st.spinner("Searching all files and evaluating..."):
            st.session_state.rag = run_rag(query_in)
            st.session_state.files = list_files()
        st.rerun()
    except Exception as exc:  # missing API key, DB down, etc.: show it instead of crashing
        st.error(f"Backend call failed: `{exc}`")

rag = st.session_state.rag
if rag is not None:
    if not rag.rag_output:
        st.warning("Nothing is indexed yet. Run the ingest step first.")
    else:
        st.subheader("Eval score per file (0-1)")
        st.dataframe(
            [{"file": f, "score": rag.scores.get(f)} for f in rag.rag_output],
            hide_index=True,
            use_container_width=True,
        )
        with st.expander(f"RAG output ({len(rag.rag_output)} files)"):
            for name, text in rag.rag_output.items():
                st.markdown(f"**{name}**")
                st.text(text)

# --- Step 2: chat with the LLM --------------------------------------------------------------
# Search and evaluation are synchronous, so once `rag` is set the RAG output has been scored.
ready = rag is not None and bool(rag.rag_output)
with st.sidebar:
    st.header("Chat settings")
    chosen_file = st.selectbox("chosen_file", options=st.session_state.files, disabled=not ready)
    pattern = st.selectbox("Prompt pattern", options=list_patterns(), disabled=not ready)

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if prompt := st.chat_input("Ask the LLM about the chosen file", disabled=not ready):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Thinking..."):
                answer = chat(prompt, rag, chosen_file, pattern)
        except Exception as exc:
            answer = f"Sorry, the backend call failed: `{exc}`"
        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})
