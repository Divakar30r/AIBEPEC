"""The LangGraph: A -> B1 -> (B2 | B3) for create, A -> C1 -> C2 for modify.

    START -> check_intent --create + JSON--> create_ddl --+--> suggest_keys  --+--> respond -> END
                  |                                       +--> suggest_types -+
                  +--modify + table--> load_dependencies --found--> plan_modification -> respond
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
    respond,
    route_after_dependencies,
    route_after_intent,
)
from .state import AgentState
from .TableDependencies import load_dependencies


def build_graph():
    g = StateGraph(AgentState)

    g.add_node(NODES["intent"], check_intent)
    g.add_node(NODES["create_ddl"], create_ddl)
    g.add_node(NODES["suggest_keys"], suggest_keys)
    g.add_node(NODES["suggest_types"], suggest_types)
    g.add_node(NODES["load_dependencies"], load_dependencies)
    g.add_node(NODES["plan_modification"], plan_modification)
    g.add_node(NODES["respond"], respond)

    g.add_edge(START, NODES["intent"])
    g.add_conditional_edges(
        NODES["intent"],
        route_after_intent,
        [NODES["create_ddl"], NODES["load_dependencies"], NODES["respond"]],
    )

    # Create branch: B1 fans out to B2 and B3, which join in respond.
    g.add_edge(NODES["create_ddl"], NODES["suggest_keys"])
    g.add_edge(NODES["create_ddl"], NODES["suggest_types"])
    g.add_edge([NODES["suggest_keys"], NODES["suggest_types"]], NODES["respond"])

    # Modify branch.
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
