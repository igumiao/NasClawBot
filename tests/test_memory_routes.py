"""Tests for memory curation API routes."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app


def _setup_memory_files(tmp_path: Path, inbox_content: str = ""):
    memory_dir = tmp_path / "agent-memory"
    memory_dir.mkdir(parents=True)
    if inbox_content:
        (memory_dir / "memory_inbox.md").write_text(inbox_content, encoding="utf-8")
    (memory_dir / "user_profile.md").write_text("", encoding="utf-8")
    (memory_dir / "knowledge.md").write_text(
        "# Knowledge\n"
        "\n"
        "## TMDB\n"
        "\n"
        "## M-Team\n"
        "\n"
        "## Other\n",
        encoding="utf-8",
    )
    return memory_dir


def test_get_inbox_empty(monkeypatch, tmp_path: Path):
    memory_dir = _setup_memory_files(tmp_path)
    monkeypatch.setattr("app.api.memory_routes._MEMORY_DIR", memory_dir)
    client = TestClient(app)
    response = client.get("/memory/inbox")
    assert response.status_code == 200
    data = response.json()
    assert data["entries"] == []
    assert data["entry_count"] == 0


def test_get_inbox_with_entries(monkeypatch, tmp_path: Path):
    memory_dir = _setup_memory_files(
        tmp_path,
        "## 2026-06-12 10:17 | 知识\n\n测试条目。\n\n---\n",
    )
    monkeypatch.setattr("app.api.memory_routes._MEMORY_DIR", memory_dir)
    client = TestClient(app)
    response = client.get("/memory/inbox")
    assert response.status_code == 200
    data = response.json()
    assert data["entry_count"] == 1
    assert data["entries"][0]["text"] == "测试条目。"


def test_curate_with_mock_llm(monkeypatch, tmp_path: Path):
    memory_dir = _setup_memory_files(
        tmp_path,
        "## 2026-06-12 10:17 | 知识\n\n测试条目。\n\n---\n",
    )
    monkeypatch.setattr("app.api.memory_routes._MEMORY_DIR", memory_dir)

    mock_response = MagicMock()
    mock_response.content = json.dumps({
        "suggestions": [{
            "inbox_index": 0,
            "preview": "测试条目。",
            "action": "keep",
            "destination": "knowledge",
            "section": "TMDB",
            "edited_text": "润色后文本",
        }],
        "inbox_entry_count": 1,
    })

    with patch("app.services.curator._build_curator_llm") as mock_llm_class:
        mock_llm_class.return_value.invoke.return_value = mock_response
        client = TestClient(app)
        response = client.post("/memory/curate")
    assert response.status_code == 200
    data = response.json()
    assert data["inbox_entry_count"] == 1
    assert data["suggestions"][0]["action"] == "keep"
    assert "sections" in data
    assert data["sections"]["user_profile"] == []
    assert data["sections"]["knowledge"] == ["TMDB", "M-Team", "Other"]


def test_apply_moves_entries(monkeypatch, tmp_path: Path):
    memory_dir = _setup_memory_files(
        tmp_path,
        "## 2026-06-12 10:17 | 知识\n\n保留条目。\n\n---\n"
        "## 2026-06-12 10:18 | 知识\n\n丢弃条目。\n\n---\n",
    )
    monkeypatch.setattr("app.api.memory_routes._MEMORY_DIR", memory_dir)
    client = TestClient(app)

    response = client.patch("/memory/curate/apply", json={
        "inbox_entry_count": 2,
        "decisions": [
            {"inbox_index": 0, "action": "keep", "destination": "knowledge", "section": "TMDB", "text": "保留条目。"},
            {"inbox_index": 1, "action": "discard"},
        ],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["applied"] == 1
    assert data["discarded"] == 1
    assert data["remaining"] == 0

    # Verify knowledge.md was updated
    knowledge = (memory_dir / "knowledge.md").read_text(encoding="utf-8")
    assert "保留条目" in knowledge

    # Verify inbox is empty now
    inbox = (memory_dir / "memory_inbox.md").read_text(encoding="utf-8")
    assert "保留条目" not in inbox
    assert "丢弃条目" not in inbox


def test_apply_rejects_count_mismatch(monkeypatch, tmp_path: Path):
    memory_dir = _setup_memory_files(
        tmp_path, "## 2026-06-12 10:17 | 知识\n\n单条。\n\n---\n"
    )
    monkeypatch.setattr("app.api.memory_routes._MEMORY_DIR", memory_dir)
    client = TestClient(app)

    response = client.patch("/memory/curate/apply", json={
        "inbox_entry_count": 99,
        "decisions": [],
    })
    assert response.status_code == 409


def test_full_curation_flow(monkeypatch, tmp_path: Path):
    """Simulate complete flow: write to inbox -> curate -> apply."""
    memory_dir = _setup_memory_files(tmp_path)
    from app.services.markdown_memory_store import MarkdownMemoryStore
    store = MarkdownMemoryStore(memory_dir)
    store.append_to_inbox("用户偏好 4K HDR 画质。在多次对话中用户选择了 4K 资源。")
    store.append_to_inbox("M-Team 搜索中文片名时不应加 IMDb 过滤。")
    store.append_to_inbox("用户不喜欢恐怖片。")

    monkeypatch.setattr("app.api.memory_routes._MEMORY_DIR", memory_dir)
    client = TestClient(app)

    # Step 1: Read inbox
    resp = client.get("/memory/inbox")
    assert resp.status_code == 200
    assert resp.json()["entry_count"] == 3

    # Step 2: Mock curator
    mock_response = MagicMock()
    mock_response.content = json.dumps({
        "suggestions": [
            {"inbox_index": 0, "preview": "用户偏好 4K", "action": "keep", "destination": "user_profile", "section": None, "edited_text": "偏好 4K HDR 画质。"},
            {"inbox_index": 1, "preview": "M-Team 搜索", "action": "keep", "destination": "knowledge", "section": "M-Team", "edited_text": "搜索中文片名时不加 IMDb 过滤更准。"},
            {"inbox_index": 2, "preview": "用户不喜欢恐怖片", "action": "keep", "destination": "user_profile", "section": None, "edited_text": "不喜欢恐怖片。"},
        ],
        "inbox_entry_count": 3,
    })

    with patch("app.services.curator._build_curator_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = mock_response
        resp = client.post("/memory/curate")
    assert resp.status_code == 200

    # Step 3: Apply all
    resp = client.patch("/memory/curate/apply", json={
        "inbox_entry_count": 3,
        "decisions": [
            {"inbox_index": 0, "action": "keep", "destination": "user_profile", "text": "偏好 4K HDR 画质。"},
            {"inbox_index": 1, "action": "keep", "destination": "knowledge", "section": "M-Team", "text": "搜索中文片名时不加 IMDb 过滤更准。"},
            {"inbox_index": 2, "action": "keep", "destination": "user_profile", "text": "不喜欢恐怖片。"},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["applied"] == 3
    assert data["remaining"] == 0

    # Verify files updated
    user_profile = (memory_dir / "user_profile.md").read_text(encoding="utf-8")
    assert "4K HDR" in user_profile
    assert "恐怖片" in user_profile
    knowledge = (memory_dir / "knowledge.md").read_text(encoding="utf-8")
    assert "IMDb" in knowledge


def test_apply_user_profile_keep_ignores_section(monkeypatch, tmp_path: Path):
    memory_dir = _setup_memory_files(
        tmp_path,
        "## 2026-06-12 10:17 | 知识\n\n用户喜欢简洁回答。\n\n---\n",
    )
    monkeypatch.setattr("app.api.memory_routes._MEMORY_DIR", memory_dir)
    client = TestClient(app)

    response = client.patch("/memory/curate/apply", json={
        "inbox_entry_count": 1,
        "decisions": [
            {
                "inbox_index": 0,
                "action": "keep",
                "destination": "user_profile",
                "section": "Communication Style",
                "text": "用户喜欢简洁回答。",
            },
        ],
    })

    assert response.status_code == 200
    user_profile = (memory_dir / "user_profile.md").read_text(encoding="utf-8")
    assert "Communication Style" not in user_profile
    assert "- [" in user_profile
    assert "用户喜欢简洁回答。" in user_profile


def test_apply_modify_replaces_line(monkeypatch, tmp_path: Path):
    memory_dir = _setup_memory_files(tmp_path)
    (memory_dir / "knowledge.md").write_text(
        "# Knowledge\n\n## TMDB\n- old tip\n\n## M-Team\n- another\n\n## Other\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.api.memory_routes._MEMORY_DIR", memory_dir)
    client = TestClient(app)

    response = client.patch("/memory/curate/apply", json={
        "inbox_entry_count": 0,
        "decisions": [
            {"action": "modify", "destination": "knowledge", "existing_text": "- old tip", "new_text": "- updated tip"},
        ],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["modified"] == 1

    knowledge = (memory_dir / "knowledge.md").read_text(encoding="utf-8")
    assert "- updated tip" in knowledge
    assert "- old tip" not in knowledge


def test_apply_delete_removes_line(monkeypatch, tmp_path: Path):
    memory_dir = _setup_memory_files(tmp_path)
    (memory_dir / "knowledge.md").write_text(
        "# Knowledge\n\n## TMDB\n- stale entry\n\n## M-Team\n- keep this\n\n## Other\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.api.memory_routes._MEMORY_DIR", memory_dir)
    client = TestClient(app)

    response = client.patch("/memory/curate/apply", json={
        "inbox_entry_count": 0,
        "decisions": [
            {"action": "delete", "destination": "knowledge", "existing_text": "- stale entry"},
        ],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] == 1

    knowledge = (memory_dir / "knowledge.md").read_text(encoding="utf-8")
    assert "- stale entry" not in knowledge
    assert "- keep this" in knowledge


def test_apply_rejects_unmatched_existing_text(monkeypatch, tmp_path: Path):
    memory_dir = _setup_memory_files(tmp_path)
    monkeypatch.setattr("app.api.memory_routes._MEMORY_DIR", memory_dir)
    client = TestClient(app)

    response = client.patch("/memory/curate/apply", json={
        "inbox_entry_count": 0,
        "decisions": [
            {"action": "modify", "destination": "knowledge", "existing_text": "- not in file", "new_text": "- will fail"},
        ],
    })
    assert response.status_code == 400
    assert "无法定位原文片段" in response.json()["detail"]


def test_apply_mix_keep_modify_delete(monkeypatch, tmp_path: Path):
    memory_dir = _setup_memory_files(
        tmp_path,
        "## 2026-06-12 10:17 | 知识\n\n新知识点。\n\n---\n",
    )
    (memory_dir / "knowledge.md").write_text(
        "# Knowledge\n\n## TMDB\n- stale line\n\n## M-Team\n- keep this\n\n## Other\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.api.memory_routes._MEMORY_DIR", memory_dir)
    client = TestClient(app)

    response = client.patch("/memory/curate/apply", json={
        "inbox_entry_count": 1,
        "decisions": [
            {"action": "keep", "inbox_index": 0, "destination": "knowledge", "section": "TMDB", "text": "新知识点。"},
            {"action": "modify", "destination": "knowledge", "existing_text": "- stale line", "new_text": "- fresh line"},
            {"action": "delete", "destination": "knowledge", "existing_text": "- keep this"},
        ],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["applied"] == 1
    assert data["modified"] == 1
    assert data["deleted"] == 1
    assert data["remaining"] == 0

    knowledge = (memory_dir / "knowledge.md").read_text(encoding="utf-8")
    assert "新知识点" in knowledge
    assert "- fresh line" in knowledge
    assert "- keep this" not in knowledge
    assert "- stale line" not in knowledge
