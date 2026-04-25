"""Centralized runtime settings loaded from environment variables.

The project is intentionally simple for now: one cached settings object shared
across adapters, API routes, and scripts.
"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel


def _load_project_env_file() -> None:
    """Load project-root `.env` values into process env when missing.

    Real environment variables keep precedence. `.env` only backfills absent
    keys to make local development more convenient.
    """

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if (
            len(value) >= 2
            and ((value[0] == "'" and value[-1] == "'") or (value[0] == '"' and value[-1] == '"'))
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_project_env_file()


class Settings(BaseModel):
    """Typed configuration surface used by the application."""

    app_name: str = "fnOS Media Agent"
    mteam_base_url: str = os.getenv("MTEAM_BASE_URL", "")
    mteam_api_key: str = os.getenv("MTEAM_API_KEY", "")
    qb_base_url: str = os.getenv("QB_BASE_URL", "")
    qb_username: str = os.getenv("QB_USERNAME", "")
    qb_password: str = os.getenv("QB_PASSWORD", "")
    database_path: str = os.getenv("DATABASE_PATH", "nas_media_agent.db")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached settings instance."""
    return Settings()
