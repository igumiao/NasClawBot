# Memory Evolution — Design Spec

## Overview

Extend the Memory Curator (`v1`) with Evolution capabilities: the curator not
only classifies inbox entries but also inspects existing `user_profile.md` and
`knowledge.md` content and proposes modifications or deletions of stale,
contradictory, or duplicate entries.

This spec builds on `docs/superpowers/specs/2026-06-12-memory-curator-design.md`.
Everything already in place (GET /memory/inbox, inbox parse, frontend MemoryPanel
tab, section dropdowns) stays unchanged except where explicitly modified below.

---

## Data Model Changes

### `CuratorSuggestion` (backend — `app/services/curator.py`)

`action` gains two new values.  Fields that were always present now become
optional for the new action types.

```python
class CuratorSuggestion(BaseModel):
    # ---- keep / discard (unchanged) ----
    inbox_index: int | None = None   # null for modify / delete (not from inbox)
    preview: str = ""                # first ~30 chars of original inbox text (empty for modify/delete)
    action: Literal["keep", "discard", "modify", "delete"]

    # keep-specific
    destination: Literal["user_profile", "knowledge"] | None = None
    section: str | None = None
    edited_text: str | None = None

    # ---- modify / delete (new) ----
    existing_text: str | None = None  # exact original line from the file
    new_text: str | None = None       # replacement line (modify only)
    reason: str | None = None         # why this change is needed
```

**Validation rules:**
- `keep` / `discard`: `inbox_index` required; `existing_text` must be `None`.
- `modify`: `existing_text`, `new_text`, `destination`, `section`, `reason` all required.
- `delete`: `existing_text`, `destination`, `section`, `reason` all required.

### Frontend types (`chatApi.ts`)

```typescript
type CuratorAction = "keep" | "discard" | "modify" | "delete";

interface CurationSuggestion {
  inbox_index: number | null;
  preview: string;
  action: CuratorAction;
  destination: "user_profile" | "knowledge" | null;
  section: string | null;
  edited_text: string | null;
  existing_text: string | null;
  new_text: string | null;
  reason: string | null;
}
```

### Apply decision type (`CuratorApplyDecision`)

```python
class CuratorApplyDecision(BaseModel):
    action: Literal["keep", "discard", "modify", "delete"]
    inbox_index: int | None = None       # keep/discard only
    destination: Literal["user_profile", "knowledge"] | None = None
    section: str | None = None
    text: str | None = None              # keep: content to append
    existing_text: str | None = None     # modify/delete: exact line to match
    new_text: str | None = None          # modify: replacement line

class CuratorApplyRequest(BaseModel):
    inbox_entry_count: int
    decisions: list[CuratorApplyDecision]

class CuratorApplyResponse(BaseModel):
    applied: int
    discarded: int
    modified: int
    deleted: int
    remaining: int
```

---

## New Store Methods

All new methods live under `_inbox_lock` for thread safety.

### `replace_in_section(kind, existing_text, new_text) → bool`

1. Load the file, split into lines.
2. Find the first line whose `.strip()` equals `existing_text.strip()`.
3. Replace it with `new_text`.
4. Write the file back.
5. Return `True` if found and replaced, `False` otherwise.

### `delete_from_section(kind, existing_text) → bool`

1. Load the file, split into lines.
2. Find the first line whose `.strip()` equals `existing_text.strip()`.
3. Remove that line (and the following blank line if the next line is empty).
4. Write the file back.
5. Return `True` if found and removed, `False` otherwise.

**Matching semantics:**
- Exact match on `strip()` — no substring matching, no fuzzy matching.
- Match failure returns `False`; the apply endpoint returns a 400-level error
  with the unmatched `existing_text` so the operator can fix or skip that card.

---

## Curator Prompt Changes

### Time awareness

The curator call is a one-shot LLM invocation — it has no access to the `current_time`
tool.  `_build_prompt()` must compute the current UTC date at call time
(`datetime.now(timezone.utc)`) and inject it as the first line of the prompt,
exactly like how the Agent system prompt gets a dynamic date line from `APP_TIMEZONE`:

