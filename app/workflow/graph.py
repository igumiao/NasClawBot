"""LangGraph wiring for search-to-confirmation and confirmation execution paths."""

from langgraph.graph import END, START, StateGraph

from app.llm.client import LocalConstraintExtractor
from app.workflow.nodes import (
    execute_download_node,
    extract_constraints_node,
    score_results_node,
    search_node,
)
from app.workflow.state import AgentState


def build_workflow(extractor=None, search_tool=None):
    """Build and compile a minimal graph with optional direct confirmation execution."""

    if extractor is None:
        extractor = LocalConstraintExtractor()
    if search_tool is None:
        raise ValueError("search_tool is required to build workflow.")

    def route_start(state: dict) -> str:
        if state.get("confirmation_payload"):
            return "execute_download"
        return "extract_constraints"

    graph = StateGraph(AgentState)
    graph.add_node("execute_download", execute_download_node)
    graph.add_node(
        "extract_constraints",
        lambda state: extract_constraints_node(state, extractor),
    )
    graph.add_node(
        "search_mteam",
        lambda state: search_node(state, search_tool),
    )
    graph.add_node("score_results", score_results_node)

    graph.add_conditional_edges(
        START,
        route_start,
        {
            "execute_download": "execute_download",
            "extract_constraints": "extract_constraints",
        },
    )
    graph.add_edge("execute_download", END)
    graph.add_edge("extract_constraints", "search_mteam")
    graph.add_edge("search_mteam", "score_results")
    graph.add_edge("score_results", END)

    return graph.compile()
