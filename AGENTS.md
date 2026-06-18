# AGENTS.md

## Project Summary

NasClawBot is a single-user, self-hosted NAS/PT media assistant and an Agent engineering playground.

The current codebase has been intentionally simplified to a gated Agent loop with tool safety, checkpoint persistence, and a React frontend:

```text
/chat/agent -> NasClawAgentRunner + ToolCallingAgent + Filter/Gate + JSON checkpoints
/download -> explicit user action -> qB add paused
/mteam/free-topped -> topped free torrent browser for ratio boosting
/memory/* -> Agent memory inbox, curation, and evolution
```

There is no active workflow runtime, no `/confirm` route, and no legacy `/chat` route. `/chat/agent` is the sole chat interaction path.

## Current Architecture

- `app/api/chat_routes.py`: FastAPI routes for `/chat/agent`, `/download`, `/health`, session management, approvals, settings, and router inclusion for qB, M-Team, and memory.
- `/chat/agent`: the active Agent route. It delegates conversation lifecycle to `NasClawAgentRunner`, registers 20 base tools plus 14 MCP filesystem tools (when active). Read-only tools execute immediately; action tools require user approval unless covered by an active session download authorization grant. Supports multi-turn history, and persists JSON conversation checkpoints under `memory/agent-sessions/{session_id}.json`.
- `GET /chat/agent/sessions`: lists persisted Agent conversation checkpoint summaries. Does not call an LLM or tools.
- `GET /chat/agent/sessions/{session_id}`: returns one persisted Agent conversation checkpoint with renderable message history. Does not call an LLM or tools.
- `POST /chat/agent/sessions/{session_id}/approvals/{approval_id}/approve`: approves a pending Agent tool call. Optional body `{"decision":"approve_once"}` or `{"decision":"approve_and_grant_session"}` controls whether an eligible download-add approval also creates a session grant. For checkpoints with `paused_loop`, the runner validates the paused provider tool call against the approval record, executes the tool, appends the provider `tool` result, and resumes the normal tool loop. Legacy checkpoints without `paused_loop` fall back to the deterministic approval summary path.
- `POST /chat/agent/sessions/{session_id}/approvals/{approval_id}/deny`: denies a pending Agent tool call without executing the tool. For checkpoints with `paused_loop`, the runner resumes the provider tool-call protocol with a `USER_DENIED` tool error and continues the normal tool loop.
- `PATCH /chat/agent/sessions/{session_id}`: updates a session checkpoint. Currently supports `title` in `metadata.title` for session renaming.
- `DELETE /chat/agent/sessions/{session_id}`: deletes a persisted session checkpoint (HTTP 204 on success).
- `GET /settings/download-authorization` and `PUT /settings/download-authorization`: read and write the Settings-backed download authorization policy used by the "本会话内允许" approval action.
- `GET /settings/tmdb-network` and `PUT /settings/tmdb-network`: read and write the Settings-backed TMDB-only proxy override. When enabled, TMDB requests use the configured HTTP/HTTPS proxy and ignore process proxy env vars for those requests; when disabled, HTTPX keeps its normal environment proxy behavior.
- `GET /health/services/tmdb`: checks only TMDB reachability and credentials, used by the Settings TMDB network card so testing the proxy does not probe Tavily, M-Team, or qB.
- `/download`: explicit user action; calls `QBAddTorrentTool` and submits to qBittorrent paused. Supports optional `save_path` and `tag` (media type label). Default download path is configured via `DOWNLOAD_DEFAULT_SAVE_PATH` env var (default `""`); when set, it appears in the system prompt and approval cards.
- `app/agent/runner.py`: application-level Agent runner that loads/saves conversation checkpoints, builds the current `ToolCallingAgent`, restores history, registers MCP tools and skill tools, and extracts route-facing search results/tool calls.
- The Agent system prompt is intentionally compact. Tool-specific usage lives in tool descriptions; the runner appends a dynamic current-date/timezone line from `APP_TIMEZONE` and L1 skill metadata.
- `NasClawAgentRunner.run/approve/deny` are serialized per session inside the current server process so concurrent approval decisions cannot execute the same side effect twice. Cross-process coordination remains a future durable-store concern.
- `ToolCallingLoop`: applies `Filter` before sending tool schemas to the LLM, applies `Gate` before `tool.run()`, and returns `awaiting_approval` with `pending_approvals` for confirm-gated calls. It supports serial approval resume: approve/deny appends the provider `tool` result, then the loop continues with normal tool choice. It still performs one forced final LLM pass with `tool_choice="none"` when `max_steps` is reached.
- `ToolCallingLoop` records token/cache usage from model outputs into checkpoint metadata: `context_usage` (last model request snapshot) and `session_usage` (cumulative Agent session summary, accumulated across turns).
- `ToolObservation`: loop-level envelope for one tool call. It stores `tool_name`, `tool_call_id`, arguments, full structured `ToolResponse`, separate LLM-facing `observation_text`, and gate markers.
- `ContextWindowManager`: runs preflight context checks before LLM calls. NasClawBot uses a 128K configured context window (env `CONTEXT_WINDOW`, default 128000), enables smart compression at 70% context pressure, keeps the latest 4 rounds active, stores a `summary` message for the model, and preserves compressed-away originals in checkpoint `archives`.
- `hello_agents/checkpoints/`: framework-level `ConversationCheckpointStore` protocol plus the current JSON implementation.
- `app/domain/authorization.py`: Settings-backed download authorization policy and session-grant helpers. The policy is limited to `qb_add_torrent` and `qb_add_torrents`, requires paused qB adds, and constrains allowed save path prefixes, per-batch count, and per-session total count. (Categories removed — auth is path-only.)
- `app/services/download_authorization_store.py`: JSON persistence for the download authorization policy under `memory/settings/download-authorization.json`. Session grants live in conversation checkpoint metadata and disappear with the session.
- `app/domain/tmdb_network.py` and `app/services/tmdb_network_store.py`: Settings-backed TMDB network override stored under `memory/settings/tmdb-network.json`. This is scoped to TMDB so qB, M-Team, LLM, Tavily, and local services are not accidentally routed through a user proxy.
- `app/tools/`: per-tool modules (`current_time.py`, `memory_search.py`, `remember_this.py`, `mteam_search.py`, `tavily_search.py`, `member_profile.py`, `qb_add_torrent.py`, `qb_add_torrents.py`, `qb_list_torrents.py`, `qb_get_torrent.py`, `qb_list_tags.py` (active), `qb_list_categories.py` (deprecated, kept for compat), `qb_control_torrent.py`, `qb_set_global_speed.py`, `qb_set_torrent_speed.py`, and TMDB tools), re-exported via `__init__.py`.
- `app/adapters/mteam.py`: M-Team API boundary for search, detail, download token generation, and member profile. Search results include `labelsNew` (Chinese subtitle detection) and `hasChineseSubtitle` (community-submitted flag). `build_search_payload` supports optional `discount` and `hot` parameters; `search_raw()` returns unnormalized items for services that need raw `status` fields.
- `app/services/mteam_free_service.py`: two-pass service for finding ratio-boosting torrents. Pass 1 fetches `discount=FREE`; Pass 2 scans without discount filter to catch `mallSingleFree` (community-funded free). Filters by minimum size and groups results by topping level 1/2.
- `app/api/mteam_routes.py`: `GET /mteam/free-topped?min_size_gb=10&topping_only=true` — returns topped free torrents split by level2/level1 for the ratio-boosting UI tab.
- `app/adapters/qbittorrent.py`: qBittorrent API boundary for paused add, listing, detail, control, and speed limits (global + per-torrent).
- `app/domain/models.py`: shared search result models.

