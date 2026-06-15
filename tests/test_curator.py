"""Tests for curator service."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.services.curator import CuratorResult, CuratorSuggestion, run_curation
from app.services.markdown_memory_store import MarkdownMemoryStore


def test_curator_result_validation():
    valid = CuratorResult(
        suggestions=[
            CuratorSuggestion(
                inbox_index=0,
                preview="前30字预览",
                action="keep",
                destination="knowledge",
                section="TMDB",
                edited_text="润色后文本",
            )
        ],
        inbox_entry_count=1,
    )
    assert valid.suggestions[0].action == "keep"


def test_curator_result_rejects_invalid_action():
    with pytest.raises(ValidationError):
        CuratorResult(
            suggestions=[
                CuratorSuggestion(
                    inbox_index=0,
                    preview="x",
                    action="merge",  # not allowed in v1
                )
            ],
            inbox_entry_count=1,
        )


def test_run_curation_empty_inbox(tmp_path: Path):
    store = MarkdownMemoryStore(tmp_path)
    result = run_curation(store)
    assert result.inbox_entry_count == 0
    assert result.suggestions == []


def test_run_curation_with_mock_llm(tmp_path: Path):
    """Mock LLM returns JSON with keep/discard/modify/delete, verify curator parses all."""
    (tmp_path / "memory_inbox.md").write_text(
        "## 2026-06-12 10:17 | 知识\n\n用户偏好：华语片用中文名搜索。\n\n---\n"
        "## 2026-06-15 10:00 | 知识\n\n用户现在叫 Maifa。\n\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "user_profile.md").write_text(
        "# User Profile\n\n## Identity\n- 我叫 IGUMIAO-NAS\n",
        encoding="utf-8",
    )
    (tmp_path / "knowledge.md").write_text(
        "# Knowledge\n\n## TMDB\n- old tip\n\n## M-Team\n- another\n\n## Other\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)

    mock_response = MagicMock()
    mock_response.content = json.dumps(
        {
            "suggestions": [
                {
                    "inbox_index": 0,
                    "preview": "用户偏好：华语片用中文名",
                    "action": "keep",
                    "destination": "knowledge",
                    "section": "M-Team",
                    "edited_text": "华语片用中文名搜索，非华语片用英文原名。",
                },
                {
                    "inbox_index": 1,
                    "preview": "用户现在叫 Maifa",
                    "action": "discard",
                },
                {
                    "inbox_index": None,
                    "preview": "",
                    "action": "modify",
                    "destination": "user_profile",
                    "section": "Identity",
                    "existing_text": "- 我叫 IGUMIAO-NAS",
                    "new_text": "- [2026-06-15] 用户称呼为 Maifa / M大人",
                    "reason": "称呼已更新",
                },
                {
                    "inbox_index": None,
                    "preview": "",
                    "action": "delete",
                    "destination": "knowledge",
                    "section": "TMDB",
                    "existing_text": "- old tip",
                    "reason": "该信息已过时",
                },
            ],
            "inbox_entry_count": 2,
        }
    )

    with patch("app.services.curator._build_curator_llm", return_value=MagicMock()) as mock_llm:
        mock_llm.return_value.invoke.return_value = mock_response
        result = run_curation(store)

    assert result.inbox_entry_count == 2
    assert len(result.suggestions) == 4

    keep = [s for s in result.suggestions if s.action == "keep"]
    assert len(keep) == 1
    assert keep[0].destination == "knowledge"

    modify = [s for s in result.suggestions if s.action == "modify"]
    assert len(modify) == 1
    assert modify[0].existing_text == "- 我叫 IGUMIAO-NAS"
    assert modify[0].new_text is not None

    delete = [s for s in result.suggestions if s.action == "delete"]
    assert len(delete) == 1
    assert delete[0].existing_text == "- old tip"
    assert delete[0].reason is not None


def test_curator_suggestion_modify_accepts_new_fields():
    suggestion = CuratorSuggestion(
        inbox_index=None,
        preview="",
        action="modify",
        destination="user_profile",
        section="Identity",
        existing_text="我叫 IGUMIAO-NAS",
        new_text="- [2026-06-15] 用户称呼为 Maifa",
        reason="称呼已更新",
    )
    assert suggestion.action == "modify"
    assert suggestion.inbox_index is None
    assert suggestion.existing_text == "我叫 IGUMIAO-NAS"


def test_curator_suggestion_delete_accepts_new_fields():
    suggestion = CuratorSuggestion(
        inbox_index=None,
        preview="",
        action="delete",
        destination="knowledge",
        section="Other",
        existing_text="过时提示",
        reason="信息不再适用",
    )
    assert suggestion.action == "delete"
    assert suggestion.new_text is None


def test_build_prompt_includes_current_date_and_evolution_rules(monkeypatch):
    """Verify the curator prompt includes the current UTC date and evolution instructions."""
    from app.services.curator import _build_prompt
    from unittest.mock import MagicMock
    import datetime as dt

    frozen_date = dt.datetime(2026, 6, 15, 12, 0, 0, tzinfo=dt.timezone.utc)

    # Patch datetime.datetime (the class) at the stdlib level, since _build_prompt
    # does a local "from datetime import datetime" inside the function.
    mock_class = MagicMock()
    mock_class.now.return_value = frozen_date
    mock_class.timezone = dt.timezone
    monkeypatch.setattr("datetime.datetime", mock_class)

    prompt = _build_prompt(
        entries=[{"index": 0, "timestamp": "2026-06-15", "text": "test"}],
        user_profile="# User Profile\n\n## Identity\n- old info\n",
        knowledge="# Knowledge\n\n## TMDB\n- some tip\n",
        sections={"user_profile": ["Identity"], "knowledge": ["TMDB"]},
    )
    assert "当前日期：2026-06-15" in prompt
    assert "UTC" in prompt
    assert "modify" in prompt.lower()
    assert "delete" in prompt.lower()
    assert "existing_text" in prompt
