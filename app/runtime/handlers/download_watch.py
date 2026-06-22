"""Handler that polls qBittorrent for an incomplete download until it finishes.

The ``DownloadWatchHandler`` is registered for the ``download_watch`` task kind.
It periodically checks the status of a torrent in qBittorrent, correlates the
task to the torrent via the ``nasclaw-task-{task_id}`` tag, and takes the
appropriate follow-up action when the download completes.

Handler signature matches ``Handler`` from the runtime registry::

    outcome = await handler(task, store, scheduler)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from app.adapters.qbittorrent import QBittorrentAdapter
from app.domain.downloads import FOLLOW_UP_AUTO_ORGANIZE, FOLLOW_UP_NOTIFY_ONLY
from app.domain.runtime_tasks import (
    ChildTaskSpec,
    Complete,
    Fail,
    Reschedule,
    RuntimeTask,
    Spawn,
    TaskEventSeverity,
    TaskOutcome,
)
from app.runtime.scheduler import TaskScheduler
from app.runtime.store import RuntimeTaskStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONSECUTIVE_MISSES_THRESHOLD: int = 3
"""Number of consecutive ``get_torrent`` null results before failing the task.

After this many polls where qB returns no torrent for the known ``qb_hash``,
the handler transitions to ``QB_TORRENT_MISSING`` failure.
"""

ORGANIZE_DEDUPE_KEY_PREFIX: str = "organize-"
"""Prefix for the ``organize_download`` child-task dedupe key.

