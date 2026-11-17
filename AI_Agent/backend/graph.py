"""The LangGraph: A -> B1 -> (B2 | B3) for create, A -> C1 -> C2 for modify.

    START -> check_intent --create + JSON--> create_ddl --+--> suggest_keys  --+--> respond -> END
                  |                                       +--> suggest_types -+
                  +--modify + table--Send x N tables--> fetch_table [C1A -> C1B] (parallel)
                                                              |
                                                       load_dependencies --found--> plan_modification -> respond
                  +--anything else (or table not found)--> respond

B2 and B3 run in parallel and ``respond`` waits for both.
"""

from langgraph.graph import END, START, StateGraph

from .Alternatetypes import suggest_types
from .BackendConstants import NODES
from .KeySuggestions import suggest_keys
from .Modifications import plan_modification
from .nodes import (
    check_intent,
    create_ddl,
    load_dependencies,
    respond,
    route_after_dependencies,
    route_after_intent,
)
from .state import AgentState, TableFetchOutput, TableFetchState
from .SubGraphnodes import find_table, read_table, route_after_find


def build_table_fetch_graph():
    """The compiled C1A -> C1B subgraph, used as the ``fetch_table`` node of the main graph."""
    g = StateGraph(TableFetchState, output_schema=TableFetchOutput)
    g.add_node(NODES["find_table"], find_table)
    g.add_node(NODES["read_table"], read_table)
    g.add_edge(START, NODES["find_table"])
    g.add_conditional_edges(NODES["find_table"], route_after_find, [NODES["read_table"], END])
    g.add_edge(NODES["read_table"], END)
    return g.compile()


def build_graph():
    g = StateGraph(AgentState)

    g.add_node(NODES["intent"], check_intent)
    g.add_node(NODES["create_ddl"], create_ddl)
    g.add_node(NODES["suggest_keys"], suggest_keys)
    g.add_node(NODES["suggest_types"], suggest_types)
    g.add_node(NODES["fetch_table"], build_table_fetch_graph())  # subgraph C1A -> C1B
    g.add_node(NODES["load_dependencies"], load_dependencies)
    g.add_node(NODES["plan_modification"], plan_modification)
    g.add_node(NODES["respond"], respond)

    g.add_edge(START, NODES["intent"])
    g.add_conditional_edges(
        NODES["intent"],
        route_after_intent,
        [NODES["create_ddl"], NODES["fetch_table"], NODES["respond"]],
    )

    # Create branch: B1 fans out to B2 and B3, which join in respond.
    g.add_edge(NODES["create_ddl"], NODES["suggest_keys"])
    g.add_edge(NODES["create_ddl"], NODES["suggest_types"])
    g.add_edge([NODES["suggest_keys"], NODES["suggest_types"]], NODES["respond"])

    # Modify branch: Send fans out one fetch_table subgraph run per table; load_dependencies (C1)
    # runs once all of them are done and joins their results.
    g.add_edge(NODES["fetch_table"], NODES["load_dependencies"])
    g.add_conditional_edges(
        NODES["load_dependencies"],
        route_after_dependencies,
        [NODES["plan_modification"], NODES["respond"]],
    )
    g.add_edge(NODES["plan_modification"], NODES["respond"])

    g.add_edge(NODES["respond"], END)
    return g.compile()


def graph_mermaid() -> str:
    """Mermaid source of the graph (shown in the UI sidebar)."""
    return build_graph().get_graph().draw_mermaid()