### MCP Filesystem Integration

The project integrates a filesystem MCP server (`@modelcontextprotocol/server-filesystem` via `npx`) for media library organization. Managed by `app/mcp_pool.py` with process-level lifecycle. 14 tools exposed to the Agent (read, write, create_directory, list_directory, move_file, search_files, get_file_info, etc.). Configuration routed through `Settings` (`app/config.py`) supporting process env vars and `.env` fallback: `MCP_FS_ENABLED` (default `true`) and `MCP_FS_ALLOWED_DIRS` (default `""`). Docker deployments use volume mapping with Node.js in the Dockerfile.

### Skill System

The Agent can load domain-specific skill documents on demand via three-tier progressive disclosure (L1 metadata → L2 body → L3 resources):

| File | Purpose |
|------|---------|
| `hello_agents/skills/loader.py` | `SkillLoader` — scans `skills/` directory, parses YAML frontmatter |
| `hello_agents/tools/builtin/skill_tool.py` | `SkillTool` — bridges SkillLoader to ToolRegistry as `skill_load` |
| `skills/renaming-rules/SKILL.md` | Media file naming and directory organization rules |
| `skills/test/SKILL.md` | Verification skill for testing the load mechanism |

Skills auto-register at startup. L1 descriptions are injected into the system prompt. The `skill_load` tool is in the Filter allow list.

### Memory System

The Agent has a persistent markdown-based memory system with automated curation via `memory_search` and `remember_this` tools.