Combined with the qB hash (e.g. ``organize-<qb_hash>``) to guarantee
idempotent child creation when the watch handler retries after the download
has already completed.
"""

# Dynamic polling bounds (seconds).
_DYN_POLL_MIN: int = 30
_DYN_POLL_MAX: int = 600
_DYN_POLL_DEFAULT: int = 30  # First poll / no history.
_DYN_POLL_STALL: int = 60   # Progress stalled (speed ≈ 0).
_DYN_WARMUP_POLLS: int = 2  # Fixed-interval polls before dynamic mode.
_DYN_EMA_ALPHA: float = 0.3  # Smoothing factor for speed EMA.


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class DownloadWatchConfig:
    """Polling and backoff configuration for download-watch tasks.

    Attributes:
        poll_seconds: Base interval (in seconds) between poll ticks when the
            download is still in progress.  Default 30.
        error_backoff_max: Maximum backoff (in seconds) for transient qB
            errors, used as the cap for exponential backoff.  Default 600
            (10 minutes).
    """

    poll_seconds: int = 30
    error_backoff_max: int = 600


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class DownloadWatchHandler:
    """Poll qBittorrent for an incomplete download and take follow-up action.

    The handler is invoked repeatedly (via ``Reschedule`` outcomes) until the
    torrent reaches ``progress >= 1.0`` or a terminal error occurs.

    Constructor accepts infrastructure dependencies that are shared across
    invocations.  The ``__call__`` method matches the ``Handler`` protocol
    from the runtime registry.
    """

    def __init__(
        self,
        qb_adapter: QBittorrentAdapter,
        config: DownloadWatchConfig,
        scheduler: TaskScheduler,
        store: RuntimeTaskStore,
        clock: Callable[[], datetime],
        path_mapping: dict[str, str] | None = None,
    ) -> None:
        """Initialise the handler.

        Args:
            qb_adapter: Configured qBittorrent adapter for listing and
                fetching torrents.
            config: Polling interval, backoff limits, and related settings.
            scheduler: The ``TaskScheduler`` for spawning child tasks.
            store: The ``RuntimeTaskStore`` for state transitions.
            clock: Callable returning the current ``datetime``, used for
                all timestamp calculations.
            path_mapping: Optional dict mapping qB-reported path prefixes
                to local filesystem prefixes (e.g. ``{"D:\\": "/mnt/d/"}``).
                Only needed when qB and MCP run on different OSes.
        """
        self._qb = qb_adapter
        self._config = config
        self._scheduler = scheduler
        self._store = store
        self._clock = clock
        self._path_mapping = path_mapping or {}

    def _translate_path(self, path: str) -> str:
        """Apply configured path prefix translations to *path*.

        Returns the translated path if any mapping prefix matches, otherwise
        the original path unchanged.  After translation, Windows backslash
        separators are normalised to forward slashes for Linux filesystem
        compatibility (MCP, WSL, Docker).
        """
        if not self._path_mapping or not path:
            return path
        for qb_prefix, local_prefix in self._path_mapping.items():
            if path.startswith(qb_prefix):
                translated = local_prefix + path[len(qb_prefix):]
                return translated.replace("\\", "/")
        return path

    # ------------------------------------------------------------------
    # Handler protocol
    # ------------------------------------------------------------------

    async def __call__(
        self,
        task: RuntimeTask,
        store: RuntimeTaskStore,
        scheduler: TaskScheduler,
    ) -> TaskOutcome:
        """Execute one poll cycle for *task*.

        Two-phase dispatch:

        1. **Hash resolution** (first call only) -- when ``payload.qb_hash``
           is not yet known, correlates the task to a qB torrent via the
           ``nasclaw-task-{task_id}`` tag.

        2. **Polling** (subsequent calls) -- fetches the torrent by hash,
           checks progress, and returns the appropriate outcome.

        Args:
            task: The claimed ``RuntimeTask`` with a payload containing
                ``qb_hash``, optional ``torrent_name``, and state counters.
            store: The concrete ``RuntimeTaskStore`` for state transitions
                (forwarded to the handler by the worker).
            scheduler: The external ``TaskScheduler`` for spawning child
                tasks (forwarded to the handler by the worker).

        Returns:
            A ``TaskOutcome``:

            - ``Reschedule`` -- normal polling (download still in progress).
            - ``Complete`` -- download finished.
            - ``Spawn`` -- organisation child task created for the completed
              download.
            - ``Fail`` -- terminal correlation or missing-torrent error.
        """
        payload = task.payload or {}
        qb_hash = payload.get("qb_hash")
        now = self._clock()

        if not qb_hash:
            return self._resolve_qb_hash(task, now)

        return self._poll_torrent(payload, qb_hash, now)

    # ------------------------------------------------------------------
    # Hash resolution (first call only)
    # ------------------------------------------------------------------

    def _resolve_qb_hash(
        self,
        task: RuntimeTask,
        now: datetime,
    ) -> TaskOutcome:
        """Correlate the task to a qB torrent via ``nasclaw-task-{id}`` tag.

        Uses ``list_torrents`` with the correlation tag that was attached
        during the qB submission in ``DownloadCoordinator``.

        Results:
            0 torrents -> ``Reschedule`` (qB may not have indexed the tag yet).
            1 torrent  -> persist ``qb_hash``, ``torrent_name``, ``save_path``
                          into payload and ``Reschedule``.
            >1 torrent -> ``Fail`` with ``AMBIGUOUS_QB_CORRELATION``.
        """
        correlation_tag = f"nasclaw-task-{task.task_id}"
        run_after = (now + timedelta(seconds=self._config.poll_seconds)).isoformat()

        try:
            torrents = self._qb.list_torrents(tag=correlation_tag)
        except Exception as exc:
            logger.warning(
                "list_torrents failed for task %s tag=%s: %s",
                task.task_id,
                correlation_tag,
                exc,
            )
            return Reschedule(
                run_after=run_after,
                reason="list_torrents call failed, will retry",
            )

        count = len(torrents)

        if count == 0:
            logger.info(
                "No qB torrent found for task %s tag=%s",
                task.task_id,
                correlation_tag,
            )
            return Reschedule(run_after=run_after)

        if count == 1:
            t = torrents[0]
            qb_hash = t.get("hash", "")
            logger.info(
                "Resolved qB hash %s for task %s (name=%s)",
                qb_hash,
                task.task_id,
                t.get("name", ""),
            )
            return Reschedule(
                run_after=run_after,
                payload_patch={
                    "qb_hash": qb_hash,
                    "torrent_name": t.get("name", ""),
                    "save_path": self._translate_path(t.get("save_path", "")),
                    "consecutive_misses": 0,
                    "consecutive_errors": 0,
                    "last_poll_at": now.isoformat(),
                    "last_progress": 0.0,
                    "poll_count": 0,
                },
            )

        # count > 1
        logger.error(
            "Ambiguous qB correlation for task %s tag=%s: %d torrents found",
            task.task_id,
            correlation_tag,
            count,
        )
        return Fail(
            code="AMBIGUOUS_QB_CORRELATION",
            message=(
                f"Found {count} torrents with tag {correlation_tag!r}; "
                f"expected at most 1"
            ),
            retryable=False,
            details={
                "correlation_tag": correlation_tag,
                "torrent_count": count,
            },
        )

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _compute_next_poll(
        self,
        payload: dict[str, Any],
        current_progress: float,
        now: datetime,
        default_seconds: int = _DYN_POLL_DEFAULT,
    ) -> tuple[int, float | None]:
        """Compute the next poll delay and EMA-smoothed speed.

        Returns ``(delay_seconds, smooth_speed)``.  *smooth_speed* is
        ``None`` during warm-up (no speed computed yet); the caller
        should persist it in the task payload for the next cycle.
        """
        poll_count = payload.get("poll_count", 0)

        # Warm-up: fixed interval for the first few polls.
        if poll_count < _DYN_WARMUP_POLLS:
            return default_seconds, None

        last_progress = payload.get("last_progress")
        last_poll_at = payload.get("last_poll_at")

        if last_progress is None or last_poll_at is None:
            return default_seconds, None

        try:
            last_time = datetime.fromisoformat(last_poll_at)
        except (ValueError, TypeError):
            return default_seconds, None

        elapsed = (now - last_time).total_seconds()
        if elapsed <= 0:
            return default_seconds, None

        delta = current_progress - float(last_progress)
        if delta <= 0:
            return _DYN_POLL_STALL, None

        current_speed = delta / elapsed
        if current_speed <= 0:
            return _DYN_POLL_STALL, None

        # EMA smoothing to reduce jitter.
        prev_smooth = payload.get("smooth_speed")
        if prev_smooth is not None and float(prev_smooth) > 0:
            smooth_speed = (
                _DYN_EMA_ALPHA * current_speed
                + (1 - _DYN_EMA_ALPHA) * float(prev_smooth)
            )
        else:
            smooth_speed = current_speed

        remaining = 1.0 - current_progress
        if remaining <= 0:
            return _DYN_POLL_MIN, smooth_speed

        eta = remaining / smooth_speed
        next_poll = int(eta * 0.5)
        return max(_DYN_POLL_MIN, min(_DYN_POLL_MAX, next_poll)), smooth_speed

    def _poll_torrent(
        self,
        payload: dict[str, Any],
        qb_hash: str,
        now: datetime,
    ) -> TaskOutcome:
        """Fetch torrent state from qB and return the appropriate outcome.

        Dispatches to specialised helper methods based on the result of
        ``get_torrent``:
        - ``None`` returned -> miss tracking / fail path.
        - Exception raised -> transient error / exponential backoff path.
        - Torrent found   -> progress check / completion path.
        """
        consecutive_misses = payload.get("consecutive_misses", 0)
        consecutive_errors = payload.get("consecutive_errors", 0)

        try:
            torrent = self._qb.get_torrent(qb_hash)
        except Exception as exc:
            logger.warning(
                "get_torrent failed for hash %s: %s",
                qb_hash,
                exc,
            )
            return self._transient_error(
                consecutive_errors,
                now,
                error=str(exc),
            )

        if torrent is None:
            return self._torrent_miss(qb_hash, consecutive_misses, now)

        # Reset error/miss counters on any successful fetch.
        progress = torrent.get("progress", 0.0)
        state = torrent.get("state", "")
        poll_count = int(payload.get("poll_count", 0)) + 1
        payload_patch: dict[str, Any] = {
            "consecutive_misses": 0,
            "consecutive_errors": 0,
            "last_poll_at": now.isoformat(),
            "last_progress": progress,
            "poll_count": poll_count,
        }

        if progress < 1.0:
            delay, smooth_speed = self._compute_next_poll(
                payload, progress, now,
            )
            if smooth_speed is not None:
                payload_patch["smooth_speed"] = smooth_speed
            logger.info(
                "Torrent %s still in progress progress=%.4f state=%s "
                "next_poll=%ds poll=%d",
                qb_hash,
                progress,
                state,
                delay,
                poll_count,
            )
            return Reschedule(
                run_after=(
                    now + timedelta(seconds=delay)
                ).isoformat(),
                payload_patch=payload_patch,
                reason=f"progress={progress:.4f} state={state}",
            )

        return self._handle_completed(
            payload, torrent, payload_patch, now,
        )

    def _torrent_miss(
        self,
        qb_hash: str,
        consecutive_misses: int,
        now: datetime,
    ) -> TaskOutcome:
        """Handle a missing torrent (``get_torrent`` returned ``None``).

        Increments the miss counter.  When the threshold is reached,
        transitions to ``QB_TORRENT_MISSING`` failure.
        """
        consecutive_misses += 1
        logger.warning(
            "Torrent %s not found (miss %d/%d)",
            qb_hash,
            consecutive_misses,
            CONSECUTIVE_MISSES_THRESHOLD,
        )

        if consecutive_misses >= CONSECUTIVE_MISSES_THRESHOLD:
            return Fail(
                code="QB_TORRENT_MISSING",
                message=(
                    f"Torrent {qb_hash} was not found in qBittorrent "
                    f"after {CONSECUTIVE_MISSES_THRESHOLD} consecutive polls"
                ),
                retryable=False,
                details={
                    "qb_hash": qb_hash,
                    "consecutive_misses": consecutive_misses,
                },
            )

        return Reschedule(
            run_after=(
                now + timedelta(seconds=self._config.poll_seconds)
            ).isoformat(),
            payload_patch={"consecutive_misses": consecutive_misses},
            reason=f"torrent not found (miss {consecutive_misses})",
        )

    def _transient_error(
        self,
        consecutive_errors: int,
        now: datetime,
        error: str = "",
    ) -> TaskOutcome:
        """Handle a transient qB error with exponential backoff.

        Backoff formula: ``poll_seconds * 2 ** (consecutive_errors - 1)``
        capped at ``error_backoff_max``.
        """
        consecutive_errors += 1
        delay = min(
            self._config.poll_seconds * (2 ** (consecutive_errors - 1)),
            self._config.error_backoff_max,
        )
        run_after = (now + timedelta(seconds=delay)).isoformat()

        logger.warning(
            "Transient qB error (consecutive_errors=%d) retrying in %ds: %s",
            consecutive_errors,
            delay,
            error,
        )

        return Reschedule(
            run_after=run_after,
            payload_patch={"consecutive_errors": consecutive_errors},
            reason=f"transient error, backoff {delay}s",
        )

    # ------------------------------------------------------------------
    # Completion handling
    # ------------------------------------------------------------------

    def _handle_completed(
        self,
        payload: dict[str, Any],
        torrent: dict[str, Any],
        payload_patch: dict[str, Any],
        now: datetime,
    ) -> TaskOutcome:
        """Dispatch completion follow-up based on resolved mode.

        Three branches:

        * ``auto_organize``  -> ``Spawn`` an ``organize_download`` child task.
        * ``notify_only``    -> ``Complete`` with a ``download_completed`` event.
        * ``none`` / unknown -> ``Complete`` without events.
        * missing ``content_path`` -> ``Complete`` with a warning event
          signalling the user should investigate.
        """
        qb_hash = torrent.get("hash", "")
        torrent_name = torrent.get("name", "")
        content_path = self._translate_path(torrent.get("content_path", "") or "")
        save_path = self._translate_path(torrent.get("save_path", ""))

        # Update payload with final torrent metadata.
        payload_patch["torrent_name"] = torrent_name
        payload_patch["save_path"] = save_path

        if not content_path:
            logger.warning(
                "Torrent %s completed but content_path is empty",
                qb_hash,
            )
            return Complete(
                result={
                    "qb_hash": qb_hash,
                    "torrent_name": torrent_name,
                    "content_path": content_path,
                    "save_path": save_path,
                },
                events=[
                    {
                        "kind": "download_completed_no_path",
                        "severity": TaskEventSeverity.WARNING,
                        "title": "下载完成但无文件路径",
                        "summary": (
                            f"种子 {torrent_name} 已完成，"
                            f"但 qBittorrent 未提供文件路径"
                        ),
                        "payload": {
                            "qb_hash": qb_hash,
                            "torrent_name": torrent_name,
                        },
                    },
                ],
            )

        # Resolve follow-up mode from the payload's resolved_follow_up dict.
        resolved = payload.get("resolved_follow_up", {}) or {}
        mode = resolved.get("mode", "")

        if mode == FOLLOW_UP_AUTO_ORGANIZE:
            auth_snapshot = resolved.get("authorization_snapshot") or {}
            return self._spawn_organize(
                qb_hash=qb_hash,
                torrent_name=torrent_name,
                save_path=save_path,
                content_path=content_path,
                auth_snapshot=auth_snapshot,
                now=now,
            )

        if mode == FOLLOW_UP_NOTIFY_ONLY:
            return Complete(
                result={
                    "qb_hash": qb_hash,
                    "torrent_name": torrent_name,
                    "content_path": content_path,
                    "save_path": save_path,
                },
                events=[
                    {
                        "kind": "download_completed",
                        "severity": TaskEventSeverity.SUCCESS,
                        "title": "下载完成",
                        "summary": f"种子 {torrent_name} 已下载完成",
                        "payload": {
                            "qb_hash": qb_hash,
                            "torrent_name": torrent_name,
                            "content_path": content_path,
                            "save_path": save_path,
                        },
                    },
                ],
            )

        # Fallback: FOLLOW_UP_NONE or unknown mode — complete silently.
        logger.info(
            "Download %s (%s) completed with mode=%r — no follow-up action",
            qb_hash,
            torrent_name,
            mode,
        )
        return Complete(
            result={
                "qb_hash": qb_hash,
                "torrent_name": torrent_name,
                "content_path": content_path,
                "save_path": save_path,
            },
        )

    def _spawn_organize(
        self,
        qb_hash: str,
        torrent_name: str,
        save_path: str,
        content_path: str,
        auth_snapshot: dict[str, Any],
        now: datetime,
    ) -> Spawn:
        """Create an ``organize_download`` child task for the completed torrent.

        Uses a dedupe key derived from the qB hash so that retries (e.g. when
        the watch handler re-runs after a crash) do not create duplicate
        organisation tasks.
        """
        child = ChildTaskSpec(
            kind="organize_download",
            payload={
                "qb_hash": qb_hash,
                "torrent_name": torrent_name,
                "save_path": save_path,
                "content_path": content_path,
                "authorization_snapshot": auth_snapshot,
            },
            dedupe_key=f"{ORGANIZE_DEDUPE_KEY_PREFIX}{qb_hash}",
        )

        logger.info(
            "Spawning organize_download child for %s (%s)",
            qb_hash,
            torrent_name,
        )

        return Spawn(
            children=[child],
            result={
                "qb_hash": qb_hash,
                "torrent_name": torrent_name,
                "content_path": content_path,
                "save_path": save_path,
                "spawned_organize": True,
            },
            events=[
                {
                    "kind": "download_completed",
                    "severity": TaskEventSeverity.SUCCESS,
                    "title": "下载完成，正在整理",
                    "summary": f"种子 {torrent_name} 已下载完成，即将自动整理",
                    "payload": {
                        "qb_hash": qb_hash,
                        "torrent_name": torrent_name,
                        "content_path": content_path,
                    },
                },
            ],
        )
