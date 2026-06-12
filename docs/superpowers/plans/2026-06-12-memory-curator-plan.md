# Memory Curator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add curator function + review UI so the operator can batch-review inbox entries and apply them to user_profile.md or knowledge.md.

**Architecture:** Three independent workstreams — store additions (append_to_section, get_sections), curator service + API routes, and frontend MemoryPanel. Store workstream must complete first (curator and routes depend on it). Curator and frontend can run in parallel after store is done.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, TypeScript, React, pytest

---

## File Structure

```
Create:  app/services/curator.py             — CuratorResult model, run_curation()
Create:  app/api/memory_routes.py             — GET /memory/inbox, POST /memory/curate, PATCH /memory/curate/apply
Modify:  app/services/markdown_memory_store.py — +append_to_section(), +get_sections(), +parse_inbox()
Modify:  app/api/schemas.py                   — +MemoryInboxEntry, +MemoryInboxResponse, +CurationResponse, +CuratorApplyRequest, +CuratorApplyResponse
Modify:  app/main.py                          — +include_router(memory_router)
Create:  tests/test_curator.py                — curator function tests
Create:  tests/test_memory_routes.py          — route integration tests
Create:  frontend/src/components/memory/MemoryPanel.tsx — review UI
Create:  frontend/src/components/memory/MemoryPanel.test.tsx — frontend tests
Modify:  frontend/src/state/uiState.ts        — +"memory" tab
Modify:  frontend/src/components/layout/WorkspaceTabs.tsx — +"记忆" tab
Modify:  frontend/src/app/AppShell.tsx        — +MemoryPanel rendering
Modify:  frontend/src/app/theme.css           — +memory panel styles
Modify:  frontend/src/api/chatApi.ts          — +inbox/curate/apply API functions
```

---

### Task 1: Parse inbox entries in MarkdownMemoryStore

**Files:**
- Modify: `app/services/markdown_memory_store.py`
- Test: `tests/test_markdown_memory_store.py`

- [ ] **Step 1: Add parse_inbox method and test**

```python
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
```

- [ ] **Step 2: Implement parse_inbox**

```python
# In markdown_memory_store.py, add to MarkdownMemoryStore class:
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
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_markdown_memory_store.py -v
```

- [ ] **Step 4: Commit**

```bash
git add app/services/markdown_memory_store.py tests/test_markdown_memory_store.py
git commit -m "feat: add parse_inbox to MarkdownMemoryStore"
```

---

### Task 2: Add append_to_section and get_sections

**Files:**
- Modify: `app/services/markdown_memory_store.py`
- Test: `tests/test_markdown_memory_store.py`

- [ ] **Step 1: Write tests**

```python
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
    assert "- [20" in lines[tmdb_idx + 1]  # old entry still there
    assert "new tip" in content
    assert lines.index("new tip") < mteam_idx
    assert lines.index("new tip") > tmdb_idx


def test_append_to_section_creates_section_if_missing(tmp_path: Path):
    store = MarkdownMemoryStore(tmp_path)
    store.append_to_section(MemoryKind.KNOWLEDGE, "NewSection", "first item")
    content = (tmp_path / "knowledge.md").read_text(encoding="utf-8")
    assert "## NewSection" in content
    assert "first item" in content
```

- [ ] **Step 2: Implement get_sections**

```python
# In MarkdownMemoryStore class:
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
```

- [ ] **Step 3: Implement append_to_section**

```python
# In MarkdownMemoryStore class:
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
```

- [ ] **Step 4: Add import**

```python
from datetime import datetime, timezone  # already imported, verify
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_markdown_memory_store.py -v
```

- [ ] **Step 6: Commit**

```bash
git add app/services/markdown_memory_store.py tests/test_markdown_memory_store.py
git commit -m "feat: add append_to_section and get_sections to MarkdownMemoryStore"
```

---

### Task 3: Curator service

**Files:**
- Create: `app/services/curator.py`
- Create: `tests/test_curator.py`

- [ ] **Step 1: Write domain models and test**

```python
# tests/test_curator.py
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
```

- [ ] **Step 2: Implement curator service**

