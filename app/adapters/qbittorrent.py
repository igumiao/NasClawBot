"""qBittorrent adapter for URL-based torrent submission.

Task 9 keeps qB integration scoped to what the MVP needs:
- login,
- category listing,
- add-by-url (no local .torrent file write),
- and deterministic name generation based on external ids.
"""

from dataclasses import dataclass
import re
from typing import Any

import httpx


@dataclass(slots=True)
class QBittorrentAdapter:
    """Boundary object for qBittorrent Web API specifics."""

    base_url: str
    username: str
    password: str
    timeout_seconds: float = 10.0

    def _normalized_base_url(self) -> str:
        """Avoid trailing-slash inconsistencies across endpoint builders."""
        return self.base_url.rstrip("/")

    def login_endpoint(self) -> str:
        return f"{self._normalized_base_url()}/api/v2/auth/login"

    def add_torrent_endpoint(self) -> str:
        return f"{self._normalized_base_url()}/api/v2/torrents/add"

    def categories_endpoint(self) -> str:
        return f"{self._normalized_base_url()}/api/v2/torrents/categories"

    def build_login_payload(self) -> dict[str, str]:
        """Payload expected by qB login endpoint."""
        return {"username": self.username, "password": self.password}

    def build_add_payload(
        self,
        url: str,
        category: str,
        rename: str,
        paused: bool = False,
        tags: list[str] | None = None,
    ) -> dict[str, str]:
        """Validate and build the add-torrent form payload."""
        clean_url = url.strip()
        clean_category = category.strip()
        clean_rename = rename.strip()
        if not clean_url:
            raise ValueError("url must not be empty")
        if not clean_category:
            raise ValueError("category must not be empty")
        if not clean_rename:
            raise ValueError("rename must not be empty")

        payload: dict[str, str] = {
            "urls": clean_url,
            "category": clean_category,
            "rename": clean_rename,
            "paused": "true" if paused else "false",
        }
        # qB expects comma-separated tag text in form payloads.
        if tags:
            payload["tags"] = ",".join(tag.strip() for tag in tags if tag.strip())
        return payload

    def _is_configured(self) -> bool:
        return bool(self.base_url.strip() and self.username.strip() and self.password.strip())

    def login(self) -> httpx.Cookies | None:
        """Log in and return auth cookies when available."""
        if not self._is_configured():
            return None
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(self.login_endpoint(), data=self.build_login_payload())
            response.raise_for_status()
            return response.cookies

    def list_categories(self) -> dict[str, Any]:
        """Read qB categories map, keyed by category name."""
        cookies = self.login()
        if cookies is None:
            return {}
        with httpx.Client(timeout=self.timeout_seconds, cookies=cookies) as client:
            response = client.get(self.categories_endpoint())
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}

    def add_torrent_url(
        self,
        url: str,
        category: str,
        rename: str,
        paused: bool = False,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Submit tokenized URL to qB and return structured result."""
        cookies = self.login()
        if cookies is None:
            return {"ok": False, "status": "not_configured", "qb_hash": None}
        payload = self.build_add_payload(
            url=url,
            category=category,
            rename=rename,
            paused=paused,
            tags=tags,
        )
        with httpx.Client(timeout=self.timeout_seconds, cookies=cookies) as client:
            response = client.post(self.add_torrent_endpoint(), data=payload)
            response.raise_for_status()
            body = response.text.strip().lower()
            ok = body in {"ok.", "ok"}
            submitted_status = "submitted_paused" if paused else "submitted"
            return {
                "ok": ok,
                "status": submitted_status if ok else "unknown",
                "qb_hash": None,
                "raw_response": response.text,
            }

    @staticmethod
    def generate_mteam_torrent_name(mteam_id: str, detail: dict[str, Any], qb_category: str) -> str:
        """Generate stable qB name anchored on M-Team torrent id."""
        title = str(detail.get("smallDescr") or detail.get("name") or f"M-Team-{mteam_id}")
        category = re.sub(r"[\\/*?:\"<>|\s]+", "_", qb_category.strip()).strip("._-")
        title = re.sub(r"[\\/*?:\"<>|]+", "", title).strip()
        title = re.sub(r"\s+", ".", title)[:96]
        parts = [f"[{mteam_id}]"]
        if category:
            parts.append(f"[{category[:30]}]")
        parts.append(f"[{title}]")
        return "".join(parts)[:250]
