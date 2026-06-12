"""Read-only markdown memory store."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from app.domain.memory import MemoryContextLine, MemoryDocument, MemoryHit, MemoryKind


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
    MemoryKind.USER_PROFILE: (
        "# User Profile\n"
        "\n"
        "## Communication Style\n"
        "\n"
        "## Tool Preferences\n"
        "\n"
        "## Project Conventions\n"
        "\n"
        "## Personal Info\n"
        "\n"
        "## Prohibitions\n"
    ),
    MemoryKind.KNOWLEDGE: (
        "# Knowledge\n"
        "\n"
        "## TMDB\n"
        "\n"
        "<!-- Example:\n"
        "- [2026-06-12] Chinese titles can map to multiple countries or years;"
        " disambiguate with TMDB before searching torrents.\n"
        "-->\n"
        "\n"
        "## M-Team\n"
        "\n"
        "<!-- Example:\n"
        "- [2026-06-12] User prefers 4K REMUX for movies, 1080p for TV series."
        " Learned from multiple download choices.\n"
        "-->\n"
        "\n"
        "## qBittorrent\n"
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
        path = self._path_for(kind)
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        lines = content.splitlines()

        target_heading = f"## {section}"
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

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entry_line = f"- [{today}] {text}"
        new_lines = lines[:insert_at] + [entry_line, ""] + lines[insert_at:]

        with self._inbox_lock:
            path.write_text("\n".join(new_lines).rstrip("\n") + "\n", encoding="utf-8")

    def format_user_profile_prompt(self) -> str:
        """Return compact prompt text for the user profile memory, or empty string."""

        document = self.load(MemoryKind.USER_PROFILE)
        lines = [line.strip() for line in document.text.splitlines() if line.strip()]
        content_lines = [
            line
            for line in lines
            if not line.startswith("#") and not _is_html_comment_line(line)
        ]
        if not content_lines:
            return ""
        compact = "\n".join(lines)
        return f"User profile memory:\n{compact}"

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

        now = datetime.now(timezone.utc)
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
