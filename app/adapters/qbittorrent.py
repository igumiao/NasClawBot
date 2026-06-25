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

from __future__ import annotations

from dataclasses import dataclass

import logging
import re
from typing import Any

try:
    import qbittorrentapi
except ModuleNotFoundError:  # pragma: no cover - exercised via dependency install/runtime
    qbittorrentapi = None

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 错误分类 — 把 qbittorrent-api 的异常体系翻译为 Agent 可理解的错误码
# ---------------------------------------------------------------------------


def _classify_qb_error(exc: Exception) -> dict[str, Any]:
    """将 qB API 异常分类为结构化错误字典，Agent 可据此决定重试/放弃/请求用户介入。

    返回字段:
        error_code:   机器可读错误码 (NETWORK_ERROR / AUTH_ERROR / TIMEOUT / …)
        error_message: 中文可读描述
        retryable:     是否可重试
    """
    exc_name = type(exc).__name__

    # 连接层错误 — 可重试
    if exc_name in ("APIConnectionError",):
        return {
            "error_code": "NETWORK_ERROR",
            "error_message": f"无法连接 qBittorrent，请检查 qB 是否运行及网络连通性 ({exc})",
            "retryable": True,
        }

    # 认证错误 — 不可重试，需用户修改配置
    if exc_name in ("Forbidden403Error", "Unauthorized401Error"):
        return {
            "error_code": "AUTH_ERROR",
            "error_message": f"qBittorrent 认证失败，请检查用户名密码配置 ({exc})",
            "retryable": False,
        }

    # 404 — 目标不存在
    if exc_name in ("NotFound404Error",):
        return {
            "error_code": "NOT_FOUND",
            "error_message": f"目标不存在（种子 hash 无效或已被删除）({exc})",
            "retryable": False,
        }

    # 409 — 冲突（通常为种子已存在）
    if exc_name in ("Conflict409Error",):
        return {
            "error_code": "CONFLICT",
            "error_message": f"种子已存在于 qBittorrent 中 ({exc})",
            "retryable": False,
        }

    # 400 — 请求参数错误
    if exc_name in ("InvalidRequest400Error", "MissingRequiredParameters400Error"):
        return {
            "error_code": "INVALID_REQUEST",
            "error_message": f"请求参数无效: {exc}",
            "retryable": False,
        }

    # 415 — 不支持的媒体类型
    if exc_name in ("UnsupportedMediaType415Error",):
        return {
            "error_code": "INVALID_REQUEST",
            "error_message": f"qBittorrent 不支持该请求类型 ({exc})",
            "retryable": False,
        }

    # 5xx — qB 内部错误，可重试
    if exc_name in ("InternalServerError500Error",):
        return {
            "error_code": "QB_INTERNAL_ERROR",
            "error_message": f"qBittorrent 内部错误，可稍后重试 ({exc})",
            "retryable": True,
        }

    # 文件错误
    if exc_name in ("FileError", "TorrentFileError", "TorrentFileNotFoundError", "TorrentFilePermissionError"):
        return {
            "error_code": "FILE_ERROR",
            "error_message": f"文件操作失败: {exc}",
            "retryable": False,
        }

    # HTTP 基类 — 按状态码范围兜底
    if exc_name in ("HTTP400Error", "HTTP4XXError"):
        return {
            "error_code": "CLIENT_ERROR",
            "error_message": f"qBittorrent 请求错误 (4xx): {exc}",
            "retryable": False,
        }
    if exc_name in ("HTTP500Error", "HTTP5XXError"):
        return {
            "error_code": "QB_INTERNAL_ERROR",
            "error_message": f"qBittorrent 服务器错误 (5xx)，可稍后重试 ({exc})",
            "retryable": True,
        }

    # 超时
    if exc_name in ("TimeoutError",) or "timeout" in exc_name.lower():
        return {
            "error_code": "TIMEOUT",
            "error_message": f"qBittorrent 请求超时 ({exc})",
            "retryable": True,
        }

    # 通用 HTTP 错误
    if exc_name in ("HTTPError", "APIError"):
        return {
            "error_code": "HTTP_ERROR",
            "error_message": f"qBittorrent API 错误: {exc}",
            "retryable": False,
        }

    # 未知异常
    return {
        "error_code": "UNKNOWN_ERROR",
        "error_message": f"qBittorrent 未知错误: {exc}",
        "retryable": False,
    }


