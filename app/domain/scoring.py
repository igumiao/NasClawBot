"""Deterministic ranking rules for search candidates.

Design intent:
- Keep ordering stable and testable (rule-based core).
- Expose simple reason tags that later LLM steps can translate into
  user-friendly explanations.
"""

import re
from collections.abc import Sequence

from app.domain.models import ResourceCandidate, ScoredCandidate, SearchConstraints

_RESOLUTION_TIERS: dict[str, int] = {
    "480p": 1,
    "720p": 2,
    "1080p": 3,
    "1440p": 4,
    "2160p": 5,
    "4k": 5,
}
_SEASON_PACK_HINTS = ("complete", "全集", "season", "s01-s", "s1-s", "全季")


def _tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric tokenization used by title-overlap scoring."""
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if token}


def _resolution_tier(value: str | None) -> int:
    """Map textual resolution to a comparable tier integer."""
    if not value:
        return 0
    normalized = value.strip().lower()
    return _RESOLUTION_TIERS.get(normalized, 0)


def _looks_like_season_pack(title: str) -> bool:
    """Heuristic check for bundled season/complete-pack titles."""
    lowered = title.lower()
    return any(hint in lowered for hint in _SEASON_PACK_HINTS)


def _score_candidate(constraints: SearchConstraints, candidate: ResourceCandidate) -> ScoredCandidate:
    """Score one candidate with additive rules and explainable reason tags."""
    score = 0.0
    reasons: list[str] = []

    if constraints.title:
        query_tokens = _tokenize(constraints.title)
        candidate_tokens = _tokenize(candidate.title)
        overlap = len(query_tokens.intersection(candidate_tokens))
        if overlap:
            score += min(overlap * 8.0, 32.0)
            reasons.append("title-token-overlap")
        if constraints.title.lower() in candidate.title.lower():
            score += 20.0
            reasons.append("title-substring-match")

    if constraints.media_type != "unknown":
        if candidate.media_type == constraints.media_type:
            score += 20.0
            reasons.append("media-type-match")
        else:
            score -= 35.0
            reasons.append("media-type-mismatch")

    if constraints.year and candidate.year:
        if constraints.year == candidate.year:
            score += 10.0
            reasons.append("year-match")
        elif abs(constraints.year - candidate.year) == 1:
            score += 5.0
            reasons.append("year-near-match")
        else:
            score -= 5.0
            reasons.append("year-mismatch")

    preferred_tier = _resolution_tier(constraints.preferred_resolution)
    candidate_tier = _resolution_tier(candidate.resolution)
    if preferred_tier and candidate_tier:
        tier_diff = abs(preferred_tier - candidate_tier)
        if tier_diff == 0:
            score += 10.0
            reasons.append("preferred-resolution-match")
        elif tier_diff == 1:
            score += 4.0
            reasons.append("preferred-resolution-near")
        else:
            score -= 4.0
            reasons.append("preferred-resolution-mismatch")

    if not constraints.allow_season_pack and _looks_like_season_pack(candidate.title):
        score -= 20.0
        reasons.append("season-pack-disallowed")

    seeders = max(candidate.seeders, 0)
    # Seeder weight changes by optimization goal:
    # speed > balanced > quality (for speed-sensitive viewing requests).
    if constraints.optimization_goal == "speed":
        score += min(seeders, 300) / 3.0
        reasons.append("seeder-boost-speed")
    elif constraints.optimization_goal == "quality":
        score += min(seeders, 300) / 40.0
        reasons.append("seeder-boost-quality-light")
    else:
        score += min(seeders, 300) / 15.0
        reasons.append("seeder-boost-balanced")

    if constraints.optimization_goal == "quality" and candidate_tier:
        score += candidate_tier * 4.0
        reasons.append("quality-resolution-boost")

    return ScoredCandidate(candidate=candidate, score=score, reasons=reasons)


def score_candidates(
    constraints: SearchConstraints | dict,
    candidates: Sequence[ResourceCandidate],
) -> list[ScoredCandidate]:
    """Score and sort candidates by score, then stable tie-breakers.

    Accepting `dict` keeps workflow integration simple while retaining strong
    typing once normalized.
    """
    normalized_constraints = (
        constraints
        if isinstance(constraints, SearchConstraints)
        else SearchConstraints.model_validate(constraints)
    )
    scored = [_score_candidate(normalized_constraints, candidate) for candidate in candidates]
    return sorted(
        scored,
        key=lambda item: (-item.score, -item.candidate.seeders, item.candidate.id),
    )
