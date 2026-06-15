# Memory Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Memory Curator with Evolution capabilities — modify/delete existing knowledge entries using exact-text matching, with time-aware curator prompt.

**Architecture:** Six tasks: store methods → schemas → curator prompt → API routes → frontend types → frontend UI. Each task modifies one layer. Backend uses TDD. Frontend follows existing MemoryPanel patterns.

**Tech Stack:** Python 3.12+ / FastAPI / Pydantic / pytest, TypeScript / React / CSS variables

---

### Task 1: Store — `replace_in_section` and `delete_from_section`

**Files:**
- Modify: `app/services/markdown_memory_store.py`
- Test: `tests/test_markdown_memory_store.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_markdown_memory_store.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_markdown_memory_store.py::test_replace_in_section_replaces_correct_line tests/test_markdown_memory_store.py::test_replace_in_section_returns_false_when_no_match tests/test_markdown_memory_store.py::test_replace_in_section_match_is_strip_only tests/test_markdown_memory_store.py::test_delete_from_section_removes_correct_line tests/test_markdown_memory_store.py::test_delete_from_section_removes_trailing_blank_line tests/test_markdown_memory_store.py::test_delete_from_section_returns_false_when_no_match -v
```

Expected: 6 failures — `AttributeError: 'MarkdownMemoryStore' object has no attribute 'replace_in_section'`

- [ ] **Step 3: Implement replace_in_section and delete_from_section**

Add to `MarkdownMemoryStore` class in `app/services/markdown_memory_store.py` (after `append_to_section`):

```python
def replace_in_section(self, kind: MemoryKind, existing_text: str, new_text: str) -> bool:
    """Replace the first line whose .strip() equals existing_text.strip() with new_text.

    Returns True if found and replaced, False otherwise.
    """
    with self._inbox_lock:
        path = self._path_for(kind)
        if not path.exists():
            return False
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        needle = existing_text.strip()
        for i, line in enumerate(lines):
            if line.strip() == needle:
                lines[i] = new_text
                path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
                return True
        return False


def delete_from_section(self, kind: MemoryKind, existing_text: str) -> bool:
    """Remove the first line whose .strip() equals existing_text.strip().

    Also removes the following blank line if present. Returns True if found and removed.
    """
    with self._inbox_lock:
        path = self._path_for(kind)
        if not path.exists():
            return False
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        needle = existing_text.strip()
        for i, line in enumerate(lines):
            if line.strip() == needle:
                del lines[i]
                if i < len(lines) and lines[i].strip() == "":
                    del lines[i]
                path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
                return True
        return False
```

Also add a public `path_for` method for the pre-validation step in Task 4:

```python
def path_for(self, kind: MemoryKind) -> Path:
    """Return the resolved path for a memory kind file."""
    return self._path_for(kind)
```

- [ ] **Step 4: Run all store tests**

```bash
.venv/bin/python -m pytest tests/test_markdown_memory_store.py -v
```

