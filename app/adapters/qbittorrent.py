"""qBittorrent adapter built on top of the qbittorrent-api client.

The adapter keeps the download surface small while exposing a
few higher-value task management operations for future agent features:
- login via the maintained client library,
- category listing,
- add-by-url (no local .torrent file write),
- task listing,
- single-task detail lookup,
- and basic task control operations.
"""

from dataclasses import dataclass
import logging
import re
from typing import Any

try:
    import qbittorrentapi
except ModuleNotFoundError:  # pragma: no cover - exercised via dependency install/runtime
    qbittorrentapi = None

logger = logging.getLogger(__name__)


def _read_value(payload: Any, key: str, default: Any = None) -> Any:
    """Read values from qB wrapper objects or plain dicts with one helper."""
    if payload is None:
        return default
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


@dataclass(slots=True)
class QBittorrentAdapter:
    """Boundary object for qBittorrent task operations."""

    base_url: str
    username: str
    password: str
    timeout_seconds: float = 10.0

    def _normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")

    def _is_configured(self) -> bool:
        return bool(self.base_url.strip() and self.username.strip() and self.password.strip())

    def _build_client(self):
        if qbittorrentapi is None:
            raise RuntimeError("qbittorrent-api is not installed")
        return qbittorrentapi.Client(
            host=self._normalized_base_url(),
            username=self.username,
            password=self.password,
            REQUESTS_ARGS={"timeout": self.timeout_seconds},
        )

    def login(self):
        """Create and authenticate a qBittorrent API client."""
        if not self._is_configured():
            logger.warning("qB login skipped: adapter is not configured")
            return None
        client = self._build_client()
        client.auth_log_in()
        logger.info("qB login succeeded base_url=%s", self._normalized_base_url())
        return client

    def build_add_payload(
        self,
        url: str,
        category: str,
        rename: str,
        paused: bool = False,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Validate and build the qbittorrent-api add kwargs."""
        clean_url = url.strip()
        clean_category = category.strip()
        clean_rename = rename.strip()
        clean_tags = [tag.strip() for tag in (tags or []) if tag.strip()]
        if not clean_url:
            raise ValueError("url must not be empty")
        if not clean_category:
            raise ValueError("category must not be empty")
        if not clean_rename:
            raise ValueError("rename must not be empty")

        payload: dict[str, Any] = {
            "urls": clean_url,
            "category": clean_category,
            "rename": clean_rename,
            "is_paused": paused,
        }
        if clean_tags:
            payload["tags"] = clean_tags
        return payload

    def list_categories(self) -> dict[str, Any]:
        """Read qB categories map, keyed by category name."""
        client = self.login()
        if client is None:
            return {}
        categories = _read_value(_read_value(client, "torrent_categories"), "categories", {})
        logger.info(
            "qB categories listed count=%s",
            len(categories) if isinstance(categories, dict) else 0,
        )
        return categories if isinstance(categories, dict) else {}

    def add_torrent_url(
        self,
        url: str,
        category: str,
        rename: str,
        paused: bool = False,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Submit tokenized URL to qB and return structured result."""
        client = self.login()
        if client is None:
            return {"ok": False, "status": "not_configured", "qb_hash": None}
        payload = self.build_add_payload(
            url=url,
            category=category,
            rename=rename,
            paused=paused,
            tags=tags,
        )
        logger.info(
            "qB add torrent started category=%s paused=%s tag_count=%s rename_chars=%s",
            payload["category"],
            paused,
            len(payload.get("tags", [])),
            len(payload["rename"]),
        )
        raw_response = client.torrents_add(**payload)
        body = str(raw_response).strip().lower()
        ok = body in {"ok.", "ok", "true"}
        submitted_status = "submitted_paused" if paused else "submitted"
        logger.info(
            "qB add torrent finished ok=%s status=%s raw_response=%s",
            ok,
            submitted_status if ok else "unknown",
            body,
        )
        return {
            "ok": ok,
            "status": submitted_status if ok else "unknown",
            "qb_hash": None,
            "raw_response": raw_response,
        }

    def _serialize_torrent_row(self, torrent: Any) -> dict[str, Any]:
        tags_value = str(_read_value(torrent, "tags", "") or "")
        return {
            "hash": str(_read_value(torrent, "hash", "") or ""),
            "name": str(_read_value(torrent, "name", "") or ""),
            "category": str(_read_value(torrent, "category", "") or ""),
            "tags": [tag.strip() for tag in tags_value.split(",") if tag.strip()],
            "state": str(_read_value(torrent, "state", "") or ""),
            "progress": float(_read_value(torrent, "progress", 0.0) or 0.0),
            "download_speed": int(_read_value(torrent, "dlspeed", 0) or 0),
            "upload_speed": int(_read_value(torrent, "upspeed", 0) or 0),
            "eta": int(_read_value(torrent, "eta", 0) or 0),
            "save_path": str(_read_value(torrent, "save_path", "") or ""),
            "size": int(_read_value(torrent, "size", 0) or 0),
            "total_size": int(_read_value(torrent, "total_size", 0) or 0),
        }

    def list_torrents(
        self,
        *,
        category: str | None = None,
        tag: str | None = None,
        limit: int | None = None,
        status_filter: str | None = None,
        sort: str | None = None,
        reverse: bool | None = None,
    ) -> list[dict[str, Any]]:
        """List tasks with lightweight structured fields for UI/agent use."""
        client = self.login()
        if client is None:
            return []

        kwargs: dict[str, Any] = {}
        if category and category.strip():
            kwargs["category"] = category.strip()
        if tag and tag.strip():
            kwargs["tag"] = tag.strip()
        if limit is not None:
            kwargs["limit"] = limit
        if status_filter and status_filter.strip():
            kwargs["status_filter"] = status_filter.strip()
        if sort and sort.strip():
            kwargs["sort"] = sort.strip()
        if reverse is not None:
            kwargs["reverse"] = reverse

        rows = client.torrents_info(**kwargs)
        serialized = [self._serialize_torrent_row(row) for row in rows]
        logger.info(
            "qB torrents listed result_count=%s category=%s tag=%s status_filter=%s",
            len(serialized),
            kwargs.get("category"),
            kwargs.get("tag"),
            kwargs.get("status_filter"),
        )
        return serialized

    def get_torrent(self, torrent_hash: str) -> dict[str, Any] | None:
        """Return one task with merged properties when found."""
        clean_hash = torrent_hash.strip()
        if not clean_hash:
            raise ValueError("torrent_hash must not be empty")

        client = self.login()
        if client is None:
            return None

        rows = client.torrents_info(torrent_hashes=clean_hash)
        if not rows:
            logger.info("qB torrent detail not found qb_hash=%s", clean_hash)
            return None
        result = self._serialize_torrent_row(rows[0])
        properties = client.torrents_properties(torrent_hash=clean_hash)
        result.update(
            {
                "comment": str(_read_value(properties, "comment", "") or ""),
                "total_uploaded": int(_read_value(properties, "total_uploaded", 0) or 0),
                "share_ratio": float(_read_value(properties, "share_ratio", 0.0) or 0.0),
                "creation_date": int(_read_value(properties, "creation_date", 0) or 0),
            }
        )
        logger.info("qB torrent detail fetched qb_hash=%s state=%s", clean_hash, result.get("state"))
        return result

    def control_torrent(
        self,
        torrent_hash: str,
        *,
        action: str,
        delete_files: bool = False,
    ) -> dict[str, Any]:
        """Dispatch supported lifecycle actions to qBittorrent."""
        clean_hash = torrent_hash.strip()
        if not clean_hash:
            raise ValueError("torrent_hash must not be empty")

        normalized_action = action.strip().lower()
        action_map = {
            "pause": "pause",
            "resume": "resume",
            "recheck": "recheck",
            "reannounce": "reannounce",
            "delete": "delete",
        }
        if normalized_action not in action_map:
            raise ValueError(f"Unsupported torrent action: {action}")

        client = self.login()
        if client is None:
            return {"ok": False, "status": "not_configured", "qb_hash": clean_hash}

        logger.info(
            "qB torrent action started qb_hash=%s action=%s delete_files=%s",
            clean_hash,
            normalized_action,
            delete_files,
        )
        if normalized_action == "pause":
            client.torrents_pause(torrent_hashes=clean_hash)
        elif normalized_action == "resume":
            client.torrents_resume(torrent_hashes=clean_hash)
        elif normalized_action == "recheck":
            client.torrents_recheck(torrent_hashes=clean_hash)
        elif normalized_action == "reannounce":
            client.torrents_reannounce(torrent_hashes=clean_hash)
        else:
            client.torrents_delete(
                torrent_hashes=clean_hash,
                delete_files=delete_files,
            )
        logger.info("qB torrent action finished qb_hash=%s action=%s", clean_hash, normalized_action)
        return {"ok": True, "status": normalized_action, "qb_hash": clean_hash}

    def set_global_speed_limits(
        self,
        upload_limit: int | None = None,
        download_limit: int | None = None,
    ) -> dict[str, Any]:
        """Set global transfer speed limits in bytes/s. None means no change."""
        client = self.login()
        if client is None:
            return {"ok": False, "status": "not_configured", "upload_limit": upload_limit, "download_limit": download_limit}

        if upload_limit is not None:
            client.transfer.upload_limit = upload_limit
        if download_limit is not None:
            client.transfer.download_limit = download_limit

        logger.info(
            "qB global speed limits set upload_limit=%s download_limit=%s",
            upload_limit,
            download_limit,
        )
        return {"ok": True, "upload_limit": upload_limit, "download_limit": download_limit}

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
