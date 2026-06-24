"""Isolated trial environment for NasClawBot Agent behavioral evaluation.

Each trial gets its own temp directory, Settings snapshot, CallJournal,
recording dependencies, and NasClawAgentRunner so that evaluation runs are
fully isolated from production state and from each other.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.agent.runner import NasClawAgentRunner
from app.config import Settings, get_settings
from evals.loader import get_fixture
from evals.models import EvalCase, Fixture
from evals.recording import CallJournal, create_recording_dependencies
from hello_agents.checkpoints.json_store import JSONConversationCheckpointStore


@dataclass
class EvalEnvironment:
    """Isolated environment for one trial.

    Owns the work directory, call journal, recording dependencies, and the
    runner instance.  Call ``cleanup()`` after the trial completes to remove
    all trial artifacts.
    """

    run_id: str
    suite: str
    case_id: str
    repetition: int
    label: str
    fixture: Fixture
    work_dir: Path  # trial-specific temp directory
    call_journal: CallJournal
    runner: NasClawAgentRunner
    session_id: str
    fixed_now: datetime
    clock_offset: timedelta = field(default_factory=timedelta)

    def cleanup(self) -> None:
        """Remove the trial work directory and all its contents."""
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)


def create_trial_environment(
    run_id: str,
    suite: str,
    case: EvalCase,
    repetition: int,
    label: str,
    base_work_dir: Path,
    fixed_date_str: str = "2026-06-15",
    fixed_timezone: str = "Asia/Shanghai",
) -> EvalEnvironment:
    """Build an isolated EvalEnvironment for one trial.

    Steps
    -----
    1. Create the trial work directory (``{case.id}-r{repetition:02d}``)
       with ``checkpoints/``, ``memory/``, ``runtime/``, ``traces/``, and
       ``settings/`` subdirectories.
    2. Build a **Settings** snapshot cloned from the production environment
       with overridden timezone, download path, and isolated task DB path.
       Real LLM / M-Team / qB / TMDB / Tavily credentials are preserved from
       the process environment so the runner can construct the agent — the
       recording ``dependencies`` object prevents any real network calls.
    3. Create a ``CallJournal`` that records every dependency interaction.
    4. Resolve the **Fixture** attached to the eval case.
    5. Create **recording dependencies** via
       ``create_recording_dependencies(fixture, call_journal)``.
    6. Create a ``JSONConversationCheckpointStore`` rooted under the work
       directory.
    7. Build a **session ID** in the format
       ``eval-{run_id[:8]}-{case.id}-{label}-r{repetition:02d}``.
    8. Compute **fixed_now** as noon on *fixed_date_str* in the given
       timezone (default ``Asia/Shanghai``).
    9. Instantiate ``NasClawAgentRunner`` with the isolated store, settings,
       fixed time, trace root, and recording dependencies.  Background task
       stores (download automation factory, runtime task store, task
       management service) are all set to ``None`` — the recording
       dependencies handle them.
    10. Return the ``EvalEnvironment``.
    """
    # ── 1. Trial work directory ──────────────────────────────────────────
    work_dir = base_work_dir / f"{case.id}-r{repetition:02d}"
    for sub in ("checkpoints", "memory", "runtime", "traces", "settings"):
        (work_dir / sub).mkdir(parents=True, exist_ok=True)

    # ── 2. Build eval Settings snapshot ──────────────────────────────────
    base_config = get_settings().model_dump()
    base_config["app_timezone"] = fixed_timezone
    base_config["download_default_save_path"] = "/eval/downloads"
    # Isolate task database so eval runs never touch the production DB.
    base_config["task_db_path"] = str(work_dir / "runtime" / "tasks.db")
    eval_settings = Settings.model_validate(base_config)

    # ── 3. CallJournal ───────────────────────────────────────────────────
    call_journal = CallJournal()

    # ── 4. Resolve fixture ───────────────────────────────────────────────
    fixture = get_fixture(case)

    # ── 5. Recording dependencies ────────────────────────────────────────
    deps = create_recording_dependencies(fixture, call_journal)

    # ── 6. Checkpoint store ──────────────────────────────────────────────
    checkpoint_store = JSONConversationCheckpointStore(work_dir / "checkpoints")

    # ── 7. Session ID ────────────────────────────────────────────────────
    session_id = f"eval-{run_id[:8]}-{case.id}-{label}-r{repetition:02d}"

    # ── 8. Fixed now (noon on fixed_date_str in given timezone) ──────────
    tz = ZoneInfo(fixed_timezone)
    parsed = datetime.strptime(fixed_date_str, "%Y-%m-%d")
    fixed_now = parsed.replace(hour=12, tzinfo=tz)

    # ── 9. Runner ────────────────────────────────────────────────────────
    runner = NasClawAgentRunner(
        checkpoint_store=checkpoint_store,
        settings=eval_settings,
        fixed_now=fixed_now,
        trace_root=work_dir / "traces",
        dependencies=deps,
        memory_root=work_dir / "memory",
        download_automation_factory=None,
        runtime_task_store=None,
        task_management_service_factory=None,
    )

    # ── 10. Return ───────────────────────────────────────────────────────
    return EvalEnvironment(
        run_id=run_id,
        suite=suite,
        case_id=case.id,
        repetition=repetition,
        label=label,
        fixture=fixture,
        work_dir=work_dir,
        call_journal=call_journal,
        runner=runner,
        session_id=session_id,
        fixed_now=fixed_now,
    )