Expected: all tests pass (existing + 6 new = 24 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_markdown_memory_store.py app/services/markdown_memory_store.py
git commit -m "feat: add replace_in_section and delete_from_section to memory store"
```

---

### Task 2: Schema — extend action types and decision models

**Files:**
- Modify: `app/services/curator.py` (CuratorSuggestion model)
- Modify: `app/api/schemas.py` (CurationSuggestion, CuratorApplyDecision, CuratorApplyRequest, CuratorApplyResponse)
- Test: `tests/test_curator.py`

- [ ] **Step 1: Update CuratorSuggestion in curator.py**

Replace `CuratorSuggestion` class in `app/services/curator.py`:

```python
class CuratorSuggestion(BaseModel):
    inbox_index: int | None = None   # null for modify / delete
    preview: str = ""                # empty for modify/delete
    action: Literal["keep", "discard", "modify", "delete"]

    # keep-specific
    destination: Literal["user_profile", "knowledge"] | None = None
    section: str | None = None
    edited_text: str | None = None

    # modify / delete-specific
    existing_text: str | None = None  # exact original line from the file to match
    new_text: str | None = None       # replacement line (modify only)
    reason: str | None = None         # why this change is needed
```

- [ ] **Step 2: Update API schemas in schemas.py**

Replace `CurationSuggestion`, `CuratorApplyDecision`, `CuratorApplyRequest`, `CuratorApplyResponse` in `app/api/schemas.py`:

```python
class CurationSuggestion(BaseModel):
    inbox_index: int | None = None
    preview: str = ""
    action: Literal["keep", "discard", "modify", "delete"]
    destination: Literal["user_profile", "knowledge"] | None = None
    section: str | None = None
    edited_text: str | None = None
    existing_text: str | None = None
    new_text: str | None = None
    reason: str | None = None


class CuratorApplyDecision(BaseModel):
    action: Literal["keep", "discard", "modify", "delete"]
    inbox_index: int | None = None
    destination: Literal["user_profile", "knowledge"] | None = None
    section: str | None = None
    text: str | None = None
    existing_text: str | None = None
    new_text: str | None = None


class CuratorApplyRequest(BaseModel):
    inbox_entry_count: int
    decisions: list[CuratorApplyDecision] = Field(default_factory=list)


class CuratorApplyResponse(BaseModel):
    applied: int
    discarded: int
    modified: int
    deleted: int
    remaining: int
```

- [ ] **Step 3: Add schema tests**

Append to `tests/test_curator.py`:

```python
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
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/test_curator.py -v
```

Expected: 7 tests pass (existing + 2 new)

- [ ] **Step 5: Verify compilation**

```bash
.venv/bin/python -m compileall app/services/curator.py app/api/schemas.py -q
```

- [ ] **Step 6: Commit**

```bash
git add app/services/curator.py app/api/schemas.py tests/test_curator.py
git commit -m "feat: extend curator schema with modify/delete action types"
```

---

### Task 3: Curator prompt — time injection + evolution rules

**Files:**
- Modify: `app/services/curator.py` (`_build_prompt()`)
- Test: `tests/test_curator.py`

- [ ] **Step 1: Write test for time injection**

Append to `tests/test_curator.py`:

```python
def test_build_prompt_includes_current_date_and_evolution_rules(monkeypatch):
    """Verify the curator prompt includes the current UTC date and evolution instructions."""
    from app.services.curator import _build_prompt
    from unittest.mock import MagicMock
    import datetime as dt

    frozen_date = dt.datetime(2026, 6, 15, 12, 0, 0, tzinfo=dt.timezone.utc)
    monkeypatch.setattr("app.services.curator.datetime", MagicMock())
    import app.services.curator as curator_mod
    curator_mod.datetime.now.return_value = frozen_date

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
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
.venv/bin/python -m pytest tests/test_curator.py::test_build_prompt_includes_current_date_and_evolution_rules -v
```

Expected: FAIL — prompt doesn't contain "当前日期" or evolution rules yet.

- [ ] **Step 3: Rewrite _build_prompt**

Replace `_build_prompt` in `app/services/curator.py`:

```python
def _build_prompt(entries: list[dict], user_profile: str, knowledge: str, sections: dict) -> str:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    entries_text = "\n\n---\n\n".join(
        f"[索引 {e['index']}] {e['timestamp']}\n{e['text']}" for e in entries
    )
    user_sections = "\n".join(f"- {s}" for s in sections.get("user_profile", []))
    knowledge_sections = "\n".join(f"- {s}" for s in sections.get("knowledge", []))

    return f"""当前日期：{now}（UTC）。用这个日期判断信息是否过时。

你是 NasClawBot 的记忆整理助手。分析收件箱条目和已有记忆，判断每条应该保留、丢弃、修改还是删除。

## 现有用户画像 (user_profile.md)

{user_profile if user_profile.strip() else "（空）"}

## 现有知识库 (knowledge.md)

{knowledge if knowledge.strip() else "（空）"}

## 收件箱条目

{entries_text if entries_text.strip() else "（空）"}

## 可用的章节

user_profile 可用章节：
{user_sections}

knowledge 可用章节：
{knowledge_sections}

## 判定规则

### inbox 条目（keep / discard）
- **user_profile** 适合：个人偏好、沟通风格、身份、操作习惯、禁止事项。
- **knowledge** 适合：领域技巧、操作经验、事实性环境信息。
- 如果条目和已有内容高度重复，标记为 discard。
- 如果条目没有长期保留价值，标记为 discard。
- 润色文本：修正错别字、精简表达、补充必要上下文，保持原意不变。

### 已有条目（modify / delete）
- **矛盾检测**：如果 inbox 新条目和已有条目矛盾，标记 modify 旧条目（用新信息替代旧信息）。如果已有条目之间互相矛盾，modify 过时的、保留最新的。
- **过时检测**：如果已有条目明显过时或无效（结合日期判断），标记 delete。
- **重复检测**：如果 inbox 条目和已有条目高度重复，discard inbox 条目即可（不需要 modify 已有条目）。

### modify / delete 输出要求
- `existing_text`：文件中的**精确原文**，一字不差。后端用它定位要修改/删除的行。
- `new_text`（modify）：替换后的完整行内容，保持 markdown 格式。
- `reason`：简要说明为什么要修改或删除这条信息。
- 不要凭空创造 modify/delete——只有当已有内容确实需要变更时才输出。

## 输出要求

严格输出 JSON，不要加任何其他文本：

{{"suggestions": [...], "inbox_entry_count": {len(entries)}}}

每条 suggestion：
- inbox_index: 整数（modify/delete 时为 null）
- preview: 原文前30字（modify/delete 时为空字符串）
- action: "keep" / "discard" / "modify" / "delete"
- destination: "user_profile" 或 "knowledge"（discard 时为 null）
- section: 章节名（discard 时为 null）
- edited_text: 润色后文本（discard/modify/delete 时为 null）
- existing_text: 文件中的精确原文（仅 modify/delete 需要，必须一字不差）
- new_text: 替换后的行内容（仅 modify 需要）
- reason: 修改/删除的原因（仅 modify/delete 需要）"""
```

- [ ] **Step 4: Update mock LLM test for full action coverage**

Replace `test_run_curation_with_mock_llm` in `tests/test_curator.py`:

```python
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
```

- [ ] **Step 5: Run all curator tests**

```bash
.venv/bin/python -m pytest tests/test_curator.py -v
```

Expected: 8 tests pass

- [ ] **Step 6: Commit**

```bash
git add app/services/curator.py tests/test_curator.py
git commit -m "feat: add time injection and evolution rules to curator prompt"
```

---

### Task 4: API — extend curate and apply endpoints

**Files:**
- Modify: `app/api/memory_routes.py`
- Test: `tests/test_memory_routes.py`

- [ ] **Step 1: Update curate response serialization**

In `app/api/memory_routes.py`, in the `curate()` function, update the suggestion dict to include new fields:

```python
return CurationResponse(
    suggestions=[
        {
            "inbox_index": s.inbox_index,
            "preview": s.preview,
            "action": s.action,
            "destination": s.destination,
            "section": s.section,
            "edited_text": s.edited_text,
            "existing_text": s.existing_text,
            "new_text": s.new_text,
            "reason": s.reason,
        }
        for s in result.suggestions
    ],
    inbox_entry_count=result.inbox_entry_count,
    sections=CurationSections(
        user_profile=store.get_sections(MemoryKind.USER_PROFILE),
        knowledge=store.get_sections(MemoryKind.KNOWLEDGE),
    ),
)
```

- [ ] **Step 2: Update apply_curation endpoint**

Replace the `apply_curation` function in `app/api/memory_routes.py`:

```python
@router.patch("/curate/apply", response_model=CuratorApplyResponse)
def apply_curation(request: CuratorApplyRequest):
    store = _build_store()
    entries = store.parse_inbox()
    if len(entries) != request.inbox_entry_count:
        raise HTTPException(
            status_code=409,
            detail=f"Inbox changed: expected {request.inbox_entry_count} entries, found {len(entries)}.",
        )

    kind_map = {
        "user_profile": MemoryKind.USER_PROFILE,
        "knowledge": MemoryKind.KNOWLEDGE,
    }

    # Pre-validate all modify/delete decisions — check existing_text exists before applying anything
    for decision in request.decisions:
        if decision.action in ("modify", "delete"):
            if not decision.destination or not decision.existing_text:
                raise HTTPException(
                    status_code=400,
                    detail="modify/delete requires destination and existing_text.",
                )
            kind = kind_map[decision.destination]
            path = store.path_for(kind)
            if not path.exists():
                raise HTTPException(
                    status_code=400,
                    detail=f"无法定位原文片段: {decision.existing_text}",
                )
            content = path.read_text(encoding="utf-8")
            needle = decision.existing_text.strip()
            if not any(line.strip() == needle for line in content.splitlines()):
                raise HTTPException(
                    status_code=400,
                    detail=f"无法定位原文片段: {decision.existing_text}",
                )

    applied = 0
    discarded = 0
    modified = 0
    deleted = 0
    processed_inbox: set[int] = set()

    for decision in request.decisions:
        if decision.action == "keep" and decision.destination and decision.text:
            if decision.inbox_index is not None:
                processed_inbox.add(decision.inbox_index)
            store.append_to_section(
                kind=kind_map[decision.destination],
                section=decision.section or "Other",
                text=decision.text,
            )
            applied += 1
        elif decision.action == "discard":
            if decision.inbox_index is not None:
                processed_inbox.add(decision.inbox_index)
            discarded += 1
        elif decision.action == "modify":
            store.replace_in_section(
                kind=kind_map[decision.destination or "knowledge"],
                existing_text=decision.existing_text or "",
                new_text=decision.new_text or "",
            )
            modified += 1
        elif decision.action == "delete":
            store.delete_from_section(
                kind=kind_map[decision.destination or "knowledge"],
                existing_text=decision.existing_text or "",
            )
            deleted += 1

    # Rebuild inbox from unprocessed entries
    remaining = [entries[i] for i in range(len(entries)) if i not in processed_inbox]
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
        modified=modified,
        deleted=deleted,
        remaining=len(remaining),
    )
