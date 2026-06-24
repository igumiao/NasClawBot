"""Recording/Fake dependency implementations for Agent behavioral evaluation.

Every Recording class wraps a :class:`Fixture <evals.models.Fixture>` for
canned responses and a :class:`CallJournal` for recording every call made
during a trial.  ``create_recording_dependencies()`` assembles them into
an ``AgentToolDependencies`` that the Agent runner can use for zero-side-effect
evaluation runs.
"""

from __future__ import annotations

import threading
from itertools import count
from typing import Any

from app.agent.dependencies import AgentToolDependencies
from app.domain.downloads import (
    BatchDownloadSubmissionResult,
    DownloadMonitorReceipt,
    DownloadMonitorRequest,
    DownloadMonitorUpdate,
    DownloadSubmissionRequest,
    DownloadSubmissionResult,
)
from app.services.task_management import TaskManagementError, TaskView
from evals.models import CallJournalEntry, Fixture, FixtureQbTask, FixtureResource


# ======================================================================
# CallJournal
# ======================================================================


class CallJournal:
    """Thread-safe append-only store for :class:`CallJournalEntry` records.

    Thread safety is provided by a :class:`threading.Lock` so that trials
    with concurrent tool execution (should that ever be needed) do not
    corrupt the journal.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[CallJournalEntry] = []
        self._counter = count(1)

    def record(
        self,
        dependency: str,
        operation: str,
        arguments: dict[str, Any] | None = None,
        outcome: str = "success",
        started_at: str = "",
        duration_ms: float = 0.0,
        kind: str = "read",
    ) -> "CallJournalEntry":
        """Append one journal entry under the lock and return it."""
        with self._lock:
            entry = CallJournalEntry(
                sequence=next(self._counter),
                kind=kind,  # type: ignore[arg-type]
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
        """Return a snapshot of all entries in insertion order."""
        with self._lock:
            return list(self._entries)

    @property
    def count(self) -> int:
        """Return the number of recorded entries."""
        with self._lock:
            return len(self._entries)

    def filter_by(
        self,
        dependency: str | None = None,
        operation: str | None = None,
    ) -> list[CallJournalEntry]:
        """Return entries matching the supplied filters (AND-ed).

        Parameters
        ----------
        dependency:
            If set, only entries with this dependency value are returned.
        operation:
            If set, only entries with this operation value are returned.
        """
        result: list[CallJournalEntry] = []
        with self._lock:
            for entry in self._entries:
                if dependency is not None and entry.dependency != dependency:
                    continue
                if operation is not None and entry.operation != operation:
                    continue
                result.append(entry)
        return result


# ======================================================================
# Serialisation helpers
# ======================================================================


def _resource_to_search_dict(r: FixtureResource) -> dict[str, Any]:
    """Convert a *FixtureResource* to the dict shape produced by
    ``MTeamAdapter.search_torrents_by_keyword``."""
    return {
        "id": r.torrent_id,
        "title": r.title,
        "name": r.title,
        "small_description": None,
        "has_chinese_subtitle": r.has_chinese_subtitle,
        "seeders": r.seeders,
        "leechers": r.leechers,
        "discount": r.discount or None,
        "imdb": None,
        "douban": None,
        "size": r.size,
        "size_bytes": r.size_bytes,
        "source": "mteam",
        "raw": r.model_dump(),
    }


def _resource_to_detail_dict(r: FixtureResource) -> dict[str, Any]:
    """Convert a *FixtureResource* to the dict shape produced by
    ``MTeamAdapter.get_torrent_details``."""
    return {
        "id": r.torrent_id,
        "name": r.title,
        "smallDescr": r.title,
        "size": r.size_bytes,
        "status": {
            "seeders": r.seeders,
            "leechers": r.leechers,
            "discount": r.discount,
        },
    }


def _qb_task_to_dict(t: FixtureQbTask) -> dict[str, Any]:
    """Serialise a *FixtureQbTask* to the dict shape produced by
    ``QBittorrentAdapter._serialize_torrent_row``."""
    return {
        "hash": t.hash,
        "name": t.name,
        "category": t.category,
        "tags": list(t.tags),
        "state": t.state,
        "progress": t.progress,
        "download_speed": 0,
        "upload_speed": 0,
        "eta": 0,
        "save_path": "",
        "content_path": "",
        "size": t.size_bytes,
        "total_size": t.size_bytes,
        "completion_on": 0,
    }


def _now_stub() -> str:
    """Return the evaluation world's fixed UTC timestamp."""
    return "2026-06-15T04:00:00+00:00"


