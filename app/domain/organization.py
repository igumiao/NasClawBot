"""Organization automation policy models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class OrganizationAutomationPolicy(BaseModel):
    """User-configured policy for automating media file organization.

    After a torrent download completes and is seeded, the organization
    automation system can move/rename media files according to this policy.
    Deletion and overwrite are permanently disabled for safety.
    """

    enabled: bool = False
    default_after_download: Literal["auto_organize", "notify_only"] = "notify_only"
    allowed_source_path_prefixes: list[str] = Field(default_factory=list)
    destination_root: str = ""
    allow_delete: bool = Field(default=False, frozen=True)
    allow_overwrite: bool = Field(default=False, frozen=True)

    @field_validator("allowed_source_path_prefixes", mode="before")
    @classmethod
    def _normalize_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [line for line in value.splitlines()]
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    @field_validator("allow_delete")
    @classmethod
    def _force_allow_delete(cls, value: bool) -> bool:
        return False

    @field_validator("allow_overwrite")
    @classmethod
    def _force_allow_overwrite(cls, value: bool) -> bool:
        return False


def default_organization_automation_policy() -> OrganizationAutomationPolicy:
    return OrganizationAutomationPolicy()
