"""Domain models shared by workflow and adapters.

Keeping these types centralized makes contracts easier to understand during
early development.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

MediaType = Literal["movie", "tv", "anime", "unknown"]
UrgencyLevel = Literal["normal", "high"]
OptimizationGoal = Literal["balanced", "speed", "quality"]


class SearchConstraints(BaseModel):
    """Normalized intent fields extracted from user language."""

    query_text: str
    title: str | None = None
    year: int | None = None
    media_type: MediaType = "unknown"
    preferred_resolution: str | None = None
    allow_season_pack: bool = True
    urgency: UrgencyLevel = "normal"
    optimization_goal: OptimizationGoal = "balanced"


class ResourceCandidate(BaseModel):
    """One normalized search result entry from an external source."""

    id: str
    title: str
    media_type: str
    year: int | None = None
    resolution: str | None = None
    seeders: int = 0
    size: str
    size_bytes: int | None = None
    source: str


class ConfirmationCandidate(BaseModel):
    """Minimal result fields carried across the confirmation boundary."""

    id: str
    title: str
    seeders: int = 0
    resolution: str | None = None
    size: str | None = None


class ConfirmationPayload(BaseModel):
    """Structured confirmation-stage payload shared by workflow and API."""

    summary: str = ""
    recommended_result_id: str | None = None
    results: list[ConfirmationCandidate] = Field(default_factory=list)
    selected_result_id: str | None = None
    qb_category: str | None = None
    execution_result: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None