```python
# app/services/curator.py
"""Curator service: classify inbox entries and suggest destinations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.config import get_settings
from app.domain.memory import MemoryKind
from app.services.markdown_memory_store import MarkdownMemoryStore
from hello_agents.llm import HelloAgentsLLM


class CuratorSuggestion(BaseModel):
    inbox_index: int
    preview: str
    action: Literal["keep", "discard"]
    destination: Literal["user_profile", "knowledge"] | None = None
    section: str | None = None
    edited_text: str | None = None


class CuratorResult(BaseModel):
    suggestions: list[CuratorSuggestion]
    inbox_entry_count: int


def _build_curator_llm():
    settings = get_settings()
    return HelloAgentsLLM(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=0.1,
    )


def _build_prompt(entries: list[dict], user_profile: str, knowledge: str, sections: dict) -> str:
    entries_text = "\n\n---\n\n".join(
        f"[索引 {e['index']}] {e['timestamp']}\n{e['text']}" for e in entries
    )
    user_sections = "\n".join(f"- {s}" for s in sections.get("user_profile", []))
    knowledge_sections = "\n".join(f"- {s}" for s in sections.get("knowledge", []))

    return f"""你是 NasClawBot 的记忆整理助手。分析以下收件箱条目，判断每条应该保留还是丢弃。

## 收件箱条目

{entries_text}

## 现有用户画像 (user_profile.md)

{user_profile if user_profile.strip() else "（空）"}

## 现有知识库 (knowledge.md)

{knowledge if knowledge.strip() else "（空）"}

## 可用的章节

user_profile 可用章节：{user_sections}
knowledge 可用章节：{knowledge_sections}

## 判定规则

- **user_profile** 适合：个人偏好、沟通风格、身份、操作习惯、禁止事项。这类信息影响 Agent 的行为方式。
- **knowledge** 适合：领域技巧、操作经验、事实性环境信息。这类信息在特定场景下按需搜索。
- 如果条目和已有内容高度重复，标记为 discard。
- 如果条目没有长期保留价值（如单次搜索结果），标记为 discard。
- 润色文本：修正错别字、精简表达、补充必要上下文，但保持原意不变。

## 输出要求

严格输出 JSON，不要加任何其他文本：

{{"suggestions": [...], "inbox_entry_count": {len(entries)}}}

每条 suggestion：
- inbox_index: 整数
- preview: 原文前30字
- action: "keep" 或 "discard"
- destination: "user_profile" 或 "knowledge"（discard 时为 null）
- section: 章节名（discard 时为 null）
- edited_text: 润色后文本（discard 时为 null）"""


def run_curation(store: MarkdownMemoryStore) -> CuratorResult:
    """Analyze inbox entries and return structured suggestions.  Does not modify files."""

    entries = store.parse_inbox()
    if not entries:
        return CuratorResult(suggestions=[], inbox_entry_count=0)

    user_profile = store.load(MemoryKind.USER_PROFILE).text
    knowledge = store.load(MemoryKind.KNOWLEDGE).text
    sections = {
        "user_profile": store.get_sections(MemoryKind.USER_PROFILE),
        "knowledge": store.get_sections(MemoryKind.KNOWLEDGE),
    }

    prompt = _build_prompt(entries, user_profile, knowledge, sections)
    llm = _build_curator_llm()
    messages = [{"role": "user", "content": prompt}]
    response = llm.invoke(messages)
    raw = response.content.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3]

    return CuratorResult.model_validate_json(raw)
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_curator.py -v
```

- [ ] **Step 4: Commit**

```bash
git add app/services/curator.py tests/test_curator.py
git commit -m "feat: add curator service with LLM classification"
```

---

### Task 4: API schemas

**Files:**
- Modify: `app/api/schemas.py`

- [ ] **Step 1: Add schemas**

```python
# Add to app/api/schemas.py (after existing schemas, before last class)

class MemoryInboxEntry(BaseModel):
    index: int
    timestamp: str
    text: str


class MemoryInboxResponse(BaseModel):
    entries: list[MemoryInboxEntry] = Field(default_factory=list)
    entry_count: int


class CurationSuggestion(BaseModel):
    inbox_index: int
    preview: str
    action: Literal["keep", "discard"]
    destination: Literal["user_profile", "knowledge"] | None = None
    section: str | None = None
    edited_text: str | None = None


class CurationSections(BaseModel):
    user_profile: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)


class CurationResponse(BaseModel):
    suggestions: list[CurationSuggestion] = Field(default_factory=list)
    inbox_entry_count: int
    sections: CurationSections = Field(default_factory=CurationSections)


class CuratorApplyDecision(BaseModel):
    inbox_index: int
    action: Literal["keep", "discard"]
    destination: Literal["user_profile", "knowledge"] | None = None
    section: str | None = None
    text: str | None = None


class CuratorApplyRequest(BaseModel):
    inbox_entry_count: int
    decisions: list[CuratorApplyDecision] = Field(default_factory=list)


class CuratorApplyResponse(BaseModel):
    applied: int
    discarded: int
    remaining: int
```

