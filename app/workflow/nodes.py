"""Workflow nodes for search, confirmation, and execution in Phase 2A."""

from collections.abc import Callable
from typing import Any

from app.domain.models import ConfirmationCandidate, ConfirmationPayload, ResourceCandidate
from app.services.receipt_service import build_receipt
from app.tools.download_tools import prepare_download_execution
from app.tools.search_tools import search_mteam_candidates


def keyword_finder_node(state: dict, keyword_finder) -> dict:
    """Extract a single keyword from user text."""

    raw_output = keyword_finder.invoke(state["user_message"])
    keyword = _normalize_keyword_output(raw_output)
    return {"keyword": keyword}


def _normalize_keyword_output(raw_output: Any) -> str:
    if isinstance(raw_output, str) and raw_output.strip():
        return raw_output.strip()

    if isinstance(raw_output, dict):
        value = raw_output.get("keyword")
        if isinstance(value, str) and value.strip():
            return value.strip()

    raise TypeError(
        'keyword_finder must return a non-empty string or include a non-empty "keyword" field'
    )


def search_node(state: dict, search_tool) -> dict:
    """Execute search using one keyword."""

    results = search_mteam_candidates(search_tool, state["keyword"])
    normalized_results = [
        item if isinstance(item, ResourceCandidate) else ResourceCandidate.model_validate(item)
        for item in results
    ]
    return {"search_results": normalized_results}


def _build_confirmation_payload(candidates: list[ResourceCandidate]) -> ConfirmationPayload:
    if not candidates:
        return ConfirmationPayload(
            summary="I couldn't find matching candidates. You can refine your request.",
            recommended_result_id=None,
            results=[],
        )

    top = candidates[0]
    return ConfirmationPayload(
        summary="I found matching candidates and paused for confirmation.",
        recommended_result_id=top.id,
        results=[
            ConfirmationCandidate(
                id=item.id,
                title=item.title,
                seeders=item.seeders,
                resolution=item.resolution,
                size=item.size,
            )
            for item in candidates[:3]
        ],
    )


def confirmation_payload_node(state: dict) -> dict:
    """Convert search results into a minimal UI-ready confirmation payload."""

    payload = _build_confirmation_payload(state.get("search_results", []))
    return {
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

    payload = _coerce_confirmation_payload(state.get("confirmation_payload"))
    selected_result = _resolve_selected_result(payload)
    selected_result_id = selected_result.id
    selected_result_data = selected_result.model_dump(exclude_none=True)

    execution = prepare_download_execution(selected_result_data)
    qb_category = payload.qb_category or "movie"
    execution_outcome = download_executor(selected_result_data, qb_category)
    qb_hash = execution_outcome.get("qb_hash")
    status = str(execution_outcome.get("status", "submitted_paused"))
    receipt = build_receipt(
        resource_title=execution["resource_title"],
        external_id=execution["external_id"],
        qb_category=qb_category,
        qb_hash=str(qb_hash) if qb_hash else None,
        status=status,
    )
    enriched_payload = payload.model_copy(
        update={
            "selected_result_id": selected_result_id,
            "execution_result": execution,
            "receipt": receipt,
        }
    )
    return {
        "confirmation_payload": enriched_payload,
        "receipt": receipt,
        "status": "completed" if status in {"submitted", "submitted_paused"} else status,
    }


def _coerce_confirmation_payload(raw_payload: Any) -> ConfirmationPayload:
    if isinstance(raw_payload, ConfirmationPayload):
        return raw_payload
    if isinstance(raw_payload, dict):
        return ConfirmationPayload.model_validate(raw_payload)
    return ConfirmationPayload()


def _resolve_selected_result(payload: ConfirmationPayload) -> ConfirmationCandidate:
    results = payload.results
    selected_result_id = payload.selected_result_id or payload.recommended_result_id
    if not selected_result_id and results:
        selected_result_id = results[0].id
    if not selected_result_id:
        raise ValueError("confirmation_payload must contain at least one selectable result.")

    selected = next((item for item in results if item.id == selected_result_id), None)
    if selected is None:
        raise ValueError(f"Selected result id '{selected_result_id}' was not found in results.")
    return selected


def _default_download_executor(selected_result: dict[str, Any], qb_category: str) -> dict[str, Any]:
    """Fallback executor used in tests/dev when adapters are not injected."""
    _ = selected_result
    _ = qb_category
    return {"status": "submitted_paused", "qb_hash": "stub-hash"}
