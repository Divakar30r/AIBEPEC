"""Entry point for the UI: run the graph for one chat turn."""

from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.messages import HumanMessage

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


def run_agent(
    history: list[dict[str, str]],
    question: str,
    on_node: Callable[[str, str], None] | None = None,
) -> AgentReply:
    """Run one turn. ``history`` is the earlier chat as ``{"role", "content"}`` dicts.

    ``on_node(name, status)`` is called live as each graph node starts ("running") and ends
    ("done" or "error"); parallel nodes are both "running" at once.
    """
    global _graph
    if _graph is None:
        _graph = build_graph()
    result: dict = {}
    inputs = {"messages": [*to_messages(history), HumanMessage(content=question)]}
    # subgraphs=True also reports the nodes inside the C1A/C1B subgraph; each chunk then starts
    # with a namespace tuple (empty for the main graph).
    for namespace, mode, chunk in _graph.stream(
        inputs, stream_mode=["tasks", "values"], subgraphs=True
    ):
        if mode == "tasks" and on_node:
            if "result" not in chunk:
                on_node(chunk["name"], "running")
            else:
                on_node(chunk["name"], "error" if chunk.get("error") else "done")
        elif mode == "values" and not namespace:
            result = chunk  # the last main-graph one is the final state
    return AgentReply(
        text=result["reply"], script=result.get("script", ""), intent=result.get("intent", "")
    )

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