- [ ] **Step 2: Verify import of Literal**

```python
# Ensure top of schemas.py has:
from typing import Any, Literal  # Literal already imported, verify
```

- [ ] **Step 3: Run type check**

```bash
.venv/bin/python -m compileall app/api/schemas.py -q
```

- [ ] **Step 4: Commit**

```bash
git add app/api/schemas.py
git commit -m "feat: add memory curator API schemas"
```

---

### Task 5: Memory API routes

**Files:**
- Create: `app/api/memory_routes.py`
- Create: `tests/test_memory_routes.py`

- [ ] **Step 1: Write route tests**

```python
# tests/test_memory_routes.py
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
    (memory_dir / "user_profile.md").write_text("# User Profile\n\n## Media Preferences\n", encoding="utf-8")
    (memory_dir / "knowledge.md").write_text("# Knowledge\n\n## TMDB\n\n## Other\n", encoding="utf-8")
    return memory_dir


def test_get_inbox_empty(monkeypatch, tmp_path: Path):
    memory_dir = _setup_memory_files(tmp_path)
    monkeypatch.setattr(
        "app.api.memory_routes._MEMORY_DIR",
        memory_dir,
    )
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
```

- [ ] **Step 2: Implement memory_routes.py**

```python
# app/api/memory_routes.py
"""HTTP routes for memory inbox and curation."""

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.schemas import (
    CuratorApplyRequest,
    CuratorApplyResponse,
    CurationResponse,
    MemoryInboxEntry,
    MemoryInboxResponse,
)
from app.domain.memory import MemoryKind
from app.services.curator import run_curation
from app.services.markdown_memory_store import MarkdownMemoryStore

_MEMORY_DIR = Path(__file__).resolve().parents[2] / "memory" / "agent-memory"


def _build_store() -> MarkdownMemoryStore:
    return MarkdownMemoryStore(_MEMORY_DIR)


def build_memory_router() -> APIRouter:
    router = APIRouter(prefix="/memory", tags=["memory"])

    @router.get("/inbox", response_model=MemoryInboxResponse)
    def get_inbox():
        store = _build_store()
        entries = store.parse_inbox()
        return MemoryInboxResponse(
            entries=[
                MemoryInboxEntry(
                    index=e["index"],
                    timestamp=str(e["timestamp"]),
                    text=str(e["text"]),
                )
                for e in entries
            ],
            entry_count=len(entries),
        )

    @router.post("/curate", response_model=CurationResponse)
    def curate():
        store = _build_store()
        try:
            result = run_curation(store)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Curator LLM call failed: {exc}")
        return CurationResponse(
            suggestions=[
                {
                    "inbox_index": s.inbox_index,
                    "preview": s.preview,
                    "action": s.action,
                    "destination": s.destination,
                    "section": s.section,
                    "edited_text": s.edited_text,
                }
                for s in result.suggestions
            ],
            inbox_entry_count=result.inbox_entry_count,
            sections={
                "user_profile": store.get_sections(MemoryKind.USER_PROFILE),
                "knowledge": store.get_sections(MemoryKind.KNOWLEDGE),
            },
        )

    @router.patch("/curate/apply", response_model=CuratorApplyResponse)
    def apply_curation(request: CuratorApplyRequest):
        store = _build_store()
        entries = store.parse_inbox()
        if len(entries) != request.inbox_entry_count:
            raise HTTPException(
                status_code=409,
                detail=f"Inbox changed: expected {request.inbox_entry_count} entries, found {len(entries)}.",
            )

        applied = 0
        discarded = 0
        processed: set[int] = set()
        kind_map = {
            "user_profile": MemoryKind.USER_PROFILE,
            "knowledge": MemoryKind.KNOWLEDGE,
        }

        for decision in request.decisions:
            processed.add(decision.inbox_index)
            if decision.action == "keep" and decision.destination and decision.text:
                store.append_to_section(
                    kind=kind_map[decision.destination],
                    section=decision.section or "Other",
                    text=decision.text,
                )
                applied += 1
            else:
                discarded += 1

        # Rebuild inbox from unprocessed entries
        remaining = [entries[i] for i in range(len(entries)) if i not in processed]
        inbox_path = _MEMORY_DIR / "memory_inbox.md"
        if remaining:
            blocks = []
            for entry in remaining:
                blocks.append(
                    f"## {entry['timestamp']} | 知识\n\n{entry['text']}\n\n---\n"
                )
            inbox_path.write_text("\n".join(blocks), encoding="utf-8")
        elif inbox_path.exists():
            inbox_path.write_text("", encoding="utf-8")

        return CuratorApplyResponse(
            applied=applied,
            discarded=discarded,
            remaining=len(remaining),
        )

    return router
```

