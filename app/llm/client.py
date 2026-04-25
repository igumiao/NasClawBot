"""LLM client interfaces and a practical local stub extractor.

The workflow depends on an `invoke(message)` contract. This file provides a
simple extractor that can be replaced by a real model-backed implementation in
later tasks without changing workflow wiring.
"""

from typing import Protocol


class ConstraintExtractor(Protocol):
    """Interface for extracting structured constraints from user language."""

    def invoke(self, message: str) -> dict:
        ...


class LocalConstraintExtractor:
    """Heuristic extractor used as a safe default during early development."""

    def invoke(self, message: str) -> dict:
        lowered = message.lower()
        optimization_goal = "speed" if any(
            token in lowered for token in ("tonight", "quick", "fast", "马上", "今晚")
        ) else "balanced"
        urgency = "high" if optimization_goal == "speed" else "normal"

        media_type = "unknown"
        if any(token in lowered for token in ("movie", "film", "电影")):
            media_type = "movie"
        elif any(token in lowered for token in ("series", "show", "tv", "剧")):
            media_type = "tv"

        return {
            "query_text": message,
            "title": None,
            "year": None,
            "media_type": media_type,
            "preferred_resolution": None,
            "allow_season_pack": True,
            "urgency": urgency,
            "optimization_goal": optimization_goal,
        }
