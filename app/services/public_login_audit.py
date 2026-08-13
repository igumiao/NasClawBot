"""Minimal successful-login registry for non-local experience visitors."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import threading
from typing import Callable

from app.services.experience_auth import IPAddress


logger = logging.getLogger(__name__)


class PublicLoginAudit:
    """Write one privacy-limited JSONL entry per successful public login."""

    def __init__(
        self,
        path: Path,
        *,
        is_local: Callable[[IPAddress | None], bool],
        enabled: bool = True,
        retention_days: int = 180,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if retention_days <= 0:
            raise ValueError(
                "EXPERIENCE_LOGIN_AUDIT_RETENTION_DAYS must be greater than zero."
            )
        self.path = path
        self._is_local = is_local
        self._enabled = enabled
        self._retention = timedelta(days=retention_days)
        self._now = now
        self._lock = threading.Lock()

    def record_success(self, client_address: IPAddress | None) -> bool:
        """Record one successful non-local login; return whether it was written."""
        if not self._enabled or self._is_local(client_address):
            return False

        occurred_at = self._now().astimezone(timezone.utc)
        entry = {
            "timestamp": occurred_at.isoformat(),
            "event": "login_success",
            "client_ip": str(client_address) if client_address is not None else "unknown",
        }
        with self._lock:
            try:
                retained = self._load_since(occurred_at - self._retention)
                retained.append(entry)
                self._replace(retained)
            except OSError:
                # Audit storage is ancillary and must not turn a valid login
                # into a server error. Do not include the visitor IP in logs.
                logger.warning("Public login audit write failed", exc_info=True)
                return False
        return True

    def _load_since(self, cutoff: datetime) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        retained: list[dict[str, str]] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            try:
                value = json.loads(line)
                timestamp = datetime.fromisoformat(value["timestamp"])
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                if (
                    timestamp >= cutoff
                    and value.get("event") == "login_success"
                    and isinstance(value.get("client_ip"), str)
                ):
                    retained.append(
                        {
                            "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
                            "event": "login_success",
                            "client_ip": value["client_ip"],
                        }
                    )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return retained

    def _replace(self, entries: list[dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        content = "".join(
            f"{json.dumps(entry, ensure_ascii=True, separators=(',', ':'))}\n"
            for entry in entries
        )
        temporary_path.write_text(content, encoding="utf-8")
        temporary_path.chmod(0o600)
        temporary_path.replace(self.path)
