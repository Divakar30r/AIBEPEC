"""Graph nodes A (intent), B1 (create DDL), C1 (load dependencies) and the final respond node,
plus the routers."""

from langchain_core.messages import AIMessage
from langgraph.types import Send

from .BackendConstants import INTENTS, MESSAGES, NODES
from .config import settings
from .llm import ask
from .SampleTypes import describe_sample
from .state import AgentState, split_messages
from .TableDependencies import TableInfo, table_names, table_not_found_message
from .Util import extract_sql, find_json_sample, is_valid_sample, parse_json_object


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


def load_dependencies(state: AgentState) -> dict:
    """Node C1: join the per-table results of the C1A/C1B runs into the dependency context."""
    primary = state.get("table_name", "")
    results = sorted(state.get("table_results", []), key=lambda r: r["index"])
    infos: list[TableInfo] = [r["info"] for r in results if r["info"] is not None]
    missing: list[str] = [r["name"] for r in results if r["info"] is None]
    target = infos[0] if infos and primary and infos[0].name.lower() == primary.lower() else None
    return {
        "table_found": not missing,
        "missing_tables": missing,
        "table_name": target.name if target else primary,
        "dependencies": "\n\n".join(i.render() for i in infos),
        "column_types": target.column_types if target else {},
    }


def fan_out_tables(state: AgentState) -> list[Send]:
    """Router: one parallel run of the C1A/C1B subgraph per table (this is the Send fan-out)."""
    names = table_names(state.get("table_name", ""), state.get("related_tables", []))
    return [
        Send(NODES["fetch_table"], {"index": i, "table_name": name})
        for i, name in enumerate(names)
    ]


def route_after_intent(state: AgentState) -> str | list[Send]:
    """Create needs a valid JSON sample, modify needs a table name; otherwise answer directly.

    Modify fans out: one C1A/C1B subgraph run per table (primary + related), in parallel.
    """
    if state["intent"] == INTENTS["create"] and state["json_valid"]:
        return NODES["create_ddl"]
    if state["intent"] == INTENTS["modify"] and state["table_name"] and (
        state["json_valid"] or not state["json_sample"]
    ):
        return fan_out_tables(state)
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