| File | Purpose |
|------|---------|
| `app/services/markdown_memory_store.py` | Markdown file store with flat `user_profile` append plus sectioned `knowledge` append/replace/delete |
| `app/services/curator.py` | LLM-based curator — classifies inbox entries, generates add/modify/delete/skip actions |
| `app/api/memory_routes.py` | `GET /memory/inbox`, `GET /memory/curation`, `POST /memory/curation/apply` |
| `app/domain/memory.py` | `MemoryKind` enum (user/feedback/project/reference) |
| `frontend/src/components/memory/MemoryPanel.tsx` | Curation review UI with per-card approve/reject |

Memory is stored under `memory/agent-memory/`. `user_profile.md` is a flat timestamped bullet log (`- [YYYY-MM-DD] ...`) injected into the Agent system prompt with timestamps stripped; it must not use section headings. `knowledge.md` remains sectioned and is searched on demand by the `memory_search` tool. `MEMORY.md` is the index loaded into context.

### Frontend

- `frontend/`: React + Vite workspace with Chat, Downloads, 刷流 (ratio boosting), Memory, and Settings tabs.
- `AppShell` owns `activeAgentSessionId`, drives session switching, refreshes the session list, and routes rename/delete/new-session actions. Polls `GET /health` every 30s for backend status.
- `ConversationSidebar` is a collapsible multi-session sidebar (64px icon-only, localStorage-persisted), live session list sorted by recent activity, inline rename via `PATCH`, delete with confirm dialog via `DELETE`, "+ 新对话" button.
- `ChatPanel` receives `activeSessionId` and delegates session lifecycle to `useAgentChatSession`. Assistant messages render as Markdown (`react-markdown` + `remark-gfm`). `ApprovalCard` renders batch torrent items and exposes "本会话内允许" only when policy-eligible. The composer context bar shows last-request context pressure plus both last-request and cumulative session cache hit rates.
- `SettingsPanel` includes the TMDB network proxy editor and download authorization policy editor (save path prefixes, per-batch limit, per-session limit).
- `MemoryPanel` renders the memory curation review UI.
- Layout locked to `100vh` with CSS Grid, sidebar transition animation (240ms), acrylic composer backdrop.
- Session id stored in `sessionStorage` via `agentSessionStorage.ts` for tab-scoped persistence.
- `ref/mteam-api-reference.md`: authoritative local M-Team API reference.

### M-Team Search Contract

- Agent-facing `mteam_search` parameters are optional `keyword`, `sort_by`, `imdb`, and `douban`.
- `mteam_search` always uses M-Team `normal` mode. Do not expose `movie`, `tvshow`, or other mode selection to the Agent.
- Use names, aliases, years, season numbers, and episode numbers first; treat IMDb as an auxiliary signal.
- `sort_by` is limited to `smallest`, `largest`, and `most_seeded`. Omitting it preserves M-Team's default newest-first ordering.
- Do not expose `discount`, pagination, raw `sortField`/`sortDirection`, categories, or local hard-filter arguments to the Agent.
- The adapter requests page 1 with 20 rows. `MTeamSearchTool` returns at most the first 10 normalized candidates.
- Read dynamic torrent state only from the response `status` object: `status.seeders`, `status.leechers`, and `status.discount`.
- Candidate display titles prefer the release `name`. Resolution detection prefers `smallDescr`; falls back to `name`. Supported resolutions: `4320p`, `2160p`, `1080p`, `720p`.
- `labelsNew` is the primary source for Chinese subtitle detection; `hasChineseSubtitle` (community-submitted flag) is a secondary signal.
- `discount` is returned as candidate information for user choice, not as an Agent search parameter.

### Tool Safety

- **Filter** (`hello_agents/tools/filter.py`): narrows tool list before sending to LLM. Controls context window and sub-agent capability scope. Currently allows 20 base tools plus dynamically registered MCP tools.
- **Gate** (`hello_agents/tools/gate.py`): three-gate check (deny → confirm → allow) on each `ToolCall` before `tool.run()`. Parameter-aware. Currently confirms: all 5 qB action tools + `mcp_filesystem_write_file` + `mcp_filesystem_edit_file`. Read-only MCP tools and `move_file`/`create_directory` default to ALLOW (directory confinement is the primary safety boundary).
- `ASK_USER` gate results pause the loop with `status="awaiting_approval"` and route-facing `pending_approvals`. The loop saves the assistant tool-call message but does not write a provider `tool` result before approval. `pending_approvals` are persisted for UI/lifecycle recovery; `metadata["paused_loop"]` is persisted for provider protocol resume.
- While a non-expired approval is pending, new user messages are rejected. Expired approvals are moved to resolved metadata before the next Agent turn. The current loop allows one pending approval at a time. If the model emits multiple simultaneous `ASK_USER` calls, the invalid assistant tool-call message is not persisted; the loop feeds model-visible replan feedback and asks for exactly one approval-gated call, or a batch tool when it is the same kind of action.
- `app/agent/approvals.py`: application-level `ApprovalRecord` lifecycle. Pending records live in checkpoint `metadata["pending_approvals"]`; resolved records move to `metadata["approvals"]` with `approved`, `denied`, `failed`, or `expired` status.
- `metadata["authorization_grants"]`: session-scoped download-add grants created by approving with `approve_and_grant_session`. Grants are checked before `Gate` for `qb_add_torrent` and `qb_add_torrents` only.
- Factory functions: `deny_command()`, `deny_paths()`, `deny_outside_workspace()`, `deny_regex()`.

