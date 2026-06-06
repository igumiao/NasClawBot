# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Project Overview

NasClawBot is a single-user NAS/PT media assistant. The active implementation is intentionally simple:

```text
/chat     -> readonly M-Team search -> search results
/chat/agent -> experimental NasClawAgentRunner + ToolCallingAgent + gated download approvals + JSON checkpoints
/download -> explicit user action -> qB add paused
/qb/*     -> qB task management
```

The project is building a minimal context-aware Agent loop from this baseline. Do not assume the older workflow/runtime design is still active.

## Important Current Facts

- There is no `/confirm` route.
- There is no `confirmation_payload`.
- There is no `HelloAgentWorkflowRunner`.
- There is no `SequentialWorkflow`.
- There is no active workflow runtime.
- `/chat` still calls `MTeamSearchTool` directly and does not use LLM/session history.
- `/chat/agent` is the experimental Agent route. It delegates to `NasClawAgentRunner`, currently uses `ToolCallingAgent` with `mteam_search`, read-only `member_profile`, and confirm-gated `qb_add_torrent`, supports multi-turn history, and persists JSON conversation checkpoints under `memory/agent-sessions/{session_id}.json`.
- `GET /chat/agent/sessions` lists persisted Agent checkpoint summaries without calling an LLM or tools.
- `GET /chat/agent/sessions/{session_id}` returns one persisted Agent checkpoint with renderable message history, also without calling an LLM or tools.
- `POST /chat/agent/sessions/{session_id}/approvals/{approval_id}/approve` approves a pending `qb_add_torrent` call. For checkpoints with `paused_loop`, the runner validates the paused provider tool call against the approval record, executes the tool, appends the provider `tool` result, resumes the LLM with `tool_choice="none"`, and clears the pending approval. Legacy checkpoints without `paused_loop` fall back to the deterministic approval summary path.
- `POST /chat/agent/sessions/{session_id}/approvals/{approval_id}/deny` denies a pending Agent tool call without executing the tool. For checkpoints with `paused_loop`, the runner resumes the provider tool-call protocol with a `USER_DENIED` tool error and a no-tools final LLM pass.
- `PATCH /chat/agent/sessions/{session_id}`: updates a session checkpoint. Currently supports `title` in `metadata.title` for session renaming.
- `DELETE /chat/agent/sessions/{session_id}`: deletes a persisted session checkpoint (HTTP 204 on success).
- The browser Chat tab now uses `/chat/agent` as its active experience path. It renders Agent tool-call summaries, search candidates, and gated download approval cards; `/download` remains available as the stable explicit API but is not called by the Chat result button.
- `hello_agents/checkpoints/` defines the thin `ConversationCheckpointStore` boundary and the current JSON implementation.
- Tool wrappers live in `app/tools/` (per-tool modules, re-exported via `__init__.py`).
- M-Team and qB integration lives behind adapters in `app/adapters/`.
- `mteam_search` exposes only optional `keyword`, `mode`, `sort_by`, `imdb`, and `douban` to the LLM. It requests 20 rows from M-Team and returns at most 5 candidates.
- `hello_agents/tools/` provides `Filter` (pre-LLM tool selection) and `Gate` (pre-execution deny/confirm).
- `ToolPermission` and `ToolFilter` have been removed in favor of `Filter` + `Gate`.
- Historical LangGraph and HelloAgents runtime docs are archived under `docs/archive/`.

## Dev Commands

Backend, from repo root:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/test_chat_api.py tests/test_mteam_adapter.py tests/test_mteam_search_tool.py tests/test_qb_adapter.py -q
.venv/bin/python -m compileall app hello_agents -q
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend, from `frontend/`:

```bash
npm test
npm run typecheck
npm run build
npm run dev
```

There is no formal Python formatter configured yet.

## Architecture Notes

`app/api/chat_routes.py` owns the current interaction surface:

