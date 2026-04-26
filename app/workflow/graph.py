"""LangGraph wiring for search-to-confirmation and confirmation execution paths."""

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.domain.models import ConfirmationPayload
from app.llm.find_keyword_llm import FindKeywordLLM
from app.tools.search_tools import SearchTool
from app.workflow.nodes import (
    confirmation_payload_node,
    execute_download_with_executor_node,
    keyword_finder_node,
    search_node,
)
from app.workflow.state import AgentState


def build_workflow(
    keyword_finder=None,
    search_tool: SearchTool | None = None,
    download_executor: Callable[[dict[str, Any], str], dict[str, Any]] | None = None,
):
    """Build and compile a minimal graph with optional direct confirmation execution."""

    if keyword_finder is None:
        keyword_finder = FindKeywordLLM()
    if search_tool is None:
        raise ValueError("search_tool is required to build workflow.")
    if download_executor is None:
        download_executor = lambda _selected, _category: {
            "status": "submitted_paused",
            "qb_hash": "stub-hash",
        }

    def route_start(state: dict) -> str:
        if state.get("confirmation_payload"):
            return "execute_download"
        return "keyword_finder"

    graph = StateGraph(AgentState)
    graph.add_node(
        "execute_download",
        lambda state: execute_download_with_executor_node(state, download_executor),
    )
    graph.add_node(
        "keyword_finder",
        lambda state: keyword_finder_node(state, keyword_finder),
    )
    graph.add_node(
        "search_mteam",
        lambda state: search_node(state, search_tool),
    )
    graph.add_node("build_confirmation_payload", confirmation_payload_node)

    graph.add_conditional_edges(
        START,
        route_start,
        {
            "execute_download": "execute_download",
            "keyword_finder": "keyword_finder",
        },
    )
    graph.add_edge("execute_download", END)
    graph.add_edge("keyword_finder", "search_mteam")
    graph.add_edge("search_mteam", "build_confirmation_payload")
    graph.add_edge("build_confirmation_payload", END)

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
        confirmation_payload: dict[str, Any] | ConfirmationPayload | None,
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
        if isinstance(confirmation_payload, ConfirmationPayload):
            payload = confirmation_payload
        else:
            payload = ConfirmationPayload.model_validate(confirmation_payload)
        if selected_result_id:
            payload = payload.model_copy(update={"selected_result_id": selected_result_id})
        return self._graph.invoke({"session_id": session_id, "confirmation_payload": payload})