```

- [ ] **Step 3: Write route tests**

Append to `tests/test_memory_routes.py`:

```python
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
```

- [ ] **Step 4: Run all route tests**

```bash
.venv/bin/python -m pytest tests/test_memory_routes.py -v
```

Expected: 10 tests pass (6 existing + 4 new)

- [ ] **Step 5: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -q
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add app/api/memory_routes.py tests/test_memory_routes.py
git commit -m "feat: extend apply endpoint with modify/delete and pre-validation"
```

---

### Task 5: Frontend types — update chatApi.ts

**Files:**
- Modify: `frontend/src/api/chatApi.ts`

- [ ] **Step 1: Update memory-related types**

Replace the memory types in `frontend/src/api/chatApi.ts` (lines ~94-160):

```typescript
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
  inbox_index: number | null;
  preview: string;
  action: "keep" | "discard" | "modify" | "delete";
  destination: "user_profile" | "knowledge" | null;
  section: string | null;
  edited_text: string | null;
  existing_text: string | null;
  new_text: string | null;
  reason: string | null;
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
  action: "keep" | "discard" | "modify" | "delete";
  inbox_index?: number | null;
  destination?: "user_profile" | "knowledge";
  section?: string;
  text?: string;
  existing_text?: string;
  new_text?: string;
}

export interface CuratorApplyResponse {
  applied: number;
  discarded: number;
  modified: number;
  deleted: number;
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

- [ ] **Step 2: Run typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: may fail on MemoryPanel.tsx (uses old types) — acceptable, fixed in Task 6.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/chatApi.ts
git commit -m "feat: extend frontend types for modify/delete actions"
```

