"""LangGraph wiring for the Task 6 search-to-confirmation workflow."""

from langgraph.graph import END, START, StateGraph

from app.llm.client import LocalConstraintExtractor
from app.workflow.nodes import extract_constraints_node, score_results_node, search_node
from app.workflow.state import AgentState


def build_workflow(extractor=None, search_tool=None):
    """Build and compile the minimal graph used by Task 6 tests."""

    if extractor is None:
        extractor = LocalConstraintExtractor()
    if search_tool is None:
        raise ValueError("search_tool is required to build workflow for Task 6.")

    graph = StateGraph(AgentState)
    graph.add_node(
        "extract_constraints",
        lambda state: extract_constraints_node(state, extractor),
    )
    graph.add_node(
        "search_mteam",
        lambda state: search_node(state, search_tool),
    )
    graph.add_node("score_results", score_results_node)

    graph.add_edge(START, "extract_constraints")
    graph.add_edge("extract_constraints", "search_mteam")
    graph.add_edge("search_mteam", "score_results")
    graph.add_edge("score_results", END)

    return graph.compile()
