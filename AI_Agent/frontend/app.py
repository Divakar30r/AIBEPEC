"""Streamlit chat UI for the DDL agent.

Run from the project folder:  uv run streamlit run frontend/app.py
"""

import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

# Streamlit puts this script's folder on sys.path, not the project root where `backend` lives.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent import AgentReply, resume_agent, run_agent  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.BackendConstants import NODE_LABELS  # noqa: E402
from backend.executor import execute_script, summarize_script  # noqa: E402

st.set_page_config(page_title="DDL Agent", page_icon="🛠️", layout="wide")
st.title("DDL Agent")
st.caption(
    f"Describe a table to create (with a JSON sample) or an existing table to modify. "
    f"Target: `{settings.pg_target_db}` / schema `{settings.target_schema}`."
)

st.session_state.setdefault("messages", [])  # {"role", "content"}
st.session_state.setdefault("script_text", "")  # content of the script pane on the right
st.session_state.setdefault("last_exec", None)  # (ok, message) of the last execution
if "pending_script" in st.session_state:
    # A new script from the agent: it can only be put into the pane's widget before the widget
    # is created in this run, so the agent turn leaves it here and the rerun applies it.
    st.session_state.script_text = st.session_state.pop("pending_script")
st.session_state.setdefault("node_status", {})  # graph node -> running | done | error (last run)
st.session_state.setdefault("exec_log", [])  # one-line summary per executed script
# Thread of a turn paused on B4's question; while set, the next chat input is the answer to it.
st.session_state.setdefault("pending_thread", None)

# (kind, node name or label text, indent in px): the graph drawn as a flow, top to bottom.
FLOW = [
    ("node", "check_intent", 0),
    ("lbl", "↳ create, valid JSON sample", 10),
    ("node", "create_ddl", 10),
    ("lbl", "↳ in parallel", 26),
    ("node", "suggest_keys", 26),
    ("node", "suggest_types", 26),
    ("node", "ask_revision", 10),
    ("lbl", "↳ modify, table named", 10),
    ("lbl", "↳ once per table, in parallel", 26),
    ("node", "find_table", 26),
    ("node", "read_table", 26),
    ("node", "load_dependencies", 10),
    ("node", "plan_modification", 10),
    ("lbl", "↳ every path ends", 0),
    ("node", "respond", 0),
]
FLOW_CSS = """<style>
.flow{font-size:.85rem;line-height:1.2}
.flow .n{border:1px solid rgba(128,128,128,.5);border-radius:8px;padding:5px 9px;margin:4px 0;opacity:.5}
.flow .l{font-size:.72rem;opacity:.6;margin:8px 0 0}
.flow .n.running{opacity:1;border-color:#f5a623;background:rgba(245,166,35,.18);animation:pulse 1s ease-in-out infinite}
.flow .n.done{opacity:1;border-color:#2e9e5b;background:rgba(46,158,91,.18)}
.flow .n.error{opacity:1;border-color:#d64545;background:rgba(214,69,69,.18)}
@keyframes pulse{50%{box-shadow:0 0 8px 2px rgba(245,166,35,.7)}}
</style>"""
STATUS_ICON = {"running": "⏳ ", "done": "✓ ", "error": "✗ "}


def render_flow(box) -> None:
    """Draw the graph into ``box``; each node is coloured by its status in the current/last run."""
    status = st.session_state.node_status
    rows = []
    for kind, name, indent in FLOW:
        if kind == "lbl":
            rows.append(f'<div class="l" style="margin-left:{indent}px">{name}</div>')
        else:
            state = status.get(name, "")
            rows.append(
                f'<div class="n {state}" style="margin-left:{indent}px">'
                f"{STATUS_ICON.get(state, '')}{NODE_LABELS[name]}</div>"
            )
    box.html(FLOW_CSS + '<div class="flow">' + "".join(rows) + "</div>")


