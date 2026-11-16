"""Node B2: suggest primary keys and indexes for a generated CREATE script."""

from .llm import ask
from .state import AgentState


def suggest_keys(state: AgentState) -> dict:
    return {"key_suggestions": ask("key-suggestions", ddl_script=state["ddl_script"])}
