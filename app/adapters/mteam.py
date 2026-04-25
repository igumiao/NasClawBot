"""M-Team adapter for search/detail/download-token operations.

Task 9 keeps this adapter intentionally small but functional:
- it preserves stable M-Team torrent ids as the external key,
- separates search from detail/download-url calls,
- and exposes normalization helpers so workflow code stays clean.
"""

from dataclasses import dataclass
from typing import Any

import httpx


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
        """Build shared request headers expected by current M-Team APIs."""
        return {
            "x-api-key": self.api_key,
            "content-type": "application/json",
        }

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

    def _post_json(self, endpoint: str, *, json_payload: dict[str, Any] | None = None, data_payload: dict[str, Any] | None = None) -> dict[str, Any]:
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

    def _response_data_or_none(self, payload: dict[str, Any]) -> Any:
        message = str(payload.get("message", "")).upper()
        if message != "SUCCESS":
            return None
        return payload.get("data")

    def search_torrents_by_keyword(self, keyword: str, page: int = 1, page_size: int = 20) -> list[dict[str, Any]]:
        """Return normalized candidate rows from M-Team search."""
        if not self._is_configured():
            return []
        payload = self.build_search_payload(keyword=keyword, page=page, page_size=page_size)
        raw = self._post_json(self.search_endpoint(), json_payload=payload)
        data = self._response_data_or_none(raw)
        if not isinstance(data, dict):
            return []
        items = data.get("data", [])
        if not isinstance(items, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            torrent_id = str(item.get("id", "")).strip()
            if not torrent_id:
                continue
            normalized.append(
                {
                    "id": torrent_id,
                    "title": str(item.get("smallDescr") or item.get("name") or f"M-Team {torrent_id}"),
                    "name": str(item.get("name") or item.get("smallDescr") or f"M-Team {torrent_id}"),
                    "seeders": int(item.get("status", {}).get("seeders", 0) or 0),
                    "size": self._format_size(item.get("size")),
                    "source": "mteam",
                    "raw": item,
                }
            )
        return normalized

    def get_torrent_details(self, torrent_id: str) -> dict[str, Any] | None:
        """Fetch full detail for a stable M-Team torrent id."""
        if not self._is_configured():
            return None
        payload = self.build_detail_payload(torrent_id)
        raw = self._post_json(self.detail_endpoint(), data_payload=payload)
        data = self._response_data_or_none(raw)
        return data if isinstance(data, dict) else None

    def get_torrent_download_url(self, torrent_id: str) -> str | None:
        """Generate one-time download URL via M-Team genDlToken endpoint."""
        if not self._is_configured():
            return None
        payload = self.build_download_token_payload(torrent_id)
        raw = self._post_json(self.download_token_endpoint(), data_payload=payload)
        data = self._response_data_or_none(raw)
        if not data:
            return None
        return str(data)

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