- [ ] **Step 3: Register router in main.py**

```python
# In app/main.py, add import:
from app.api.memory_routes import build_memory_router

# In create_app(), add after existing router includes:
app.include_router(build_memory_router())
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_memory_routes.py -v
```

- [ ] **Step 5: Commit**

```bash
git add app/api/memory_routes.py app/main.py tests/test_memory_routes.py
git commit -m "feat: add memory inbox and curator API routes"
```

---

### Task 6: Frontend — types, state, and API client

**Files:**
- Modify: `frontend/src/state/uiState.ts`
- Modify: `frontend/src/api/chatApi.ts`
- Modify: `frontend/src/components/layout/WorkspaceTabs.tsx`
- Modify: `frontend/src/app/AppShell.tsx`

- [ ] **Step 1: Add "memory" to WorkspaceTab**

```typescript
// frontend/src/state/uiState.ts
export type WorkspaceTab = "chat" | "downloads" | "settings" | "free-torrents" | "memory";
```

- [ ] **Step 2: Add API functions to chatApi.ts**

```typescript
// frontend/src/api/chatApi.ts — add these exports:

export interface MemoryInboxEntry {
  index: number;
  timestamp: string;
  text: string;
}

export interface MemoryInboxResponse {
  entries: MemoryInboxEntry[];
  entry_count: number;
}

export interface CurationSuggestion {
  inbox_index: number;
  preview: string;
  action: "keep" | "discard";
  destination: "user_profile" | "knowledge" | null;
  section: string | null;
  edited_text: string | null;
}

export interface CurationResponse {
  suggestions: CurationSuggestion[];
  inbox_entry_count: number;
  sections: {
    user_profile: string[];
    knowledge: string[];
  };
}

export interface CuratorApplyDecision {
  inbox_index: number;
  action: "keep" | "discard";
  destination?: "user_profile" | "knowledge";
  section?: string;
  text?: string;
}

export interface CuratorApplyResponse {
  applied: number;
  discarded: number;
  remaining: number;
}

export async function fetchInbox(): Promise<MemoryInboxResponse> {
  const res = await fetch("/memory/inbox");
  if (!res.ok) throw new Error("Failed to fetch inbox");
  return res.json();
}

export async function fetchCuration(): Promise<CurationResponse> {
  const res = await fetch("/memory/curate", { method: "POST" });
  if (!res.ok) throw new Error("Failed to run curation");
  return res.json();
}

export async function applyCuration(
  inboxEntryCount: number,
  decisions: CuratorApplyDecision[]
): Promise<CuratorApplyResponse> {
  const res = await fetch("/memory/curate/apply", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ inbox_entry_count: inboxEntryCount, decisions }),
  });
  if (!res.ok) throw new Error("Failed to apply curation");
  return res.json();
}
```

- [ ] **Step 3: Add "记忆" tab to WorkspaceTabs**

```typescript
// frontend/src/components/layout/WorkspaceTabs.tsx
// Add to the tabs array:
const tabs: Array<{ id: WorkspaceTab; label: string }> = [
  { id: "chat", label: "Chat" },
  { id: "downloads", label: "Downloads" },
  { id: "memory", label: "记忆" },
  { id: "free-torrents", label: "刷流" },
  { id: "settings", label: "状态" },
];
```