# ======================================================================
# Recording adapters
# ======================================================================


class RecordingMTeamAdapter:
    """Records calls and returns canned M-Team data from a *fixture*.

    Every public method writes a ``CallJournalEntry`` to *journal* before
    returning the fixture-driven response.
    """

    def __init__(self, fixture: Fixture, journal: CallJournal) -> None:
        self._fixture = fixture
        self._journal = journal

    # -- search ---------------------------------------------------------

    def search_torrents_by_keyword(
        self,
        keyword: str = "",
        page: int = 1,
        page_size: int = 20,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Return all fixture resources as M-Team search-result dicts."""
        self._journal.record(
            "mteam",
            "search_torrents_by_keyword",
            {"keyword": keyword, "page": page, "page_size": page_size, **kwargs},
        )
        return [_resource_to_search_dict(r) for r in self._fixture.resources]

    def search(
        self, keyword: str = "", page: int = 1, page_size: int = 20
    ) -> list[dict[str, Any]]:
        """Alias matching ``MTeamAdapter.search``."""
        return self.search_torrents_by_keyword(
            keyword=keyword, page=page, page_size=page_size
        )

    # -- detail ---------------------------------------------------------

    def get_torrent_details(self, torrent_id: str) -> dict[str, Any] | None:
        """Return the matching fixture resource as a detail dict, or None."""
        self._journal.record(
            "mteam", "get_torrent_details", {"torrent_id": torrent_id}
        )
        for r in self._fixture.resources:
            if r.torrent_id == torrent_id:
                return _resource_to_detail_dict(r)
        return None

    def get_detail(self, torrent_id: str) -> dict[str, Any] | None:
        """Alias matching ``MTeamAdapter.get_detail``."""
        return self.get_torrent_details(torrent_id=torrent_id)

    # -- download URL ---------------------------------------------------

    def get_torrent_download_url(self, torrent_id: str) -> str | None:
        """Return a deterministic fake download URL for *torrent_id*."""
        self._journal.record(
            "mteam", "get_torrent_download_url", {"torrent_id": torrent_id}
        )
        return f"https://mteam.fake/download/{torrent_id}"

    def get_download_url(self, torrent_id: str) -> str | None:
        """Alias matching ``MTeamAdapter.get_download_url``."""
        return self.get_torrent_download_url(torrent_id=torrent_id)

    # -- URL validation -------------------------------------------------

    def is_download_url_torrent(self, url: str) -> bool:
        """Return True for URLs matching the fake domain pattern."""
        self._journal.record("mteam", "is_download_url_torrent", {"url": url})
        return "mteam.fake/download/" in url

    # -- member profile -------------------------------------------------

    def get_member_profile(self, uid: str | None = None) -> dict[str, Any] | None:
        """Return a stub member profile."""
        self._journal.record("mteam", "get_member_profile", {"uid": uid})
        return {
            "uid": uid or "eval_user",
            "userName": "EvalUser",
            "uploaded": 10 * 1024**4,
            "downloaded": 1024**4,
            "bonus": 5000.0,
        }


class RecordingQBAdapter:
    """Records calls and returns canned qBittorrent data from a *fixture*.

    All mutating methods return a success dict without side effects.
    """

    def __init__(self, fixture: Fixture, journal: CallJournal) -> None:
        self._fixture = fixture
        self._journal = journal

    def add_torrent_url(
        self,
        url: str,
        category: str,
        rename: str,
        paused: bool = False,
        tags: list[str] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Record the add and return a success receipt."""
        self._journal.record(
            "qb",
            "add_torrent_url",
            {
                "url": url,
                "category": category,
                "rename": rename,
                "paused": paused,
                "tags": tags,
                **extra,
            },
            kind="effect",
        )
        status = "submitted_paused" if paused else "submitted"
        return {"ok": True, "status": status, "qb_hash": None, "raw_response": "Ok."}

    def list_torrents(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Return fixture qb_tasks serialised as the adapter would."""
        self._journal.record("qb", "list_torrents", dict(kwargs))
        return [_qb_task_to_dict(t) for t in self._fixture.qb_tasks]

    def get_torrent(self, torrent_hash: str) -> dict[str, Any] | None:
        """Return the matching fixture qb_task, or None."""
        self._journal.record("qb", "get_torrent", {"torrent_hash": torrent_hash})
        for t in self._fixture.qb_tasks:
            if t.hash == torrent_hash:
                return _qb_task_to_dict(t)
        return None

    def list_tags(self) -> list[str]:
        """Return all unique tags found across fixture qb_tasks."""
        self._journal.record("qb", "list_tags", {})
        seen: set[str] = set()
        for t in self._fixture.qb_tasks:
            seen.update(t.tags)
        return sorted(seen)

    def control_torrent(
        self,
        torrent_hash: str,
        *,
        action: str,
        delete_files: bool = False,
    ) -> dict[str, Any]:
        """Record the control action and return a success dict."""
        self._journal.record(
            "qb",
            "control_torrent",
            {
                "torrent_hash": torrent_hash,
                "action": action,
                "delete_files": delete_files,
            },
            kind="effect",
        )
        return {"ok": True, "status": action, "qb_hash": torrent_hash}

    def set_global_speed_limits(
        self,
        upload_limit: int | None = None,
        download_limit: int | None = None,
    ) -> dict[str, Any]:
        """Record the speed change and return a success dict."""
        self._journal.record(
            "qb",
            "set_global_speed_limits",
            {"upload_limit": upload_limit, "download_limit": download_limit},
            kind="effect",
        )
        return {
            "ok": True,
            "upload_limit": upload_limit,
            "download_limit": download_limit,
        }

    def set_torrent_speed_limits(
        self,
        torrent_hash: str,
        upload_limit: int | None = None,
        download_limit: int | None = None,
    ) -> dict[str, Any]:
        """Record the per-torrent speed change and return a success dict."""
        self._journal.record(
            "qb",
            "set_torrent_speed_limits",
            {
                "torrent_hash": torrent_hash,
                "upload_limit": upload_limit,
                "download_limit": download_limit,
            },
            kind="effect",
        )
        return {
            "ok": True,
            "torrent_hash": torrent_hash,
            "upload_limit": upload_limit,
            "download_limit": download_limit,
        }


class RecordingTavilyAdapter:
    """Records calls and returns empty web-search stubs."""

    def __init__(self, journal: CallJournal) -> None:
        self._journal = journal

    def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        """Record the search and return an empty result structure."""
        self._journal.record("tavily", "search", {"query": query, **kwargs})
        return {
            "query": query,
            "answer": None,
            "results": [],
            "response_time": 0,
            "usage": {"credits": 0},
        }


class RecordingTMDBAdapter:
    """Records calls and returns canned TMDB data from a *fixture*."""

    def __init__(self, fixture: Fixture, journal: CallJournal) -> None:
        self._fixture = fixture
        self._journal = journal

    def search_multi(self, query: str, **kwargs: Any) -> dict[str, Any]:
        """Return fixture search results for *query*, or an empty structure."""
        self._journal.record("tmdb", "search_multi", {"query": query, **kwargs})
        results = self._fixture.tmdb_search_results.get(query)
        if results is None:
            normalized_query = " ".join(query.casefold().split())
            results = []
            for fixture_query, fixture_results in self._fixture.tmdb_search_results.items():
                normalized_fixture_query = " ".join(fixture_query.casefold().split())
                if normalized_fixture_query in normalized_query:
                    results = fixture_results
                    break
        return {
            "page": 1,
            "results": results,
            "total_pages": 1,
            "total_results": len(results),
        }

    def movie_details(self, movie_id: int) -> dict[str, Any]:
        """Return fixture details for *movie_id*, or an empty dict."""
        self._journal.record("tmdb", "movie_details", {"movie_id": movie_id})
        return self._fixture.tmdb_details.get(str(movie_id), {})

    def tv_details(self, series_id: int) -> dict[str, Any]:
        """Return fixture details for *series_id*, or an empty dict."""
        self._journal.record("tmdb", "tv_details", {"series_id": series_id})
        return self._fixture.tmdb_details.get(str(series_id), {})

    def discover_movie(self, **filters: Any) -> dict[str, Any]:
        """Return an empty paginated discover-movie structure."""
        self._journal.record("tmdb", "discover_movie", dict(filters))
        return {"page": 1, "results": [], "total_pages": 0, "total_results": 0}

    def discover_tv(self, **filters: Any) -> dict[str, Any]:
        """Return an empty paginated discover-tv structure."""
        self._journal.record("tmdb", "discover_tv", dict(filters))
        return {"page": 1, "results": [], "total_pages": 0, "total_results": 0}

    def trending_all(self, time_window: str = "day") -> dict[str, Any]:
        """Return an empty paginated trending structure."""
        self._journal.record("tmdb", "trending_all", {"time_window": time_window})
        return {"page": 1, "results": [], "total_pages": 0, "total_results": 0}


class RecordingMemoryStore:
    """Records calls and returns safe stubs.  Never touches the filesystem."""

    def __init__(self, journal: CallJournal) -> None:
        self._journal = journal

    def ensure_template_files(self) -> None:
        """No-op: never writes template files."""
        self._journal.record("memory", "ensure_template_files", {}, kind="effect")

    def format_user_profile_prompt(self) -> str:
        """Return an empty string (no profile data in eval mode)."""
        self._journal.record("memory", "format_user_profile_prompt", {})
        return ""

    def search(self, query: str, limit: int | None = None) -> list[Any]:
        """Return an empty list — no knowledge is pre-loaded in eval mode."""
        self._journal.record("memory", "search", {"query": query, "limit": limit})
        return []

    def append_to_inbox(self, text: str) -> str:
        """Record the inbox entry and return it (no actual write).

        This is the method called by the ``remember_this`` tool.
        """
        self._journal.record("memory", "append_to_inbox", {"text": text}, kind="effect")
        return text

    def append_user_profile(self, text: str) -> None:
        """Record the profile append (eval-interface convenience)."""
        self._journal.record("memory", "append_user_profile", {"text": text}, kind="effect")

    def remember(self, kind: str, text: str) -> None:
        """Record a generic memory fact (eval-interface convenience).

        This is not called by Agent tools directly; it exists so that
        evaluation harness scripts can assert that the Agent *intended*
        to remember something without going through the full inbox/curation
        pipeline.
        """
        self._journal.record("memory", "remember", {"kind": kind, "text": text}, kind="effect")


class RecordingDownloadAutomation:
    """Records calls and returns canned submission results from a *fixture*.

    Downloads are always accepted unless ``fixture.download_submit_error``
    matches the requested torrent id.
    """

    def __init__(self, fixture: Fixture, journal: CallJournal) -> None:
        self._fixture = fixture
        self._journal = journal

    def submit_downloads(
        self,
        requests: list[DownloadSubmissionRequest],
        completion_action: str = "none",
        source_session_id: str | None = None,
        idempotency_key: str = "",
    ) -> BatchDownloadSubmissionResult:
        """Record each request and return a :class:`BatchDownloadSubmissionResult`.

        Parameters
        ----------
        requests:
            One or more download requests.  Each is recorded separately in
            the journal.
        completion_action:
            ``"none"`` (default), ``"notify"``, or ``"organize"``.  When
            set to a non-``"none"`` value a synthetic ``watch_task_id`` is
            included in the result.
        source_session_id:
            Opaque session identifier passed through for audit.
        idempotency_key:
            Deduplication key forwarded to the journal.
        """
        now = _now_stub()
        items: list[DownloadSubmissionResult] = []
        error_result = self._fixture.download_submit_error
        configured_result = self._fixture.download_submit

        for req in requests:
            matched_result = (
                error_result
                if error_result is not None and error_result.torrent_id == req.torrent_id
                else (
                    configured_result
                    if configured_result is not None
                    and configured_result.torrent_id == req.torrent_id
                    else None
                )
            )
            self._journal.record(
                "download",
                "submit_downloads",
                {
                    "torrent_id": req.torrent_id,
                    "completion_action": completion_action,
                    "source_session_id": source_session_id,
                    "idempotency_key": idempotency_key,
                    "save_path": req.save_path,
                    "tag": req.tag,
                    "qb_category": req.qb_category,
                },
                outcome=matched_result.outcome if matched_result is not None else "success",
                kind="effect",
            )

            # Honour the fixture error mapping.
            if matched_result is not None and matched_result.outcome != "success":
                items.append(
                    DownloadSubmissionResult(
                        receipt_id=f"rec-{req.torrent_id}-{now}",
                        torrent_id=req.torrent_id,
                        status="failed",
                        error=matched_result.code or "fixture_error",
                        submitted_at=now,
                    )
                )
                continue

            # Nominal accepted case.
            watch_task_id: str | None = None
            if completion_action and completion_action != "none":
                watch_task_id = f"watch-{req.torrent_id}-{now}"

            items.append(
                DownloadSubmissionResult(
                    receipt_id=f"rec-{req.torrent_id}-{now}",
                    torrent_id=req.torrent_id,
                    status="accepted",
                    watch_task_id=watch_task_id,
                    submission_receipt={
                        "ok": True,
                        "status": "submitted_paused",
                        "qb_hash": None,
                        "raw_response": "Ok.",
                    },
                    submitted_at=now,
                )
            )

        summary: dict[str, int] = {}
        for item in items:
            summary[item.status] = summary.get(item.status, 0) + 1
        return BatchDownloadSubmissionResult(items=items, summary=summary)

    def create_monitor(
        self,
        request: DownloadMonitorRequest,
        source_session_id: str | None,
        idempotency_key: str,
    ) -> DownloadMonitorReceipt:
        """Record a monitor creation and return a synthetic receipt."""
        self._journal.record(
            "download",
            "create_monitor",
            {
                "torrent_hash": request.torrent_hash,
                "mode": request.mode,
                "on_completed": request.on_completed,
                "source_session_id": source_session_id,
                "idempotency_key": idempotency_key,
            },
            kind="effect",
        )
        now = _now_stub()
        return DownloadMonitorReceipt(
            task_id=f"watch-{request.torrent_hash}-{now}",
            torrent_hash=request.torrent_hash,
            torrent_name=request.torrent_hash,
            start_at=request.start_at,
            mode=request.mode,
            on_completed=request.on_completed or "notify",
            status="queued",
        )

    def update_monitor(
        self,
        request: DownloadMonitorUpdate,
    ) -> DownloadMonitorReceipt:
        """Record a monitor update and return a synthetic receipt."""
        self._journal.record(
            "download",
            "update_monitor",
            {
                "task_id": request.task_id,
                "mode": request.mode,
                "on_completed": request.on_completed,
                "start_at": request.start_at,
            },
            kind="effect",
        )
        return DownloadMonitorReceipt(
            task_id=request.task_id,
            torrent_hash="unknown",
            torrent_name="unknown",
            start_at=request.start_at,
            mode=request.mode or "once",
            on_completed=request.on_completed or "notify",
            status="queued",
        )


# ======================================================================
# Recording task management
# ======================================================================


class RecordingTaskManagement:
    """Records task queries/mutations against fixture-backed TaskView values."""

    def __init__(self, fixture: Fixture, journal: CallJournal) -> None:
        self._fixture = fixture
        self._journal = journal

    def list_tasks(self, query: Any = None) -> list[TaskView]:
        self._journal.record(
            "task_mgmt", "list_tasks",
            {"query": str(query) if query else None},
        )
        tasks = [
            TaskView(
                task_id=task.task_id,
                kind=task.kind,
                status=task.status.lower(),
                description=task.title,
            )
            for task in self._fixture.background_tasks
        ]
        if query is not None:
            if getattr(query, "status", None):
                tasks = [task for task in tasks if task.status == query.status]
            if getattr(query, "kind", None):
                tasks = [task for task in tasks if task.kind == query.kind]
            tasks = tasks[: int(getattr(query, "limit", 50))]
        return tasks

    def get_task(self, task_id: str) -> TaskView:
        self._journal.record("task_mgmt", "get_task", {"task_id": task_id})
        for task in self.list_tasks():
            if task.task_id == task_id:
                return task
        raise TaskManagementError("TASK_NOT_FOUND", f"Task {task_id!r} not found")

    def cancel_task(self, task_id: str) -> TaskView:
        self._journal.record(
            "task_mgmt", "cancel_task", {"task_id": task_id}, kind="effect",
        )
        task = self.get_task(task_id)
        if task.status not in {"queued", "waiting"}:
            raise TaskManagementError(
                "CANCEL_REJECTED",
                f"Task {task_id!r} is {task.status} and cannot be cancelled",
            )
        return task.model_copy(update={"status": "cancelled"})


# ======================================================================
# Recording runtime task store
# ======================================================================


class RecordingRuntimeTaskStore:
    """Records calls and returns empty event lists (no real events in eval).

    The ``get_events_for_session`` and ``mark_events_injected`` methods
    match the production ``RuntimeTaskStore`` interface so that the runner's
    background-event injection path works correctly — it just finds no
    events to inject.
    """

    def __init__(self, journal: CallJournal) -> None:
        self._journal = journal

    def get_events_for_session(
        self, source_session_id: str, uninjected_only: bool = False,
    ) -> list[Any]:
        self._journal.record(
            "runtime_store", "get_events_for_session",
            {
                "source_session_id": source_session_id,
                "uninjected_only": uninjected_only,
            },
        )
        return []

    def mark_events_injected(self, event_ids: list[str], now: Any) -> None:
        self._journal.record(
            "runtime_store", "mark_events_injected",
            {"event_ids": event_ids},
            kind="effect",
        )

    def list_events(
        self,
        *,
        limit: int = 50,
        filters: dict[str, Any] | None = None,
    ) -> list[Any]:
        """Return an empty event history while preserving the production interface."""
        self._journal.record(
            "runtime_store",
            "list_events",
            {"limit": limit, "filters": dict(filters or {})},
        )
        return []


# ======================================================================
# Recording MCP pool
# ======================================================================

# Hardcoded MCP filesystem tool schemas matching the production
# @modelcontextprotocol/server-filesystem tools.  These schemas are
# stable and rarely change; they ensure the LLM sees the same tool
# contracts in evaluation as in production.  Calls are recorded but
# never touch the filesystem.
_MCP_FS_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "read_text_file",
        "description": "Read the complete contents of a text file (UTF-8). "
                       "Supports optional head/tail line limits.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to read."},
                "head": {"type": "integer", "description": "Return first N lines only."},
                "tail": {"type": "integer", "description": "Return last N lines only."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_media_file",
        "description": "Read a media file (image/audio/video) and return it as base64.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the media file."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_multiple_files",
        "description": "Read the contents of multiple files simultaneously.",
        "input_schema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to read.",
                },
            },
            "required": ["paths"],
        },
    },
    {
        "name": "write_file",
        "description": "Create a new file or overwrite an existing file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path where the file will be written."},
                "content": {"type": "string", "description": "Content to write to the file."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Make line-based edits to a text file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to edit."},
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "oldText": {"type": "string", "description": "Text to replace."},
                            "newText": {"type": "string", "description": "Replacement text."},
                        },
                        "required": ["oldText", "newText"],
                    },
                    "description": "List of edit operations.",
                },
                "dryRun": {"type": "boolean", "description": "Preview changes without applying."},
            },
            "required": ["path", "edits"],
        },
    },
    {
        "name": "create_directory",
        "description": "Create a new directory or ensure a directory exists.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path of the directory to create."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_directory",
        "description": "Get a list of files and directories in a given directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path of the directory to list."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_directory_with_sizes",
        "description": "Get a detailed listing with file sizes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path of the directory to list."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "directory_tree",
        "description": "Get a recursive tree view of files and directories as JSON.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to start the tree from."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "move_file",
        "description": "Move or rename files and directories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source path."},
                "destination": {"type": "string", "description": "Destination path."},
            },
            "required": ["source", "destination"],
        },
    },
    {
        "name": "search_files",
        "description": "Recursively search for files and directories matching a pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Starting directory for the search."},
                "pattern": {"type": "string", "description": "Glob pattern to match."},
                "excludePatterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Glob patterns to exclude.",
                },
            },
            "required": ["path", "pattern"],
        },
    },
    {
        "name": "get_file_info",
        "description": "Retrieve detailed metadata about a file or directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file or directory."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_allowed_directories",
        "description": "List the directories that the server is allowed to access.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


class RecordingMcpPool:
    """Recording MCP pool that returns hardcoded filesystem tool schemas.

    Tool schemas match the production ``@modelcontextprotocol/server-filesystem``
    tools so the LLM sees the same tool contracts.  ``call_tool_sync`` records
    the call to the journal and returns a synthetic success string without
    touching the filesystem.

    Only the 13 tools listed in ``_MCP_CHAT_TOOLS`` are exposed; the
    deprecated ``read_file`` alias is excluded, matching the production runner.
    """

    SERVER_NAME = "filesystem"
    _EFFECT_TOOLS = frozenset(
        {"write_file", "edit_file", "create_directory", "move_file"}
    )

    def __init__(self, journal: CallJournal) -> None:
        self._journal = journal
        self.server_names = [self.SERVER_NAME]

    def get_tools(
        self, server_name: str | None = None,
    ) -> list[tuple[str, Any]]:
        """Return hardcoded filesystem tool schemas as ``(server_name, McpToolInfo)``."""
        from hello_agents.tools.mcp.client import McpToolInfo

        result: list[tuple[str, Any]] = []
        for schema in _MCP_FS_TOOL_SCHEMAS:
            if server_name is not None and server_name != self.SERVER_NAME:
                continue
            result.append((
                self.SERVER_NAME,
                McpToolInfo(
                    name=schema["name"],
                    description=schema["description"],
                    input_schema=schema["input_schema"],
                ),
            ))
        return result

    def call_tool_sync(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict,
        timeout: float = 30.0,
    ) -> object:
        """Record the call and return a synthetic success response."""
        self._journal.record(
            "mcp",
            f"call_{tool_name}",
            {"server": server_name, "arguments": arguments},
            kind="effect" if tool_name in self._EFFECT_TOOLS else "read",
        )
        return f"[eval] {tool_name} executed successfully (recording mode)"

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict,
    ) -> object:
        """Async path — delegates to ``call_tool_sync`` in recording mode."""
        return self.call_tool_sync(server_name, tool_name, arguments)

    async def start_all(self) -> dict[str, bool]:
        return {self.SERVER_NAME: True}

    async def stop_all(self) -> None:
        pass


# ======================================================================
# Factory
# ======================================================================


def create_recording_dependencies(
    fixture: Fixture,
    call_journal: CallJournal,
) -> AgentToolDependencies:
    """Build an ``AgentToolDependencies`` with every adapter replaced by a
    recording stub.

    Parameters
    ----------
    fixture:
        Canned test data used by all recording implementations.
    call_journal:
        Shared :class:`CallJournal` that records every dependency call made
        during the trial.

    Returns
    -------
    AgentToolDependencies
        A fully wired dependency object suitable for passing to
        ``NasClawAgentRunner``. Task, runtime-event, and MCP adapters preserve
        the production interfaces while recording instead of mutating real state.
    """
    return AgentToolDependencies(
        mteam=RecordingMTeamAdapter(fixture, call_journal),
        qb=RecordingQBAdapter(fixture, call_journal),
        tmdb=RecordingTMDBAdapter(fixture, call_journal),
        tavily=RecordingTavilyAdapter(call_journal),
        memory_store=RecordingMemoryStore(call_journal),
        download_automation=RecordingDownloadAutomation(fixture, call_journal),
        task_management=RecordingTaskManagement(fixture, call_journal),
        runtime_task_store=RecordingRuntimeTaskStore(call_journal),
        mcp_pool=RecordingMcpPool(call_journal),
    )
