"""Entry point for the UI: run the graph for one chat turn."""

from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from .config import settings
from .graph import build_graph

_graph = None


@dataclass
class AgentReply:
    text: str
    script: str  # executable SQL, '' when the reply has none
    intent: str


def _to_messages(history: list[dict[str, str]]) -> list[BaseMessage]:
    recent = history[-settings.history_messages :] if settings.history_messages > 0 else []
    return [
        (HumanMessage if m["role"] == "user" else AIMessage)(content=m["content"]) for m in recent
    ]


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
    inputs = {"messages": [*_to_messages(history), HumanMessage(content=question)]}
    for mode, chunk in _graph.stream(inputs, stream_mode=["tasks", "values"]):
        if mode == "tasks" and on_node:
            if "result" not in chunk:
                on_node(chunk["name"], "running")
            else:
                on_node(chunk["name"], "error" if chunk.get("error") else "done")
        elif mode == "values":
            result = chunk  # the last one is the final state
    return AgentReply(
        text=result["reply"], script=result.get("script", ""), intent=result.get("intent", "")
    )