- [ ] **Step 4: Add MemoryPanel to AppShell**

```typescript
// In AppShell.tsx, add import:
import { MemoryPanel } from "../components/memory/MemoryPanel";

// Add panel div after free-torrents panel:
<div style={panelStyle(activeTab === "memory")}>
  <section role="tabpanel" id="workspace-panel-memory" aria-labelledby="workspace-tab-memory">
    <MemoryPanel />
  </section>
</div>
```

- [ ] **Step 5: Typecheck**

```bash
cd frontend && npm run typecheck
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/state/uiState.ts frontend/src/api/chatApi.ts frontend/src/components/layout/WorkspaceTabs.tsx frontend/src/app/AppShell.tsx
git commit -m "feat: add memory tab placeholder and API client"
```

---

### Task 7: Frontend — MemoryPanel component

**Files:**
- Create: `frontend/src/components/memory/MemoryPanel.tsx`
- Create: `frontend/src/components/memory/MemoryPanel.test.tsx`
- Modify: `frontend/src/app/theme.css`

- [ ] **Step 1: Write MemoryPanel component**

```typescript
// frontend/src/components/memory/MemoryPanel.tsx
import { useCallback, useEffect, useId, useState } from "react";
import {
  fetchInbox,
  fetchCuration,
  applyCuration,
  type MemoryInboxEntry,
  type CurationSuggestion,
  type CuratorApplyDecision,
} from "../../api/chatApi";

type EntryState = {
  entry: MemoryInboxEntry;
  suggestion: CurationSuggestion | null;
  editedText: string;
  destination: "user_profile" | "knowledge";
  section: string;
  status: "pending" | "applied" | "discarded";
};

export function MemoryPanel() {
  const panelId = useId();
  const [entries, setEntries] = useState<MemoryInboxEntry[]>([]);
  const [entryStates, setEntryStates] = useState<Map<number, EntryState>>(new Map());
  const [sections, setSections] = useState<{ user_profile: string[]; knowledge: string[] }>({ user_profile: [], knowledge: [] });
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [curated, setCurated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadInbox = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchInbox();
      setEntries(data.entries);
      setEntryStates(new Map());
      setCurated(false);
    } catch (e) {
      setError("无法加载收件箱");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadInbox(); }, [loadInbox]);

  const runCuration = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchCuration();
      const map = new Map<number, EntryState>();
      for (const s of data.suggestions) {
        const entry = entries.find(e => e.index === s.inbox_index);
        if (entry) {
          map.set(s.inbox_index, {
            entry,
            suggestion: s,
            editedText: s.edited_text ?? entry.text,
            destination: s.destination ?? "knowledge",
            section: s.section ?? "Other",
            status: "pending",
          });
        }
      }
      setEntryStates(map);
      setSections(data.sections);
      setCurated(true);
    } catch (e) {
      setError("记忆分析失败");
    } finally {
      setLoading(false);
    }
  };

  const applyDecisions = async () => {
    const decisions: CuratorApplyDecision[] = [];
    let appliedCount = 0;
    let discardedCount = 0;

    for (const state of entryStates.values()) {
      if (state.status === "applied") continue;
      const decision: CuratorApplyDecision = {
        inbox_index: state.entry.index,
        action: state.status === "discarded" ? "discard" : "keep",
        destination: state.destination,
        section: state.section,
        text: state.editedText,
      };
      decisions.push(decision);
      if (state.status === "discarded") discardedCount++;
      else appliedCount++;
    }

    setApplying(true);
    setError(null);
    try {
      await applyCuration(entries.length, decisions);
      setEntries(prev => prev.filter(e => {
        const s = entryStates.get(e.index);
        return !s || (s.status !== "applied" && s.status !== "discarded");
      }));
      setEntryStates(new Map());
      setCurated(false);
    } catch (e) {
      setError(`应用失败: ${String(e)}`);
    } finally {
      setApplying(false);
    }
  };

  const updateEntry = (index: number, update: Partial<EntryState>) => {
    setEntryStates(prev => {
      const next = new Map(prev);
      const current = next.get(index);
      if (current) next.set(index, { ...current, ...update });
      return next;
    });
  };

  const markApplied = (index: number) => updateEntry(index, { status: "applied" });
  const markDiscarded = (index: number) => updateEntry(index, { status: "discarded" });

  const pendingCount = Array.from(entryStates.values()).filter(s => s.status === "pending").length;
  const appliedCount = Array.from(entryStates.values()).filter(s => s.status === "applied").length;
  const discardedCount = Array.from(entryStates.values()).filter(s => s.status === "discarded").length;

  return (
    <div className="memory-panel" id={panelId}>
      <header className="memory-panel-header">
        <h2>記憶收件箱</h2>
        {entries.length > 0 && !curated && (
          <button className="memory-analyze-btn" onClick={runCuration} disabled={loading}>
            {loading ? "分析中..." : "分析"}
          </button>
        )}
      </header>

      {error && <p className="memory-error">{error}</p>}

      {loading && <p className="memory-loading">加载中...</p>}

      {!loading && entries.length === 0 && (
        <p className="memory-empty">暂无待整理记忆。Agent 调用 remember_this 后会出现在这里。</p>
      )}

      {!loading && entryStates.size === 0 && entries.length > 0 && (
        <div className="memory-unanalyzed">
          <p>收件箱中有 {entries.length} 条未分析条目。</p>
          <button onClick={runCuration}>开始分析</button>
        </div>
      )}

      {!loading && entryStates.size > 0 && (
        <div className="memory-cards">
          {Array.from(entryStates.values())
            .sort((a, b) => a.entry.index - b.entry.index)
            .map(state => (
              <div
                key={state.entry.index}
                className={`memory-card ${state.status}`}
              >
                <header className="memory-card-header">
                  <span className="memory-card-index">
                    条目 {state.entry.index + 1}/{entries.length}
                  </span>
                  <time className="memory-card-time">{state.entry.timestamp}</time>
                </header>

                <textarea
                  className="memory-card-textarea"
                  value={state.editedText}
                  onChange={e => updateEntry(state.entry.index, { editedText: e.target.value })}
                  disabled={state.status !== "pending"}
                  rows={4}
                />

                <div className="memory-card-controls">
                  <select
                    value={state.destination}
                    onChange={e => updateEntry(state.entry.index, {
                      destination: e.target.value as "user_profile" | "knowledge",
                    })}
                    disabled={state.status !== "pending"}
                  >
                    <option value="user_profile">user_profile</option>
                    <option value="knowledge">knowledge</option>
                  </select>

                  <select
                    value={state.section}
                    onChange={e => updateEntry(state.entry.index, { section: e.target.value })}
                    disabled={state.status !== "pending"}
                  >
                    {(sections[state.destination] ?? []).map(sec => (
                      <option key={sec} value={sec}>{sec}</option>
                    ))}
                  </select>

                  {state.status === "pending" && (
                    <>
                      <button onClick={() => markApplied(state.entry.index)}>应用</button>
                      <button onClick={() => markDiscarded(state.entry.index)}>丢弃</button>
                    </>
                  )}
                  {state.status === "applied" && <span className="memory-status-badge applied">✓ 待应用</span>}
                  {state.status === "discarded" && <span className="memory-status-badge discarded">✗ 已丢弃</span>}
                </div>
              </div>
            ))}
        </div>
      )}

      {entryStates.size > 0 && pendingCount > 0 && (
        <footer className="memory-panel-footer">
          <span>
            已选 {appliedCount} 条应用 · {discardedCount} 条丢弃 · {pendingCount} 条未处理
          </span>
          <button
            className="memory-apply-all-btn"
            onClick={applyDecisions}
            disabled={applying || appliedCount === 0}
          >
            {applying ? "应用中..." : `全部应用 (${appliedCount})`}
          </button>
        </footer>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Write CSS styles**

```css
/* Add to frontend/src/app/theme.css */