def _build_error_result(exc: Exception, operation: str) -> dict[str, Any]:
    """将异常 + 操作名包装为统一错误返回字典。"""
    error = _classify_qb_error(exc)
    logger.warning("qB %s failed code=%s retryable=%s exc=%s", operation, error["error_code"], error["retryable"], exc)
    return {"ok": False, "status": "error", **error}


def _read_value(payload: Any, key: str, default: Any = None) -> Any:
    """Read values from qB wrapper objects or plain dicts with one helper."""
    if payload is None:
        return default
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


@dataclass
class QBittorrentAdapter:
    """Boundary object for qBittorrent task operations.

    Caches the authenticated client after the first ``login()`` call so
    subsequent operations within the same adapter instance reuse the
    session cookie without a fresh auth round-trip.
    """

    base_url: str
    username: str
    password: str
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        self._client: Any = None

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
        """Return an authenticated qBittorrent API client, caching on first call."""
        if not self._is_configured():
            logger.warning("qB login skipped: adapter is not configured")
            return None
        if self._client is not None:
            return self._client
        self._client = self._build_client()
        self._client.auth_log_in()
        logger.info("qB login succeeded base_url=%s", self._normalized_base_url())
        return self._client

    def health(self) -> str:
        """Check qBittorrent API reachability and credentials.

        Uses ``login()`` as a connectivity+auth probe.  Returns one of
        ``"ok"``, ``"unconfigured"``, ``"unavailable"``, or ``"error"``.
        """
        if not self._is_configured():
            logger.warning("qB health check skipped: adapter is not configured")
            return "unconfigured"

        if qbittorrentapi is None:
            logger.warning("qB health check failed: qbittorrent-api not installed")
            return "error"

        logger.info("qB health check started")
        try:
            client = self._build_client()
            client.auth_log_in()
            return "ok"
        except Exception as exc:
            exc_type = type(exc).__name__.lower()
            exc_str = str(exc).lower()
            # Connection failures (DNS, refused, timeout) → unavailable
            if any(kw in exc_type for kw in ("connection", "timeout", "connect")):
                logger.warning("qB health check failed: unavailable (%s)", exc)
                return "unavailable"
            if any(kw in exc_str for kw in ("connection refused", "name or service not known", "timed out", "timeout")):
                logger.warning("qB health check failed: unavailable (%s)", exc)
                return "unavailable"
            # Auth failures (bad credentials) → error
            if any(kw in exc_type for kw in ("login", "forbidden", "unauthorized", "auth")):
                logger.warning("qB health check failed: error (%s)", exc)
                return "error"
            if any(kw in exc_str for kw in ("403", "401", "unauthorized", "forbidden", "login failed")):
                logger.warning("qB health check failed: error (%s)", exc)
                return "error"
            logger.warning("qB health check failed: unexpected error (%s)", exc)
            return "error"

    def build_add_payload(
        self,
        url: str,
        category: str,
        rename: str,
        paused: bool = False,
        tags: list[str] | None = None,
        add_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Validate and build the qbittorrent-api add kwargs.

        ``add_tags`` is an internal-only tag list (e.g. correlation tracking
        tags like ``nasclaw-task-{id}``). These are merged into the final
        ``tags`` parameter sent to qB but are kept separate at the adapter
        boundary so the caller can distinguish user-facing tags from
        internal tracking tags.
        """
        clean_url = url.strip()
        clean_category = category.strip()
        clean_rename = rename.strip()
        clean_tags = [tag.strip() for tag in (tags or []) if tag.strip()]
        clean_add_tags = [tag.strip() for tag in (add_tags or []) if tag.strip()]
        all_tags = clean_tags + clean_add_tags
        if not clean_url:
            raise ValueError("url must not be empty")
        if not clean_rename:
            raise ValueError("rename must not be empty")

        payload: dict[str, Any] = {
            "urls": clean_url,
            "rename": clean_rename,
            "is_paused": paused,
        }
        if clean_category:
            payload["category"] = clean_category
        if all_tags:
            payload["tags"] = all_tags
        return payload

    def list_categories(self) -> dict[str, Any]:
        """Read qB categories map, keyed by category name."""
        client = self.login()
        if client is None:
            return {}
        try:
            categories = _read_value(_read_value(client, "torrent_categories"), "categories", {})
        except Exception as exc:
            logger.warning("qB list_categories failed: %s", exc)
            return {}
        logger.info(
            "qB categories listed count=%s",
            len(categories) if isinstance(categories, dict) else 0,
        )
        return categories if isinstance(categories, dict) else {}

    def list_tags(self) -> list[str]:
        """Read all qB torrent tags (flat list of tag name strings).

        Raises QBittorrentError when login fails or the API call errors.
        """
        client = self.login()
        if client is None:
            raise QBittorrentError("qBittorrent 登录失败，无法获取标签列表。")
        tags = client.torrents_tags()
        if isinstance(tags, list):
            return [str(t) for t in tags]
        return list(tags) if hasattr(tags, "__iter__") else []

    def add_torrent_url(
        self,
        url: str,
        category: str,
        rename: str,
        paused: bool = False,
        tags: list[str] | None = None,
        add_tags: list[str] | None = None,
        **extra_kwargs: Any,
    ) -> dict[str, Any]:
        """Submit tokenized URL to qB and return structured result.``"""
        client = self.login()
        if client is None:
            return {"ok": False, "status": "not_configured", "error_code": "NOT_CONFIGURED",
                    "error_message": "qBittorrent 未配置，无法添加下载任务", "retryable": False}
        payload = self.build_add_payload(
            url=url,
            category=category,
            rename=rename,
            paused=paused,
            tags=tags,
            add_tags=add_tags,
        )
        payload.update(extra_kwargs)
        logger.info(
            "qB add torrent started category=%s paused=%s tag_count=%s rename_chars=%s",
            payload.get("category", ""),
            paused,
            len(payload.get("tags", [])),
            len(payload.get("rename", "")),
        )
        try:
            raw_response = client.torrents_add(**payload)
        except Exception as exc:
            return _build_error_result(exc, "add_torrent")

        # -- qB 5.x returns TorrentsAddedMetadata (dict subclass) ----------
        if isinstance(raw_response, dict):
            success_count = raw_response.get("success_count", 0)
            pending_count = raw_response.get("pending_count", 0)
            hashes = raw_response.get("added_torrent_ids", [])
            ok = (success_count + pending_count) > 0
            qb_hash = hashes[0] if hashes else None
            submitted_status = "submitted_paused" if paused else "submitted"
            status = submitted_status if ok else "unknown"
            logger.info(
                "qB add torrent finished ok=%s status=%s success=%s pending=%s hash=%s",
                ok,
                status,
                success_count,
                pending_count,
                qb_hash,
            )
            return {
                "ok": ok,
                "status": status,
                "qb_hash": qb_hash,
                "raw_response": raw_response,
            }

        # -- qB 4.x returns "Ok." / "Ok" / "true" string ------------------
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
        state = str(_read_value(torrent, "state", "") or "")
        return {
            "hash": str(_read_value(torrent, "hash", "") or ""),
            "name": str(_read_value(torrent, "name", "") or ""),
            "category": str(_read_value(torrent, "category", "") or ""),
            "tags": [tag.strip() for tag in tags_value.split(",") if tag.strip()],
            "state": state,
            "progress": float(_read_value(torrent, "progress", 0.0) or 0.0),
            "download_speed": int(_read_value(torrent, "dlspeed", 0) or 0),
            "upload_speed": int(_read_value(torrent, "upspeed", 0) or 0),
            "eta": int(_read_value(torrent, "eta", 0) or 0),
            "save_path": str(_read_value(torrent, "save_path", "") or ""),
            "content_path": str(_read_value(torrent, "content_path", "") or ""),
            "size": int(_read_value(torrent, "size", 0) or 0),
            "total_size": int(_read_value(torrent, "total_size", 0) or 0),
            "completion_on": int(_read_value(torrent, "completion_on", 0) or 0),
        }

    def _fetch_tracker_diagnostics(self, torrent_hash: str) -> dict[str, Any]:
        """Fetch tracker-level error info for a single torrent.

        Returns a dict with:
            has_error: whether this torrent has reported tracker errors
            error_summary: a one-line aggregate of all tracker error messages
            trackers: list of {url, status, msg} for trackers with non-empty messages
        """
        client = self.login()
        if client is None:
            return {"has_error": False, "error_summary": "", "trackers": []}
        try:
            raw = client.torrents_trackers(torrent_hash=torrent_hash)
        except Exception as exc:
            logger.warning("qB tracker fetch failed hash=%s: %s", torrent_hash, exc)
            return {"has_error": False, "error_summary": "", "trackers": []}

        errors: list[dict[str, Any]] = []
        for t in (raw or []):
            msg = str(_read_value(t, "msg", "") or "").strip()
            if msg:
                errors.append({
                    "url": str(_read_value(t, "url", "") or ""),
                    "status": int(_read_value(t, "status", 0) or 0),
                    "msg": msg,
                })
        summary = "; ".join(e["msg"] for e in errors) if errors else ""
        return {
            "has_error": bool(errors),
            "error_summary": summary,
            "trackers": errors,
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

        try:
            rows = client.torrents_info(**kwargs)
        except Exception as exc:
            logger.warning("qB list_torrents failed: %s", exc)
            return []
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

        try:
            rows = client.torrents_info(torrent_hashes=clean_hash)
        except Exception as exc:
            logger.warning("qB get_torrent failed hash=%s: %s", clean_hash, exc)
            return None
        if not rows:
            logger.info("qB torrent detail not found qb_hash=%s", clean_hash)
            return None
        result = self._serialize_torrent_row(rows[0])
        try:
            properties = client.torrents_properties(torrent_hash=clean_hash)
        except Exception as exc:
            logger.warning("qB torrent properties failed hash=%s: %s", clean_hash, exc)
            properties = {}
        result.update(
            {
                "comment": str(_read_value(properties, "comment", "") or ""),
                "total_uploaded": int(_read_value(properties, "total_uploaded", 0) or 0),
                "share_ratio": float(_read_value(properties, "share_ratio", 0.0) or 0.0),
                "creation_date": int(_read_value(properties, "creation_date", 0) or 0),
            }
        )
        # Fetch tracker errors for diagnostic visibility
        diagnostics = self._fetch_tracker_diagnostics(clean_hash)
        result.update(diagnostics)
        logger.info("qB torrent detail fetched qb_hash=%s state=%s has_error=%s",
                     clean_hash, result.get("state"), diagnostics.get("has_error"))
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
            return {"ok": False, "status": "not_configured", "error_code": "NOT_CONFIGURED",
                    "error_message": "qBittorrent 未配置", "retryable": False, "qb_hash": clean_hash}

        logger.info(
            "qB torrent action started qb_hash=%s action=%s delete_files=%s",
            clean_hash,
            normalized_action,
            delete_files,
        )
        try:
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
        except Exception as exc:
            return _build_error_result(exc, f"control_torrent/{normalized_action}")
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
            return {"ok": False, "status": "not_configured", "error_code": "NOT_CONFIGURED",
                    "error_message": "qBittorrent 未配置", "retryable": False,
                    "upload_limit": upload_limit, "download_limit": download_limit}

        try:
            if upload_limit is not None:
                client.transfer.upload_limit = upload_limit
            if download_limit is not None:
                client.transfer.download_limit = download_limit
        except Exception as exc:
            return _build_error_result(exc, "set_global_speed")

        logger.info(
            "qB global speed limits set upload_limit=%s download_limit=%s",
            upload_limit,
            download_limit,
        )
        return {"ok": True, "upload_limit": upload_limit, "download_limit": download_limit}

    def set_torrent_speed_limits(
        self,
        torrent_hash: str,
        upload_limit: int | None = None,
        download_limit: int | None = None,
    ) -> dict[str, Any]:
        """Set per-torrent speed limits in bytes/s. None means no change."""
        clean_hash = torrent_hash.strip()
        if not clean_hash:
            raise ValueError("torrent_hash must not be empty")

        client = self.login()
        if client is None:
            return {
                "ok": False,
                "status": "not_configured",
                "error_code": "NOT_CONFIGURED",
                "error_message": "qBittorrent 未配置",
                "retryable": False,
                "torrent_hash": clean_hash,
                "upload_limit": upload_limit,
                "download_limit": download_limit,
            }

        try:
            if upload_limit is not None:
                client.torrents_set_upload_limit(torrent_hashes=clean_hash, limit=upload_limit)
            if download_limit is not None:
                client.torrents_set_download_limit(torrent_hashes=clean_hash, limit=download_limit)
        except Exception as exc:
            return _build_error_result(exc, "set_torrent_speed")

        logger.info(
            "qB torrent speed limits set hash=%s upload_limit=%s download_limit=%s",
            clean_hash,
            upload_limit,
            download_limit,
        )
        return {
            "ok": True,
            "torrent_hash": clean_hash,
            "upload_limit": upload_limit,
            "download_limit": download_limit,
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
