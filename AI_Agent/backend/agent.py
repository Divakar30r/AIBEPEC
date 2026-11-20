"""Entry points for the UI: run the graph for one chat turn, resume a paused one, run a subgraph."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.messages import HumanMessage as LC_HumanMessage
from langgraph.types import Command as LG_Command

from .graph import build_graph, build_table_fetch_graph
from .TableDependencies import TableInfo
from .Util import to_messages

_graph = None
_table_fetch_graph = None


@dataclass
class AgentReply:
    text: str
    script: str  # executable SQL, '' when the reply has none
    intent: str
    thread_id: str = ""  # set while the graph is paused: pass it to resume_agent
    awaiting_revision: bool = False  # True: ``text`` is B4's question and the turn is not finished


def _stream(
    graph_input, thread_id: str, on_node: Callable[[str, str], None] | None
) -> AgentReply:
    """Stream the graph on one thread (the memory-saver key) until it ends or pauses."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    config = {"configurable": {"thread_id": thread_id}}
    result: dict = {}
    # subgraphs=True also reports the nodes inside the C1A/C1B subgraph; each chunk then starts
    # with a namespace tuple (empty for the main graph).
    for namespace, mode, chunk in _graph.stream(
        graph_input, config, stream_mode=["tasks", "values"], subgraphs=True
    ):
        if mode == "tasks" and on_node:
            if "result" not in chunk:
                on_node(chunk["name"], "running")
            else:
                on_node(chunk["name"], "error" if chunk.get("error") else "done")
        elif mode == "values" and not namespace:
            result = chunk  # the last main-graph one is the final state
    snapshot = _graph.get_state(config)
    if snapshot.interrupts:  # paused by B4: its question is the interrupt's value
        return AgentReply(
            text=snapshot.interrupts[0].value,
            script=snapshot.values.get("ddl_script", ""),
            intent=snapshot.values.get("intent", ""),
            thread_id=thread_id,
            awaiting_revision=True,
        )
    return AgentReply(
        text=result["reply"], script=result.get("script", ""), intent=result.get("intent", "")
    )


def run_agent(
    history: list[dict[str, str]],
    question: str,
    on_node: Callable[[str, str], None] | None = None,
) -> AgentReply:
    """Run one turn. ``history`` is the earlier chat as ``{"role", "content"}`` dicts.

    ``on_node(name, status)`` is called live as each graph node starts ("running") and ends
    ("done" or "error"); parallel nodes are both "running" at once.

    Every turn gets its own thread: the whole history is sent each time, so one shared thread would
    pile up duplicate messages and per-table results from earlier turns. When the reply has
    ``awaiting_revision`` the turn is paused: answer it with ``resume_agent(reply.thread_id, ...)``.
    """
    inputs = {"messages": [*to_messages(history), LC_HumanMessage(content=question)]}
    return _stream(inputs, uuid.uuid4().hex, on_node)


def resume_agent(
    thread_id: str,
    answer: str,
    on_node: Callable[[str, str], None] | None = None,
) -> AgentReply:
    """Resume a turn paused by B4 with the user's reply. The LLM reads it as Y or N: Y redoes B1
    with B3's types, anything else goes on to the final answer with a note that the revision was
    dropped. Raises when the thread is unknown (e.g. the app restarted)."""
    return _stream(LG_Command(resume=answer), thread_id, on_node)


# Sub agent run
def run_table_fetch(table_name: str, index: int = 0) -> TableInfo | None:
    """Run the C1A -> C1B subgraph on its own for one table: no question, no history.

    Returns the table's columns, constraints, indexes and referencing foreign keys, or None when
    the table does not exist in the target schema.
    """
    global _table_fetch_graph
    if _table_fetch_graph is None:
        _table_fetch_graph = build_table_fetch_graph()
    result = _table_fetch_graph.invoke({"index": index, "table_name": table_name})
    return result["table_results"][0]["info"]
