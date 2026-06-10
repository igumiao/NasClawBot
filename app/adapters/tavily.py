"""Tavily Search API adapter -- read-only web search boundary."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TavilyError(Exception):
    """Tavily API call failed."""


@dataclass(slots=True)
class TavilyAdapter:
    """Thin HTTP boundary for Tavily Search API."""

    api_key: str
    base_url: str = "https://api.tavily.com"
    timeout_seconds: float = 20.0

    def _is_configured(self) -> bool:
        return bool(self.api_key.strip())

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        time_range: str | None = None,
    ) -> dict[str, Any]:
        """Search the web with Tavily.

        Returns Tavily's response shape, or an empty search response when the
        adapter is not configured.
        """
        if not self._is_configured():
            logger.warning("Tavily search skipped: adapter is not configured")
            return {
                "query": query,
                "answer": None,
                "results": [],
                "response_time": 0,
                "usage": {"credits": 0},
            }

        payload: dict[str, Any] = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "basic",
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
            "max_results": max_results,
        }
        if time_range:
            payload["time_range"] = time_range

        url = f"{self.base_url.rstrip('/')}/search"
        logger.info("Tavily search started query=%s max_results=%s", query, max_results)

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                data: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Tavily search failed error=%s", exc)
            raise TavilyError(str(exc)) from exc

        return data

    def health(self) -> str:
        """Check Tavily API reachability and credentials.

        Returns one of ``"ok"``, ``"unconfigured"``, ``"unavailable"``,
        or ``"error"``.
        """
        if not self._is_configured():
            logger.warning("Tavily health check skipped: adapter is not configured")
            return "unconfigured"

        payload = {
            "api_key": self.api_key,
            "query": "test",
            "search_depth": "basic",
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
            "max_results": 1,
        }
        url = f"{self.base_url.rstrip('/')}/search"
        logger.info("Tavily health check started")

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
            return "ok"
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
            logger.warning("Tavily health check failed: unavailable")
            return "unavailable"
        except httpx.HTTPStatusError as exc:
            if 400 <= exc.response.status_code < 500:
                logger.warning("Tavily health check failed: error status=%s", exc.response.status_code)
                return "error"
            logger.warning("Tavily health check failed: unavailable status=%s", exc.response.status_code)
            return "unavailable"
        except Exception:
            logger.exception("Tavily health check failed: unexpected error")
            return "error"
