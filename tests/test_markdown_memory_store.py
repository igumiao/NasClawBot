"""Tests for the read-only markdown memory store."""

from pathlib import Path

import pytest

from app.domain.memory import MemoryKind
from app.services.markdown_memory_store import MarkdownMemoryStore

# ---------------------------------------------------------------------------
# parse_inbox
# ---------------------------------------------------------------------------


def test_parse_inbox_returns_entries(tmp_path: Path):
    (tmp_path / "memory_inbox.md").write_text(
        "## 2026-06-12 10:17 | 知识\n"
        "\n"
        "用户偏好：华语片用中文名搜索。\n"
        "\n"
        "---\n"
        "## 2026-06-12 10:18 | 知识\n"
        "\n"
        "用户喜欢动漫。\n"
        "\n"
        "---\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)
    entries = store.parse_inbox()
    assert len(entries) == 2
    assert entries[0]["index"] == 0
    assert entries[0]["timestamp"] == "2026-06-12 10:17"
    assert entries[0]["text"] == "用户偏好：华语片用中文名搜索。"
    assert entries[1]["index"] == 1
    assert entries[1]["text"] == "用户喜欢动漫。"


def test_parse_inbox_missing_file_returns_empty(tmp_path: Path):
    store = MarkdownMemoryStore(tmp_path)
    assert store.parse_inbox() == []


def test_parse_inbox_handles_trailing_separator(tmp_path: Path):
    (tmp_path / "memory_inbox.md").write_text(
        "## 2026-06-12 10:17 | 知识\n\nsingle entry\n\n---\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)
    entries = store.parse_inbox()
    assert len(entries) == 1


def test_missing_memory_files_are_empty_documents(tmp_path: Path):
    store = MarkdownMemoryStore(tmp_path)

    assert store.load(MemoryKind.KNOWLEDGE).kind == MemoryKind.KNOWLEDGE
    assert store.load(MemoryKind.KNOWLEDGE).text == ""
    assert store.search("anything") == []
    assert store.format_user_profile_prompt() == ""


def test_search_finds_case_insensitive_lines_with_sections(tmp_path: Path):
    (tmp_path / "knowledge.md").write_text(
        "# Movies\n"
        "Dune has a 2021 adaptation.\n"
        "\n"
        "## Cast\n"
        "Zendaya appears in DUNE.\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)

    hits = store.search("dune", limit=10)

    assert [hit.line_number for hit in hits] == [2, 5]
    assert [hit.section for hit in hits] == ["Movies", "Cast"]
    assert hits[0].text == "Dune has a 2021 adaptation."


def test_search_respects_limit(tmp_path: Path):
    (tmp_path / "knowledge.md").write_text(
        "alpha one\nalpha two\nalpha three\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)

    hits = store.search("alpha", limit=2)
    assert len(hits) == 2
    assert hits[0].text == "alpha one"
    assert hits[1].text == "alpha two"


def test_search_ranks_heading_matches_before_body_matches(tmp_path: Path):
    (tmp_path / "knowledge.md").write_text(
        "# Search Notes\n"
        "TMDB is useful for title disambiguation.\n"
        "\n"
        "## TMDB\n"
        "- Chinese titles can map to multiple years.\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)

    hits = store.search("tmdb", limit=5)

    assert [hit.match_type for hit in hits] == ["heading", "body"]
    assert hits[0].score > hits[1].score
    assert hits[0].line_number == 4


def test_search_returns_context_lines(tmp_path: Path):
    (tmp_path / "knowledge.md").write_text(
        "# Knowledge\n"
        "line before\n"
        "target alpha\n"
        "line after\n"
        "second after\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)

    hits = store.search("alpha", limit=1)

    assert hits[0].context is not None
    assert [(line.line_number, line.text) for line in hits[0].context] == [
        (1, "# Knowledge"),
        (2, "line before"),
        (3, "target alpha"),
        (4, "line after"),
        (5, "second after"),
    ]


def test_search_rejects_invalid_limit(tmp_path: Path):
    store = MarkdownMemoryStore(tmp_path)

    with pytest.raises(ValueError, match="limit must be >= 1"):
        store.search("alpha", limit=0)

    with pytest.raises(ValueError, match="limit must be an integer"):
        store.search("alpha", limit="many")


def test_format_user_profile_prompt_compacts_blank_lines(tmp_path: Path):
    (tmp_path / "user_profile.md").write_text(
        "\n# User\n\nPrefers concise answers.\n\nAvoids real downloads.\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)

    assert store.format_user_profile_prompt() == (
        "User profile memory:\n"
        "# User\n"
        "Prefers concise answers.\n"
        "Avoids real downloads."
    )


def test_format_user_profile_prompt_ignores_heading_only_template(tmp_path: Path):
    (tmp_path / "user_profile.md").write_text(
        "# User Profile\n\n"
        "## Communication Style\n\n"
        "## Tool Preferences\n\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)

    assert store.format_user_profile_prompt() == ""


def test_store_never_reads_symlinked_file_outside_root(tmp_path: Path):
    outside = tmp_path / "outside.md"
    outside.write_text("secret alpha\n", encoding="utf-8")
    root = tmp_path / "memory"
    root.mkdir()
    (root / "knowledge.md").symlink_to(outside)
    store = MarkdownMemoryStore(root)

    with pytest.raises(ValueError, match="outside configured root"):
        store.load(MemoryKind.KNOWLEDGE)


def test_ensure_template_files_creates_missing_files(tmp_path: Path):
    store = MarkdownMemoryStore(tmp_path)
    store.ensure_template_files()

    assert (tmp_path / "user_profile.md").read_text(encoding="utf-8").startswith("# User Profile")
    assert (tmp_path / "knowledge.md").read_text(encoding="utf-8").startswith("# Knowledge")
    assert not (tmp_path / "memory.md").exists()


def test_ensure_template_files_never_overwrites_existing_files(tmp_path: Path):
    (tmp_path / "knowledge.md").write_text("custom knowledge\n", encoding="utf-8")
    store = MarkdownMemoryStore(tmp_path)
    store.ensure_template_files()

    assert (tmp_path / "knowledge.md").read_text(encoding="utf-8") == "custom knowledge\n"


def test_ensure_template_files_idempotent(tmp_path: Path):
    store = MarkdownMemoryStore(tmp_path)
    store.ensure_template_files()
    mtime_before = (tmp_path / "knowledge.md").stat().st_mtime
    store.ensure_template_files()
    mtime_after = (tmp_path / "knowledge.md").stat().st_mtime

    assert mtime_before == mtime_after
