"""JSON persistence for download defaults settings."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.domain.download_defaults import (
    DownloadDefaults,
    default_download_defaults,
)


DEFAULTS_FILENAME = "download-defaults.json"


class DownloadDefaultsStore:
    """Small JSON store for the user's download preference defaults."""

    def __init__(self, settings_dir: Path) -> None:
        self.settings_dir = settings_dir
        self.path = settings_dir / DEFAULTS_FILENAME

    def load(self) -> DownloadDefaults:
        if not self.path.exists():
            return default_download_defaults()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default_download_defaults()
        if not isinstance(data, dict):
            return default_download_defaults()
        try:
            return DownloadDefaults.model_validate(data)
        except ValidationError:
            return default_download_defaults()

    def save(self, defaults: DownloadDefaults) -> DownloadDefaults:
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(defaults.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return defaults
