"""Node C2: decide between ALTER and recreating the table, and write the script."""

from .config import settings
from .llm import ask
from .SampleTypes import describe_changes
from .state import AgentState, split_messages
from .textutil import extract_sql


def plan_modification(state: AgentState) -> dict:
    history, question = split_messages(state)
    if state.get("json_valid"):
        field_changes = describe_changes(state["json_sample"], state.get("column_types", {}))
    else:
        field_changes = "(no JSON given: follow the request text)"
    plan = ask(
        "modification-plan",
        history=history,
        question=question,
        schema_name=settings.target_schema,
        table_name=state["table_name"],
        dependencies=state["dependencies"],
        field_changes=field_changes,
    )
    return {"modification_plan": plan, "script": extract_sql(plan)}
