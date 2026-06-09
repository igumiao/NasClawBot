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
- `/chat/agent` is the experimental Agent route. It delegates to `NasClawAgentRunner`, currently uses `ToolCallingAgent` with 15 tools: `current_time`, `mteam_search`, `tavily_search`, 4 TMDB tools (`tmdb_search`, `tmdb_details`, `tmdb_discover`, `tmdb_trending`), `member_profile`, and 7 qB tools (`qb_add_torrent`, `qb_list_torrents`, `qb_get_torrent`, `qb_list_categories`, `qb_control_torrent`, `qb_set_global_speed`, `qb_set_torrent_speed`). Read-only tools execute immediately; action tools (`qb_add_torrent`, `qb_control_torrent`, `qb_set_*_speed`) require user approval. Supports multi-turn history, and persists JSON conversation checkpoints under `memory/agent-sessions/{session_id}.json`.
- `GET /chat/agent/sessions` lists persisted Agent checkpoint summaries without calling an LLM or tools.
- `GET /chat/agent/sessions/{session_id}` returns one persisted Agent checkpoint with renderable message history, also without calling an LLM or tools.
- `POST /chat/agent/sessions/{session_id}/approvals/{approval_id}/approve` approves a pending Agent tool call (`qb_add_torrent`, `qb_control_torrent`, `qb_set_global_speed`, or `qb_set_torrent_speed`). For checkpoints with `paused_loop`, the runner validates the paused provider tool call against the approval record, executes the tool, appends the provider `tool` result, resumes the LLM with `tool_choice="none"`, and clears the pending approval. Legacy checkpoints without `paused_loop` fall back to the deterministic approval summary path.
- `POST /chat/agent/sessions/{session_id}/approvals/{approval_id}/deny` denies a pending Agent tool call without executing the tool. For checkpoints with `paused_loop`, the runner resumes the provider tool-call protocol with a `USER_DENIED` tool error and a no-tools final LLM pass.
- `PATCH /chat/agent/sessions/{session_id}`: updates a session checkpoint. Currently supports `title` in `metadata.title` for session renaming.
- `DELETE /chat/agent/sessions/{session_id}`: deletes a persisted session checkpoint (HTTP 204 on success).
- The browser Chat tab now uses `/chat/agent` as its active experience path. It renders Agent tool-call summaries, search candidates, and gated download approval cards; `/download` remains available as the stable explicit API but is not called by the Chat result button.
- `hello_agents/checkpoints/` defines the thin `ConversationCheckpointStore` boundary and the current JSON implementation.
- Tool wrappers live in `app/tools/` (per-tool modules, re-exported via `__init__.py`).
- M-Team and qB integration lives behind adapters in `app/adapters/`.
- `mteam_search` exposes only optional `keyword`, `mode`, `sort_by`, `imdb`, and `douban` to the LLM. It requests 20 rows from M-Team and returns at most 10 candidates. Agent policy defaults searches to `normal`; names/aliases/years/season info are preferred, with IMDb as an auxiliary signal rather than the default hard filter for TV/variety/anime resources.
- `hello_agents/tools/` provides `Filter` (pre-LLM tool selection) and `Gate` (pre-execution deny/confirm).
- `ToolPermission` and `ToolFilter` have been removed in favor of `Filter` + `Gate`.
- Historical LangGraph and HelloAgents runtime docs are archived under `docs/archive/`.

## Dev Commands

Backend, from repo root:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/test_chat_api.py tests/test_mteam_adapter.py tests/test_mteam_search_tool.py tests/test_qb_adapter.py tests/test_qb_tools.py -q
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

`frontend/src/app/AppShell.tsx` is the root layout controller. It owns:
- `activeAgentSessionId` (lifted from ChatPanel for cross-component switching).
- Sidebar collapse state persisted to `localStorage` (`nasclawbot-sidebar-collapsed`).
- Session list fetched from `GET /chat/agent/sessions` via `chatApi.listAgentSessions()`.
- `handleRenameSession` → `PATCH /chat/agent/sessions/{id}`.
- `handleDeleteSession` → `DELETE /chat/agent/sessions/{id}` (deletes current → switches to the blank new-conversation state).
- Backend health polling every 30s (green/red dot + label).
- `display: none` keeps inactive tab panels mounted.

