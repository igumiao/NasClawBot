# Memory Curator — Design Spec

## Overview

Add a curator function and review UI so the operator can batch-review Agent-written
inbox entries and selectively apply them to `user_profile.md` or `knowledge.md`.

---

## API Surface

### `GET /memory/inbox`

Read `memory/agent-memory/memory_inbox.md`, split by `---` separator, return parsed
entries.

**Response:**
```json
{
  "entries": [
    {
      "index": 0,
      "timestamp": "2026-06-12T10:17:00",
      "text": "用户偏好：华语片用中文名搜索..."
    }
  ],
  "entry_count": 4
}
```

- Returns empty list when inbox doesn't exist.
- Timestamp parsed from markdown heading `## YYYY-MM-DD HH:MM`.
- `text` is everything between the heading and the next `---`.

### `POST /memory/curate`

Trigger curator LLM analysis. Inputs:
- All inbox entries (full text)
- `user_profile.md` full text (for dedup / classification context)
- `knowledge.md` full text (for dedup / classification context)

LLM is prompted to output JSON. The app parses and returns the structured list.
**This endpoint does not write any files.**

**Response:**
```json
{
  "inbox_entry_count": 4,
  "suggestions": [
    {
      "inbox_index": 0,
      "preview": "用户偏好：华语片用中文名搜索...",
      "action": "keep",
      "destination": "user_profile",
      "section": "Media Preferences",
      "edited_text": "搜索策略：华语片用中文名，非华语片用英文原名搜索。"
    },
    {
      "inbox_index": 3,
      "preview": "TMDB 失败后改用 tavily...",
      "action": "keep",
      "destination": "knowledge",
      "section": "TMDB",
      "edited_text": "TMDB 搜索无结果时改用 tavily_search 多换关键词查证。"
    }
  ]
}
```

**Action values:**
- `keep` — worth keeping, provide destination/section/edited_text
- `discard` — duplicate, garbage, or not worth keeping; no destination needed

**Error cases:**
- No LLM configured → 503
- LLM call fails → 502 with error detail
- Empty inbox → 200 with empty suggestions

### `PATCH /memory/curate/apply`

Execute user-reviewed decisions. Request body:

```json
{
  "inbox_entry_count": 4,
  "decisions": [
    { "inbox_index": 0, "action": "keep", "destination": "user_profile", "section": "Media Preferences", "text": "..." },
    { "inbox_index": 1, "action": "keep", "destination": "knowledge", "section": "TMDB", "text": "..." },
    { "inbox_index": 2, "action": "discard" },
    { "inbox_index": 3, "action": "keep", "destination": "knowledge", "section": "Other", "text": "..." }
  ]
}
```

**Process:**
1. Read inbox, split by `---` into entries list
2. Validate `len(entries) == inbox_entry_count` → 409 if mismatch
3. For each `keep` decision: `store.append_to_section(destination, section, text)`
4. Rebuild inbox from unprocessed entries (indices not in decisions)
5. Return summary

**Response:**
```json
{
  "applied": 3,
  "discarded": 1,
  "remaining": 0
}
```

**Thread safety:** Both inbox read/write and target file appends happen under `_inbox_lock`.

---

## New Methods on MarkdownMemoryStore

### `append_to_section(kind, section, text)`

Append a line to `user_profile.md` or `knowledge.md` under the given `## Section` heading.
- Find the `## Section` line.
- Walk forward to the next `## ` heading (or EOF).
- Insert `text` before the next heading, with a blank line separator.
- If the section heading doesn't exist, append to end of file with the heading auto-created.
- Thread-safe under `_inbox_lock`.

### `get_sections(kind)`

Return list of `## ` heading strings from a file. Used by frontend to populate
section dropdowns, and by the curator prompt to know available sections.

---

## Curator Function

### Location: `app/services/curator.py`

```python
def run_curation(store: MarkdownMemoryStore) -> CuratorResult:
    """Read inbox + profiles, call LLM once, return structured suggestions."""
```

- Reads inbox, user_profile, knowledge from store
- Builds a prompt containing all three files' full text
- Calls LLM (configured via settings, same as Agent LLM)
- Parses JSON response
- Returns `CuratorResult` with `suggestions` and `inbox_entry_count`

