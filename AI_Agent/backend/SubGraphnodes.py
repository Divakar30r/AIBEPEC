"""Nodes of the C1A -> C1B subgraph (one run per table): find the table, then read its details."""

from langgraph.graph import END as LG_END

# Called through the module (not ``from ... import``) so a patched TableDependencies.lookup_table
# or read_table_info, as the tests do, is the one used here.
from . import TableDependencies
from .BackendConstants import NODES
from .state import TableFetchState


def find_table(state: TableFetchState) -> dict:
    """Subgraph node C1A: does the table exist? Missing tables are reported with info=None."""
    found = TableDependencies.lookup_table(state["table_name"])
    if found is None:
        return {"table_results": [{"index": state["index"], "name": state["table_name"], "info": None}]}
    return {"oid": found[0], "real_name": found[1]}


def route_after_find(state: TableFetchState) -> str:
    return NODES["read_table"] if "oid" in state else LG_END


def read_table(state: TableFetchState) -> dict:
    """Subgraph node C1B: read columns, constraints, indexes and referencing foreign keys."""
    info = TableDependencies.read_table_info(state["oid"], state["real_name"])
    return {"table_results": [{"index": state["index"], "name": state["table_name"], "info": info}]}