.memory-panel {
  padding: 1.5rem;
  height: 100%;
  overflow-y: auto;
}

.memory-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.memory-panel-header h2 {
  font-size: 1.25rem;
  font-weight: 600;
  margin: 0;
}

.memory-analyze-btn {
  padding: 0.5rem 1.25rem;
  border: none;
  border-radius: 0.5rem;
  background: var(--clr-primary);
  color: white;
  font-weight: 500;
  cursor: pointer;
}

.memory-analyze-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.memory-error {
  color: var(--clr-error);
  padding: 0.5rem;
  background: rgba(239, 68, 68, 0.1);
  border-radius: 0.375rem;
  margin-bottom: 1rem;
}

.memory-loading,
.memory-empty {
  text-align: center;
  padding: 3rem 1rem;
  color: var(--clr-text-2);
}

.memory-unanalyzed {
  text-align: center;
  padding: 2rem;
}

.memory-unanalyzed button {
  margin-top: 0.75rem;
  padding: 0.5rem 1.5rem;
  border: none;
  border-radius: 0.5rem;
  background: var(--clr-primary);
  color: white;
  font-weight: 500;
  cursor: pointer;
}

.memory-cards {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.memory-card {
  background: var(--clr-bg-2);
  border-radius: 0.5rem;
  padding: 1rem;
  border-left: 3px solid var(--clr-border);
  transition: border-color 0.2s;
}

.memory-card.pending {
  border-left-color: #f59e0b;
}

.memory-card.applied {
  border-left-color: #10b981;
}

.memory-card.discarded {
  border-left-color: #ef4444;
  opacity: 0.6;
}

.memory-card-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 0.5rem;
  font-size: 0.8125rem;
  color: var(--clr-text-2);
}

