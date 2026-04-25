"""Centralized runtime settings loaded from environment variables.

The project is intentionally simple for now: one cached settings object shared
across adapters, API routes, and scripts.
"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel


def _read_project_env_defaults() -> dict[str, str]:
    """Read project-root `.env` into a plain defaults dict.

    Environment variables from the real process still have higher precedence.
    """

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return {}
    parsed = dotenv_values(env_path)
    return {
        key: value
        for key, value in parsed.items()
        if key and value is not None
    }


_ENV_DEFAULTS = _read_project_env_defaults()


def _get_env(name: str, default: str = "") -> str:
    """Resolve config value from process env first, then `.env`, then default."""
    return os.getenv(name, _ENV_DEFAULTS.get(name, default))


class Settings(BaseModel):
    """Typed configuration surface used by the application."""

    app_name: str = "fnOS Media Agent"
    mteam_base_url: str = _get_env("MTEAM_BASE_URL")
    mteam_api_key: str = _get_env("MTEAM_API_KEY")
    qb_base_url: str = _get_env("QB_BASE_URL")
    qb_username: str = _get_env("QB_USERNAME")
    qb_password: str = _get_env("QB_PASSWORD")
    database_path: str = _get_env("DATABASE_PATH", "nas_media_agent.db")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached settings instance."""
    return Settings()
