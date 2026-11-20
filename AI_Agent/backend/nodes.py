"""Graph nodes A (intent), B1 (create DDL), B4 (ask to revise), C1 (load dependencies) and the
final respond node, plus the routers."""

from typing import Literal

from langchain_core.messages import AIMessage as LC_AIMessage
from langgraph.graph import END as LG_END
from langgraph.types import Command as LG_Command, Send as LG_Send, interrupt as LG_interrupt

from .BackendConstants import INTENTS, MESSAGES, NO_CHANGES_MARKER, NODES
from .config import settings
from .llm import ask
from .SampleTypes import describe_sample
from .state import AgentState, split_messages
from .TableDependencies import TableInfo, table_names, table_not_found_message
from .Util import (
    extract_sql,
    find_json_sample,
    is_valid_sample,
    parse_json_object,
)


def check_intent(state: AgentState) -> dict:
    """Node A: create, modify or other? Also finds the table name and any JSON sample."""
    history, question = split_messages(state)
    parsed = parse_json_object(ask("intent", history=history, question=question)) or {}
    intent = str(parsed.get("intent", "")).lower()
    allowed = [INTENTS["create"], INTENTS["modify"], INTENTS["other"]]  # "drop" is only for B4
    intent = intent if intent in allowed else INTENTS["other"]
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
    """Node B1: CREATE TABLE script from the JSON sample, or (after B4) with B3's types applied."""
    if state.get("revise_ddl"):
        reply = ask(
            "revise-ddl",
            dialect=settings.db_dialect,
            ddl_script=state["ddl_script"],
            type_suggestions=state.get("type_suggestions", ""),
        )
        return {"ddl_script": extract_sql(reply)}
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


def ask_revision(state: AgentState) -> LG_Command[Literal["create_ddl", "respond"]]:
    """Node B4: after B2 and B3, ask the human whether B1 should be redone with B3's types.

    ``interrupt`` pauses the graph (it needs the checkpointer) and hands the question to the
    caller, who resumes with ``Command(resume=<reply>)``. On resume this node runs again from the
    top, so nothing before ``interrupt`` may have side effects (the LLM call comes after it).
    A Y from the LLM goes back to B1; anything else goes on to ``respond`` with ``revision_reply``
    set to INTENTS["drop"], so the answer carries the drop note. Nothing is asked when B3 found no
    change worth making.
    """
    suggestions = state.get("type_suggestions", "")
    if NO_CHANGES_MARKER in suggestions.lower():
        return LG_Command(goto=NODES["respond"])
    answer = str(LG_interrupt(MESSAGES["revise_question"].format(type_suggestions=suggestions)))
    if wants_revision(answer, suggestions):
        return LG_Command(goto=NODES["create_ddl"], update={"revise_ddl": True})
    return LG_Command(goto=NODES["respond"], update={"revision_reply": INTENTS["drop"]})


def wants_revision(answer: str, suggestions: str) -> bool:
    """Ask the LLM whether the reply to B4's question is a clear yes: it answers just Y or N."""
    reply = ask("revision-answer", type_suggestions=suggestions, answer=answer)
    return reply.strip().upper().startswith("Y")


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


def fan_out_tables(state: AgentState) -> list[LG_Send]:
    """Router: one parallel run of the C1A/C1B subgraph per table (this is the Send fan-out)."""
    names = table_names(state.get("table_name", ""), state.get("related_tables", []))
    return [
        LG_Send(NODES["fetch_table"], {"index": i, "table_name": name})
        for i, name in enumerate(names)
    ]


def route_after_intent(state: AgentState) -> str | list[LG_Send]:
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


def route_after_ddl(state: AgentState) -> list[str]:
    """B1 fans out to B2 and B3; after a revision only B2 runs again (B3's types are applied)."""
    if state.get("revise_ddl"):
        return [NODES["suggest_keys"]]
    return [NODES["suggest_keys"], NODES["suggest_types"]]


def route_after_keys(state: AgentState) -> str:
    """First pass: B3's branch carries on to B4, so B2 ends here. After a revision B2 is the only
    branch left, so it goes to ``respond``."""
    return NODES["respond"] if state.get("revise_ddl") else LG_END


def route_after_dependencies(state: AgentState) -> str:
    return NODES["plan_modification"] if state["table_found"] else NODES["respond"]


def respond(state: AgentState) -> dict:
    """Compose the final answer from whatever the branch produced."""
    intent = state.get("intent", INTENTS["other"])
    script = ""

    if intent == INTENTS["create"] and state.get("ddl_script"):
        script = state["ddl_script"]
        types_text = (
            MESSAGES["types_applied"] if state.get("revise_ddl") else state.get("type_suggestions", "")
        )
        reply = "\n\n".join(
            [
                MESSAGES["ddl_intro"],
                f"```sql\n{script}\n```",
                MESSAGES["keys_heading"],
                state.get("key_suggestions", ""),
                MESSAGES["types_heading"],
                types_text,
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

    if state.get("revision_reply") == INTENTS["drop"]:
        reply = f"{reply}\n\n{MESSAGES['drop_msg']}"

    return {"script": script, "reply": reply, "messages": [LC_AIMessage(content=reply)]}