.memory-card-index {
  font-weight: 500;
}

.memory-card-textarea {
  width: 100%;
  min-height: 80px;
  background: var(--clr-bg-1);
  color: var(--clr-text-1);
  border: 1px solid var(--clr-border);
  border-radius: 0.375rem;
  padding: 0.5rem;
  font-size: 0.875rem;
  resize: vertical;
  margin-bottom: 0.5rem;
}

.memory-card-textarea:disabled {
  opacity: 0.7;
}

.memory-card-controls {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.memory-card-controls select {
  background: var(--clr-bg-1);
  color: var(--clr-text-1);
  border: 1px solid var(--clr-border);
  border-radius: 0.375rem;
  padding: 0.375rem 0.5rem;
  font-size: 0.8125rem;
}

.memory-card-controls button {
  padding: 0.25rem 0.75rem;
  border: 1px solid var(--clr-border);
  border-radius: 0.375rem;
  background: var(--clr-bg-1);
  color: var(--clr-text-1);
  font-size: 0.8125rem;
  cursor: pointer;
}

.memory-card-controls button:hover {
  background: var(--clr-bg-3);
}

.memory-status-badge {
  font-size: 0.8125rem;
  font-weight: 500;
}

.memory-status-badge.applied {
  color: #10b981;
}

.memory-status-badge.discarded {
  color: #ef4444;
}

.memory-panel-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 1rem;
  padding: 0.75rem;
  background: var(--clr-bg-2);
  border-radius: 0.5rem;
  font-size: 0.875rem;
  color: var(--clr-text-2);
}

.memory-apply-all-btn {
  padding: 0.5rem 1.5rem;
  border: none;
  border-radius: 0.5rem;
  background: #10b981;
  color: white;
  font-weight: 500;
  cursor: pointer;
}

.memory-apply-all-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

- [ ] **Step 3: Write minimal frontend test**

```typescript
// frontend/src/components/memory/MemoryPanel.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { MemoryPanel } from "./MemoryPanel";

vi.mock("../../api/chatApi", () => ({
  fetchInbox: vi.fn().mockResolvedValue({ entries: [], entry_count: 0 }),
  fetchCuration: vi.fn(),
  applyCuration: vi.fn(),
}));

describe("MemoryPanel", () => {
  it("shows empty state when inbox is empty", async () => {
    render(<MemoryPanel />);
    expect(await screen.findByText(/暂无待整理记忆/)).toBeTruthy();
  });
});
```

- [ ] **Step 4: Typecheck and test**

```bash
cd frontend && npm run typecheck && npm test -- MemoryPanel
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/memory/ frontend/src/app/theme.css
git commit -m "feat: add MemoryPanel with curation review UI"
```

---

### Task 8: Integration — end-to-end smoke test

**Files:**
- Modify: `tests/test_memory_routes.py` (extend)

- [ ] **Step 1: End-to-end test**