### MCP Framework (`hello_agents/tools/mcp/`)

Generic MCP (Model Context Protocol) client bridge — JSON-RPC 2.0 over STDIO, built on `mcp` Python SDK. Currently running a filesystem MCP server.

| File | Purpose |
|------|---------|
| `hello_agents/tools/mcp/client.py` | `McpServerConfig`, `McpConnection` (subprocess lifecycle via `stdio_client` + `ClientSession`), `McpPool` (multi-server, `call_tool`/`call_tool_sync`) |
| `hello_agents/tools/mcp/bridge.py` | `McpBridgeTool` (MCP tool → `Tool` with schema conversion), `register_mcp_tools()` (batch register + Filter integration) |
| `app/mcp_pool.py` | Module-level `McpPool` singleton — `init_mcp_pool()`, `shutdown_mcp_pool()`, `get_mcp_pool()` |

Key design points:
- **Naming:** `mcp_{server_name}_{tool_name}`.
- **Schema:** MCP `inputSchema` → `ToolParameter` list.
- **Filter:** `register_mcp_tools()` composes MCP tool names into the existing `Filter` predicate.
- **Gate:** MCP tools default to `ALLOW` (read-only); overridable per tool.
- **Sync bridge:** `McpPool.call_tool_sync()` → `asyncio.run_coroutine_threadsafe()` bridges from FastAPI thread pool to the main event loop. 30s timeout.
- **Graceful degradation:** `get_mcp_pool()` returns `None` when no servers are configured; runner skips MCP registration.

### Docker Deployment

`Dockerfile` installs Node.js (for `npx`/MCP) alongside Python dependencies. Container listens on fixed port 18000; `docker-compose.yml` maps `${APP_PORT:-18000}:18000` for host port selection. Bridge networking (no longer host mode). Volumes for NAS media paths, `memory/`, and `skills/` (mounted, not copied). See `.env` for configuration.

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

A `Makefile` and `package.json` provide convenience scripts for build and test.

## Safety Rules

- Never trigger real downloads in tests or demos unless explicitly requested.
- qB download submissions must stay paused by default.
- Never log secrets, API keys, cookies, or full tokenized download URLs.
- Keep M-Team torrent id as the stable external identifier.
- Keep search, detail, and token generation as separate operations.
- Do not download `.torrent` files locally; pass token URLs directly to qB.
- Do not expose destructive file operations to an open Agent loop.

## Direction

Continue evolving the gated Agent loop:

```text
POST   /chat/agent    # Agent loop with 20 base tools + 14 MCP tools + approval gating
GET    /chat/agent/sessions
GET    /chat/agent/sessions/{session_id}
PATCH  /chat/agent/sessions/{session_id}       # rename (metadata.title)
DELETE /chat/agent/sessions/{session_id}       # delete checkpoint
POST   /download      # stable explicit download action
```

The current Agent loop exposes 20 base tools: read-only tools (`current_time`, `memory_search`, `mteam_search`, `tavily_search`, `tmdb_search`, `tmdb_details`, `tmdb_discover`, `tmdb_trending`, `member_profile`, `qb_list_torrents`, `qb_get_torrent`, `qb_list_tags`) execute freely; `remember_this` writes to the memory inbox; action tools (`qb_add_torrent`, `qb_add_torrents`, `qb_control_torrent`, `qb_set_global_speed`, `qb_set_torrent_speed`) require user approval unless covered by an active session grant; `skill_load` loads domain-specific skill documents. Download tools accept optional `tag` for media type labeling. An additional 14 MCP filesystem tools (`mcp_filesystem_*`) are available when the MCP pool is active. All qB submissions are paused by default. Downloads go to an inbox for later manual organization.

Future improvement ideas are intentionally not finalized. Preserve them in `docs/design/agent-loop-improvement-notes.md` rather than overfitting the first loop implementation.
