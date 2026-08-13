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


def _get_int_env(name: str, default: int = 0) -> int:
    """Resolve an integer config value from env vars."""
    raw = _get_env(name, str(default))
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise ValueError(f"{name} must be an integer.") from None


def _get_log_level_env(name: str, default: str = "INFO") -> str:
    """Resolve a logging level name with a clear validation error."""
    value = _get_env(name, default).strip().upper()
    valid_levels = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
    if value not in valid_levels:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(valid_levels))}.")
    return value


def _get_experience_code_env(name: str = "EXPERIENCE_ACCESS_CODE") -> str:
    """Load an optional five-character ASCII alphanumeric access code."""
    value = _get_env(name).strip()
    if value and (
        len(value) != 5
        or any(not (char.isascii() and char.isalnum()) for char in value)
    ):
        raise ValueError(
            f"{name} must be exactly five ASCII letters or digits when configured."
        )
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
    context_window: int = Field(default_factory=lambda: _get_int_env("CONTEXT_WINDOW", 128000))
    tmdb_api_key: str = Field(default_factory=lambda: _get_env("TMDB_API_KEY"))
    tavily_api_key: str = Field(default_factory=lambda: _get_env("TAVILY_API_KEY"))
    database_path: str = Field(default_factory=lambda: _get_env("DATABASE_PATH", "nas_media_agent.db"))
    download_default_save_path: str = Field(
        default_factory=lambda: _get_env("DOWNLOAD_DEFAULT_SAVE_PATH", ""),
    )
    qb_add_paused: bool = Field(
        default_factory=lambda: _get_bool_env("QB_ADD_PAUSED", False),
    )
    mcp_fs_enabled: bool = Field(
        default_factory=lambda: _get_bool_env("MCP_FS_ENABLED", True),
    )
    mcp_fs_allowed_dirs: str = Field(
        default_factory=lambda: _get_env("MCP_FS_ALLOWED_DIRS", ""),
    )
    experience_access_code: str = Field(
        default_factory=_get_experience_code_env,
        repr=False,
    )
    experience_trust_proxy_headers: bool = Field(
        default_factory=lambda: _get_bool_env("EXPERIENCE_TRUST_PROXY_HEADERS", False),
    )
    experience_trusted_proxy_cidrs: str = Field(
        default_factory=lambda: _get_env(
            "EXPERIENCE_TRUSTED_PROXY_CIDRS",
            "127.0.0.1/32,::1/128,172.16.0.0/12",
        ),
    )
    experience_local_long_session: bool = Field(
        default_factory=lambda: _get_bool_env("EXPERIENCE_LOCAL_LONG_SESSION", True),
    )
    experience_local_session_days: int = Field(
        default_factory=lambda: _get_int_env("EXPERIENCE_LOCAL_SESSION_DAYS", 180),
    )
    experience_local_cidrs: str = Field(
        default_factory=lambda: _get_env(
            "EXPERIENCE_LOCAL_CIDRS",
            (
                "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8,"
                "fc00::/7,fe80::/10,::1/128"
            ),
        ),
    )

    # ------------------------------------------------------------------
    # Runtime configuration (task orchestration, download watch, organize)
    # ------------------------------------------------------------------
    task_worker_tick_seconds: int = Field(
        default_factory=lambda: _get_int_env("TASK_WORKER_TICK_SECONDS", 2),
    )
    download_watch_poll_seconds: int = Field(
        default_factory=lambda: _get_int_env("DOWNLOAD_WATCH_POLL_SECONDS", 30),
    )
    download_watch_error_backoff_max_seconds: int = Field(
        default_factory=lambda: _get_int_env("DOWNLOAD_WATCH_ERROR_BACKOFF_MAX_SECONDS", 600),
    )
    task_lease_seconds: int = Field(
        default_factory=lambda: _get_int_env("TASK_LEASE_SECONDS", 120),
    )
    task_worker_concurrency: int = Field(
        default_factory=lambda: _get_int_env("TASK_WORKER_CONCURRENCY", 4),
    )
    download_watch_concurrency: int = Field(
        default_factory=lambda: _get_int_env("DOWNLOAD_WATCH_CONCURRENCY", 4),
    )
    organize_worker_concurrency: int = Field(
        default_factory=lambda: _get_int_env("ORGANIZE_WORKER_CONCURRENCY", 1),
    )
    qb_path_mapping: str = Field(
        default_factory=lambda: _get_env("QB_PATH_MAPPING", ""),
        description=(
            "Optional comma-separated path prefix translations for qB-reported "
            "paths, e.g. 'D:\\->/mnt/d/'.  Only needed when qBittorrent runs "
            "on a different OS from the MCP filesystem server (e.g. Windows "
            "qB + WSL server).  Empty string disables translation."
        ),
    )
    task_db_path: str = Field(
        default_factory=lambda: _get_env("TASK_DB_PATH", "memory/runtime/tasks.db"),
        description=(
            "Filesystem path to the runtime task SQLite database.  "
            "Override in tests to isolate from the production database."
        ),
    )
    task_purge_max_age_seconds: int = Field(
        default_factory=lambda: _get_int_env("TASK_PURGE_MAX_AGE_SECONDS", 3600),
        description=(
            "Maximum age (in seconds) for terminal tasks (SUCCEEDED, FAILED, "
            "CANCELLED) before they are purged from the database along with "
            "their run records.  Event lifetime is managed independently via "
            "EVENT_CONSUMED_PURGE_SECONDS and EVENT_MAX_AGE_SECONDS.  "
            "Default 3600 (1 hour)."
        ),
    )
    event_consumed_purge_seconds: int = Field(
        default_factory=lambda: _get_int_env("EVENT_CONSUMED_PURGE_SECONDS", 86400),
        description=(
            "Maximum age (in seconds) for task events that have been BOTH "
            "acknowledged AND injected before they are purged.  Ensures "
            "events are visible for a window after the user has seen "
            "them and the Agent has been notified.  Default 86400 (24 hours)."
        ),
    )
    event_max_age_seconds: int = Field(
        default_factory=lambda: _get_int_env("EVENT_MAX_AGE_SECONDS", 604800),
        description=(
            "Absolute maximum age (in seconds) for any task event before "
            "it is purged regardless of acknowledgement/injection status.  "
            "Default 604800 (7 days)."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached settings instance."""
    return Settings()
