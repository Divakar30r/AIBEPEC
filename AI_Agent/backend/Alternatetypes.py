"""Node B3: suggest alternate data types for fields of a generated CREATE script."""

from .llm import ask
from .state import AgentState


def suggest_types(state: AgentState) -> dict:
    return {
        "type_suggestions": ask(
            "alternate-types", ddl_script=state["ddl_script"], json_sample=state["json_sample"]
        )
    }