`frontend/src/components/layout/ConversationSidebar.tsx` is a full multi-session sidebar:
- Collapsible: narrows to 64px icon-only mode with 240ms CSS grid-animated transition, persisted in `localStorage`.
- In collapsed mode, the original brand mark remains the only top control; hover/focus turns it into the expand-sidebar button.
- Session list from `GET /chat/agent/sessions`, sorted by `saved_at` descending (most recent active first).
- Click a session → lifts `activeAgentSessionId` in AppShell → `useAgentChatSession` resets local state and restores that checkpoint.
- "+ 新对话" button switches to a blank new-conversation state; the first send generates the session id and writes the checkpoint.
- Hover reveals `⋯` menu button per session row.
- Menu: 重命名 (inline text input, Enter to save, Esc to cancel, PATCH to backend) + 删除 (confirm dialog, DELETE to backend).
- Empty state when no sessions exist.
- Long titles truncated with `text-overflow: ellipsis`, full title on `title` attribute.

`frontend/src/components/chat/ChatPanel.tsx` accepts `activeSessionId` from AppShell and delegates session behavior to `useAgentChatSession`. The hook wraps checkpoint restore, message sending, approval lifecycle, approval expiry, stale async-response guards, and the first-send transition from blank conversation to active session. Assistant messages render as Markdown through `MarkdownContent` (react-markdown + remark-gfm).

`frontend/src/state/agentSessionStorage.ts` extracts sessionStorage read/write for the active session id (browser-session scoped, survives refresh within the same tab).

`frontend/src/app/theme.css` provides:
- Fixed viewport layout: `.app-shell` locked to `100vh`, `.workspace-shell` with sticky topbar.
- Collapsible sidebar: `data-sidebar-collapsed` attribute on `.app-shell` transitions `grid-template-columns` between `268px` and `64px` over 240ms.
- Session list with `overflow-y: auto`, active row highlight (`data-active="true"`), hover menu button reveal, and in-flow context menu so short lists do not require scrolling to reach actions.
- Collapsed brand mark hover/focus behavior: the `N` mark remains fixed-size and reveals the expand icon on interaction.
- Inline rename input, confirm dialog backdrop, conversation context menu (重命名 / 删除 with `.danger`).
- `.chat-panel` fills remaining height, `.chat-thread` scrolls independently.
- `.composer-shell` pinned at bottom with acrylic `backdrop-filter: blur(16px)`. 

`ref/mteam-api-reference.md` is the local source of truth for M-Team endpoints.

### M-Team Search Contract

- `mode`: `normal`, `movie`, `tvshow`, or `music`.
- `sort_by`: `smallest`, `largest`, or `most_seeded`. Omit it for M-Team's default newest-first ordering.
- Do not expose `discount`, pagination, raw sort fields, categories, or local hard filters to the LLM in the current phase.
- Keep the adapter reusable: it returns the full first-page pool of 20 rows. `MTeamSearchTool` applies the product-facing limit of 10.
- Read `seeders`, `leechers`, and `discount` only from each result's `status` object.
- Use release `name` as the candidate display title. Detect resolution from `smallDescr` first, falling back to `name` only when `smallDescr` is absent or empty. Current normalized values include `4320p`, `2160p`, `1080p`, and `720p`.
- Return `discount` as informational candidate metadata; do not use it as a search input.

### Tool Safety: Filter + Gate

Two independent layers, no `ToolPermission` enum:

- **Filter** (`hello_agents/tools/filter.py`): runs **before** tools are sent to the LLM. Narrows the tool list to control context window usage and sub-agent capability scope. Currently allows 15 tools: `current_time`, `mteam_search`, `tavily_search`, `tmdb_search`, `tmdb_details`, `tmdb_discover`, `tmdb_trending`, `member_profile`, `qb_add_torrent`, `qb_list_torrents`, `qb_get_torrent`, `qb_list_categories`, `qb_control_torrent`, `qb_set_global_speed`, `qb_set_torrent_speed`. `Filter(allow=lambda name: ...)` also supported.
- **Gate** (`hello_agents/tools/gate.py`): runs **after** LLM returns a tool call, **before** `tool.run()`. Three gates: deny_rules → confirm_rules → default allow. Works on `ToolCall` (tool_name + params), so decisions can be parameter-aware (`bash("ls")` passes, `bash("sudo rm -rf /")` denied).