- `POST /chat`: trims the user message, calls `MTeamSearchTool`, returns `ChatResponse.results`.
- `POST /chat/agent`: validates the request, delegates to `NasClawAgentRunner`, and returns a normal `ChatResponse`.
- `GET /chat/agent/sessions`: lists persisted Agent conversation summaries.
- `GET /chat/agent/sessions/{session_id}`: loads one persisted Agent conversation checkpoint.
- `POST /download`: accepts a torrent id, calls `QBAddTorrentTool`, submits to qB paused, and returns a receipt.
- `POST /chat/agent/sessions/{session_id}/approvals/{approval_id}/approve`: approves and executes a pending Agent download request. With `paused_loop`, the runner appends the real provider `tool` result and resumes the LLM with `tool_choice="none"`; legacy checkpoints fall back to the deterministic summary path.
- `POST /chat/agent/sessions/{session_id}/approvals/{approval_id}/deny`: cancels a pending Agent download request. With `paused_loop`, the runner resumes the provider protocol with a `USER_DENIED` tool error and a no-tools final LLM pass.
- `PATCH /chat/agent/sessions/{session_id}`: updates session metadata (currently `title` in `metadata.title`).
- `DELETE /chat/agent/sessions/{session_id}`: deletes a persisted checkpoint, returns 204 on success.
- qB management routes are included from `app/api/qb_routes.py`.

`app/agent/runner.py` owns the experimental Agent conversation lifecycle: load checkpoint, build the current tool-calling agent, restore history, run one turn, save checkpoint, and extract route-facing search results/tool calls.

`NasClawAgentRunner.run/approve/deny` are serialized per session within the current server process. This prevents concurrent approval decisions from executing the same download twice; multi-process coordination still requires a future transactional durable store.

`ToolCallingLoop` applies `Filter` before sending tool schemas to the LLM and applies `Gate` before `tool.run()`. `DENY` produces a permission-denied observation without executing the tool. `ASK_USER` pauses the loop with `status="awaiting_approval"` and route-facing `pending_approvals`; it saves the assistant tool-call message but does not write a provider `tool` result before approval. NasClawBot persists `pending_approvals` for UI/lifecycle recovery and `metadata["paused_loop"]` for provider protocol resume. Approve/deny now resume the paused provider tool-call protocol when `paused_loop` exists; deterministic approval remains a legacy fallback.

While a session has a non-expired pending approval, `/chat/agent` rejects new user messages. Before a new turn, the runner resolves expired approvals without executing the tool, removes the unresolved provider assistant tool-call message, and allows the conversation to continue. The current loop supports one pending approval at a time; multiple simultaneous `ASK_USER` tool calls return a controlled approval conflict.

`app/agent/approvals.py` defines the application-level approval lifecycle. Pending records include `session_id`, `expires_at`, `risk`, `decision`, `result`, and `error`; resolved records move from checkpoint `metadata["pending_approvals"]` to `metadata["approvals"]`.

`ToolCallingLoop` performs one forced final LLM pass with `tool_choice="none"` when `max_steps` is reached. That pass summarizes current observations without executing more tools; if it fails or returns tool calls, the loop falls back to the controlled max-steps message.

`ToolObservation` is the loop-level envelope for one tool call. It stores `tool_name`, `tool_call_id`, arguments, full structured `ToolResponse`, separate LLM-facing `observation_text`, and gate markers (`gate_result`, `gate_reason`, `approval_id`); routes should read `observation.response.data` rather than parsing tool-message text.

`ContextWindowManager` performs preflight context checks before LLM calls. NasClawBot currently uses a conservative 64K configured context window, enables smart compression at 70% context pressure, keeps the latest 4 rounds active, writes a `summary` message into active history, and preserves compressed-away originals in checkpoint `archives`.

`frontend/src/components/chat/ChatPanel.tsx` renders the active Agent experience. It calls `/chat/agent`, displays `ToolActivityCard` before `SearchResultCard`, sends a selected torrent id back through the Agent to request `qb_add_torrent`, and renders `ApprovalCard` for approve/deny. Assistant messages are rendered as Markdown through `MarkdownContent` (react-markdown + remark-gfm). The active Agent session id is stored in browser session storage and restored from `GET /chat/agent/sessions/{session_id}` after refresh.

