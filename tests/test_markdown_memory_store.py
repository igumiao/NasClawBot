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
        "\n<!-- note -->\n\n- [2026-06-18] Prefers concise answers.\n\n- [2026-06-18] Avoids real downloads.\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)

    assert store.format_user_profile_prompt() == (
        "- Prefers concise answers.\n"
        "- Avoids real downloads."
    )


def test_format_user_profile_prompt_ignores_heading_only_template(tmp_path: Path):
    (tmp_path / "user_profile.md").write_text("", encoding="utf-8")
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

    assert (tmp_path / "user_profile.md").read_text(encoding="utf-8") == ""
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


# ---------------------------------------------------------------------------
# get_sections
# ---------------------------------------------------------------------------


def test_get_sections_returns_headings(tmp_path: Path):
    (tmp_path / "knowledge.md").write_text(
        "# Knowledge\n\n## TMDB\n- item\n\n## M-Team\n- item\n\n## Other\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)
    sections = store.get_sections(MemoryKind.KNOWLEDGE)
    assert sections == ["TMDB", "M-Team", "Other"]


def test_get_sections_missing_file_returns_empty(tmp_path: Path):
    store = MarkdownMemoryStore(tmp_path)
    assert store.get_sections(MemoryKind.KNOWLEDGE) == []


# ---------------------------------------------------------------------------
# append_to_section
# ---------------------------------------------------------------------------


def test_append_to_section_inserts_under_correct_heading(tmp_path: Path):
    (tmp_path / "knowledge.md").write_text(
        "# Knowledge\n\n## TMDB\n- old entry\n\n## M-Team\n- another\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)
    store.append_to_section(MemoryKind.KNOWLEDGE, "TMDB", "new tip")
    content = (tmp_path / "knowledge.md").read_text(encoding="utf-8")
    lines = content.splitlines()
    tmdb_idx = next(i for i, l in enumerate(lines) if l.strip() == "## TMDB")
    mteam_idx = next(i for i, l in enumerate(lines) if l.strip() == "## M-Team")
    assert "- old entry" in lines  # old entry still there
    assert "new tip" in content
    new_tip_line_idx = next(i for i, l in enumerate(lines) if "new tip" in l)
    assert new_tip_line_idx < mteam_idx
    assert new_tip_line_idx > tmdb_idx
    # new tip inserted after the old entry content, before next section heading
    assert lines[new_tip_line_idx].startswith("- [20")


def test_append_to_section_creates_section_if_missing(tmp_path: Path):
    store = MarkdownMemoryStore(tmp_path)
    store.append_to_section(MemoryKind.KNOWLEDGE, "NewSection", "first item")
    content = (tmp_path / "knowledge.md").read_text(encoding="utf-8")
    assert "## NewSection" in content
    assert "first item" in content


def test_append_user_profile_entry_appends_flat_timestamped_bullet(tmp_path: Path):
    (tmp_path / "user_profile.md").write_text("", encoding="utf-8")
    store = MarkdownMemoryStore(tmp_path)

    store.append_user_profile_entry("喜欢简洁回答。")

    content = (tmp_path / "user_profile.md").read_text(encoding="utf-8")
    assert "## " not in content
    assert "- [" in content
    assert "喜欢简洁回答。" in content


def test_append_user_profile_entry_strips_existing_date_prefix(tmp_path: Path):
    store = MarkdownMemoryStore(tmp_path)

    store.append_user_profile_entry("- [2026-06-01] 已带日期的条目")

    content = (tmp_path / "user_profile.md").read_text(encoding="utf-8")
    assert content.count("- [") == 1
    assert "已带日期的条目" in content


# ---------------------------------------------------------------------------
# replace_in_section
# ---------------------------------------------------------------------------


def test_replace_in_section_replaces_correct_line(tmp_path: Path):
    (tmp_path / "knowledge.md").write_text(
        "# Knowledge\n\n## TMDB\n- old tip\n\n## M-Team\n- another\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)
    result = store.replace_in_section(MemoryKind.KNOWLEDGE, "- old tip", "- new improved tip")
    assert result is True
    content = (tmp_path / "knowledge.md").read_text(encoding="utf-8")
    assert "- new improved tip" in content
    assert "- old tip" not in content


def test_replace_in_section_returns_false_when_no_match(tmp_path: Path):
    (tmp_path / "knowledge.md").write_text(
        "# Knowledge\n\n## TMDB\n- tip one\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)
    result = store.replace_in_section(MemoryKind.KNOWLEDGE, "- nonexistent line", "- new")
    assert result is False
    content = (tmp_path / "knowledge.md").read_text(encoding="utf-8")
    assert "- tip one" in content


def test_replace_in_section_match_is_strip_only(tmp_path: Path):
    (tmp_path / "knowledge.md").write_text(
        "# Knowledge\n\n  - padded tip  \n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)
    result = store.replace_in_section(MemoryKind.KNOWLEDGE, "- padded tip", "- clean tip")
    assert result is True
    content = (tmp_path / "knowledge.md").read_text(encoding="utf-8")
    assert "- clean tip" in content
    assert "- padded tip" not in content


def test_replace_in_section_missing_whitespace_fallback(tmp_path: Path):
    """LLM drops a space: '我叫 IGUMIAO' vs '我叫IGUMIAO'."""
    (tmp_path / "knowledge.md").write_text(
        "# Knowledge\n\n- 我叫 IGUMIAO-NAS，也叫\"大人\"\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)
    # LLM returned version with space missing between Chinese and English
    result = store.replace_in_section(
        MemoryKind.KNOWLEDGE,
        "- 我叫IGUMIAO-NAS，也叫\"大人\"",
        "- 我叫 Maifa，也叫\"M大人\"",
    )
    assert result is True
    content = (tmp_path / "knowledge.md").read_text(encoding="utf-8")
    assert "Maifa" in content
    assert "IGUMIAO" not in content


def test_replace_in_section_extra_whitespace_fallback(tmp_path: Path):
    """LLM adds extra spaces."""
    (tmp_path / "knowledge.md").write_text(
        "# Knowledge\n\n- hello world\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)
    result = store.replace_in_section(
        MemoryKind.KNOWLEDGE,
        "- hello   world",
        "- hello universe",
    )
    assert result is True
    content = (tmp_path / "knowledge.md").read_text(encoding="utf-8")
    assert "hello universe" in content


def test_find_line_index_exact_match(tmp_path: Path):
    store = MarkdownMemoryStore(tmp_path)
    idx = store.find_line_index(["- a", "- b", "- c"], "- b")
    assert idx == 1


def test_find_line_index_whitespace_fallback(tmp_path: Path):
    store = MarkdownMemoryStore(tmp_path)
    idx = store.find_line_index(
        ["- 我叫 IGUMIAO-NAS", "- another line"],
        "- 我叫IGUMIAO-NAS",
    )
    assert idx == 0


def test_find_line_index_none_when_no_match(tmp_path: Path):
    store = MarkdownMemoryStore(tmp_path)
    idx = store.find_line_index(["- a", "- b"], "- completely different")
    assert idx is None


# ---------------------------------------------------------------------------
# delete_from_section
# ---------------------------------------------------------------------------


def test_delete_from_section_removes_correct_line(tmp_path: Path):
    (tmp_path / "knowledge.md").write_text(
        "# Knowledge\n\n## TMDB\n- stale tip\n- keep tip\n\n## M-Team\n- another\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)
    result = store.delete_from_section(MemoryKind.KNOWLEDGE, "- stale tip")
    assert result is True
    content = (tmp_path / "knowledge.md").read_text(encoding="utf-8")
    assert "- stale tip" not in content
    assert "- keep tip" in content


def test_delete_from_section_removes_trailing_blank_line(tmp_path: Path):
    (tmp_path / "knowledge.md").write_text(
        "# Knowledge\n\n## TMDB\n- only entry\n\n## M-Team\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)
    result = store.delete_from_section(MemoryKind.KNOWLEDGE, "- only entry")
    assert result is True
    content = (tmp_path / "knowledge.md").read_text(encoding="utf-8")
    assert "- only entry" not in content
    assert "\n\n\n" not in content


def test_delete_from_section_returns_false_when_no_match(tmp_path: Path):
    (tmp_path / "knowledge.md").write_text(
        "# Knowledge\n\n## TMDB\n- tip one\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)
    result = store.delete_from_section(MemoryKind.KNOWLEDGE, "- nonexistent")
    assert result is False
    content = (tmp_path / "knowledge.md").read_text(encoding="utf-8")
    assert "- tip one" in content


def test_delete_from_section_whitespace_fallback(tmp_path: Path):
    """LLM drops spaces: delete still works."""
    (tmp_path / "knowledge.md").write_text(
        "# Knowledge\n\n- 我叫 IGUMIAO-NAS，也叫\"大人\"\n",
        encoding="utf-8",
    )
    store = MarkdownMemoryStore(tmp_path)
    result = store.delete_from_section(
        MemoryKind.KNOWLEDGE,
        "- 我叫IGUMIAO-NAS，也叫\"大人\"",
    )
    assert result is True
    content = (tmp_path / "knowledge.md").read_text(encoding="utf-8")
    assert "IGUMIAO" not in content


# ---------------------------------------------------------------------------
# _find_similar_lines
# ---------------------------------------------------------------------------


def test_find_similar_lines_returns_overlapping_lines():
    lines = [
        "# header",
        "- 我叫 IGUMIAO-NAS，也叫\"大人\"",
        "- completely unrelated",
        "",
    ]
    similar = MarkdownMemoryStore._find_similar_lines(
        lines, "- 我叫IGUMIAO-NAS，也叫\"大人\""
    )
    assert len(similar) >= 1
    assert "IGUMIAO" in similar[0]


def test_find_similar_lines_skips_headings_and_blanks():
    lines = ["# header", "", "## section", "- actual content"]
    similar = MarkdownMemoryStore._find_similar_lines(lines, "content")
    assert similar == ["- actual content"]


# ---------------------------------------------------------------------------
# _strip_date_prefix
# ---------------------------------------------------------------------------


def test_strip_date_prefix_removes_leading_date():
    from app.services.markdown_memory_store import _strip_date_prefix

    assert _strip_date_prefix("- [2026-06-15] hello world") == "hello world"
    assert _strip_date_prefix("- [2024-01-01] keep this") == "keep this"


def test_strip_date_prefix_no_date_unchanged():
    from app.services.markdown_memory_store import _strip_date_prefix

    assert _strip_date_prefix("plain text") == "plain text"
    assert _strip_date_prefix("- just a dash") == "- just a dash"
