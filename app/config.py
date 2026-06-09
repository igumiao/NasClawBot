"""Centralized runtime settings loaded from environment variables.

The project is intentionally simple for now: one cached settings object shared
across adapters, API routes, and scripts.
"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, Field


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


def _get_bool_env(name: str, default: bool = False) -> bool:
    """Resolve a boolean config value with common string forms."""
    raw_value = _get_env(name, "true" if default else "false")
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean-like value.")


def _get_log_level_env(name: str, default: str = "INFO") -> str:
    """Resolve a logging level name with a clear validation error."""
    value = _get_env(name, default).strip().upper()
    valid_levels = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
    if value not in valid_levels:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(valid_levels))}.")
    return value


class Settings(BaseModel):
    """Typed configuration surface used by the application."""

    app_name: str = "fnOS Media Agent"
    mteam_base_url: str = Field(default_factory=lambda: _get_env("MTEAM_BASE_URL"))
    mteam_api_key: str = Field(default_factory=lambda: _get_env("MTEAM_API_KEY"))
    qb_base_url: str = Field(default_factory=lambda: _get_env("QB_BASE_URL"))
    qb_username: str = Field(default_factory=lambda: _get_env("QB_USERNAME"))
    qb_password: str = Field(default_factory=lambda: _get_env("QB_PASSWORD"))
    llm_model: str = Field(default_factory=lambda: _get_env("LLM_MODEL", "deepseek-v4-pro"))
    llm_api_key: str = Field(default_factory=lambda: _get_env("LLM_API_KEY"))
    llm_base_url: str = Field(default_factory=lambda: _get_env("LLM_BASE_URL", "https://api.deepseek.com"))
    llm_reasoning_split: bool = Field(default_factory=lambda: _get_bool_env("LLM_REASONING_SPLIT", True))
    llm_log_raw_output: bool = Field(default_factory=lambda: _get_bool_env("LLM_LOG_RAW_OUTPUT", False))
    log_level: str = Field(default_factory=lambda: _get_log_level_env("LOG_LEVEL", "INFO"))
    app_timezone: str = Field(default_factory=lambda: _get_env("APP_TIMEZONE", "Asia/Shanghai"))
    tmdb_api_key: str = Field(default_factory=lambda: _get_env("TMDB_API_KEY"))
    tavily_api_key: str = Field(default_factory=lambda: _get_env("TAVILY_API_KEY"))
    database_path: str = Field(default_factory=lambda: _get_env("DATABASE_PATH", "nas_media_agent.db"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached settings instance."""
    return Settings()
