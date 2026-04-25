"""LangGraph wiring for search-to-confirmation and confirmation execution paths."""

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.llm.client import LocalConstraintExtractor
from app.tools.search_tools import SearchTool
from app.workflow.nodes import (
    execute_download_with_executor_node,
    extract_constraints_node,
    score_results_node,
    search_node,
)
from app.workflow.state import AgentState


def build_workflow(
    extractor=None,
    search_tool: SearchTool | None = None,
    download_executor: Callable[[dict[str, Any], str], dict[str, Any]] | None = None,
):
    """Build and compile a minimal graph with optional direct confirmation execution."""

    if extractor is None:
        extractor = LocalConstraintExtractor()
    if search_tool is None:
        raise ValueError("search_tool is required to build workflow.")
    if download_executor is None:
        download_executor = lambda _selected, _category: {
            "status": "submitted",
            "qb_hash": "stub-hash",
        }

    def route_start(state: dict) -> str:
        if state.get("confirmation_payload"):
            return "execute_download"
        return "extract_constraints"

    graph = StateGraph(AgentState)
    graph.add_node(
        "execute_download",
        lambda state: execute_download_with_executor_node(state, download_executor),
    )
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


class LangGraphWorkflowRunner:
    """Thin facade used by API routes for chat/confirm actions."""

    def __init__(self, graph):
        self._graph = graph

    def run_chat(self, session_id: str, message: str) -> dict[str, Any]:
        return self._graph.invoke({"session_id": session_id, "user_message": message})

    def run_confirm(
        self,
        session_id: str,
        *,
        action: str,
        confirmation_payload: dict[str, Any] | None,
        selected_result_id: str | None = None,
        feedback_text: str | None = None,
    ) -> dict[str, Any]:
        normalized_action = action.strip().lower()
        if normalized_action == "cancel":
            return {
                "session_id": session_id,
                "status": "canceled",
                "messages": ["Request canceled by user."],
            }

        if normalized_action == "reject_and_refine":
            if not (feedback_text or "").strip():
                return {
                    "session_id": session_id,
                    "status": "error",
                    "error": "feedback_text is required for reject_and_refine.",
                }
            return self.run_chat(session_id=session_id, message=feedback_text or "")

        if normalized_action != "approve":
            return {
                "session_id": session_id,
                "status": "error",
                "error": f"Unsupported action: {action}",
            }
        if not confirmation_payload:
            return {
                "session_id": session_id,
                "status": "error",
                "error": "confirmation_payload is required for approve.",
            }
        payload = dict(confirmation_payload)
        if selected_result_id:
            payload["selected_result_id"] = selected_result_id
        return self._graph.invoke({"session_id": session_id, "confirmation_payload": payload})
