"""Recording/Fake dependency implementations for behavioral evaluation.

Every Recording class wraps a Fixture and writes every operation to a
thread-safe CallJournal so that scorers can verify that no real-world
side effects occurred before approval, and that approved actions were
recorded exactly once.
"""

from __future__ import annotations

import threading
from typing import Any

from app.agent.dependencies import AgentToolDependencies
from app.domain.downloads import (
    BatchDownloadSubmissionResult,
    DownloadSubmissionResult,
)
from evals.models import CallJournalEntry, Fixture


# ── CallJournal ────────────────────────────────────────────────────────

class CallJournal:
    """Thread-safe append-only journal of dependency interactions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[CallJournalEntry] = []
        self._seq = 0

    def record(
        self,
        dependency: str,
        operation: str,
        arguments: dict[str, Any] | None = None,
        outcome: str = "success",
        started_at: str = "",
        duration_ms: float = 0.0,
    ) -> CallJournalEntry:
        with self._lock:
            self._seq += 1
            entry = CallJournalEntry(
                sequence=self._seq,
                dependency=dependency,
                operation=operation,
                arguments=arguments or {},
                outcome=outcome,
                started_at=started_at,
                duration_ms=duration_ms,
            )
            self._entries.append(entry)
            return entry

    @property
    def entries(self) -> list[CallJournalEntry]:
        with self._lock:
            return list(self._entries)

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def filter_by(
        self, dependency: str | None = None, operation: str | None = None
    ) -> list[CallJournalEntry]:
        result: list[CallJournalEntry] = []
        with self._lock:
            for entry in self._entries:
                if dependency is not None and entry.dependency != dependency:
                    continue
                if operation is not None and entry.operation != operation:
                    continue
                result.append(entry)
        return result


# ── Recording adapters ─────────────────────────────────────────────────

class RecordingMTeamAdapter:
    """M-Team adapter that returns fixture data and records to journal."""

    def __init__(self, fixture: Fixture, journal: CallJournal) -> None:
        self._fixture = fixture
        self._journal = journal

    def search_torrents_by_keyword(
        self, keyword: str, page: int = 1, page_size: int = 20, **kwargs: Any
    ) -> list[dict[str, Any]]:
        self._journal.record("mteam", "search_torrents_by_keyword", {
            "keyword": keyword, "page": page, "page_size": page_size,
        })
        results: list[dict[str, Any]] = []
        for r in self._fixture.resources:
            results.append({
                "id": r.torrent_id,
                "title": r.title,
                "size": r.size,
                "size_bytes": r.size_bytes,
                "seeders": r.seeders,
                "leechers": r.leechers,
                "discount": r.discount,
                "smallDescr": r.resolution or "",
                "labelsNew": r.labels_new,
                "hasChineseSubtitle": r.has_chinese_subtitle,
                "status": {
                    "seeders": r.seeders,
                    "leechers": r.leechers,
                    "discount": r.discount,
                },
            })
        return results

    def get_torrent_details(self, torrent_id: str) -> dict[str, Any] | None:
        self._journal.record("mteam", "get_torrent_details", {"torrent_id": torrent_id})
        for r in self._fixture.resources:
            if r.torrent_id == torrent_id:
                return {"id": r.torrent_id, "title": r.title, "size": r.size}
        return None

    def get_torrent_download_url(self, torrent_id: str) -> str | None:
        self._journal.record("mteam", "get_torrent_download_url", {"torrent_id": torrent_id})
        return f"https://mteam.fake/download/{torrent_id}"

    def is_download_url_torrent(self, url: str) -> bool:
        return bool(url and "mteam.fake" in url)


class RecordingQBAdapter:
    """qBittorrent adapter that returns fixture data and records to journal."""

    def __init__(self, fixture: Fixture, journal: CallJournal) -> None:
        self._fixture = fixture
        self._journal = journal

    def add_torrent_url(
        self, *, url: str, category: str, rename: str,
        tags: list[str], paused: bool, **extra_kwargs: Any,
    ) -> dict[str, Any]:
        self._journal.record("qb", "add_torrent_url", {
            "url": url, "category": category, "rename": rename,
            "tags": tags, "paused": paused,
        })
        return {"ok": True, "status": "submitted_paused", "qb_hash": "eval-hash-0001"}

    def list_torrents(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._journal.record("qb", "list_torrents", kwargs)
        return [
            {
                "hash": t.hash,
                "name": t.name,
                "size": t.size_bytes,
                "progress": t.progress,
                "state": t.state,
                "category": t.category,
                "tags": ",".join(t.tags),
            }
            for t in self._fixture.qb_tasks
        ]

    def get_torrent(self, hash: str) -> dict[str, Any] | None:
        self._journal.record("qb", "get_torrent", {"hash": hash})
        for t in self._fixture.qb_tasks:
            if t.hash == hash:
                return {
                    "hash": t.hash,
                    "name": t.name,
                    "size": t.size_bytes,
                    "progress": t.progress,
                    "state": t.state,
                    "category": t.category,
                    "tags": ",".join(t.tags),
                }
        return None

    def list_tags(self) -> list[str]:
        self._journal.record("qb", "list_tags", {})
        return ["movie", "tv", "anime"]

    def control_torrent(self, hash: str, action: str) -> dict[str, Any]:
        self._journal.record("qb", "control_torrent", {"hash": hash, "action": action})
        return {"ok": True}

    def set_global_speed(self, download: int, upload: int) -> dict[str, Any]:
        self._journal.record("qb", "set_global_speed", {"download": download, "upload": upload})
        return {"ok": True}

    def set_torrent_speed(self, hash: str, download: int, upload: int) -> dict[str, Any]:
        self._journal.record("qb", "set_torrent_speed", {
            "hash": hash, "download": download, "upload": upload,
        })
        return {"ok": True}

    def generate_mteam_torrent_name(
        self, mteam_id: str, detail: dict[str, Any], qb_category: str,
    ) -> str:
        return f"{mteam_id}-{qb_category}.torrent"


class RecordingTavilyAdapter:
    """Tavily adapter that returns empty results and records to journal."""

    def __init__(self, journal: CallJournal) -> None:
        self._journal = journal

    def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        self._journal.record("tavily", "search", {"query": query, **kwargs})
        return {"results": [], "answer": ""}


class RecordingTMDBAdapter:
    """TMDB adapter that returns fixture data and records to journal."""

    def __init__(self, fixture: Fixture, journal: CallJournal) -> None:
        self._fixture = fixture
        self._journal = journal

    def search_multi(self, query: str, **kwargs: Any) -> dict[str, Any]:
        self._journal.record("tmdb", "search_multi", {"query": query, **kwargs})
        results = self._fixture.tmdb_search_results.get(query, [])
        return {"results": results}

    def get_details(self, movie_id: str | int, **kwargs: Any) -> dict[str, Any]:
        self._journal.record("tmdb", "get_details", {"movie_id": str(movie_id), **kwargs})
        return self._fixture.tmdb_details.get(str(movie_id), {})

    def discover(self, **kwargs: Any) -> dict[str, Any]:
        self._journal.record("tmdb", "discover", kwargs)
        return {"results": []}

    def trending(self, **kwargs: Any) -> dict[str, Any]:
        self._journal.record("tmdb", "trending", kwargs)
        return {"results": []}


class RecordingMemoryStore:
    """Memory store that records operations to journal without real I/O."""

    def __init__(self, journal: CallJournal) -> None:
        self._journal = journal

    def ensure_template_files(self) -> None:
        pass

    def format_user_profile_prompt(self) -> str:
        return ""

    def search(self, query: str) -> list[dict[str, Any]]:
        self._journal.record("memory", "search", {"query": query})
        return []

    def append_user_profile(self, text: str) -> None:
        self._journal.record("memory", "append_user_profile", {"text": text})

    def remember(self, kind: str, text: str) -> None:
        self._journal.record("memory", "remember", {"kind": kind, "text": text})


class RecordingDownloadAutomation:
    """Download automation that records submissions and returns fixture results."""

    def __init__(self, fixture: Fixture, journal: CallJournal) -> None:
        self._fixture = fixture
        self._journal = journal

    def submit_downloads(
        self,
        requests: list[Any],
        completion_action: str,
        source_session_id: str | None = None,
        idempotency_key: str = "",
    ) -> BatchDownloadSubmissionResult:
        items: list[DownloadSubmissionResult] = []
        for req in requests:
            torrent_id = getattr(req, "torrent_id", str(req))
            self._journal.record(
                "download_automation", "submit_download",
                {
                    "torrent_id": torrent_id,
                    "completion_action": completion_action,
                    "idempotency_key": idempotency_key,
                },
            )
            # Use fixture's download_submit for known IDs, error for others.
            if (self._fixture.download_submit_error
                    and self._fixture.download_submit_error.torrent_id == torrent_id):
                items.append(DownloadSubmissionResult(
                    torrent_id=torrent_id,
                    status="error",
                    error=self._fixture.download_submit_error.code or "SUBMIT_FAILED",
                ))
            else:
                items.append(DownloadSubmissionResult(
                    torrent_id=torrent_id,
                    status="submitted_paused",
                    resource_title=f"Resource {torrent_id}",
                ))
        return BatchDownloadSubmissionResult(items=items)


# ── Factory ────────────────────────────────────────────────────────────

def create_recording_dependencies(
    fixture: Fixture,
    call_journal: CallJournal,
) -> AgentToolDependencies:
    """Build a full set of Recording dependencies for one trial."""
    return AgentToolDependencies(
        mteam=RecordingMTeamAdapter(fixture, call_journal),
        qb=RecordingQBAdapter(fixture, call_journal),
        tmdb=RecordingTMDBAdapter(fixture, call_journal),
        tavily=RecordingTavilyAdapter(call_journal),
        memory_store=RecordingMemoryStore(call_journal),
        download_automation=RecordingDownloadAutomation(fixture, call_journal),
        task_management=None,
        runtime_task_store=None,
        mcp_pool=None,
    )
