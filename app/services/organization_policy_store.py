"""JSON persistence and one-way migration for organization authorization."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.domain.organization import (
    OrganizationAuthorizationPolicy,
    default_organization_authorization_policy,
)


POLICY_FILENAME = "organization-authorization.json"
LEGACY_POLICY_FILENAME = "organization-automation.json"


class OrganizationAuthorizationPolicyStore:
    """Fail-closed JSON store with legacy settings migration."""

    def __init__(self, settings_dir: Path) -> None:
        self.settings_dir = settings_dir
        self.path = settings_dir / POLICY_FILENAME
        self.legacy_path = settings_dir / LEGACY_POLICY_FILENAME

    def load(self) -> OrganizationAuthorizationPolicy:
        if self.path.exists():
            return self._load_current()
        migrated = self._load_legacy_for_migration()
        if migrated is None:
            return default_organization_authorization_policy()
        return self.save(migrated)

    def save(
        self,
        policy: OrganizationAuthorizationPolicy,
    ) -> OrganizationAuthorizationPolicy:
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(policy.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return policy

    def _load_current(self) -> OrganizationAuthorizationPolicy:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("policy JSON must be an object")
            return OrganizationAuthorizationPolicy.model_validate(data)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError):
            return default_organization_authorization_policy()

    def _load_legacy_for_migration(self) -> OrganizationAuthorizationPolicy | None:
        if not self.legacy_path.exists():
            return None
        try:
            data = json.loads(self.legacy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return OrganizationAuthorizationPolicy(
            background_organization_allowed=bool(data.get("enabled", False)),
            allowed_source_path_prefixes=data.get("allowed_source_path_prefixes", []),
            destination_root=data.get("destination_root", ""),
        )