**LLM prompt key instructions:**
- For each inbox entry, decide keep/discard
- Classification rules:
  - **user_profile**: personal preferences, communication style, identity, tool habits, prohibitions
  - **knowledge**: domain tips, operational lessons, factual information about the user's environment
- Edit text for clarity and conciseness while preserving meaning
- If an entry substantially overlaps with an existing profile/knowledge entry, mark as discard with reason
- Output must be valid JSON matching the schema

**JSON Schema (enforced via Pydantic):**
```python
class CuratorSuggestion(BaseModel):
    inbox_index: int
    preview: str  # first ~30 chars of original
    action: Literal["keep", "discard"]
    destination: Literal["user_profile", "knowledge"] | None = None
    section: str | None = None  # must be one of the headings in the target file (from get_sections)
    edited_text: str | None = None

class CuratorResult(BaseModel):
    suggestions: list[CuratorSuggestion]
    inbox_entry_count: int
```

---

## Frontend

### New Tab: "记忆"

- Added to `WorkspaceTab` union: `"chat" | "downloads" | "settings" | "free-torrents" | "memory"`
- Tab label: `"记忆"` with badge count when inbox has entries
- Panel: `MemoryPanel.tsx` under `frontend/src/components/memory/`

### MemoryPanel

**States:**
1. **Empty** — no inbox entries, show "暂无待整理记忆"
2. **Loading** — fetching inbox or running curator
3. **Review** — cards displayed, awaiting user decisions
4. **Applying** — executing decisions, show spinner

**Card layout (each inbox entry):**
- Timestamp header
- Editable `<textarea>` pre-filled with curator's `edited_text`
- Two dropdowns: destination (`user_profile` / `knowledge`), section (populated from `get_sections`)
- "应用" and "丢弃" buttons per card
- Color coding: applied cards get green left border, discarded get red, pending stay amber

**Bottom bar:**
- Summary: "已选择 N 条应用 · M 条丢弃 · K 条未处理"
- "全部应用" button → calls `PATCH /memory/curate/apply` with all non-discarded decisions
- Toast on success/error

**Data flow:**
1. Tab click → `GET /memory/inbox` → render cards or empty state
2. "分析" button → `POST /memory/curate` → populate cards with curator suggestions
3. User edits text, changes dropdowns
4. "全部应用" → `PATCH /memory/curate/apply` → refresh inbox

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Inbox doesn't exist | GET returns empty; curate returns empty; apply returns error |
| LLM call fails | POST /memory/curate returns 502 with error message |
| Concurrent modification | PATCH /memory/curate/apply returns 409 if entry count mismatches |
| Invalid decision JSON | PATCH returns 422 via Pydantic validation |
| File I/O error | 500 with message |

---

## Test Plan

### Unit tests (`tests/test_curator.py`)
- `run_curation` with empty inbox returns empty result
- `run_curation` with mock LLM returns correctly structured suggestions
- Pydantic schema validation

### Store tests (`tests/test_markdown_memory_store.py`)
- `append_to_section` appends under correct heading
- `append_to_section` with non-existent section auto-creates it
- `get_sections` returns all headings
- `append_to_section` is thread-safe

### Route tests (`tests/test_memory_routes.py`)
- `GET /memory/inbox` with missing file → empty
- `GET /memory/inbox` with entries → correct parsed output
- `POST /memory/curate` with mock LLM → correct response
- `PATCH /memory/curate/apply` → files updated, inbox rebuilt
- `PATCH /memory/curate/apply` with count mismatch → 409

### Frontend tests (existing pattern)
- `MemoryPanel.test.tsx` — empty state, card rendering, button actions

---

## Non-Goals (v1)

- Merge action — curator only outputs keep/discard; if a new entry overlaps with existing knowledge, the curator should output discard with a reason
- Automatic trigger — operator explicitly clicks "分析" to run curation
- Undo/revert applied decisions
- Frontend progress indicator beyond loading spinner during LLM call
- Curator prompt customisation UI (prompt is hardcoded in curator.py)
- Curator cannot edit `user_profile.md` sections — it can only suggest entries for existing section headings