with st.sidebar:
    st.header("Agent graph")
    flow_box = st.empty()
    render_flow(flow_box)
    st.subheader("Executed scripts")
    if st.session_state.exec_log:
        st.markdown("\n".join(f"- {line}" for line in reversed(st.session_state.exec_log)))
    else:
        st.caption("Nothing executed yet.")
    if st.button("Clear chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.node_status = {}
        st.session_state.pending_thread = None
        st.rerun()


def add_message(role: str, content: str, **extra) -> None:
    st.session_state.messages.append({"role": role, "content": content, **extra})


def run_script() -> None:
    """Execute the script in the right pane; the outcome also goes into the chat history."""
    script = st.session_state.script_text
    result = execute_script(script)
    stamp = datetime.now().strftime("%H:%M")
    summary = summarize_script(script)
    st.session_state.last_exec = (result.ok, result.message)
    if result.ok:
        st.session_state.exec_log.append(f"✅ {stamp} · {summary}")
        add_message("assistant", f"✅ Executed `{summary}`: {result.message}")
    else:
        reason = result.message.strip().splitlines()[0][:60]
        st.session_state.exec_log.append(f"❌ {stamp} · {summary} — {reason}")
        add_message(
            "assistant",
            f"❌ Executing `{summary}` failed and was rolled back:\n\n```\n{result.message}\n```",
        )


PANE_HEIGHT = 560  # px; chat and script pane scroll inside this, so the page itself does not grow

chat_outer, script_outer = st.columns([3, 2], gap="large")
chat_col = chat_outer.container(height=PANE_HEIGHT, border=True)  # scrolls on its own
script_col = script_outer.container(height=PANE_HEIGHT, border=True)  # scrolls on its own

with script_col: # RIGHT PANE: script editor and execute button
    st.subheader("Final script")
    st.caption(
        "Filled with the latest generated script. Edit it or paste your own, then execute. "
        "Allowed: CREATE, ALTER, DROP, COMMENT, INSERT; the whole script is one transaction."
    )
    st.text_area(
        "Script", key="script_text", height=300, label_visibility="collapsed",
        placeholder="CREATE TABLE ...",
    )
    st.button(
        "Execute script",
        on_click=run_script,
        disabled=not st.session_state.script_text.strip(),
        type="primary",
        use_container_width=True,
        help=f"Runs the script in one transaction on {settings.pg_target_db}",
    )
    if st.session_state.last_exec:
        ok, detail = st.session_state.last_exec
        if ok:
            st.success(detail)
        else:
            st.error(detail)

with chat_col: #MIDDLE PANE: chat history and input box
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
    if st.session_state.messages:
        # Keep the newest message in view: scroll the chat container to the last message.
        st.iframe(  # static script of ours, no user content
            "<script>try{const m=window.parent.document.querySelectorAll("
            "'[data-testid=\"stChatMessage\"]');"
            "if(m.length)m[m.length-1].scrollIntoView({block:'end'});}catch(e){}</script>",
            height=1,
        )


def on_node(name: str, state: str) -> None:
    """Graph callback: colour the node in the sidebar flow as it starts and ends."""
    st.session_state.node_status[name] = state
    render_flow(flow_box)


def show_reply(reply: AgentReply) -> None:
    """Store the agent's reply. A paused turn (B4's question) keeps its thread for the answer."""
    add_message("assistant", reply.text)
    if reply.script:
        st.session_state.pending_script = reply.script
    st.session_state.pending_thread = reply.thread_id if reply.awaiting_revision else None


def show_failure(exc: Exception) -> None:
    for name, state in st.session_state.node_status.items():
        if state == "running":
            st.session_state.node_status[name] = "error"
    st.session_state.pending_thread = None
    add_message("assistant", f"Sorry, the agent failed: `{exc}`")


def run_turn(question: str) -> None:
    """A new chat turn: run the graph from the start on the question."""
    # History is taken before the new question is added: the agent gets it as a separate input.
    history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
    add_message("user", question)
    st.session_state.node_status = {}
    render_flow(flow_box)
    with chat_col:
        with st.chat_message("user"):
            st.markdown(question)
        try:
            with st.spinner("Thinking..."):
                reply = run_agent(history, question, on_node) # Graph being initiated
            show_reply(reply)
        except Exception as exc:  # missing token, DB down, ...: show it instead of crashing
            show_failure(exc)


def resume_turn(thread_id: str, answer: str) -> None:
    """Resume the turn paused on B4's question with the user's reply.

    The graph asks the LLM whether it is a Y. Node statuses are kept: B1 to B3 stay green and only
    the nodes that run again change.
    """
    add_message("user", answer)
    with chat_col:
        with st.chat_message("user"):
            st.markdown(answer)
        try:
            with st.spinner("Thinking..."):
                reply = resume_agent(thread_id, answer, on_node)
            show_reply(reply)
        except Exception as exc:  # e.g. the app restarted and the paused thread is gone
            show_failure(exc)


def handle_question(question: str) -> None:
    """The submitted text answers B4's pending question, or starts a new turn.

    Whatever the user types while B4 waits is its answer: a Y regenerates the script with B3's
    types, anything else finishes the turn with the original script and a note.
    The chat and the script pane are redrawn by the ``st.rerun()`` that follows this call.
    """
    thread_id = st.session_state.pending_thread
    if thread_id is None:
        run_turn(question)
        return
    st.session_state.pending_thread = None
    resume_turn(thread_id, question)


CHAT_PLACEHOLDER = "e.g. create a table for this order JSON: {...}"  # hint in the empty input box

# Wait for the question: chat_input returns the text only on the run triggered by a submit,
# otherwise None, so nothing below runs until the user submits.
question = st.chat_input(placeholder=CHAT_PLACEHOLDER, key="chat_input")
 
if question: # Whenever user submits question, handle it and rerun the app to show the new state and next rounds
    handle_question(question)
    st.rerun()
