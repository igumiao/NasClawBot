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
    """Mock LLM returns structured JSON, verify curator parses it."""
    (tmp_path / "memory_inbox.md").write_text(
        "## 2026-06-12 10:17 | 知识\n\n用户偏好：华语片用中文名搜索。\n\n---\n",
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
                }
            ],
            "inbox_entry_count": 1,
        }
    )

    with patch("app.services.curator._build_curator_llm", return_value=MagicMock()) as mock_llm:
        mock_llm.return_value.invoke.return_value = mock_response
        result = run_curation(store)

    assert result.inbox_entry_count == 1
    assert result.suggestions[0].action == "keep"
    assert result.suggestions[0].destination == "knowledge"
    assert result.suggestions[0].section == "M-Team"


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
