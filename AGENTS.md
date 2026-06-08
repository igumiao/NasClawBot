# AGENTS.md

## Project Summary

NasClawBot is a single-user, self-hosted NAS/PT media assistant and an Agent engineering playground.

The current codebase has been intentionally reset to a simpler baseline:

```text
chat request -> readonly M-Team search -> search results
explicit download action -> M-Team detail/token -> qB add paused
```

There is no active workflow runtime, no `/confirm` route, and no `confirmation_payload`.

An experimental gated Agent loop now exists alongside the stable baseline:

```text
/chat/agent -> NasClawAgentRunner -> ToolCallingAgent + 9 tools (mteam_search, member_profile, 7 qB tools) -> JSON checkpoint persistence
```

This path is for learning and iteration. `/chat` remains the stable no-LLM baseline.

## Current Architecture

- `app/api/chat_routes.py`: FastAPI routes for `/chat`, `/download`, `/health`, `/`, and qB router inclusion.
- `/chat`: performs a direct `MTeamSearchTool` call and returns `results`. It does not call an LLM and does not persist Agent history.
- `/chat/agent`: experimental Agent route. It delegates conversation lifecycle to `NasClawAgentRunner`, registers 9 tools: `mteam_search`, `member_profile`, and 7 qB tools (`qb_add_torrent`, `qb_list_torrents`, `qb_get_torrent`, `qb_list_categories`, `qb_control_torrent`, `qb_set_global_speed`, `qb_set_torrent_speed`). Read-only tools execute immediately; action tools require user approval. Supports multi-turn history, and persists JSON conversation checkpoints under `memory/agent-sessions/{session_id}.json`.
- `GET /chat/agent/sessions`: lists persisted Agent conversation checkpoint summaries. It does not call an LLM or tools.
- `GET /chat/agent/sessions/{session_id}`: returns one persisted Agent conversation checkpoint with renderable message history. It does not call an LLM or tools.
- `POST /chat/agent/sessions/{session_id}/approvals/{approval_id}/approve`: approves a pending Agent tool call (`qb_add_torrent`, `qb_control_torrent`, `qb_set_global_speed`, or `qb_set_torrent_speed`). For checkpoints with `paused_loop`, the runner validates the paused provider tool call against the approval record, executes the tool, appends the provider `tool` result, resumes the LLM with `tool_choice="none"`, and clears the pending approval. Legacy checkpoints without `paused_loop` fall back to the deterministic approval summary path.
- `POST /chat/agent/sessions/{session_id}/approvals/{approval_id}/deny`: denies a pending Agent tool call without executing the tool. For checkpoints with `paused_loop`, the runner resumes the provider tool-call protocol with a `USER_DENIED` tool error and a no-tools final LLM pass.
- `PATCH /chat/agent/sessions/{session_id}`: updates a session checkpoint. Currently supports `title` in `metadata.title` for session renaming.
- `DELETE /chat/agent/sessions/{session_id}`: deletes a persisted session checkpoint (HTTP 204 on success).
- `app/agent/runner.py`: application-level Agent runner that loads/saves conversation checkpoints, builds the current `ToolCallingAgent`, restores history, and extracts route-facing search results/tool calls.
- `NasClawAgentRunner.run/approve/deny` are serialized per session inside the current server process so concurrent approval decisions cannot execute the same side effect twice. Cross-process coordination remains a future durable-store concern.
- `ToolCallingLoop`: applies `Filter` before sending tool schemas to the LLM, applies `Gate` before `tool.run()`, returns `awaiting_approval` with `pending_approvals` for confirm-gated calls, and performs one forced final LLM pass with `tool_choice="none"` when `max_steps` is reached.
- `ToolObservation`: loop-level envelope for one tool call. It stores `tool_name`, `tool_call_id`, arguments, full structured `ToolResponse`, separate LLM-facing `observation_text`, and gate markers (`gate_result`, `gate_reason`, `approval_id`).
- `ContextWindowManager`: runs preflight context checks before LLM calls. NasClawBot currently uses a conservative 64K configured context window, enables smart compression at 70% context pressure, keeps the latest 4 rounds active, stores a `summary` message for the model, and preserves compressed-away originals in checkpoint `archives`.
- `hello_agents/checkpoints/`: framework-level `ConversationCheckpointStore` protocol plus the current JSON implementation.
- `/download`: explicit user action; calls `QBAddTorrentTool` and submits to qBittorrent paused.
- `app/tools/`: per-tool modules (`mteam_search.py`, `member_profile.py`, `qb_add_torrent.py`, `qb_list_torrents.py`, `qb_get_torrent.py`, `qb_list_categories.py`, `qb_control_torrent.py`, `qb_set_global_speed.py`, `qb_set_torrent_speed.py`), re-exported via `__init__.py`.
- `app/adapters/mteam.py`: M-Team API boundary for search, detail, download token generation, and member profile.
- `app/adapters/qbittorrent.py`: qBittorrent API boundary for paused add, listing, detail, control, and speed limits (global + per-torrent).
- `app/domain/models.py`: shared search result models.
- `frontend/`: React + Vite workspace with Chat, Downloads, and Settings tabs. Key architectural choices:
  - `AppShell` owns `activeAgentSessionId`, drives session switching, refreshes the session list, and routes rename/delete/new-session actions.
  - `ConversationSidebar` is a functional multi-session sidebar: collapsible (64px icon-only, localStorage-persisted), live session list from `GET /chat/agent/sessions` sorted by recent activity, inline rename via `PATCH`, delete with confirm dialog via `DELETE`, "+ 新对话" button, empty state, active-row highlight, hover/focus action menu, and collapsed brand mark that turns into the expand button on hover/focus.
  - `ChatPanel` receives `activeSessionId` from `AppShell` and delegates session lifecycle to `useAgentChatSession`; the hook restores checkpoints, resets state on external session changes, sends Agent messages, handles approvals, guards stale async responses, and emits session activity for sidebar refresh.
  - Chat renders Assistant messages as Markdown (`react-markdown` + `remark-gfm`), `ToolActivityCard`, `SearchResultCard`, `ApprovalCard`, `ReceiptCard`, and `ErrorCard`.
  - Layout locked to `100vh` with CSS Grid: sticky topbar, independently scrollable message area, pinned composer, sidebar transition animation (240ms), and context menu/confirm-dialog styles.
  - `AppShell` polls `GET /health` every 30s for live green/red backend status indicator.
  - Session id stored in `sessionStorage` via `agentSessionStorage.ts` for tab-scoped persistence.
