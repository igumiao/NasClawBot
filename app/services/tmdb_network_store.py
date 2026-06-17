"""JSON persistence for TMDB network settings."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.domain.tmdb_network import (
    TMDBNetworkSettings,
    default_tmdb_network_settings,
)


SETTINGS_FILENAME = "tmdb-network.json"


class TMDBNetworkSettingsStore:
    """Small JSON store for TMDB-only network overrides."""

    def __init__(self, settings_dir: Path) -> None:
        self.settings_dir = settings_dir
        self.path = settings_dir / SETTINGS_FILENAME

    def load(self) -> TMDBNetworkSettings:
        if not self.path.exists():
            return default_tmdb_network_settings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default_tmdb_network_settings()
        if not isinstance(data, dict):
            return default_tmdb_network_settings()
        try:
            return TMDBNetworkSettings.model_validate(data)
        except ValidationError:
            return default_tmdb_network_settings()

    def save(self, settings: TMDBNetworkSettings) -> TMDBNetworkSettings:
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(settings.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return settings
