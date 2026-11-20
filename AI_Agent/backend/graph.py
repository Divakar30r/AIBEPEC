"""The LangGraph: A -> B1 -> (B2 | B3) -> B4 for create, A -> C1 -> C2 for modify.

    START -> check_intent --create + JSON--> create_ddl --+--> suggest_keys  --(END)
                  |                              ^        +--> suggest_types --> ask_revision (B4)
                  |                              |                                 |  pauses: Y/other?
                  |                              +------------- Y (revise_ddl) ----+
                  |            (second pass: create_ddl -> suggest_keys only -> respond)
                  |                                                                +-- other --> respond
                  +--modify + table--Send x N tables--> fetch_table [C1A -> C1B] (parallel)
                                                              |
                                                       load_dependencies --found--> plan_modification -> respond
                  +--anything else (or table not found)--> respond

B2 and B3 run in parallel. B4 then pauses the graph with ``interrupt`` and asks whether to redo B1
with B3's types; the answer comes back through ``Command(resume=...)``. B2 and B3 are NOT joined
into ``respond``: after a revision B3 is skipped, and a join would wait for it forever.
"""

from langgraph.checkpoint.memory import InMemorySaver as LG_CP_InMemorySaver
from langgraph.graph import END as LG_END, START as LG_START, StateGraph as LG_StateGraph

from .Alternatetypes import suggest_types
from .BackendConstants import NODES
from .KeySuggestions import suggest_keys
from .Modifications import plan_modification
from .nodes import (
    ask_revision,
    check_intent,
    create_ddl,
    load_dependencies,
    respond,
    route_after_dependencies,
    route_after_ddl,
    route_after_intent,
    route_after_keys,
)
from .state import AgentState, TableFetchOutput, TableFetchState
from .SubGraphnodes import find_table, read_table, route_after_find


def build_table_fetch_graph():
    """The compiled C1A -> C1B subgraph, used as the ``fetch_table`` node of the main graph."""
    g = LG_StateGraph(TableFetchState, output_schema=TableFetchOutput)
    g.add_node(NODES["find_table"], find_table)
    g.add_node(NODES["read_table"], read_table)
    g.add_edge(LG_START, NODES["find_table"])
    g.add_conditional_edges(NODES["find_table"], route_after_find, [NODES["read_table"], LG_END])
    g.add_edge(NODES["read_table"], LG_END)
    return g.compile()


def build_graph():
    g = LG_StateGraph(AgentState)

    g.add_node(NODES["intent"], check_intent)
    g.add_node(NODES["create_ddl"], create_ddl)
    g.add_node(NODES["suggest_keys"], suggest_keys)
    g.add_node(NODES["suggest_types"], suggest_types)
    g.add_node(NODES["ask_revision"], ask_revision)  # B4: interrupt, then Command(goto=...)
    g.add_node(NODES["fetch_table"], build_table_fetch_graph())  # subgraph C1A -> C1B
    g.add_node(NODES["load_dependencies"], load_dependencies)
    g.add_node(NODES["plan_modification"], plan_modification)
    g.add_node(NODES["respond"], respond)

    g.add_edge(LG_START, NODES["intent"])
    g.add_conditional_edges(
        NODES["intent"],
        route_after_intent,
        [NODES["create_ddl"], NODES["fetch_table"], NODES["respond"]],
    )

    # Create branch: B1 fans out to B2 and B3 (only B2 after a revision). B3 leads to B4, which
    # sends the graph back to B1 (Y) or on to respond via Command(goto=...). B2 ends its branch
    # on the first pass and leads to respond after a revision.
    g.add_conditional_edges(
        NODES["create_ddl"],
        route_after_ddl,
        [NODES["suggest_keys"], NODES["suggest_types"]],
    )
    g.add_edge(NODES["suggest_types"], NODES["ask_revision"])
    g.add_conditional_edges(NODES["suggest_keys"], route_after_keys, [NODES["respond"], LG_END])

    # Modify branch: Send fans out one fetch_table subgraph run per table; load_dependencies (C1)
    # runs once all of them are done and joins their results.
    g.add_edge(NODES["fetch_table"], NODES["load_dependencies"])
    g.add_conditional_edges(
        NODES["load_dependencies"],
        route_after_dependencies,
        [NODES["plan_modification"], NODES["respond"]],
    )
    g.add_edge(NODES["plan_modification"], NODES["respond"])

    g.add_edge(NODES["respond"], LG_END)
    # The checkpointer is what lets B4's interrupt pause and resume (state is kept per thread_id).
    return g.compile(checkpointer=LG_CP_InMemorySaver())


def graph_mermaid() -> str:
    """Mermaid source of the graph (shown in the UI sidebar)."""
    return build_graph().get_graph().draw_mermaid()