- `ref/mteam-api-reference.md`: authoritative local M-Team API reference.

### M-Team Search Contract

- Agent-facing `mteam_search` parameters are optional `keyword`, `mode`, `sort_by`, `imdb`, and `douban`.
- `mode` is limited to `normal`, `movie`, `tvshow`, and `music`.
- `sort_by` is limited to `smallest`, `largest`, and `most_seeded`. Omitting it preserves M-Team's default newest-first ordering.
- Do not expose `discount`, pagination, raw `sortField`/`sortDirection`, categories, or local hard-filter arguments to the Agent in the current phase.
- The adapter requests page 1 with 20 rows. `MTeamSearchTool` returns at most the first 5 normalized candidates so `/chat`, `/chat/agent`, and the frontend share the same product limit.
- Read dynamic torrent state only from the response `status` object: `status.seeders`, `status.leechers`, and `status.discount`. Top-level fields with those names are not authoritative.
- Candidate display titles prefer the release `name`. Resolution detection prefers `smallDescr`; only when it is absent or empty may detection fall back to `name`. Supported normalized resolutions currently include `4320p`, `2160p`, `1080p`, and `720p`.
- `discount` is returned as candidate information for user choice, but it is not an Agent search parameter.

### Tool Safety

- **Filter** (`hello_agents/tools/filter.py`): narrows tool list before sending to LLM. Controls context window and sub-agent capability scope.
- **Gate** (`hello_agents/tools/gate.py`): three-gate check (deny → confirm → allow) on each `ToolCall` before `tool.run()`. Parameter-aware — `bash("ls")` and `bash("sudo rm -rf /")` can have different outcomes.
- `ASK_USER` gate results pause the loop with `ToolCallingLoopResult.status == "awaiting_approval"` and route-facing `pending_approvals`. The loop saves the assistant tool-call message but does not write a provider `tool` result before approval. `pending_approvals` are persisted for UI/lifecycle recovery; `metadata["paused_loop"]` is persisted for provider protocol resume.
- While a non-expired approval is pending, new user messages are rejected. Expired approvals are moved to resolved metadata before the next Agent turn so the session can continue without executing the tool. The current loop allows one pending approval at a time; multiple simultaneous `ASK_USER` tool calls return a controlled approval conflict.
- `app/agent/approvals.py`: application-level `ApprovalRecord` lifecycle for gated tool calls. Pending records live in checkpoint `metadata["pending_approvals"]`; resolved records move to `metadata["approvals"]` with `approved`, `denied`, `failed`, or `expired` status.
- Factory functions: `deny_command()`, `deny_paths()`, `deny_outside_workspace()`, `deny_regex()`.
- `ToolPermission` and `ToolFilter` have been removed.

