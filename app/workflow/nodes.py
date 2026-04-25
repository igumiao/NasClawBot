"""Workflow nodes for the minimal Task 6 LangGraph path."""

from app.domain.models import ResourceCandidate, ScoredCandidate
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