---

### Task 6: Frontend UI — modify/delete cards in MemoryPanel

**Files:**
- Modify: `frontend/src/components/memory/MemoryPanel.tsx`
- Modify: `frontend/src/app/theme.css`

- [ ] **Step 1: Add CSS for modify/delete card styles**

Append to `frontend/src/app/theme.css`, after the last `.memory-apply-all-btn:disabled` block:

```css
.memory-card.modify {
  border-left-color: #3b82f6;
}

.memory-card.delete {
  border-left-color: var(--danger);
}

.memory-card-existing {
  font-size: 0.8125rem;
  color: var(--muted);
  text-decoration: line-through;
  padding: 0.375rem 0.5rem;
  background: var(--surface-soft);
  border-radius: var(--radius);
  margin-bottom: 0.375rem;
  white-space: pre-wrap;
  word-break: break-word;
}

.memory-card-new-textarea {
  width: 100%;
  background: var(--surface-soft);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.5rem 0.625rem;
  font-size: 0.875rem;
  line-height: 1.5;
  resize: vertical;
  min-height: 60px;
  margin-bottom: 0.5rem;
}

.memory-card-new-textarea:focus {
  outline: none;
  border-color: var(--border-strong);
  background: var(--surface);
}

.memory-card-reason {
  font-size: 0.75rem;
  color: var(--muted);
  margin-bottom: 0.5rem;
  font-style: italic;
}

.memory-status-badge.modify {
  color: #3b82f6;
  background: rgba(59, 130, 246, 0.08);
}

.memory-status-badge.delete {
  color: var(--danger);
  background: rgba(198, 95, 54, 0.08);
}

.memory-card-controls button.skip-btn {
  border-color: transparent;
  color: var(--muted);
  background: transparent;
}

.memory-card-controls button.skip-btn:hover {
  background: var(--surface-soft);
}
```

