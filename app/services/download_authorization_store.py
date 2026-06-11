"""JSON persistence for download authorization settings."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.domain.authorization import (
    DownloadAuthorizationPolicy,
    default_download_authorization_policy,
)


POLICY_FILENAME = "download-authorization.json"


class DownloadAuthorizationPolicyStore:
    """Small JSON store for the single v1 download authorization policy."""

    def __init__(self, settings_dir: Path) -> None:
        self.settings_dir = settings_dir
        self.path = settings_dir / POLICY_FILENAME

    def load(self) -> DownloadAuthorizationPolicy:
        if not self.path.exists():
            return default_download_authorization_policy()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default_download_authorization_policy()
        if not isinstance(data, dict):
            return default_download_authorization_policy()
        try:
            return DownloadAuthorizationPolicy.model_validate(data)
        except ValidationError:
            return default_download_authorization_policy()

    def save(self, policy: DownloadAuthorizationPolicy) -> DownloadAuthorizationPolicy:
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(policy.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return policy
