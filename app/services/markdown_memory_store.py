"""Read-only markdown memory store."""

from __future__ import annotations

import re
from pathlib import Path
from threading import Lock

from app.domain.memory import MemoryContextLine, MemoryDocument, MemoryHit, MemoryKind
from app.domain.runtime_tasks import app_now, app_now_iso


DEFAULT_MARKDOWN_MEMORY_ROOT = Path(__file__).resolve().parents[2] / "memory" / "agent-memory"

MEMORY_FILENAMES: dict[MemoryKind, str] = {
    MemoryKind.USER_PROFILE: "user_profile.md",
    MemoryKind.KNOWLEDGE: "knowledge.md",
}
DEFAULT_MEMORY_SEARCH_LIMIT = 5
MAX_MEMORY_SEARCH_LIMIT = 20
DEFAULT_MEMORY_CONTEXT_LINES = 2
HEADING_MATCH_SCORE = 2.0
BODY_MATCH_SCORE = 1.0


MEMORY_INBOX_FILENAME = "memory_inbox.md"

_TEMPLATES: dict[MemoryKind, str] = {
    MemoryKind.USER_PROFILE: "",
    MemoryKind.KNOWLEDGE: (
        "# Knowledge\n"
        "\n"
        "## TMDB\n"
        "\n"
        "<!-- Example:\n"
        "- Chinese titles can map to multiple countries or years;"
        " disambiguate with TMDB before searching torrents.\n"
        "-->\n"
        "\n"
        "## M-Team\n"
        "\n"
        "<!-- Example:\n"
        "- User prefers 4K REMUX for movies, 1080p for TV series."
        " Learned from multiple download choices.\n"
        "-->\n"
        "\n"
        "## qBittorrent\n"
        "\n"
        "## Life & Productivity\n"
        "\n"
        "<!-- 生活技巧、效率方法、跨领域知识 -->\n"
        "\n"
        "## Other\n"
    ),
}


