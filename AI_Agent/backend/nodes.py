"""Graph nodes A (intent), B1 (create DDL) and the final respond node, plus the routers."""

from langchain_core.messages import AIMessage

from .BackendConstants import INTENTS, MESSAGES, NODES
from .config import settings
from .llm import ask
from .SampleTypes import describe_sample
from .state import AgentState, split_messages
from .TableDependencies import table_not_found_message
from .textutil import extract_sql, find_json_sample, is_valid_sample, parse_json_object


def check_intent(state: AgentState) -> dict:
    """Node A: create, modify or other? Also finds the table name and any JSON sample."""
    history, question = split_messages(state)
    parsed = parse_json_object(ask("intent", history=history, question=question)) or {}
    intent = str(parsed.get("intent", "")).lower()
    intent = intent if intent in INTENTS.values() else INTENTS["other"]
    # Create may reuse a sample pasted earlier in the chat. For modify the JSON is a partial
    # sample naming the fields to change, so only the latest message counts (an older create
    # sample would wrongly mark every field as changed).
    scope = state["messages"][-1:] if intent == INTENTS["modify"] else state["messages"]
    sample = find_json_sample(scope)
    related = parsed.get("related_tables")
    return {
        "intent": intent,
        "table_name": str(parsed.get("table_name") or "").strip(),
        "related_tables": (
            [str(t).strip() for t in related if str(t).strip()] if isinstance(related, list) else []
        ),
        "json_sample": sample,
        "json_valid": bool(sample) and is_valid_sample(sample),
    }


def create_ddl(state: AgentState) -> dict:
    """Node B1: CREATE TABLE script from the JSON sample."""
    history, question = split_messages(state)
    reply = ask(
        "create-ddl",
        dialect=settings.db_dialect,
        history=history,
        question=question,
        schema_name=settings.target_schema,
        table_name=state.get("table_name", ""),
        json_sample=state["json_sample"],
        type_hints=describe_sample(state["json_sample"]),
    )
    return {"ddl_script": extract_sql(reply)}


def route_after_intent(state: AgentState) -> str:
    """Create needs a valid JSON sample, modify needs a table name; otherwise answer directly."""
    if state["intent"] == INTENTS["create"] and state["json_valid"]:
        return NODES["create_ddl"]
    if state["intent"] == INTENTS["modify"] and state["table_name"] and (
        state["json_valid"] or not state["json_sample"]
    ):
        return NODES["load_dependencies"]
    return NODES["respond"]


def route_after_dependencies(state: AgentState) -> str:
    return NODES["plan_modification"] if state["table_found"] else NODES["respond"]


def respond(state: AgentState) -> dict:
    """Compose the final answer from whatever the branch produced."""
    intent = state.get("intent", INTENTS["other"])
    script = ""

    if intent == INTENTS["create"] and state.get("ddl_script"):
        script = state["ddl_script"]
        reply = "\n\n".join(
            [
                MESSAGES["ddl_intro"],
                f"```sql\n{script}\n```",
                MESSAGES["keys_heading"],
                state.get("key_suggestions", ""),
                MESSAGES["types_heading"],
                state.get("type_suggestions", ""),
            ]
        )
    elif intent == INTENTS["modify"] and state.get("modification_plan"):
        script = state.get("script", "")
        reply = state["modification_plan"]
    elif intent in (INTENTS["create"], INTENTS["modify"]) and (
        state.get("json_sample") and not state.get("json_valid")
    ):
        reply = MESSAGES["invalid_structure"]
    elif intent == INTENTS["create"]:
        reply = MESSAGES["ask_json"]
    elif intent == INTENTS["modify"] and not state.get("table_name"):
        reply = MESSAGES["ask_table"]
    elif intent == INTENTS["modify"]:
        reply = table_not_found_message(state.get("missing_tables") or [state["table_name"]])
    else:
        reply = MESSAGES["other"]

    return {"script": script, "reply": reply, "messages": [AIMessage(content=reply)]}