```python
from datetime import datetime, timezone

now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
prompt = f"当前日期：{now}（UTC）。用这个日期判断信息是否过时。\n\n" + rest
```

This is NOT a hardcoded literal — the date is computed fresh each time
`_build_prompt()` is called.

### Additional inputs

The prompt now includes the **full text** of `user_profile.md` and `knowledge.md`
as plain markdown (no line numbers, no escaping).  The LLM reads the exact content
and copies the line it wants to modify into `existing_text`.

Each entry in those files is already date-stamped (`- [YYYY-MM-DD] ...`) by
`append_to_section`.  With the current date injected above, the LLM can compare
dates and flag old entries as stale.

### New section in the prompt

```markdown
## 修改/删除已有条目（Evolution）

除了判定收件箱条目，你还需要检查现有用户画像和知识库中是否有需要
修改或删除的内容：

1. **矛盾检测**：如果 inbox 新条目和已有条目矛盾，标记 modify 旧条目
   （用新信息替代旧信息）。如果已有条目之间互相矛盾，modify 过时的、
   保留最新的。
2. **过时检测**：如果已有条目明显过时或无效，标记 delete。
3. **重复检测**：如果 inbox 条目和已有条目高度重复，discard inbox 条目
   （不需要 modify 已有条目）。

### modify / delete 输出要求

- `existing_text`：文件中的**精确原文**，一字不差。后端用它定位要修改/删除的行。
- `new_text`（modify）：替换后的完整行内容，保持 markdown 格式。
- `reason`：简要说明为什么要修改或删除这条信息。
- 不要凭空创造 modify/delete——只有当已有内容确实需要变更时才输出。
```

The final prompt layout:

0. **当前日期** — 注入 UTC 日期，用于判断过时
1. 现有用户画像 (full user_profile.md)
2. 现有知识库 (full knowledge.md)
3. 收件箱条目
4. 可用章节列表
5. 判定规则 (keep/discard + modify/delete)
6. JSON 输出格式

---

## API Changes

### `POST /memory/curate` — unchanged signature

Response gains new suggestion shapes:

```json
{
  "inbox_entry_count": 2,
  "suggestions": [
    { "inbox_index": 0, "action": "keep", "destination": "user_profile",
      "section": "TMDB", "edited_text": "...", "preview": "..." },
    { "inbox_index": 1, "action": "discard", "preview": "..." },
    { "inbox_index": null, "action": "modify",
      "destination": "user_profile", "section": "Identity",
      "existing_text": "我叫 IGUMIAO-NAS…", "new_text": "- [2026-06-15] 用户称呼为 Maifa",
      "reason": "称呼已更新", "preview": "" },
    { "inbox_index": null, "action": "delete",
      "destination": "knowledge", "section": "Other",
      "existing_text": "旧提示内容", "reason": "信息不再适用", "preview": "" }
  ],
  "sections": { "user_profile": ["Identity", "Communication Style", ...], "knowledge": ["TMDB", "M-Team", ...] }
}
```

### `PATCH /memory/curate/apply` — extended request

```json
{
  "inbox_entry_count": 2,
  "decisions": [
    { "action": "keep",   "inbox_index": 0, "destination": "user_profile", "section": "TMDB", "text": "..." },
    { "action": "discard","inbox_index": 1 },
    { "action": "modify", "destination": "user_profile", "existing_text": "...", "new_text": "..." },
    { "action": "delete", "destination": "knowledge", "existing_text": "..." }
  ]
}
```

**Process order (inside `_inbox_lock`):**

1. Parse inbox, validate `len(entries) == inbox_entry_count` → 409 on mismatch.
2. **Pre-validate** all modify/delete decisions: check that every `existing_text`
   can be found in the target file.  Return 400 immediately if any match fails,
   before modifying any files.  (This prevents partial application — all-or-nothing.)
3. For each decision:
   - `keep` → `store.append_to_section(destination, section, text)` (unchanged).
   - `discard` → no file write.
   - `modify` → `store.replace_in_section(kind, existing_text, new_text)`.
   - `delete` → `store.delete_from_section(kind, existing_text)`.
