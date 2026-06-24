from pathlib import Path

from app.agent.runner import current_agent_session_id
from app.tools.list_task_events import ListTaskEventsTool
from app.tools.monitor_download import MonitorDownloadTool
from app.tools.task_cancel import TaskCancelTool
from app.domain.downloads import DownloadSubmissionRequest
from evals.models import Fixture
from evals.loader import load_fixture
from evals.recording import CallJournal, create_recording_dependencies

QB_HASH = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _dependencies():
    fixture = load_fixture("base-world", Path("evals/fixtures"))
    journal = CallJournal()
    return create_recording_dependencies(fixture, journal), journal


def test_recording_monitor_contract_returns_success() -> None:
    dependencies, journal = _dependencies()

    response = MonitorDownloadTool(dependencies.download_automation).run(
        {
            "torrent_hash": QB_HASH,
            "mode": "once",
            "on_completed": "notify",
        }
    )

    assert response.status.value == "success"
    assert response.data["receipt"]["mode"] == "once"
    assert response.data["receipt"]["torrent_hash"] == QB_HASH
    effects = [entry for entry in journal.entries if entry.kind == "effect"]
    assert [entry.operation for entry in effects] == ["create_monitor"]


def test_recording_runtime_store_satisfies_list_task_events_contract() -> None:
    dependencies, _journal = _dependencies()
    token = current_agent_session_id.set("eval-session")
    try:
        response = ListTaskEventsTool(dependencies.runtime_task_store).run({})
    finally:
        current_agent_session_id.reset(token)

    assert response.status.value == "success"
    assert response.data == {"events": [], "count": 0}


def test_recording_task_management_satisfies_cancel_contract() -> None:
    fixture = Fixture(
        name="task-world",
        background_tasks=[
            {
                "task_id": "task-queued",
                "kind": "download_watch",
                "status": "QUEUED",
                "title": "Queued monitor",
            }
        ],
    )
    journal = CallJournal()
    dependencies = create_recording_dependencies(fixture, journal)

    response = TaskCancelTool(dependencies.task_management).run(
        {"task_id": "task-queued"}
    )

    assert response.status.value == "success"
    assert response.data["task_id"] == "task-queued"
    assert any(
        entry.operation == "cancel_task" and entry.kind == "effect"
        for entry in journal.entries
    )


def test_recording_mcp_marks_mutations_as_effects() -> None:
    dependencies, journal = _dependencies()

    dependencies.mcp_pool.call_tool_sync(
        "filesystem",
        "move_file",
        {"source": "/media/downloads/a", "destination": "/media/library/a"},
    )
    dependencies.mcp_pool.call_tool_sync(
        "filesystem",
        "list_directory",
        {"path": "/media/library"},
    )

    entries = [entry for entry in journal.entries if entry.dependency == "mcp"]
    assert [entry.kind for entry in entries] == ["effect", "read"]


def test_recording_tmdb_accepts_title_with_year_variant() -> None:
    dependencies, _journal = _dependencies()

    result = dependencies.tmdb.search_multi("Dune 2021")

    assert result["total_results"] == 2


def test_recording_download_error_sets_journal_outcome() -> None:
    dependencies, journal = _dependencies()

    result = dependencies.download_automation.submit_downloads(
        [DownloadSubmissionRequest(torrent_id="599")],
        completion_action="notify",
    )

    assert result.items[0].status == "failed"
    entry = journal.filter_by(dependency="download", operation="submit_downloads")[0]
    assert entry.outcome == "error"


def test_recording_download_timeout_is_a_deterministic_tool_failure() -> None:
    fixture = Fixture(
        name="timeout-world",
        download_submit_error={
            "torrent_id": "101",
            "outcome": "timeout",
            "code": "TIMEOUT",
            "status": "error",
        },
    )
    journal = CallJournal()
    from evals.recording import create_recording_dependencies

    dependencies = create_recording_dependencies(fixture, journal)
    result = dependencies.download_automation.submit_downloads(
        [DownloadSubmissionRequest(torrent_id="101")],
        completion_action="notify",
    )

    assert result.items[0].status == "failed"
    assert result.items[0].error == "TIMEOUT"
    assert journal.entries[0].outcome == "timeout"
