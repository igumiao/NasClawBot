"""Workflow nodes for search, confirmation, and execution in Phase 1."""

from collections.abc import Callable
from typing import Any

from app.domain.models import ResourceCandidate, ScoredCandidate
from app.services.receipt_service import build_receipt
from app.tools.download_tools import prepare_download_execution
from app.domain.scoring import score_candidates
from app.tools.search_tools import search_mteam_candidates


def extract_constraints_node(state: dict, extractor) -> dict:
    """Extract structured search constraints from user text."""

    return {"constraints": extractor.invoke(state["user_message"])}


def search_node(state: dict, search_tool) -> dict:
    """Execute search using normalized constraints."""

    results = search_mteam_candidates(search_tool, state["constraints"])
    normalized_results = [
        item if isinstance(item, ResourceCandidate) else ResourceCandidate.model_validate(item)
        for item in results
    ]
    return {"search_results": normalized_results}


def _build_confirmation_payload(scored: list[ScoredCandidate]) -> dict:
    if not scored:
        return {
            "summary": "I couldn't find matching candidates. You can refine your request.",
            "recommended_result_id": None,
            "results": [],
            "explanation": "No candidates were returned from the search tool.",
        }

    top = scored[0]
    explanation = (
        "This result ranked first based on deterministic relevance and availability rules."
    )
    return {
        "summary": "I found matching candidates and paused for confirmation.",
        "recommended_result_id": top.candidate.id,
        "results": [
            {
                "id": item.candidate.id,
                "title": item.candidate.title,
                "score": item.score,
                "seeders": item.candidate.seeders,
                "resolution": item.candidate.resolution,
                "reasons": item.reasons,
            }
            for item in scored[:5]
        ],
        "explanation": explanation,
    }


def score_results_node(state: dict) -> dict:
    """Rank search results and convert them into a UI-ready confirmation payload."""

    scored = score_candidates(state["constraints"], state.get("search_results", []))
    payload = _build_confirmation_payload(scored)
    return {
        "scored_results": scored,
        "confirmation_payload": payload,
        "status": "awaiting_confirmation",
    }


def execute_download_node(state: dict) -> dict:
    """Build a deterministic execution + receipt result from a confirmed candidate."""
    return execute_download_with_executor_node(state, _default_download_executor)


def execute_download_with_executor_node(
    state: dict[str, Any],
    download_executor: Callable[[dict[str, Any], str], dict[str, Any]],
) -> dict[str, Any]:
    """Execute the confirmed selection through an injected executor."""

    payload = state.get("confirmation_payload", {})
    selected_result = _resolve_selected_result(payload)
    selected_result_id = str(selected_result["id"])

    execution = prepare_download_execution(selected_result)
    qb_category = str(payload.get("qb_category", "movie"))
    execution_outcome = download_executor(selected_result, qb_category)
    qb_hash = execution_outcome.get("qb_hash")
    status = str(execution_outcome.get("status", "submitted"))
    receipt = build_receipt(
        resource_title=execution["resource_title"],
        external_id=execution["external_id"],
        qb_category=qb_category,
        qb_hash=str(qb_hash) if qb_hash else None,
        status=status,
    )
    enriched_payload = {
        **payload,
        "selected_result_id": selected_result_id,
        "execution_result": execution,
        "receipt": receipt,
    }
    return {
        "confirmation_payload": enriched_payload,
        "receipt": receipt,
        "status": "completed" if status == "submitted" else status,
    }


def _resolve_selected_result(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results", [])
    selected_result_id = payload.get("selected_result_id") or payload.get("recommended_result_id")
    if not selected_result_id and results:
        selected_result_id = results[0].get("id")
    if not selected_result_id:
        raise ValueError("confirmation_payload must contain at least one selectable result.")

    selected = next((item for item in results if item.get("id") == selected_result_id), None)
    if selected is None:
        raise ValueError(f"Selected result id '{selected_result_id}' was not found in results.")
    return selected


def _default_download_executor(selected_result: dict[str, Any], qb_category: str) -> dict[str, Any]:
    """Fallback executor used in tests/dev when adapters are not injected."""
    _ = selected_result
    _ = qb_category
    return {"status": "submitted", "qb_hash": "stub-hash"}