class MarkdownMemoryStore:
    """Load and search the fixed app markdown memory files."""

    def __init__(self, root: Path = DEFAULT_MARKDOWN_MEMORY_ROOT) -> None:
        self.root = Path(root)
        self._resolved_root = self.root.resolve()
        self._inbox_lock = Lock()

    def load(self, kind: MemoryKind) -> MemoryDocument:
        path = self._path_for(kind)
        if not path.exists():
            return MemoryDocument(kind=kind, text="")
        if not path.is_file():
            return MemoryDocument(kind=kind, text="")
        try:
            return MemoryDocument(kind=kind, text=path.read_text(encoding="utf-8"))
        except OSError:
            return MemoryDocument(kind=kind, text="")

    def search(
        self,
        query: str,
        limit: int | None = None,
    ) -> list[MemoryHit]:
        needle = str(query or "").strip().lower()
        if not needle:
            return []

        normalized_limit = self._normalize_limit(limit)
        document = self.load(MemoryKind.KNOWLEDGE)
        hits = self._search_document(document, needle)
        hits.sort(
            key=lambda hit: (
                -hit.score,
                hit.line_number,
            )
        )
        return hits[:normalized_limit]

    def get_sections(self, kind: MemoryKind) -> list[str]:
        """Return all ## heading text from a memory file (excludes ### sub-headings)."""
        path = self._path_for(kind)
        if not path.exists():
            return []
        sections: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("## ") and not stripped.startswith("### "):
                sections.append(stripped[3:].strip())
        return sections

    def append_to_section(self, kind: MemoryKind, section: str, text: str) -> None:
        """Append a dated entry under a ## Section heading.  Creates section at end if absent."""
        if not section or not section.strip():
            raise ValueError("section must be a non-empty string")

        target_heading = f"## {section.strip()}"
        today = app_now().strftime("%Y-%m-%d")
        clean_text = _strip_date_prefix(text)
        entry_line = f"- [{today}] {clean_text}"

        with self._inbox_lock:
            path = self._path_for(kind)
            content = path.read_text(encoding="utf-8") if path.exists() else ""
            lines = content.splitlines()

            insert_at = len(lines)
            found = False
            for i, line in enumerate(lines):
                if line.strip() == target_heading:
                    insert_at = i + 1
                    while insert_at < len(lines) and not lines[insert_at].strip().startswith("## "):
                        insert_at += 1
                    found = True
                    break

            if not found:
                if lines and lines[-1].strip():
                    lines.append("")
                lines.append(target_heading)
                insert_at = len(lines)

            new_lines = lines[:insert_at] + [entry_line, ""] + lines[insert_at:]
            path.write_text("\n".join(new_lines).rstrip("\n") + "\n", encoding="utf-8")

    def append_user_profile_entry(self, text: str) -> None:
        """Append a dated entry to user_profile.md without section headings."""
        today = app_now().strftime("%Y-%m-%d")
        clean_text = _strip_date_prefix(text)
        entry_line = f"- [{today}] {clean_text}"

        with self._inbox_lock:
            path = self._path_for(MemoryKind.USER_PROFILE)
            content = path.read_text(encoding="utf-8") if path.exists() else ""
            lines = content.splitlines()
            content_lines = [line for line in lines if line.strip()]
            if content_lines and not content.endswith("\n"):
                content += "\n"
            content += f"{entry_line}\n"
            path.write_text(content, encoding="utf-8")

    def path_for(self, kind: MemoryKind) -> Path:
        """Return the resolved path for a memory kind file."""
        return self._path_for(kind)

    def find_line_index(self, lines: list[str], needle: str) -> int | None:
        """Return the index of the first line matching `needle`, or None.

        Two-pass matching so the LLM doesn't have to copy whitespace perfectly:
        1. Exact .strip() match (fast, precise).
        2. Whitespace-stripped match — remove ALL whitespace from both sides and compare.
        """
        needle = needle.strip()
        # Pass 1: exact strip match
        for i, line in enumerate(lines):
            if line.strip() == needle:
                return i
        # Pass 2: whitespace-stripped match (handles LLM dropping/adding spaces)
        needle_no_ws = "".join(needle.split())
        for i, line in enumerate(lines):
            if "".join(line.strip().split()) == needle_no_ws:
                return i
        return None

    def replace_in_section(self, kind: MemoryKind, existing_text: str, new_text: str) -> bool:
        """Replace the first line matching `existing_text` with `new_text`.

        Uses two-pass matching so minor whitespace differences from the LLM
        (e.g. "我叫 IGUMIAO" vs "我叫IGUMIAO") still resolve correctly.

        Returns True if found and replaced, False otherwise.
        """
        with self._inbox_lock:
            path = self._path_for(kind)
            if not path.exists():
                return False
            content = path.read_text(encoding="utf-8")
            lines = content.splitlines()
            idx = self.find_line_index(lines, existing_text)
            if idx is None:
                return False
            lines[idx] = new_text
            path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
            return True

    def delete_from_section(self, kind: MemoryKind, existing_text: str) -> bool:
        """Remove the first line matching `existing_text`.

        Uses two-pass matching (same as replace_in_section).
        Also removes the following blank line if present. Returns True if found and removed.
        """
        with self._inbox_lock:
            path = self._path_for(kind)
            if not path.exists():
                return False
            content = path.read_text(encoding="utf-8")
            lines = content.splitlines()
            idx = self.find_line_index(lines, existing_text)
            if idx is None:
                return False
            del lines[idx]
            if idx < len(lines) and lines[idx].strip() == "":
                del lines[idx]
            path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
            return True

    @staticmethod
    def _find_similar_lines(lines: list[str], needle: str, top_n: int = 3) -> list[str]:
        """Return up to `top_n` lines whose whitespace-stripped content overlaps with the needle.

        Used to provide helpful context in "cannot locate" error messages.
        """
        needle_chars = set("".join(needle.split()))
        scored: list[tuple[int, str]] = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            line_chars = set("".join(stripped.split()))
            overlap = len(needle_chars & line_chars)
            if overlap > 0:
                scored.append((overlap, stripped))
        scored.sort(key=lambda x: -x[0])
        return [line for _, line in scored[:top_n]]

    def format_user_profile_prompt(self) -> str:
        """Return compact user profile entries for prompt injection, or empty string."""

        document = self.load(MemoryKind.USER_PROFILE)
        content_lines = [
            _strip_user_profile_prompt_line(line.strip())
            for line in document.text.splitlines()
            if line.strip()
            and not line.strip().startswith("#")
            and not _is_html_comment_line(line.strip())
        ]
        if not content_lines:
            return ""
        return "\n".join(content_lines)

    def parse_inbox(self) -> list[dict[str, object]]:
        """Parse memory_inbox.md into indexed entries.  Returns empty list when file is absent."""
        inbox_path = self._resolved_root / MEMORY_INBOX_FILENAME
        if not inbox_path.exists():
            return []
        text = inbox_path.read_text(encoding="utf-8")
        entries: list[dict[str, object]] = []
        blocks = text.split("\n---\n")
        for i, block in enumerate(blocks):
            block = block.strip()
            if not block:
                continue
            lines = block.split("\n")
            heading = lines[0].lstrip("#").strip()
            parts = heading.split(" | ")
            timestamp = parts[0].strip() if parts else ""
            # Skip heading line and the blank line after it
            body_start = 2
            body_lines = [l for l in lines[body_start:] if l.strip()]
            entry_text = "\n".join(body_lines)
            if entry_text:
                entries.append({"index": i, "timestamp": timestamp, "text": entry_text})
        return entries

    def append_to_inbox(self, text: str) -> str:
        """Append a dated entry to the memory inbox file.  Returns the entry text."""

        now = app_now()
        entry = (
            f"## {now.strftime('%Y-%m-%d %H:%M')} | 知识\n"
            f"\n"
            f"{text.strip()}\n"
            f"\n"
            f"---\n"
        )
        inbox_path = self._resolved_root / MEMORY_INBOX_FILENAME
        with self._inbox_lock:
            inbox_path.parent.mkdir(parents=True, exist_ok=True)
            with open(inbox_path, "a", encoding="utf-8") as fh:
                fh.write(entry)
        return entry

    def ensure_template_files(self) -> None:
        """Create the memory directory and write default templates for any missing files.

        Idempotent: existing files are never overwritten.
        """

        with self._inbox_lock:
            self._resolved_root.mkdir(parents=True, exist_ok=True)
            for kind, filename in MEMORY_FILENAMES.items():
                path = self._resolved_root / filename
                if path.exists():
                    continue
                template = _TEMPLATES.get(kind)
                if template is not None:
                    path.write_text(template, encoding="utf-8")

    def _path_for(self, kind: MemoryKind) -> Path:
        filename = MEMORY_FILENAMES[kind]
        path = (self._resolved_root / filename).resolve()
        try:
            path.relative_to(self._resolved_root)
        except ValueError as exc:
            raise ValueError("Memory path resolved outside configured root.") from exc
        return path

    def _normalize_limit(self, limit: int | None) -> int:
        if limit is None:
            return DEFAULT_MEMORY_SEARCH_LIMIT
        try:
            parsed = int(limit)
        except (TypeError, ValueError):
            raise ValueError("limit must be an integer.") from None
        if parsed < 1:
            raise ValueError("limit must be >= 1.")
        return min(parsed, MAX_MEMORY_SEARCH_LIMIT)

    @staticmethod
    def _search_document(document: MemoryDocument, needle: str) -> list[MemoryHit]:
        hits: list[MemoryHit] = []
        section: str | None = None
        raw_lines = document.text.splitlines()
        for index, raw_line in enumerate(raw_lines, start=1):
            line = raw_line.strip()
            is_heading = line.startswith("#")
            if is_heading:
                section = line.lstrip("#").strip() or section
            if needle not in line.lower():
                continue
            match_type = "heading" if is_heading else "body"
            hits.append(
                MemoryHit(
                    kind=document.kind,
                    line_number=index,
                    text=line,
                    section=section,
                    score=HEADING_MATCH_SCORE if is_heading else BODY_MATCH_SCORE,
                    match_type=match_type,
                    context=_context_lines(raw_lines, index),
                )
            )
        return hits


def _is_html_comment_line(line: str) -> bool:
    return line.startswith("<!--") or line.endswith("-->")


def _context_lines(lines: list[str], line_number: int) -> list[MemoryContextLine]:
    start = max(1, line_number - DEFAULT_MEMORY_CONTEXT_LINES)
    end = min(len(lines), line_number + DEFAULT_MEMORY_CONTEXT_LINES)
    context: list[MemoryContextLine] = []
    for current_line_number in range(start, end + 1):
        text = lines[current_line_number - 1].strip()
        if not text:
            continue
        context.append(MemoryContextLine(line_number=current_line_number, text=text))
    return context


_DATE_PREFIX_RE = re.compile(r"^- \[\d{4}-\d{2}-\d{2}\] ")


def _strip_date_prefix(text: str) -> str:
    """Strip a leading '- [YYYY-MM-DD] ' prefix so append_to_section can add its own."""
    return _DATE_PREFIX_RE.sub("", text, count=1)


def _strip_user_profile_prompt_line(text: str) -> str:
    """Strip stored dates from user_profile bullets while preserving bullet shape."""
    if _DATE_PREFIX_RE.match(text):
        return f"- {_strip_date_prefix(text)}"
    return text