### MCP Framework (`hello_agents/tools/mcp/`)

Generic MCP (Model Context Protocol) client bridge — JSON-RPC 2.0 over STDIO, built on `mcp` Python SDK. Framework code is ready and tested; currently no MCP servers are configured.

| File | Purpose |
|------|---------|
| `hello_agents/tools/mcp/client.py` | `McpServerConfig`, `McpToolInfo`, `McpConnection` (subprocess lifecycle via `stdio_client` + `ClientSession`), `McpPool` (multi-server, `call_tool`/`call_tool_sync`) |
| `hello_agents/tools/mcp/bridge.py` | `McpBridgeTool` (MCP tool → `Tool` with schema conversion), `register_mcp_tools()` (batch register + Filter integration) |
| `app/mcp_pool.py` | Module-level `McpPool` singleton — `init_mcp_pool()`, `shutdown_mcp_pool()`, `get_mcp_pool()` |

Key design points:

- **Naming:** `mcp_{server_name}_{tool_name}`.
- **Schema:** MCP `inputSchema` → `ToolParameter` list.
- **Filter:** `register_mcp_tools()` composes MCP tool names into the existing `Filter` predicate, preserving the original allow list.
- **Gate:** MCP tools default to `ALLOW` (read-only); overridable per tool.
- **Sync bridge:** `McpPool.call_tool_sync()` → `asyncio.run_coroutine_threadsafe()` — bridges from FastAPI thread pool to the main event loop that owns MCP transport streams. 30s timeout per call.
- **Graceful degradation:** `get_mcp_pool()` returns `None` when no servers are configured; runner skips MCP registration.

## Removed Architecture

The following are intentionally not part of the active implementation:

- LangGraph workflow wiring.
- HelloAgents workflow runtime migration.
- `HelloAgentWorkflowRunner`.
- `SequentialWorkflow`.
- `WorkflowEnvelope` / runtime session persistence.
- `/confirm`.
- `ConfirmationPayload`.

Historical design and research docs live under `docs/archive/`.

Active design notes:

- `docs/design/helloagents-framework-reference.md`: current HelloAgents framework reference and boundaries.
- `docs/design/agent-loop-improvement-notes.md`: non-final notes for future Agent Loop improvements.

## Dev Commands

Run backend commands from repo root:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/test_chat_api.py tests/test_mteam_adapter.py tests/test_mteam_search_tool.py tests/test_qb_adapter.py tests/test_qb_tools.py -q
.venv/bin/python -m compileall app hello_agents -q
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run frontend commands from `frontend/`:

```bash
npm test
npm run typecheck
npm run build
npm run dev
```

## Safety Rules

- Never trigger real downloads in tests or demos unless explicitly requested.
- qB download submissions must stay paused by default.
- Never log secrets, API keys, cookies, or full tokenized download URLs.
- Keep M-Team torrent id as the stable external identifier.
- Keep search, detail, and token generation as separate operations.
- Do not download `.torrent` files locally; pass token URLs directly to qB.
- Do not expose destructive file operations to an open Agent loop.

## Direction

Continue evolving the gated Agent loop without replacing the stable baseline too early:

```text
POST   /chat          # stable direct search baseline
POST   /chat/agent    # experimental Agent loop with readonly tools and gated download
GET    /chat/agent/sessions
GET    /chat/agent/sessions/{session_id}
PATCH  /chat/agent/sessions/{session_id}       # rename (metadata.title)
DELETE /chat/agent/sessions/{session_id}       # delete checkpoint
```

The current Agent loop exposes 9 tools: read-only tools (`mteam_search`, `member_profile`, `qb_list_torrents`, `qb_get_torrent`, `qb_list_categories`) execute freely; action tools (`qb_add_torrent`, `qb_control_torrent`, `qb_set_global_speed`, `qb_set_torrent_speed`) require user approval. `qb_control_torrent` with `action=delete` is classified as `DESTRUCTIVE` risk. `qb_add_torrent` supports preset categories (电影/电视剧/综艺/动漫/纪录片) and optional `save_path`. Keep `/download` as the stable explicit side-effect path, and keep qB submissions paused by default.

Future improvement ideas are intentionally not finalized. Preserve them in `docs/design/agent-loop-improvement-notes.md` rather than overfitting the first loop implementation.
