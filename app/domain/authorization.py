"""Download authorization policy and session grant helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


DOWNLOAD_AUTHORIZATION_POLICY_ID = "download-add-torrents-v1"
POLICY_ELIGIBLE_TOOLS = {"qb_add_torrent"}


class DownloadAuthorizationPolicy(BaseModel):
    """User-configured boundary for session-scoped auto authorization."""

    enabled: bool = False
    save_path_prefixes: list[str] = Field(default_factory=list)
    max_items_per_batch: int = Field(default=10, ge=1, le=10)
    max_total_items_per_session: int = Field(default=20, ge=1, le=100)
    paused_required: bool = True

    @field_validator("save_path_prefixes", mode="before")
    @classmethod
    def _normalize_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [line for line in value.splitlines()]
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    @field_validator("paused_required")
    @classmethod
    def _force_paused_required(cls, value: bool) -> bool:
        return True


def default_download_authorization_policy() -> DownloadAuthorizationPolicy:
    return DownloadAuthorizationPolicy()


def approval_authorization_info(
    policy: DownloadAuthorizationPolicy,
    tool_name: str,
    arguments: dict[str, Any],
    default_save_path: str = "",
) -> dict[str, Any]:
    """Return UI-facing eligibility information for one pending approval."""

    if tool_name not in POLICY_ELIGIBLE_TOOLS:
        return {
            "eligible": False,
            "reason": "Tool is not eligible for session authorization",
        }
    ok, reason, item_count = _arguments_match_policy(policy, tool_name, arguments, default_save_path)
    if not ok:
        return {
            "eligible": False,
            "reason": reason,
        }
    return {
        "eligible": True,
        "policy_id": DOWNLOAD_AUTHORIZATION_POLICY_ID,
        "grant_scope_preview": {
            "tool_names": sorted(POLICY_ELIGIBLE_TOOLS),
            "save_path_prefixes": policy.save_path_prefixes,
            "max_items_per_batch": policy.max_items_per_batch,
            "max_total_items_per_session": policy.max_total_items_per_session,
            "paused_required": True,
        },
        "item_count": item_count,
    }


def create_session_grant(
    policy: DownloadAuthorizationPolicy,
    tool_name: str,
    arguments: dict[str, Any],
    used_items: int = 0,
    now: datetime | None = None,
    default_save_path: str = "",
) -> dict[str, Any]:
    """Create an active session grant from the current Settings policy."""

    ok, reason, _ = _arguments_match_policy(policy, tool_name, arguments, default_save_path)
    if not ok:
        raise ValueError(reason)
    created_at = (now or datetime.now(timezone.utc)).isoformat()
    return {
        "id": f"grant_{uuid4().hex}",
        "policy_id": DOWNLOAD_AUTHORIZATION_POLICY_ID,
        "tool_name": "download_add",
        "status": "active",
        "created_at": created_at,
        "used_total_items": used_items,
        "scope": {
            "save_path_prefixes": list(policy.save_path_prefixes),
            "max_items_per_batch": policy.max_items_per_batch,
            "max_total_items_per_session": policy.max_total_items_per_session,
            "paused_required": True,
        },
    }


def authorize_with_session_grant(
    metadata: dict[str, Any],
    policy: DownloadAuthorizationPolicy,
    tool_name: str,
    arguments: dict[str, Any],
    default_save_path: str = "",
) -> dict[str, Any] | None:
    """Consume session grant quota when a tool call fits the active policy."""

    ok, reason, item_count = _arguments_match_policy(policy, tool_name, arguments, default_save_path)
    if not ok:
        return None

    grants = metadata.get("authorization_grants")
    if not isinstance(grants, list):
        return None

    for grant in grants:
        if not isinstance(grant, dict):
            continue
        if grant.get("status") != "active":
            continue
        if grant.get("policy_id") != DOWNLOAD_AUTHORIZATION_POLICY_ID:
            continue
        if str(grant.get("tool_name") or "") not in {"download_add", *POLICY_ELIGIBLE_TOOLS}:
            continue
        if not _arguments_match_grant_scope(grant, tool_name, arguments):
            continue

        used_total = int(grant.get("used_total_items") or 0)
        scope = grant.get("scope") if isinstance(grant.get("scope"), dict) else {}
        max_total = int(scope.get("max_total_items_per_session") or policy.max_total_items_per_session)
        if used_total + item_count > max_total:
            return None
        grant["used_total_items"] = used_total + item_count
        return {
            "authorized": True,
            "grant_id": str(grant.get("id") or ""),
            "reason": "Allowed by session download authorization grant",
            "item_count": item_count,
        }
    return None


def granted_item_count(tool_name: str, response_data: dict[str, Any], arguments: dict[str, Any]) -> int:
    if tool_name != "qb_add_torrent":
        return 0
    # Batch mode: when "items" key is present in the original arguments.
    if "items" in arguments:
        summary = response_data.get("summary")
        if isinstance(summary, dict):
            try:
                return max(0, int(summary.get("succeeded") or 0))
            except (TypeError, ValueError):
                return 0
        return len(_extract_items(arguments))
    # Single-item mode.
    return 1 if response_data.get("receipt") else 0


def _arguments_match_policy(
    policy: DownloadAuthorizationPolicy,
    tool_name: str,
    arguments: dict[str, Any],
    default_save_path: str = "",
) -> tuple[bool, str, int]:
    if tool_name not in POLICY_ELIGIBLE_TOOLS:
        return False, "Tool is not eligible for session authorization", 0
    if not policy.enabled:
        return False, "Download authorization policy is disabled", 0
    if not policy.save_path_prefixes:
        return False, "Download authorization policy has no allowed save path prefixes", 0
    if arguments.get("paused") is False:
        return False, "Download authorization requires paused qB submissions", 0

    items = _extract_items(arguments)
    if not items:
        return False, "No batch items were provided", 0
    if len(items) > policy.max_items_per_batch:
        return False, "Batch item count exceeds policy limit", len(items)

    resolved_default = default_save_path.strip()
    for item in items:
        save_path = str(item.get("save_path") or "").strip()
        if not save_path:
            if not resolved_default:
                return False, (
                    "Save path is required for session authorization — "
                    "either pass save_path or configure DOWNLOAD_DEFAULT_SAVE_PATH"
                ), len(items)
            save_path = resolved_default
        if not _path_in_prefixes(save_path, policy.save_path_prefixes):
            return False, f"Save path is outside policy scope: {save_path}", len(items)
    return True, "", len(items)


def _arguments_match_grant_scope(
    grant: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
) -> bool:
    scope = grant.get("scope")
    if not isinstance(scope, dict):
        return False
    policy = DownloadAuthorizationPolicy(
        enabled=True,
        save_path_prefixes=list(scope.get("save_path_prefixes") or []),
        max_items_per_batch=int(scope.get("max_items_per_batch") or 1),
        max_total_items_per_session=int(scope.get("max_total_items_per_session") or 1),
        paused_required=True,
    )
    ok, _, _ = _arguments_match_policy(policy, tool_name, arguments, default_save_path="")
    return ok


def _extract_items(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    if "torrent_id" in arguments:
        return [
            {
                "torrent_id": arguments.get("torrent_id"),
                "save_path": arguments.get("save_path"),
            }
        ]
    items = arguments.get("items")
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, dict)]


def _path_in_prefixes(path: str, prefixes: list[str]) -> bool:
    clean_path = path.rstrip("/")
    for prefix in prefixes:
        clean_prefix = prefix.rstrip("/")
        if clean_path == clean_prefix or clean_path.startswith(clean_prefix + "/"):
            return True
    return False
