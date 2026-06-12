"""Tests for RememberThisTool."""

from pathlib import Path

import pytest

from app.services.markdown_memory_store import MarkdownMemoryStore
from app.tools.remember_this import RememberThisTool


def test_remember_this_appends_to_inbox(tmp_path: Path):
    store = MarkdownMemoryStore(tmp_path)
    tool = RememberThisTool(store)

    response = tool.run({"text": "搜索中文片名时不加 IMDb 过滤更准。原因是两次搜索加了 IMDb 都没结果。"})

    assert response.status.value == "success"
    assert "IMDb" in response.data["entry"]
    inbox = (tmp_path / "memory_inbox.md").read_text(encoding="utf-8")
    assert "IMDb" in inbox
    assert "## " in inbox
    assert "---" in inbox
    assert "| 知识" in inbox


def test_remember_this_multiple_appends(tmp_path: Path):
    store = MarkdownMemoryStore(tmp_path)
    tool = RememberThisTool(store)

    tool.run({"text": "第一条：用户偏好 4K。"})
    tool.run({"text": "第二条：避开恐怖片。"})

    inbox = (tmp_path / "memory_inbox.md").read_text(encoding="utf-8")
    assert "4K" in inbox
    assert "恐怖片" in inbox
    assert inbox.count("---") == 2


@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"text": ""},
        {"text": "x" * 2001},
        {"extra": True},
        {"text": "valid", "kind": "facts"},
        None,
    ],
)
def test_remember_this_rejects_invalid_parameters(parameters):
    response = RememberThisTool().run(parameters)
    assert response.status.value == "error"
    assert response.error_info["code"] == "INVALID_PARAM"
