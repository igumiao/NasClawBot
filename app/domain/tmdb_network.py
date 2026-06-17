"""TMDB-specific network settings."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator, model_validator


class TMDBNetworkSettings(BaseModel):
    """User-configured network override for TMDB requests."""

    enabled: bool = False
    proxy_url: str = ""

    @field_validator("proxy_url", mode="before")
    @classmethod
    def _normalize_proxy_url(cls, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("TMDB proxy URL must start with http:// or https://")
        if not parsed.hostname:
            raise ValueError("TMDB proxy URL must include a host")
        return text

    @model_validator(mode="after")
    def _require_proxy_url_when_enabled(self) -> "TMDBNetworkSettings":
        if self.enabled and not self.proxy_url:
            raise ValueError("TMDB proxy URL is required when proxy is enabled")
        return self

    @property
    def active_proxy_url(self) -> str | None:
        if not self.enabled:
            return None
        proxy_url = self.proxy_url.strip()
        return proxy_url or None


def default_tmdb_network_settings() -> TMDBNetworkSettings:
    return TMDBNetworkSettings()