`frontend/src/app/AppShell.tsx` owns the outer layout. It polls `GET /health` every 30s for live backend status (green/red dot + label), and uses `display: none` to keep inactive tab panels mounted.

`frontend/src/app/theme.css` enforces a fixed viewport layout (`.app-shell` locked to `100vh`, `.workspace-shell` with sticky topbar, `.chat-panel` fills remaining height, `.chat-thread` scrolls independently, `.composer-shell` pinned at bottom with acrylic backdrop-filter). `.conversation-sidebar` has its own `overflow-y: auto` scrollbar.

The `ConversationSidebar` is currently a placeholder. The next frontend milestone is a real multi-session sidebar with collapsible layout, session list from `GET /chat/agent/sessions`, rename via `PATCH`, delete via `DELETE`, and session switching.

`ref/mteam-api-reference.md` is the local source of truth for M-Team endpoints.

### M-Team Search Contract

- `mode`: `normal`, `movie`, `tvshow`, or `music`.
- `sort_by`: `smallest`, `largest`, or `most_seeded`. Omit it for M-Team's default newest-first ordering.
- Do not expose `discount`, pagination, raw sort fields, categories, or local hard filters to the LLM in the current phase.
- Keep the adapter reusable: it returns the full first-page pool of 20 rows. `MTeamSearchTool` applies the product-facing limit of 5.
- Read `seeders`, `leechers`, and `discount` only from each result's `status` object.
- Use release `name` as the candidate display title. Detect resolution from `smallDescr` first, falling back to `name` only when `smallDescr` is absent or empty. Current normalized values include `4320p`, `2160p`, `1080p`, and `720p`.
- Return `discount` as informational candidate metadata; do not use it as a search input.

### Tool Safety: Filter + Gate

Two independent layers, no `ToolPermission` enum:

- **Filter** (`hello_agents/tools/filter.py`): runs **before** tools are sent to the LLM. Narrows the tool list to control context window usage and sub-agent capability scope. Currently allows `["mteam_search", "member_profile", "qb_add_torrent"]`. `Filter(allow=lambda name: ...)` also supported.
- **Gate** (`hello_agents/tools/gate.py`): runs **after** LLM returns a tool call, **before** `tool.run()`. Three gates: deny_rules → confirm_rules → default allow. Works on `ToolCall` (tool_name + params), so decisions can be parameter-aware (`bash("ls")` passes, `bash("sudo rm -rf /")` denied).

Factory functions for common deny rules: `deny_command()`, `deny_paths()`, `deny_outside_workspace()`, `deny_regex()`.

### Current Experimental Agent Loop

The first loop is intentionally narrow:

```text
POST /chat/agent
  -> NasClawAgentRunner
  -> load JSON checkpoint
  -> ToolCallingAgent
  -> mteam_search, member_profile, and confirm-gated qb_add_torrent
  -> tool result back to LLM
  -> save JSON checkpoint
```

`/chat` remains the stable no-LLM route. Do not replace it until the Agent path is proven.

## Safety Rules

- Never trigger real downloads in tests/demos unless explicitly requested.
- Download submissions must remain paused by default.
- Never log secrets or full tokenized download URLs.
- Keep search, detail, and token generation separate.
- Do not download `.torrent` files locally.
- Do not expose destructive file operations to an open Agent loop.

## Next Direction

Continue evolving the gated Agent loop while keeping `/chat` stable.

- Keep `qb_add_torrent` behind approval gating.
- Keep `/download` as the stable explicit user action.
- Session management: `PATCH` for rename (metadata.title), `DELETE` for removal.
- Next frontend milestone: multi-session sidebar with collapsible layout, session list from `GET /chat/agent/sessions`, rename via `PATCH`, delete via `DELETE`, and session switching.
- Keep future loop ideas in `docs/design/agent-loop-improvement-notes.md`; do not prematurely hard-code them into the framework.