Factory functions for common deny rules: `deny_command()`, `deny_paths()`, `deny_outside_workspace()`, `deny_regex()`.

### MCP Framework (`hello_agents/tools/mcp/`)

Generic MCP (Model Context Protocol) client bridge — JSON-RPC 2.0 over STDIO transport, built on `mcp` Python SDK (`modelcontextprotocol/python-sdk`). Framework is ready; currently no MCP servers are configured.

**Key files:**

| File | Purpose |
|------|---------|
| `hello_agents/tools/mcp/client.py` | `McpConnection` (single subprocess lifecycle via `stdio_client` + `ClientSession`), `McpPool` (multi-server, tools aggregation, `call_tool`/`call_tool_sync`) |
| `hello_agents/tools/mcp/bridge.py` | `McpBridgeTool` (MCP tool → HelloAgents `Tool` instance, schema conversion), `register_mcp_tools()` (batch register into `ToolRegistry`) |
| `app/mcp_pool.py` | Module-level `McpPool` singleton, `init_mcp_pool()` / `shutdown_mcp_pool()` / `get_mcp_pool()` |

**Design decisions:**

- **Tool naming:** `mcp_{server_name}_{tool_name}` (e.g. `mcp_myserver_search`).
- **Schema conversion:** MCP `inputSchema` (JSON Schema) → `ToolParameter` list in `McpBridgeTool._parse_schema()`.
- **Filter integration:** `register_mcp_tools()` composes MCP tool names into the existing `Filter` predicate — preserves the original allow list.
- **Gate:** MCP tools default to `ALLOW` (read-only). Gate can be overridden per tool.
- **Sync/async bridge:** `McpPool.call_tool_sync()` → `asyncio.run_coroutine_threadsafe()` bridges from FastAPI thread pool to the main event loop that owns MCP transport streams. `McpBridgeTool.run()` delegates to `call_tool_sync()`.
- **Timeout:** `call_tool_sync()` enforces 30s timeout per call via `future.result(timeout=30.0)`.
- **Graceful degradation:** `get_mcp_pool()` returns `None` when no servers are configured. The runner skips MCP registration when pool is `None`.

**Adding a new MCP server (future):**

1. Create `McpServerConfig` with `command`, `args`, and `env` (API keys, proxy vars).
2. Add to `app/mcp_pool.py` → `init_mcp_pool()` — create `McpConnection`, call `connect()`, add to pool.
3. Optionally define an `allow` list to curate which tools the LLM sees.
4. MCP tools appear in the Agent toolbox alongside built-in tools, with the same Filter/Gate safety.

### Current Experimental Agent Loop

```text
POST /chat/agent
  -> NasClawAgentRunner
  -> load JSON checkpoint
  -> ToolCallingAgent
  -> 15 tools: current_time, mteam_search, tavily_search, tmdb_search,
     tmdb_details, tmdb_discover, tmdb_trending, member_profile,
     qb_add_torrent, qb_list_torrents, qb_get_torrent, qb_list_categories,
     qb_control_torrent, qb_set_global_speed, qb_set_torrent_speed
  -> Filter selects allowed tools; Gate requires approval for action tools
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
- qB Agent tools now cover search (read-only) + download + control + speed management. Read-only tools (`qb_list_*`) execute freely; action tools (`qb_control_torrent`, `qb_set_*_speed`) require user approval. `qb_control_torrent` with `action=delete` is classified as `DESTRUCTIVE` risk.
- `qb_add_torrent` now supports preset categories (电影/电视剧/综艺/动漫/纪录片) and optional `save_path` for custom download directories.
- Session management is now implemented in the frontend sidebar: list/switch/new, localStorage-persisted collapse, rename via `PATCH`, and delete via `DELETE`.
- Remaining frontend improvement: automatic title generation after the first meaningful Agent turn; do not overwrite manually renamed titles.
- Keep future loop ideas in `docs/design/agent-loop-improvement-notes.md`; do not prematurely hard-code them into the framework.
