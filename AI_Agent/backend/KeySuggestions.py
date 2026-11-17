"""Node B2: suggest primary keys and indexes for a generated CREATE script."""

from .config import settings
from .llm import ask
from .state import AgentState


def suggest_keys(state: AgentState) -> dict:
    return {
        "key_suggestions": ask(
            "key-suggestions", dialect=settings.db_dialect, ddl_script=state["ddl_script"]
        )
    }
