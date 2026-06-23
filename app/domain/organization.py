"""Authorization contracts for deterministic background organization."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class OrganizationAuthorizationPolicy(BaseModel):
    """Settings-backed authority boundary; never a behavior default."""

    model_config = {"validate_assignment": True}

    background_organization_allowed: bool = False
    allowed_source_path_prefixes: list[str] = Field(default_factory=list)
    destination_root: str = ""
    allow_delete: Literal[False] = False
    allow_overwrite: Literal[False] = False

    @model_validator(mode="before")
    @classmethod
    def _force_safety_locks(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = dict(value)
            value["allow_delete"] = False
            value["allow_overwrite"] = False
        return value

    @field_validator("allowed_source_path_prefixes", mode="before")
    @classmethod
    def _normalize_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = value.splitlines()
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    @field_validator("destination_root", mode="before")
    @classmethod
    def _normalize_destination(cls, value: Any) -> str:
        return str(value or "").strip()


class OrganizationAuthorizationSnapshot(BaseModel):
    """Immutable authority captured when an organize intent is created."""

    background_organization_allowed: Literal[True] = True
    allowed_source_path_prefixes: list[str]
    destination_root: str
    allow_delete: Literal[False] = False
    allow_overwrite: Literal[False] = False

    model_config = {"frozen": True}


def default_organization_authorization_policy() -> OrganizationAuthorizationPolicy:
    return OrganizationAuthorizationPolicy()
