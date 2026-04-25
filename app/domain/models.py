from typing import Literal

from pydantic import BaseModel, Field

MediaType = Literal["movie", "tv", "anime", "unknown"]
UrgencyLevel = Literal["normal", "high"]
OptimizationGoal = Literal["balanced", "speed", "quality"]


class SearchConstraints(BaseModel):
    query_text: str
    title: str | None = None
    year: int | None = None
    media_type: MediaType = "unknown"
    preferred_resolution: str | None = None
    allow_season_pack: bool = True
    urgency: UrgencyLevel = "normal"
    optimization_goal: OptimizationGoal = "balanced"


class ResourceCandidate(BaseModel):
    id: str
    title: str
    media_type: str
    year: int | None = None
    resolution: str | None = None
    seeders: int = 0
    size: str
    source: str


class ScoredCandidate(BaseModel):
    candidate: ResourceCandidate
    score: float
    reasons: list[str] = Field(default_factory=list)