4. Rebuild inbox from unprocessed entries (same as v1).
5. Return summary.

**Extended response:**

```python
class CuratorApplyResponse(BaseModel):
    applied: int    # keep decisions
    discarded: int  # discard decisions
    modified: int   # modify decisions
    deleted: int    # delete decisions
    remaining: int   # inbox entries left after processing
```

```json
{
  "applied": 1,
  "discarded": 1,
  "modified": 1,
  "deleted": 1,
  "remaining": 0
}
```

---

## Frontend

### MemoryPanel — new card types

| Card type | Left border | Layout | Actions |
|-----------|-------------|--------|---------|
| inbox (keep) | amber (`--warning`) | textarea + destination/section dropdown | "应用" / "丢弃" |
| modify | blue (`#3b82f6`) | two-line: crossed-out `existing_text` (read-only) above `new_text` (editable textarea), reason label, destination/section dropdown | "应用" / "跳过" |
| delete | red (`--danger`) | crossed-out `existing_text` (read-only), reason label | "确认删除" / "跳过" |
| applied | green (`--success`) | same as pending but locked | "✓ 待应用" badge |
| discarded | gray, reduced opacity | locked | "✗ 已丢弃" badge |

### Footer summary

```
已选 N 条应用 · M 条修改 · X 条删除 · Y 条丢弃 · Z 条未处理
```

Footer visible when `appliedCount + modifyCount + deleteCount > 0 || pendingCount > 0`.

### "全部应用" behavior

Collects all non-pending cards: applied → keep, modified → modify, deleted → delete, discarded → discard.  Sends a single `PATCH` and refreshes on success.

---

## Error Handling

| Scenario | Status | Behavior |
|----------|--------|----------|
| `existing_text` match fails (pre-validation) | 400 | `{"detail": "无法定位原文片段: <existing_text>"}` — **all-or-nothing**: no files are modified |
| Concurrent inbox modification | 409 | unchanged |
| Invalid decision schema | 422 | unchanged |
| LLM call fails | 502 | unchanged |

---

## Test Plan

### Store tests (`tests/test_markdown_memory_store.py`)

- `replace_in_section` replaces the correct line
- `replace_in_section` returns `False` when no match
- `replace_in_section` match is case- and whitespace-sensitive (strip only)
- `delete_from_section` removes the correct line
- `delete_from_section` removes trailing blank line
- `delete_from_section` returns `False` when no match
- Both methods are thread-safe (covered by lock)

### Curator tests (`tests/test_curator.py`)

- `run_curation` with mock LLM returns modify/delete suggestions with correct shape
- `run_curation` with contradictory profile entries produces modify suggestions
- Curator prompt includes current UTC date for time awareness
- Pydantic validation: modify requires existing_text/new_text/destination/section/reason
- Pydantic validation: delete requires existing_text/destination/section/reason

### Route tests (`tests/test_memory_routes.py`)

- `POST /memory/curate` returns modify/delete suggestions alongside keep/discard
- `PATCH /memory/curate/apply` with modify decision → line replaced in file
- `PATCH /memory/curate/apply` with delete decision → line removed from file
- `PATCH /memory/curate/apply` with unmatched existing_text → 400
- `PATCH /memory/curate/apply` with mix of keep/modify/delete → all applied, inbox rebuilt

### Frontend (`MemoryPanel.test.tsx`)

- Modify card renders before/after with reason
- Delete card renders crossed-out text with reason
- Footer shows separate counts for applied/modified/deleted/discarded/pending

---

## Non-Goals (v1)

- Automatic evolution trigger — operator explicitly clicks "分析" to run.
- Fuzzy matching — exact+strip only.
- Undo/revert applied modifications or deletions.
- Inline editing of `existing_text` in modify/delete cards (text is read-only to
  prevent match failures).
- Evolution at the Agent level — NasClawBot Agent does not call modify/delete.
  Curator is the only path for knowledge evolution.