```python
def test_full_curation_flow(monkeypatch, tmp_path: Path):
    """Simulate a complete flow: Agent writes to inbox → operator curates → apply."""
    memory_dir = tmp_path / "agent-memory"
    memory_dir.mkdir(parents=True)

    # Pre-populate user_profile and knowledge
    (memory_dir / "user_profile.md").write_text(
        "# User Profile\n\n## Media Preferences\n\n## Communication Style\n",
        encoding="utf-8",
    )
    (memory_dir / "knowledge.md").write_text(
        "# Knowledge\n\n## TMDB\n\n## M-Team\n\n## Other\n",
        encoding="utf-8",
    )

    # Step 1: Simulate remember_this writing to inbox
    from app.services.markdown_memory_store import MarkdownMemoryStore
    store = MarkdownMemoryStore(memory_dir)
    store.append_to_inbox("用户偏好 4K HDR 画质。在多次对话中用户选择了 4K 资源。")
    store.append_to_inbox("M-Team 搜索中文片名时不应加 IMDb 过滤。原因是中文匹配比 IMDb 更准确。")
    store.append_to_inbox("用户不喜欢恐怖片。这是用户的类型偏好。")

    monkeypatch.setattr("app.api.memory_routes._MEMORY_DIR", memory_dir)
    client = TestClient(app)

    # Step 2: Read inbox
    resp = client.get("/memory/inbox")
    assert resp.status_code == 200
    data = resp.json()
    assert data["entry_count"] == 3

    # Step 3: Mock curator LLM
    mock_response = MagicMock()
    mock_response.content = json.dumps({
        "suggestions": [
            {"inbox_index": 0, "preview": "用户偏好 4K", "action": "keep", "destination": "user_profile", "section": "Media Preferences", "edited_text": "偏好 4K HDR 画质。"},
            {"inbox_index": 1, "preview": "M-Team 搜索", "action": "keep", "destination": "knowledge", "section": "M-Team", "edited_text": "搜索中文片名时不加 IMDb 过滤更准。"},
            {"inbox_index": 2, "preview": "用户不喜欢恐怖片", "action": "keep", "destination": "user_profile", "section": "Media Preferences", "edited_text": "不喜欢恐怖片。"},
        ],
        "inbox_entry_count": 3,
    })

    with patch("app.services.curator._build_curator_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = mock_response
        resp = client.post("/memory/curate")
    assert resp.status_code == 200
    assert resp.json()["inbox_entry_count"] == 3

    # Step 4: Apply all
    resp = client.patch("/memory/curate/apply", json={
        "inbox_entry_count": 3,
        "decisions": [
            {"inbox_index": 0, "action": "keep", "destination": "user_profile", "section": "Media Preferences", "text": "偏好 4K HDR 画质。"},
            {"inbox_index": 1, "action": "keep", "destination": "knowledge", "section": "M-Team", "text": "搜索中文片名时不加 IMDb 过滤更准。"},
            {"inbox_index": 2, "action": "keep", "destination": "user_profile", "section": "Media Preferences", "text": "不喜欢恐怖片。"},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["applied"] == 3
    assert data["remaining"] == 0

    # Step 5: Verify files updated
    user_profile = (memory_dir / "user_profile.md").read_text(encoding="utf-8")
    assert "4K HDR" in user_profile
    assert "恐怖片" in user_profile

    knowledge = (memory_dir / "knowledge.md").read_text(encoding="utf-8")
    assert "IMDb" in knowledge

    # Inbox should be empty
    inbox_content = (memory_dir / "memory_inbox.md").read_text(encoding="utf-8")
    assert "4K" not in inbox_content
```

- [ ] **Step 2: Run full test suite**

```bash
.venv/bin/python -m pytest tests/test_markdown_memory_store.py tests/test_curator.py tests/test_memory_routes.py tests/test_agent_runner.py -v
```

- [ ] **Step 3: Final commit**

```bash
git add tests/test_memory_routes.py
git commit -m "test: add end-to-end curation flow test"
```

---

## Execution Order

Tasks 1-2 (store) must complete first. Tasks 3 and 4-5 can then run in parallel:
- Task 3 (curator) + Task 4 (schemas) + Task 5 (routes) can overlap — curator depends only on store, routes depend on curator + schemas
- Tasks 6-7 (frontend) can start after Task 5 (routes) are ready, or in parallel if the API contract is stable

Recommended dispatch: 1 → 2 → (3, 4, 5 in parallel) → (6, 7 in parallel) → 8