- [ ] **Step 2: Rewrite MemoryPanel.tsx**

Replace the entire `frontend/src/components/memory/MemoryPanel.tsx`:

```tsx
import { useCallback, useEffect, useId, useState } from "react";
import {
  fetchInbox,
  fetchCuration,
  applyCuration,
  type MemoryInboxEntry,
  type CurationSuggestion,
  type CuratorApplyDecision,
} from "../../api/chatApi";

type CardStatus = "pending" | "keep" | "discard" | "modify" | "delete";

type CardState = {
  suggestion: CurationSuggestion;
  entry: MemoryInboxEntry | null;
  editedText: string;
  destination: "user_profile" | "knowledge";
  section: string;
  status: CardStatus;
};

export function MemoryPanel() {
  const panelId = useId();
  const [entries, setEntries] = useState<MemoryInboxEntry[]>([]);
  const [cardStates, setCardStates] = useState<CardState[]>([]);
  const [sections, setSections] = useState<{ user_profile: string[]; knowledge: string[] }>({
    user_profile: [],
    knowledge: [],
  });
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
      setCardStates([]);
      setCurated(false);
    } catch (e) {
      setError("无法加载收件箱");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadInbox();
  }, [loadInbox]);

  const runCuration = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchCuration();
      const cards: CardState[] = [];
      for (const s of data.suggestions) {
        const entry = s.inbox_index != null
          ? entries.find((e) => e.index === s.inbox_index) ?? null
          : null;
        let status: CardStatus = "pending";
        let editedText = "";
        if (s.action === "modify") {
          status = "modify";
          editedText = s.new_text ?? "";
        } else if (s.action === "delete") {
          status = "delete";
          editedText = "";
        } else {
          status = "pending";
          editedText = s.edited_text ?? entry?.text ?? "";
        }
        cards.push({
          suggestion: s,
          entry,
          editedText,
          destination: s.destination ?? "knowledge",
          section: s.section ?? "Other",
          status,
        });
      }
      setCardStates(cards);
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
    for (const card of cardStates) {
      if (card.status === "pending") continue;
      if (card.status === "keep") {
        decisions.push({
          action: "keep",
          inbox_index: card.entry?.index,
          destination: card.destination,
          section: card.section,
          text: card.editedText,
        });
      } else if (card.status === "discard") {
        decisions.push({
          action: "discard",
          inbox_index: card.entry?.index,
        });
      } else if (card.status === "modify") {
        decisions.push({
          action: "modify",
          destination: card.destination,
          existing_text: card.suggestion.existing_text ?? undefined,
          new_text: card.editedText,
        });
      } else if (card.status === "delete") {
        decisions.push({
          action: "delete",
          destination: card.destination,
          existing_text: card.suggestion.existing_text ?? undefined,
        });
      }
    }

    setApplying(true);
    setError(null);
    try {
      await applyCuration(entries.length, decisions);
      setEntries((prev) =>
        prev.filter((e) => {
          const card = cardStates.find(
            (c) => c.entry?.index === e.index && (c.status === "keep" || c.status === "discard")
          );
          return !card;
        })
      );
      setCardStates([]);
      setCurated(false);
    } catch (e) {
      setError(`应用失败: ${String(e)}`);
    } finally {
      setApplying(false);
    }
  };

  const updateCard = (index: number, update: Partial<CardState>) => {
    setCardStates((prev) => {
      const next = [...prev];
      if (index >= 0 && index < next.length) {
        next[index] = { ...next[index], ...update };
      }
      return next;
    });
  };

  const markKeep = (index: number) => updateCard(index, { status: "keep" });
  const markDiscard = (index: number) => updateCard(index, { status: "discard" });
  const markModify = (index: number) => updateCard(index, { status: "modify" });
  const markDelete = (index: number) => updateCard(index, { status: "delete" });
  const markSkip = (index: number) => updateCard(index, { status: "pending" });

  const pendingCount = cardStates.filter((c) => c.status === "pending").length;
  const keepCount = cardStates.filter((c) => c.status === "keep").length;
  const discardCount = cardStates.filter((c) => c.status === "discard").length;
  const modifyCount = cardStates.filter((c) => c.status === "modify").length;
  const deleteCount = cardStates.filter((c) => c.status === "delete").length;
  const totalDecided = keepCount + discardCount + modifyCount + deleteCount;

  return (
    <div className="memory-panel" id={panelId}>
      <header className="memory-panel-header">
        <h2>记忆收件箱</h2>
        {entries.length > 0 && !curated && (
          <button className="memory-analyze-btn" onClick={runCuration} disabled={loading}>
            {loading ? "分析中..." : "分析"}
          </button>
        )}
      </header>

      {error && <p className="memory-error">{error}</p>}
      {loading && <p className="memory-loading">加载中...</p>}

      {!loading && entries.length === 0 && cardStates.length === 0 && (
        <p className="memory-empty">
          暂无待整理记忆。Agent 调用 remember_this 后会出现在这里。
        </p>
      )}

      {!loading && cardStates.length === 0 && entries.length > 0 && (
        <div className="memory-unanalyzed">
          <p>收件箱中有 {entries.length} 条未分析条目。</p>
          <button onClick={runCuration}>开始分析</button>
        </div>
      )}

      {!loading && cardStates.length > 0 && (
        <div className="memory-cards">
          {cardStates.map((card, idx) => {
            const isInbox = card.suggestion.action === "keep" || card.suggestion.action === "discard";
            const isModify = card.suggestion.action === "modify";
            const isDelete = card.suggestion.action === "delete";
            const isDecided = card.status !== "pending";

            return (
              <div key={idx} className={`memory-card ${card.status}`}>
                <header className="memory-card-header">
                  <span className="memory-card-index">
                    {isInbox && card.entry
                      ? `条目 ${card.entry.index + 1}/${entries.length}`
                      : isModify
                      ? "✎ 修改建议"
                      : "✕ 删除建议"}
                  </span>
                  {card.entry && (
                    <time className="memory-card-time">{card.entry.timestamp}</time>
                  )}
                </header>

                {card.suggestion.reason && (isModify || isDelete) && (
                  <p className="memory-card-reason">原因：{card.suggestion.reason}</p>
                )}

                {isInbox && (
                  <textarea
                    className="memory-card-textarea"
                    value={card.editedText}
                    onChange={(e) => updateCard(idx, { editedText: e.target.value })}
                    disabled={isDecided}
                    rows={4}
                  />
                )}

                {isModify && card.suggestion.existing_text && (
                  <>
                    <div className="memory-card-existing">{card.suggestion.existing_text}</div>
                    <textarea
                      className="memory-card-new-textarea"
                      value={card.editedText}
                      onChange={(e) => updateCard(idx, { editedText: e.target.value })}
                      disabled={isDecided}
                      rows={3}
                    />
                  </>
                )}

                {isDelete && card.suggestion.existing_text && (
                  <div className="memory-card-existing">{card.suggestion.existing_text}</div>
                )}

                <div className="memory-card-controls">
                  {(isInbox || isModify) && (
                    <select
                      value={card.destination}
                      onChange={(e) =>
                        updateCard(idx, { destination: e.target.value as "user_profile" | "knowledge" })
                      }
                      disabled={isDecided}
                    >
                      <option value="user_profile">user_profile</option>
                      <option value="knowledge">knowledge</option>
                    </select>
                  )}

                  <select
                    value={card.section}
                    onChange={(e) => updateCard(idx, { section: e.target.value })}
                    disabled={isDecided || isDelete}
                  >
                    {(sections[card.destination] ?? []).map((sec) => (
                      <option key={sec} value={sec}>{sec}</option>
                    ))}
                  </select>

                  {isInbox && card.status === "pending" && (
                    <>
                      <button onClick={() => markKeep(idx)}>应用</button>
                      <button onClick={() => markDiscard(idx)}>丢弃</button>
                    </>
                  )}
                  {isInbox && card.status === "keep" && (
                    <span className="memory-status-badge applied">✓ 待应用</span>
                  )}
                  {isInbox && card.status === "discard" && (
                    <span className="memory-status-badge discarded">✗ 已丢弃</span>
                  )}

                  {isModify && card.status === "modify" && (
                    <span className="memory-status-badge modify">✓ 待应用修改</span>
                  )}

                  {isDelete && card.status === "delete" && (
                    <span className="memory-status-badge delete">✗ 待删除</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {cardStates.length > 0 && (totalDecided > 0 || pendingCount > 0) && (
        <footer className="memory-panel-footer">
          <span>
            已选 {keepCount} 条应用 · {modifyCount} 条修改 · {deleteCount}{" "}
            条删除 · {discardCount} 条丢弃 · {pendingCount} 条未处理
          </span>
          <button
            className="memory-apply-all-btn"
            onClick={applyDecisions}
            disabled={applying || totalDecided === 0}
          >
            {applying ? "应用中..." : `全部应用 (${totalDecided})`}
          </button>
        </footer>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Run typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/memory/MemoryPanel.tsx frontend/src/app/theme.css
git commit -m "feat: add modify/delete cards to MemoryPanel with evolution styles"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run full backend test suite**

```bash
.venv/bin/python -m pytest tests/ -q
```

Expected: all tests pass

- [ ] **Step 2: Full frontend check**

```bash
cd frontend && npm run typecheck
```

Expected: PASS

- [ ] **Step 3: Verify Python compilation**

```bash
.venv/bin/python -m compileall app hello_agents -q
```

- [ ] **Step 4: Commit if needed (any final fixup)**

```bash
git diff
# If clean: done. If not: fix and commit.
```
