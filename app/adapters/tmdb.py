"""TMDB API v3 adapter -- read-only HTTP boundary for TMDB endpoints.

All requests automatically attach ``language=zh-CN`` and ``api_key`` as
query parameters.  The adapter follows the same pattern as
``app/adapters/mteam.py`` (``@dataclass(slots=True)``, ``_is_configured()``
guard, ``httpx.Client`` context manager, custom exception class).
"""

from dataclasses import dataclass
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TMDBError(Exception):
    """TMDB API 调用失败。"""


@dataclass(slots=True)
class TMDBAdapter:
    """Thin HTTP boundary for TMDB API v3 read-only endpoints.

    Parameters
    ----------
    api_key:
        TMDB API read access token (v3 auth).
    base_url:
        Defaults to ``https://api.themoviedb.org``.
    timeout_seconds:
        HTTP request timeout in seconds (default 10.0).
    """

    api_key: str
    base_url: str = "https://api.themoviedb.org"
    timeout_seconds: float = 10.0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_configured(self) -> bool:
        """Return ``True`` when *api_key* is non-empty (ignoring whitespace)."""
        return bool(self.api_key.strip())

    def _get(
        self,
        path: str,
        *,
        extra_params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Perform an authenticated ``GET`` to *base_url* + *path*.

        Parameters
        ----------
        path:
            URL path starting with ``/``, e.g. ``/3/search/multi``.
        extra_params:
            Optional query parameters merged on top of the standard
            ``api_key`` and ``language=zh-CN``.
        timeout:
            Override the default timeout for this single call.

        Returns
        -------
        Parsed JSON response body as a dict.

        Raises
        ------
        TMDBError
            On any HTTP error or JSON decoding failure.
        """
        params: dict[str, Any] = {
            "api_key": self.api_key,
            "language": "zh-CN",
        }
        if extra_params:
            params.update(extra_params)

        url = f"{self.base_url}{path}"
        effective_timeout = timeout if timeout is not None else self.timeout_seconds
        logger.debug("TMDB GET %s params=%s", url, params)

        try:
            with httpx.Client(timeout=effective_timeout) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                data: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("TMDB GET failed path=%s error=%s", path, exc)
            raise TMDBError(str(exc)) from exc

        return data

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def search_multi(
        self,
        query: str,
        *,
        page: int = 1,
        include_adult: bool = False,
    ) -> dict[str, Any]:
        """Search across movies, TV shows and people (``/3/search/multi``).

        Returns the full TMDB response dict, or an empty paginated
        structure when the adapter is not configured.
        """
        if not self._is_configured():
            logger.warning("TMDB search_multi skipped: adapter is not configured")
            return {"page": 1, "results": [], "total_pages": 0, "total_results": 0}

        logger.info("TMDB search_multi started query=%s page=%s", query, page)
        extra = {"query": query, "page": page, "include_adult": include_adult}
        return self._get("/3/search/multi", extra_params=extra)

    def movie_details(self, movie_id: int) -> dict[str, Any]:
        """Fetch movie details with ``external_ids`` appended.

        Returns the full TMDB response dict, or an empty dict when the
        adapter is not configured.
        """
        if not self._is_configured():
            logger.warning("TMDB movie_details skipped: adapter is not configured")
            return {}

        logger.info("TMDB movie_details started movie_id=%s", movie_id)
        return self._get(
            f"/3/movie/{movie_id}",
            extra_params={"append_to_response": "external_ids"},
        )

    def tv_details(self, series_id: int) -> dict[str, Any]:
        """Fetch TV series details with ``external_ids`` appended.

        Returns the full TMDB response dict, or an empty dict when the
        adapter is not configured.
        """
        if not self._is_configured():
            logger.warning("TMDB tv_details skipped: adapter is not configured")
            return {}

        logger.info("TMDB tv_details started series_id=%s", series_id)
        return self._get(
            f"/3/tv/{series_id}",
            extra_params={"append_to_response": "external_ids"},
        )

    def discover_movie(self, **filters: Any) -> dict[str, Any]:
        """Discover movies (``/3/discover/movie``) with optional filters.

        Example filters: ``sort_by``, ``with_genres``,
        ``primary_release_year``, ``vote_count_gte``.
        """
        if not self._is_configured():
            logger.warning("TMDB discover_movie skipped: adapter is not configured")
            return {"page": 1, "results": [], "total_pages": 0, "total_results": 0}

        logger.info("TMDB discover_movie started filters=%s", filters)
        extra = filters if filters else None
        return self._get("/3/discover/movie", extra_params=extra)

    def discover_tv(self, **filters: Any) -> dict[str, Any]:
        """Discover TV shows (``/3/discover/tv``) with optional filters.

        Example filters: ``first_air_date_year``, ``with_genres``.
        """
        if not self._is_configured():
            logger.warning("TMDB discover_tv skipped: adapter is not configured")
            return {"page": 1, "results": [], "total_pages": 0, "total_results": 0}

        logger.info("TMDB discover_tv started filters=%s", filters)
        extra = filters if filters else None
        return self._get("/3/discover/tv", extra_params=extra)

    def trending_all(self, time_window: str = "day") -> dict[str, Any]:
        """Get trending content across all media types.

        *time_window* can be ``"day"`` (default) or ``"week"``.
        """
        if not self._is_configured():
            logger.warning("TMDB trending_all skipped: adapter is not configured")
            return {"page": 1, "results": [], "total_pages": 0, "total_results": 0}

        logger.info("TMDB trending_all started time_window=%s", time_window)
        return self._get(f"/3/trending/all/{time_window}")

    def health(self) -> str:
        """Check TMDB API reachability and credentials.

        Calls ``GET /3/authentication`` directly so exception types
        are preserved for fine-grained status classification.  Returns
        one of ``"ok"``, ``"unconfigured"``, ``"unavailable"``, or
        ``"error"``.
        """
        if not self._is_configured():
            logger.warning("TMDB health check skipped: adapter is not configured")
            return "unconfigured"

        url = f"{self.base_url}/3/authentication"
        params = {"api_key": self.api_key}
        logger.info("TMDB health check started")

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
            return "ok"
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
            logger.warning("TMDB health check failed: unavailable")
            return "unavailable"
        except httpx.HTTPStatusError as exc:
            if 400 <= exc.response.status_code < 500:
                logger.warning("TMDB health check failed: error status=%s", exc.response.status_code)
                return "error"
            logger.warning("TMDB health check failed: unavailable status=%s", exc.response.status_code)
            return "unavailable"
        except Exception:
            logger.exception("TMDB health check failed: unexpected error")
            return "error"
