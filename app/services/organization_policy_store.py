"""JSON persistence for organization automation policy settings."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.domain.organization import (
    OrganizationAutomationPolicy,
    default_organization_automation_policy,
)


POLICY_FILENAME = "organization-automation.json"


class OrganizationAutomationPolicyStore:
    """Small JSON store for the organization automation policy."""

    def __init__(self, settings_dir: Path) -> None:
        self.settings_dir = settings_dir
        self.path = settings_dir / POLICY_FILENAME

    def load(self) -> OrganizationAutomationPolicy:
        if not self.path.exists():
            return default_organization_automation_policy()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default_organization_automation_policy()
        if not isinstance(data, dict):
            return default_organization_automation_policy()
        try:
            return OrganizationAutomationPolicy.model_validate(data)
        except ValidationError:
            return default_organization_automation_policy()

    def save(self, policy: OrganizationAutomationPolicy) -> OrganizationAutomationPolicy:
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(policy.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return policy
