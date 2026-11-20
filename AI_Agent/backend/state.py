"""Shared LangGraph state."""

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage as LC_BaseMessage
from langgraph.graph.message import add_messages as LG_add_messages


class AgentState(TypedDict, total=False):
    # Conversation: history followed by the latest user message. `add_messages` appends.
    messages: Annotated[list[LC_BaseMessage], LG_add_messages]

    # Node A
    intent: str  # one of INTENTS
    table_name: str  # the table to change
    related_tables: list[str]  # other existing tables the request needs read
    json_sample: str  # latest JSON the user pasted, '' if none
    # Create: the latest JSON in the whole chat. Modify: JSON in the latest message only, read as
    # a PARTIAL sample (just the fields to change).
    json_valid: bool  # True when json_sample is a non-empty object

    # Create branch
    ddl_script: str  # B1
    key_suggestions: str  # B2
    type_suggestions: str  # B3
    revise_ddl: bool  # B4: the user accepted redoing B1 with B3's types (B1 then B2, not B3 again)
    revision_reply: str  # B4: INTENTS["drop"] when the reply was not a clear Y

    # Modify branch
    # C1A/C1B subgraph runs (one per table, in parallel via Send) append here; `operator.add`
    # merges their results. Each item is a dict:
    # {"index": int, "name": str, "info": TableInfo | None}  (None = table not found).
    table_results: Annotated[list[dict], operator.add]
    table_found: bool  # C1: every named table exists
    missing_tables: list[str]  # C1
    dependencies: str  # C1
    column_types: dict[str, str]  # C1: lower-cased column name -> current type
    modification_plan: str  # C2

    # Output
    script: str  # the executable SQL (create DDL or ALTER/recreate script), '' if none
    reply: str  # the text shown to the user


def split_messages(state: AgentState) -> tuple[list[LC_BaseMessage], str]:
    """(history, latest user text): the last message is the question, the rest is history."""
    messages = state["messages"]
    last = messages[-1]
    text = last.content if isinstance(last.content, str) else str(last.content)
    return list(messages[:-1]), text


# --- C1A / C1B subgraph: runs once per table, in parallel, started by Send -------------------
class TableFetchState(TypedDict, total=False):
    """State of ONE subgraph run (separate from AgentState). Input is ``index`` + ``table_name``."""

    index: int  # position of the table in the request, so the join can restore the order
    table_name: str  # the name as the user wrote it
    oid: int  # C1A -> C1B
    real_name: str  # C1A -> C1B: the table's real (case-correct) name
    table_results: Annotated[list[dict], operator.add]  # the only key handed back to AgentState


class TableFetchOutput(TypedDict):
    table_results: list[dict]
