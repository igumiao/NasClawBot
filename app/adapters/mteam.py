"""M-Team adapter for search/detail/download-token operations.

Task 9 keeps this adapter intentionally small but functional:
- it preserves stable M-Team torrent ids as the external key,
- separates search from detail/download-url calls,
- and exposes normalization helpers so workflow code stays clean.
"""

from dataclasses import dataclass
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MTeamAdapter:
    """Small boundary object for M-Team API details."""

    base_url: str
    api_key: str
    timeout_seconds: float = 10.0

    def _normalized_base_url(self) -> str:
        """Avoid accidental double slashes when building endpoints."""
        return self.base_url.rstrip("/")

    def search_endpoint(self) -> str:
        return f"{self._normalized_base_url()}/api/torrent/search"

    def detail_endpoint(self) -> str:
        return f"{self._normalized_base_url()}/api/torrent/detail"

    def download_token_endpoint(self) -> str:
        return f"{self._normalized_base_url()}/api/torrent/genDlToken"

    def build_headers(self) -> dict[str, str]:
        """Build shared request headers for authenticated M-Team calls."""
        return {"x-api-key": self.api_key}

    def build_search_payload(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
        categories: list[int] | None = None,
    ) -> dict:
        """Validate and build search payload in one place."""
        clean_keyword = keyword.strip()
        if not clean_keyword:
            raise ValueError("keyword must not be empty")
        if page < 1:
            raise ValueError("page must be >= 1")
        if page_size < 1:
            raise ValueError("page_size must be >= 1")
        return {
            "mode": "normal",
            "keyword": clean_keyword,
            "categories": categories or [],
            "visible": 1,
            "pageNumber": page,
            "pageSize": page_size,
        }

    def build_detail_payload(self, torrent_id: str) -> dict[str, str]:
        """Payload shape for detail lookup by M-Team torrent id."""
        if not torrent_id.strip():
            raise ValueError("torrent_id must not be empty")
        return {"id": torrent_id.strip()}

    def build_download_token_payload(self, torrent_id: str) -> dict[str, str]:
        """Payload shape for download-token generation."""
        if not torrent_id.strip():
            raise ValueError("torrent_id must not be empty")
        return {"id": torrent_id.strip()}

    def _is_configured(self) -> bool:
        return bool(self.base_url.strip() and self.api_key.strip())

    def _post(
        self,
        endpoint: str,
        *,
        json_payload: dict[str, Any] | None = None,
        data_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                endpoint,
                headers=self.build_headers(),
                json=json_payload,
                data=data_payload,
            )
            response.raise_for_status()
            parsed = response.json()
            if not isinstance(parsed, dict):
                raise ValueError("M-Team API returned a non-object JSON payload.")
            return parsed

    @staticmethod
    def _is_success_response(payload: dict[str, Any]) -> bool:
        code = payload.get("code")
        if isinstance(code, str):
            if code.strip() == "0":
                return True
        elif isinstance(code, (int, float)):
            if int(code) == 0:
                return True
        message = str(payload.get("message", "")).upper()
        return message == "SUCCESS"

    def _response_data_or_none(self, payload: dict[str, Any]) -> Any:
        if not self._is_success_response(payload):
            return None
        return payload.get("data")

    def search_torrents_by_keyword(self, keyword: str, page: int = 1, page_size: int = 20) -> list[dict[str, Any]]:
        """Return normalized candidate rows from M-Team search."""
        if not self._is_configured():
            logger.warning("M-Team search skipped: adapter is not configured")
            return []
        logger.info(
            "M-Team search started keyword=%s page=%s page_size=%s",
            keyword,
            page,
            page_size,
        )
        payload = self.build_search_payload(keyword=keyword, page=page, page_size=page_size)
        raw = self._post(self.search_endpoint(), json_payload=payload)
        data = self._response_data_or_none(raw)
        if not isinstance(data, dict):
            logger.warning("M-Team search returned no usable data keyword=%s", keyword)
            return []
        items = data.get("data", [])
        if not isinstance(items, list):
            logger.warning("M-Team search returned unexpected item list keyword=%s", keyword)
            return []
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            torrent_id = str(item.get("id", "")).strip()
            if not torrent_id:
                continue
            status_info = item.get("status")
            if isinstance(status_info, dict):
                seeders = int(status_info.get("seeders", 0) or 0)
            else:
                seeders = int(item.get("seeders", 0) or 0)
            normalized.append(
                {
                    "id": torrent_id,
                    "title": str(item.get("smallDescr") or item.get("name") or f"M-Team {torrent_id}"),
                    "name": str(item.get("name") or item.get("smallDescr") or f"M-Team {torrent_id}"),
                    "seeders": seeders,
                    "size": self._format_size(item.get("size")),
                    "size_bytes": self._coerce_int(item.get("size")),
                    "source": "mteam",
                    "raw": item,
                }
            )
        logger.info(
            "M-Team search finished keyword=%s result_count=%s",
            keyword,
            len(normalized),
        )
        return normalized

    def get_torrent_details(self, torrent_id: str) -> dict[str, Any] | None:
        """Fetch full detail for a stable M-Team torrent id."""
        if not self._is_configured():
            logger.warning("M-Team detail skipped: adapter is not configured torrent_id=%s", torrent_id)
            return None
        logger.info("M-Team detail started torrent_id=%s", torrent_id)
        payload = self.build_detail_payload(torrent_id)
        raw = self._post(self.detail_endpoint(), data_payload=payload)
        data = self._response_data_or_none(raw)
        logger.info(
            "M-Team detail finished torrent_id=%s found=%s",
            torrent_id,
            isinstance(data, dict),
        )
        return data if isinstance(data, dict) else None

    def get_torrent_download_url(self, torrent_id: str) -> str | None:
        """Generate one-time download URL via M-Team genDlToken endpoint."""
        if not self._is_configured():
            logger.warning("M-Team download token skipped: adapter is not configured torrent_id=%s", torrent_id)
            return None
        logger.info("M-Team download token started torrent_id=%s", torrent_id)
        payload = self.build_download_token_payload(torrent_id)
        raw = self._post(self.download_token_endpoint(), data_payload=payload)
        data = self._response_data_or_none(raw)
        if not data:
            logger.warning("M-Team download token returned empty data torrent_id=%s", torrent_id)
            return None
        if not isinstance(data, str):
            logger.warning("M-Team download token returned non-string data torrent_id=%s", torrent_id)
            return None
        url = data.strip()
        logger.info(
            "M-Team download token finished torrent_id=%s url_present=%s",
            torrent_id,
            url.startswith("http"),
        )
        return url if url.startswith("http") else None

    def is_download_url_torrent(self, url: str) -> bool:
        """Validate that a token URL resolves to a torrent payload."""
        clean_url = (url or "").strip()
        if not clean_url.startswith("http"):
            logger.warning("Torrent URL validation skipped: URL is not HTTP")
            return False
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = client.get(clean_url)
                response.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Torrent URL validation failed during HTTP request")
            return False

        content_type = response.headers.get("content-type", "").lower()
        if "application/x-bittorrent" in content_type:
            logger.info("Torrent URL validation succeeded content_type=%s", content_type)
            return True
        # Some servers may not set the content-type consistently; bencode starts with 'd'.
        valid = response.content.startswith(b"d")
        logger.info("Torrent URL validation finished valid=%s content_type=%s", valid, content_type)
        return valid

    def search(self, keyword: str, page: int = 1, page_size: int = 20) -> list[dict[str, Any]]:
        return self.search_torrents_by_keyword(keyword=keyword, page=page, page_size=page_size)

    def get_detail(self, torrent_id: str) -> dict[str, Any] | None:
        return self.get_torrent_details(torrent_id=torrent_id)

    def get_download_url(self, torrent_id: str) -> str | None:
        return self.get_torrent_download_url(torrent_id=torrent_id)

    @staticmethod
    def _format_size(size_value: Any) -> str:
        try:
            size_bytes = int(size_value)
        except (TypeError, ValueError):
            return str(size_value or "unknown")
        if size_bytes <= 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        scale = 0
        value = float(size_bytes)
        while value >= 1024 and scale < len(units) - 1:
            value /= 1024
            scale += 1
        return f"{value:.2f} {units[scale]}"

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
