# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Project Overview

NasClawBot is a single-user NAS/PT media assistant and Agent engineering playground. The active implementation centers on a gated Agent loop with tool safety, checkpoint persistence, and a React frontend.

```text
/chat/agent -> NasClawAgentRunner + ToolCallingAgent + Filter/Gate + JSON checkpoints
/download -> explicit user action -> qB add paused
/qb/*     -> qB task management
/mteam/free-topped -> topped free torrent browser for ratio boosting
/memory/* -> Agent memory inbox, curation, and evolution
/runtime/* -> Durable background tasks: download watch, organize
```

`/chat/agent` is the sole chat interaction path. There is no legacy `/chat` route and no workflow runtime.

## Important Current Facts

- `GET /mteam/free-topped` returns topped (置顶) free torrents for ratio boosting. Uses two-pass M-Team search (discount=FREE + mallSingleFree community-funded free), grouped by toppingLevel 2/1. Frontend tab "刷流" at `frontend/src/components/free-torrents/FreeTorrentsPanel.tsx`.
- The `/download` endpoint supports optional `save_path` in the request body for custom download directories.
- All Agent downloads go to an inbox directory by default. The download path is configured via `DOWNLOAD_DEFAULT_SAVE_PATH` env var (default `""`); there is no separate JSON store for download defaults. When a non-empty default path is configured, it appears in the system prompt and approval cards.
- `qb_add_torrent` and `qb_add_torrents` do not expose `qb_category` to the LLM; the category is derived server-side. The Agent sees optional `save_path` and `tag` (for media type labeling, e.g. 电影/电视剧/动漫). Use `qb_list_tags` to query existing qB tags.

- There is no `/confirm` route, no `confirmation_payload`, no `HelloAgentWorkflowRunner`, no `SequentialWorkflow`, no active workflow runtime.
- `/chat/agent` is the active Agent route. It delegates to `NasClawAgentRunner`, which uses `ToolCallingAgent` with 20 base tools: `current_time`, `memory_search`, `remember_this`, `mteam_search`, `tavily_search`, 4 TMDB tools (`tmdb_search`, `tmdb_details`, `tmdb_discover`, `tmdb_trending`), `member_profile`, 8 qB tools (`qb_add_torrent`, `qb_add_torrents`, `qb_list_torrents`, `qb_get_torrent`, `qb_list_tags`, `qb_control_torrent`, `qb_set_global_speed`, `qb_set_torrent_speed`), and `skill_load`. An additional 14 MCP filesystem tools are registered dynamically when the MCP pool is active. Read-only tools execute immediately; action tools (`qb_add_torrent`, `qb_add_torrents`, `qb_control_torrent`, `qb_set_*_speed`) require user approval unless covered by an active session download authorization grant. Supports multi-turn history, and persists JSON conversation checkpoints under `memory/agent-sessions/{session_id}.json`.
- `GET /chat/agent/sessions` lists persisted Agent checkpoint summaries without calling an LLM or tools.
- `GET /chat/agent/sessions/{session_id}` returns one persisted Agent checkpoint with renderable message history, also without calling an LLM or tools.
- `POST /chat/agent/sessions/{session_id}/approvals/{approval_id}/approve` approves a pending Agent tool call. Optional body `{"decision":"approve_once"}` or `{"decision":"approve_and_grant_session"}` controls whether an eligible download-add approval also creates a session grant. For checkpoints with `paused_loop`, the runner validates the paused provider tool call against the approval record, executes the tool, appends the provider `tool` result, and resumes the normal tool loop with `tool_choice="auto"`. Legacy checkpoints without `paused_loop` fall back to the deterministic approval summary path.
- `POST /chat/agent/sessions/{session_id}/approvals/{approval_id}/deny` denies a pending Agent tool call without executing the tool. For checkpoints with `paused_loop`, the runner resumes the provider tool-call protocol with a `USER_DENIED` tool error and continues the normal tool loop.
- Model-output token/cache usage is persisted in checkpoint metadata, not read back from trace for UI state: `context_usage` is the last model request snapshot, while `session_usage` is the current Agent session cumulative summary.
- `PATCH /chat/agent/sessions/{session_id}`: updates a session checkpoint. Currently supports `title` in `metadata.title` for session renaming.
- `DELETE /chat/agent/sessions/{session_id}`: deletes a persisted session checkpoint (HTTP 204 on success).
- `GET /settings/download-authorization` and `PUT /settings/download-authorization` read and write the Settings-backed download authorization policy used by the "本会话内允许" approval action.
- `GET /settings/tmdb-network` and `PUT /settings/tmdb-network` read and write the Settings-backed TMDB-only proxy override. When enabled, TMDB requests use the configured HTTP/HTTPS proxy and ignore process proxy env vars for those requests; when disabled, HTTPX keeps its normal environment proxy behavior.
- `GET /health/services/tmdb` checks only TMDB reachability and credentials, used by the Settings TMDB network card so testing the proxy does not probe Tavily, M-Team, or qB.
- The Chat tab uses `/chat/agent` as its active experience path. It renders Agent tool-call summaries, search candidates, and gated download approval cards.

- `hello_agents/checkpoints/` defines the thin `ConversationCheckpointStore` boundary and the current JSON implementation.
- Tool wrappers live in `app/tools/` (per-tool modules, re-exported via `__init__.py`).
- M-Team and qB integration lives behind adapters in `app/adapters/`.
- `mteam_search` exposes only optional `keyword`, `sort_by`, `imdb`, and `douban` to the LLM. It always uses M-Team `normal` mode, requests 20 rows, and returns at most 10 candidates.
- `hello_agents/tools/` provides `Filter` (pre-LLM tool selection) and `Gate` (pre-execution deny/confirm).
- `app/domain/authorization.py` defines the download authorization policy and session grant helpers. The policy applies only to `qb_add_torrent` and `qb_add_torrents`, requires paused qB adds, and constrains allowed save path prefixes, per-batch count, and per-session total count. (Categories were removed — auth is path-only.)
- `app/services/download_authorization_store.py` persists that policy under `memory/settings/download-authorization.json`. Session grants live in checkpoint `metadata["authorization_grants"]` and disappear when the session checkpoint is deleted.
- `app/domain/tmdb_network.py` and `app/services/tmdb_network_store.py` persist a TMDB-only proxy override under `memory/settings/tmdb-network.json`. This stays service-scoped so qB, M-Team, LLM, Tavily, and local services do not inherit the TMDB proxy.
- The runtime task system (`app/runtime/`) provides SQLite-backed durable background tasks with an in-process worker loop. Two handlers are registered: `download_watch` polls qBittorrent for completion with dynamic ETA-based intervals; `organize_download` runs an `OrganizeWorkerAgent` to move files into the media library.
- `app/services/download_coordinator.py` orchestrates download submission with post-download follow-up: prepare an INITIALIZING task, submit to qB paused, then activate on success or fail on error. Follow-up modes: `auto_organize` (spawns organize task), `notify_only` (emits event), `none`.
- `GET /tasks`, `GET /tasks/{id}`, `POST /tasks/{id}/cancel`, `GET /task-events`, and `POST /task-events/{id}/acknowledge` expose the runtime task system for listing, cancelling, and acknowledging completion events.
- `GET /settings/organization-automation` and `PUT /settings/organization-automation` read/write the `OrganizationAutomationPolicy`: `enabled`, `default_after_download` (auto_organize/notify_only), `allowed_source_path_prefixes`, `destination_root`. `allow_delete` and `allow_overwrite` are forced `False` by Pydantic validator.
- The organize worker (`app/agent/organize_worker.py`) runs a separate `ToolCallingAgent` per download with 10 tools (skill_load + 2 TMDB + 7 MCP filesystem) and a dynamic Gate that denies `create_directory`/`move_file` until `skill_load("renaming-rules")` succeeds. Uses `skills_auto_register=False` to prevent overwriting the wrapper.
- `current_agent_session_id` ContextVar in `app/agent/runner.py` is set at each Agent turn start so that `qb_add_torrent`/`qb_add_torrents` pass the correct `source_session_id` to the coordinator, enabling task-event-to-session matching in the frontend.

### MCP Filesystem Integration

The project integrates a filesystem MCP server (`@modelcontextprotocol/server-filesystem` via `npx`) for media library organization. Configuration:

| Env Var | Default | Purpose |
|---------|---------|---------|
| `MCP_FS_ENABLED` | `true` | Set to `false`/`0`/`no` to disable — routed through `Settings.mcp_fs_enabled` |
| `MCP_FS_ALLOWED_DIRS` | `""` | Comma-separated allowed directories — routed through `Settings.mcp_fs_allowed_dirs` |

The MCP pool is managed by `app/mcp_pool.py` with process-level lifecycle (startup/shutdown via FastAPI lifespan). Configuration is routed through `Settings` (`app/config.py`) supporting process env vars and `.env` fallback: `mcp_fs_enabled` (default `true`) and `mcp_fs_allowed_dirs` (default `""`). 14 tools are exposed to the Agent: `read_file`, `read_text_file`, `read_media_file`, `read_multiple_files`, `write_file`, `edit_file`, `create_directory`, `list_directory`, `list_directory_with_sizes`, `directory_tree`, `move_file`, `search_files`, `get_file_info`, `list_allowed_directories`.

MCP tools are named `mcp_filesystem_{tool_name}` and are registered dynamically via `register_mcp_tools()`. They default to `ALLOW` at the Gate layer (no approval required). The bridge layer (`McpBridgeTool`) converts MCP JSON Schema input schemas to hello_agents `ToolParameter` lists.

Docker deployments use volume mapping (`-v /vol1/1000/影视:/影视`) with `MCP_FS_ALLOWED_DIRS=/影视`. The Dockerfile includes Node.js for `npx`.

### Skill System

The Agent can load domain-specific skill documents on demand via a three-tier progressive disclosure system:

| Level | What | When |
|-------|------|------|
| L1 | Name + description (~100 words) | Always in system prompt |
| L2 | Full SKILL.md body | When Agent calls `skill_load("name")` |
| L3 | Bundled resources | As referenced by L2 |

Key files:

| File | Purpose |
|------|---------|
| `hello_agents/skills/loader.py` | `SkillLoader` — scans `skills/` directory, parses YAML frontmatter, provides L1 descriptions and L2 body loading |
| `hello_agents/tools/builtin/skill_tool.py` | `SkillTool` — bridges SkillLoader to Agent ToolRegistry as `skill_load` |
| `skills/renaming-rules/SKILL.md` | Media file naming and directory organization rules |
| `skills/test/SKILL.md` | Verification skill for testing the load mechanism |

Skills are auto-registered at runner startup. L1 metadata is injected into the system prompt under a "可用技能 (Skills)" section. The `skill_load` tool is included in the Filter allow list.

### Memory System

The Agent has a persistent markdown-based memory system with automated curation:

| Tool | Purpose |
|------|---------|
| `memory_search` | Search agent memory (read-only, executes freely) |
| `remember_this` | Submit a fact/experience for curation (writes to inbox) |

Key files:

| File | Purpose |
|------|---------|
| `app/services/markdown_memory_store.py` | Markdown file store with flat `user_profile` append plus sectioned `knowledge` append, replace, and delete operations. Thread-safe via file locking. |
| `app/services/curator.py` | LLM-based curator — classifies inbox entries, generates `add`/`modify`/`delete`/`skip` actions, respects evolution rules. |
| `app/api/memory_routes.py` | `GET /memory/inbox`, `GET /memory/curation`, `POST /memory/curation/apply` |
| `app/domain/memory.py` | `MemoryKind` enum (user/feedback/project/reference) |
| `frontend/src/components/memory/MemoryPanel.tsx` | Frontend panel for reviewing curated batches, approving/rejecting per-card |

Memory is stored under `memory/agent-memory/` as markdown files. `user_profile.md` is a flat timestamped bullet log (`- [YYYY-MM-DD] ...`) injected into the Agent system prompt with timestamps stripped; it must not use section headings. `knowledge.md` remains sectioned and is searched on demand by `memory_search`. `MEMORY.md` is the index loaded into context. The curator runs with date/time injection for time-aware evolution.

### Runtime Task System

New subsystem under `app/runtime/` that manages durable background tasks for post-download automation:

**Key files:**

| File | Purpose |
|------|---------|
| `app/runtime/store.py` | `RuntimeTaskStore` — SQLite-backed persistence with `BEGIN IMMEDIATE` for atomic task claiming. Tables: `runtime_tasks`, `runtime_task_runs`, `runtime_task_events`. 18+ methods including `prepare`, `activate`, `enqueue`, `claim_due`, `finish`, `cancel`, `get`, `list_tasks`, `get_task_with_runs`, `purge_terminal_tasks`, event lifecycle. |
| `app/runtime/scheduler.py` | `TaskScheduler` — external-facing API over the store. Provides `prepare`, `activate`, `enqueue`, `fail_initialization`, `cancel`, `get`, `list_tasks`, `get_task_with_runs`. Wraps internal `payload_json`/`error_json`/`result_json` as plain dicts. |
| `app/runtime/worker.py` | `TaskWorker` — in-process async loop that claims due tasks and dispatches to registered handlers. `TaskWorkerConfig` with `tick_seconds` (default 2), `lease_seconds` (default 120), `max_concurrency` (default 4), `per_kind_semaphores`. Auto-purges terminal tasks older than 60s each tick. |
| `app/runtime/registry.py` | `HandlerRegistry` — maps task kind strings to async handler callables: `Handler = Callable[[RuntimeTask, RuntimeTaskStore, TaskScheduler], Awaitable[TaskOutcome]]`. |
| `app/runtime/handlers/download_watch.py` | `DownloadWatchHandler` — polls qBittorrent for progress via correlation tags (`nasclaw-task-{id}`). Hash resolution on first poll, then periodic progress checks with dynamic polling interval based on speed delta (ETA/2, bounded 30s–600s). On completion, spawns `organize_download` child task or emits `download_completed` event. |
| `app/runtime/handlers/organize_download.py` | `OrganizeDownloadHandler` — runs `OrganizeWorkerAgent` via `run_in_executor` for file organization. On success emits `organize_completed` event. Configurable `destination_root`, `enabled` flag, `worker_max_steps`. |
| `app/task_runtime.py` | `TaskRuntime` — composition root owning store, scheduler, registry, and worker. Factory functions: `create_task_runtime()`, `setup_download_watch_handler()`, `setup_organize_download_handler()`. Reconcilies stale INITIALIZING tasks at startup. |
| `app/domain/runtime_tasks.py` | Domain models — `TaskStatus` enum (`INITIALIZING`→`QUEUED`→`RUNNING`→`WAITING`→`SUCCEEDED`/`FAILED`/`CANCELLED`), `RuntimeTask`, `WorkerRun`, `TaskEvent`, `TaskOutcome` discriminated union (`Complete`/`Reschedule`/`Fail`/`Spawn`), `FilesystemOperationRecord`. `max_attempts` default is 8. |
| `app/runtime/organize_journal.py` | `OperationJournal` — thread-safe append-only journal for idempotent retry of filesystem operations. Implemented but not yet wired — reserved for V2. |

**Configuration (env vars):**

| Env Var | Default | Purpose |
|---------|---------|---------|
| `TASK_WORKER_TICK_SECONDS` | 2 | Worker claim interval |
| `DOWNLOAD_WATCH_POLL_SECONDS` | 30 | Default download poll interval (actual uses dynamic ETA-based) |
| `DOWNLOAD_WATCH_ERROR_BACKOFF_MAX_SECONDS` | 600 | Max backoff for qB errors |
| `TASK_LEASE_SECONDS` | 120 | Task lease duration |
| `TASK_WORKER_CONCURRENCY` | 4 | Global handler concurrency |
| `DOWNLOAD_WATCH_CONCURRENCY` | 4 | Per-kind download_watch concurrency |
| `ORGANIZE_WORKER_CONCURRENCY` | 1 | Per-kind organize_download concurrency (serial) |
| `TASK_PURGE_MAX_AGE_SECONDS` | 300 | Max age for terminal tasks before purge (5 min default) |
| `EVENT_CONSUMED_PURGE_SECONDS` | 3600 | Max age for consumed events (acknowledged + injected) (1h default) |
| `EVENT_MAX_AGE_SECONDS` | 604800 | Absolute max age for any event before purge (7d default) |
| `QB_PATH_MAPPING` | `""` | Windows→WSL path prefix translation, e.g. `D:\->/mnt/d/` |

**Design decisions:**

- Download watch polls with dynamic intervals: computes speed from progress delta between two polls, estimates ETA, polls at half-ETA (clamped to 30s–600s). Stalled progress falls back to 60s.
- Terminal tasks auto-purged after `TASK_PURGE_MAX_AGE_SECONDS` (default 300s, 5 min). Purge runs each worker tick and deletes tasks + runs only — events are managed independently.
- Task events are decoupled from task lifecycle: no FK on `runtime_task_events.task_id`, so events outlive their parent tasks. Two-tier event purge:
  - **Consumed events** (both `acknowledged_at` and `injected_at` set, both older than `EVENT_CONSUMED_PURGE_SECONDS`, default 3600s = 1h) — short retention after user + Agent have seen the event.
  - **Absolute max age** (`EVENT_MAX_AGE_SECONDS`, default 604800s = 7d) — backstop preventing unbounded table growth; deletes events older than this regardless of acknowledgement/injection status.
- `max_attempts` (renamed `max_failure_attempts`) is 8. Failed tasks retry with exponential backoff (30s, 60s, 120s… capped at 3600s).
- `QB_PATH_MAPPING` translates Windows backslash paths to Linux forward-slash paths (e.g. `D:\影视\foo` → `/mnt/d/影视/foo`). Only needed for cross-OS deployments (Windows qB + WSL MCP).
- Request logging middleware in `app/main.py` skips `/task-events` and `/health` to reduce log noise from polling.

### Download Coordination

`app/services/download_coordinator.py` (`DownloadCoordinator`) orchestrates the submission sequence: resolve follow-up mode → validate policy → prepare INITIALIZING task → submit to qB → activate or fail. Supports `submit()` for single torrents and `submit_many()` for batches. In `auto_organize` mode, the policy's immutable authorization snapshot is captured in the task payload. In `notify_only` mode, a `download_completed` event is emitted for frontend display.

`app/services/download_submission.py` (`DownloadSubmission`) extracts the M-Team/qB submission logic: fetch details, generate download token, add to qB paused, auto-download community subtitles. Returns a receipt dict with `resource_title`, `external_id`, `qb_hash`, `subtitle_count`, and `error`.

`app/domain/downloads.py` defines `DownloadSubmissionRequest` (torrent_id, qb_category, save_path, tag, after_download), `ResolvedFollowUp` (mode, source, authorization_snapshot), `DownloadSubmissionResult` (receipt_id, watch_task_id, status, resolved_follow_up), and `BatchDownloadSubmissionResult`.

### Organize Worker Agent

`app/agent/organize_worker.py` (`OrganizeWorkerAgent`) is a single-use `ToolCallingAgent` per organization run. Key characteristics:

- **Constrained tools:** 10 tools — `skill_load` + `tmdb_search` + `tmdb_details` + 7 MCP filesystem tools (`list_directory`, `directory_tree`, `read_text_file`, `get_file_info`, `search_files`, `create_directory`, `move_file`).
- **Dynamic Gate:** `_SkillGateState` flag — denies `create_directory`/`move_file` until `skill_load("renaming-rules")` returns success. `_OrganizeSkillTool` wraps `SkillTool` to toggle this flag when the skill is loaded.
- **`skills_auto_register=False`** in `Config` prevents the auto-registered `SkillTool` from overwriting the `_OrganizeSkillTool` wrapper.
- **System prompt (Chinese):** six-step workflow — load skill → scan → identify → create directories → move files → verify. Bans write operations before skill is loaded.
- **Result extraction:** post-run, parses tool observations to count `move_file` successes, detect destination, and collect issues.
- **Synchronous execution** via `loop.run_in_executor()` to avoid blocking the async event loop. Context window capped at `min(settings.context_window, 64000)`.

### Organization Automation Policy

`app/domain/organization.py` (`OrganizationAutomationPolicy`): `enabled` (default `False`), `default_after_download` (`"auto_organize"` / `"notify_only"`), `allowed_source_path_prefixes` (list), `destination_root` (string). `allow_delete` and `allow_overwrite` are forced `False` by a Pydantic validator.

`app/services/organization_policy_store.py` persists the policy under `memory/settings/organization-automation.json`.

### Task Routes API

In `app/api/task_routes.py`:

| Route | Method | Purpose |
|-------|--------|---------|
| `GET /tasks` | List tasks with optional filters (`source_session_id`, `status`, `kind`, `limit`) |
| `GET /tasks/{id}` | Task detail with runs (excludes payload/result/error) |
| `POST /tasks/{id}/cancel` | Cancel a task (idempotent) |
| `GET /task-events` | List events with filters (`source_session_id`, `acknowledged`, `after`, `limit`) |
| `POST /task-events/{id}/acknowledge` | Acknowledge an event |
| `GET /settings/organization-automation` | Read organization policy |
| `PUT /settings/organization-automation` | Write organization policy (forces allow_delete/allow_overwrite to False) |

The `POST /download` endpoint's response now includes `watch_task_id` when a download-watch task is created, enabling the frontend to correlate the download with its background task.

Task events flow: `download_completed` (from `DownloadWatchHandler`) → injected into Agent system prompt on next turn via `_format_background_events` in the runner → `organize_completed` (from `OrganizeDownloadHandler`) → also injected. The frontend polls unacknowledged events and renders `TaskEventCard` components.

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

There is no formal Python formatter configured yet. A `Makefile` and `package.json` provide convenience scripts for build and test.

## Architecture Notes

`app/api/chat_routes.py` owns the current interaction surface:

- `POST /chat/agent`: validates the request, delegates to `NasClawAgentRunner`, and returns a `ChatResponse`.
- `GET /chat/agent/sessions`: lists persisted Agent conversation summaries.
- `GET /chat/agent/sessions/{session_id}`: loads one persisted Agent conversation checkpoint.
- `POST /chat/agent/sessions/{session_id}/approvals/{approval_id}/approve`: approves and executes a pending Agent action. With `paused_loop`, the runner appends the real provider `tool` result and resumes the normal tool loop; legacy checkpoints fall back to the deterministic summary path. Optional `decision="approve_and_grant_session"` creates a session grant when eligible.
- `POST /chat/agent/sessions/{session_id}/approvals/{approval_id}/deny`: cancels a pending Agent action. With `paused_loop`, the runner resumes with a `USER_DENIED` tool error and continues the normal tool loop.
- `PATCH /chat/agent/sessions/{session_id}`: updates session metadata (currently `title` in `metadata.title`).
- `DELETE /chat/agent/sessions/{session_id}`: deletes a persisted checkpoint, returns 204 on success.
- `POST /download`: accepts a torrent id, calls `QBAddTorrentTool`, submits to qB paused, and returns a receipt. Supports optional `save_path`.
- `GET /settings/download-authorization` / `PUT /settings/download-authorization`: load and persist the session authorization policy for download-add tools.
- `GET /settings/tmdb-network` / `PUT /settings/tmdb-network`: load and persist the TMDB-only HTTP/HTTPS proxy override.
- `GET /health/services/tmdb`: run a TMDB-only health check for the Settings proxy test button.
- qB management routes are included from `app/api/qb_routes.py`.
- Memory routes are included from `app/api/memory_routes.py`.
- Task routes are included from `app/api/task_routes.py`: `GET /tasks`, `GET /tasks/{id}`, `POST /tasks/{id}/cancel`, `GET /task-events`, `POST /task-events/{id}/acknowledge`, `GET /settings/organization-automation`, `PUT /settings/organization-automation`.
- `POST /download` response now includes `watch_task_id` when a download-watch task is created for the submitted torrent.

`app/agent/runner.py` owns the Agent conversation lifecycle: load checkpoint, build the current tool-calling agent, restore history, run one turn, save checkpoint, extract route-facing search results/tool calls. Also registers MCP tools and skill tools at startup.

The Agent system prompt is intentionally compact: cross-tool search strategy, side-effect safety, and output shape stay in the prompt, while tool-specific usage belongs in tool descriptions. The runner appends a dynamic current-date/timezone line from `APP_TIMEZONE` and L1 skill metadata.

`NasClawAgentRunner.run/approve/deny` are serialized per session within the current server process. This prevents concurrent approval decisions from executing the same download twice; multi-process coordination still requires a future transactional durable store.
`current_agent_session_id` ContextVar in `app/agent/runner.py` is set at the start of each `runner.run()` so that download tools pass the correct `source_session_id` to the coordinator for task-event-to-session matching.
`NasClawAgentRunner.run` also loads unacknowledged background task events before each turn via `get_events_for_session(session_id, uninjected_only=True)`, formats them into the system prompt, and marks them injected after saving the checkpoint.

`ToolCallingLoop` applies `Filter` before sending tool schemas to the LLM and applies `Gate` before `tool.run()`. `DENY` produces a permission-denied observation without executing the tool. `ASK_USER` pauses the loop with `status="awaiting_approval"` and route-facing `pending_approvals`; it saves the assistant tool-call message but does not write a provider `tool` result before approval. NasClawBot persists `pending_approvals` for UI/lifecycle recovery and `metadata["paused_loop"]` for provider protocol resume.

While a session has a non-expired pending approval, `/chat/agent` rejects new user messages. Before a new turn, the runner resolves expired approvals without executing the tool, removes the unresolved provider assistant tool-call message, and allows the conversation to continue. The current loop supports one pending approval at a time. If the model emits multiple simultaneous `ASK_USER` calls, the invalid assistant tool-call message is not persisted; the loop feeds model-visible replan feedback and asks for exactly one approval-gated call, or a batch tool when it is the same kind of action.

`app/agent/approvals.py` defines the application-level approval lifecycle. Pending records include `session_id`, `expires_at`, `risk`, `decision`, `result`, and `error`; resolved records move from checkpoint `metadata["pending_approvals"]` to `metadata["approvals"]`.

`metadata["authorization_grants"]` stores session-scoped download-add grants created by approving with `approve_and_grant_session`. Grants are checked before `Gate` for `qb_add_torrent` and `qb_add_torrents` only; other ASK_USER tools are never covered by this policy.

`ToolCallingLoop` performs one forced final LLM pass with `tool_choice="none"` when `max_steps` is reached. That pass summarizes current observations without executing more tools; if it fails or returns tool calls, the loop falls back to the controlled max-steps message.

`ToolObservation` is the loop-level envelope for one tool call. It stores `tool_name`, `tool_call_id`, arguments, full structured `ToolResponse`, separate LLM-facing `observation_text`, and gate markers.

`ContextWindowManager` performs preflight context checks before LLM calls. NasClawBot currently uses a 128K configured context window (env `CONTEXT_WINDOW`, default 128000), enables smart compression at 70% context pressure, keeps the latest 4 rounds active, writes a `summary` message into active history, and preserves compressed-away originals in checkpoint `archives`.

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
- Session list from `GET /chat/agent/sessions`, sorted by `saved_at` descending.
- Click a session → lifts `activeAgentSessionId` in AppShell → `useAgentChatSession` resets local state and restores that checkpoint.
- "+ 新对话" button switches to a blank new-conversation state.
- Hover reveals `⋯` menu button per session row: 重命名 (inline PATCH) + 删除 (confirm dialog, DELETE).

`frontend/src/components/chat/ChatPanel.tsx` accepts `activeSessionId` from AppShell and delegates session behavior to `useAgentChatSession`. Assistant messages render as Markdown through `MarkdownContent` (react-markdown + remark-gfm). `ApprovalCard` renders batch torrent items and exposes "本会话内允许" only when the backend marks the approval as policy-eligible. `TaskEventCard` (`frontend/src/components/chat/TaskEventCard.tsx`) renders background task events (download_completed, organize_completed) with severity-based styling (green/gray/yellow/red) and an acknowledge button. The composer context bar shows last-request context pressure plus both last-request and cumulative session cache hit rates.

`frontend/src/components/settings/SettingsPanel.tsx` includes the TMDB network proxy editor, the download authorization policy editor (save path prefixes, per-batch limit, per-session limit), and the organization automation section (enabled toggle, after_download mode selector, source path prefixes textarea, destination root input, safety lock display for permanently disabled delete/overwrite).

`frontend/src/components/memory/MemoryPanel.tsx` renders the memory curation review UI with approve/reject per-card actions and visibility toggling.

`frontend/src/state/agentSessionStorage.ts` extracts sessionStorage read/write for the active session id (tab-scoped persistence).
`frontend/src/state/taskEventsState.ts` provides `useTaskEvents` hook — polls `GET /task-events` every 15s for unacknowledged events, exposes `acknowledge`/`acknowledgeAll`.
`frontend/src/api/tasksApi.ts` provides `listTasks`, `getTaskDetail`, `cancelTask`, `listTaskEvents`, `acknowledgeEvent`.

`frontend/src/app/theme.css` provides:
- Fixed viewport layout: `.app-shell` locked to `100vh`, `.workspace-shell` with sticky topbar.
- Collapsible sidebar: `data-sidebar-collapsed` attribute on `.app-shell` transitions `grid-template-columns` between `268px` and `64px` over 240ms.
- Session list with active row highlight, hover menu button reveal, and in-flow context menu.
- Collapsed brand mark hover/focus behavior for expand control.
- Inline rename input, confirm dialog backdrop, conversation context menu.
- `.chat-panel` fills remaining height, `.chat-thread` scrolls independently.
- `.composer-shell` pinned at bottom with acrylic `backdrop-filter: blur(16px)`.

`ref/mteam-api-reference.md` is the local source of truth for M-Team endpoints.

### M-Team Search Contract

- `sort_by`: `smallest`, `largest`, or `most_seeded`. Omit it for M-Team's default newest-first ordering.
- Do not expose `discount`, pagination, raw sort fields, categories, or local hard filters to the LLM.
- The adapter requests page 1 with 20 rows. `MTeamSearchTool` applies the product-facing limit of 10.
- Read `seeders`, `leechers`, and `discount` only from each result's `status` object.
- Use release `name` as the candidate display title. Detect resolution from `smallDescr` first, falling back to `name` only when `smallDescr` is absent or empty. Current normalized values include `4320p`, `2160p`, `1080p`, and `720p`.
- `labelsNew` is the primary source for Chinese subtitle detection; `hasChineseSubtitle` (community-submitted flag) serves as a secondary signal.
- Return `discount` as informational candidate metadata; do not use it as a search input.

### Tool Safety: Filter + Gate

Two independent layers, no `ToolPermission` enum:

- **Filter** (`hello_agents/tools/filter.py`): runs **before** tools are sent to the LLM. Narrows the tool list to control context window usage and sub-agent capability scope. Currently allows 20 base tools plus any dynamically registered MCP tools.
- **Gate** (`hello_agents/tools/gate.py`): runs **after** LLM returns a tool call, **before** `tool.run()`. Three gates: deny_rules → confirm_rules → default allow. Works on `ToolCall` (tool_name + params), so decisions can be parameter-aware. Currently confirms: all 5 qB action tools, plus `mcp_filesystem_write_file` and `mcp_filesystem_edit_file`. Read-only MCP tools and `mcp_filesystem_move_file`/`create_directory` default to ALLOW (directory confinement is the primary safety boundary for organization operations).

Factory functions for common deny rules: `deny_command()`, `deny_paths()`, `deny_outside_workspace()`, `deny_regex()`.

### MCP Framework (`hello_agents/tools/mcp/`)

Generic MCP (Model Context Protocol) client bridge — JSON-RPC 2.0 over STDIO transport, built on `mcp` Python SDK. Currently running a filesystem MCP server.

**Key files:**

| File | Purpose |
|------|---------|
| `hello_agents/tools/mcp/client.py` | `McpConnection` (single subprocess lifecycle via `stdio_client` + `ClientSession`), `McpPool` (multi-server, tools aggregation, `call_tool`/`call_tool_sync`) |
| `hello_agents/tools/mcp/bridge.py` | `McpBridgeTool` (MCP tool → HelloAgents `Tool` instance, schema conversion), `register_mcp_tools()` (batch register into `ToolRegistry`) |
| `app/mcp_pool.py` | Module-level `McpPool` singleton, `init_mcp_pool()` / `shutdown_mcp_pool()` / `get_mcp_pool()` |

**Design decisions:**

- **Tool naming:** `mcp_{server_name}_{tool_name}` (e.g. `mcp_filesystem_read_file`).
- **Schema conversion:** MCP `inputSchema` (JSON Schema) → `ToolParameter` list in `McpBridgeTool._parse_schema()`.
- **Filter integration:** `register_mcp_tools()` composes MCP tool names into the existing `Filter` predicate — preserves the original allow list.
- **Gate:** MCP tools default to `ALLOW` (read-only). Gate can be overridden per tool.
- **Sync/async bridge:** `McpPool.call_tool_sync()` → `asyncio.run_coroutine_threadsafe()` bridges from FastAPI thread pool to the main event loop that owns MCP transport streams. `McpBridgeTool.run()` delegates to `call_tool_sync()`.
- **Timeout:** `call_tool_sync()` enforces 30s timeout per call via `future.result(timeout=30.0)`.
- **Graceful degradation:** `get_mcp_pool()` returns `None` when no servers are configured. The runner skips MCP registration when pool is `None`.

### Docker Deployment

`Dockerfile` installs Node.js (for `npx`/MCP) alongside Python dependencies. Container listens on fixed port 18000; `docker-compose.yml` maps `${APP_PORT:-18000}:18000` so users can choose the host port. Bridge networking (no longer host mode). Volume mapping for NAS media paths and `skills/` directory (mounted, not copied). See `.env` for configuration.

### Current Agent Loop

```text
POST /chat/agent
  -> NasClawAgentRunner
  -> load JSON checkpoint
  -> inject background task events into system prompt
  -> ToolCallingAgent
  -> 20 base tools: current_time, memory_search, remember_this, mteam_search,
     tavily_search, tmdb_search, tmdb_details, tmdb_discover, tmdb_trending,
     member_profile, qb_add_torrent, qb_add_torrents, qb_list_torrents,
     qb_get_torrent, qb_list_tags, qb_control_torrent,
     qb_set_global_speed, qb_set_torrent_speed, skill_load
  + 14 MCP filesystem tools (when MCP pool active)
  -> Filter selects allowed tools; Gate requires approval for action tools
  -> tool result back to LLM
  -> mark task events as injected
  -> save JSON checkpoint
```

## Safety Rules

- Never trigger real downloads in tests/demos unless explicitly requested.
- Download submissions must remain paused by default.
- Never log secrets or full tokenized download URLs.
- Keep search, detail, and token generation separate.
- Do not download `.torrent` files locally.
- Do not expose destructive file operations to an open Agent loop.

## Next Direction

Continue evolving the gated Agent loop.

- Keep `qb_add_torrent` and `qb_add_torrents` behind approval gating unless covered by an active session download authorization grant.
- Keep `/download` as the stable explicit user action.
- qB Agent tools cover search (read-only) + download + control + speed management. Read-only tools execute freely; action tools require user approval. `qb_control_torrent` with `action=delete` is classified as `DESTRUCTIVE` risk.
- MCP filesystem tools are available for media library organization (renaming, moving, directory creation). Access is limited to configured directories via `MCP_FS_ALLOWED_DIRS`.
- "本会话内允许" is limited to download-add tools and the Settings policy boundary: enabled flag, allowed save path prefixes, max items per batch, max total items per session, and `paused_required=true`.
- Session management in the frontend sidebar: list/switch/new, localStorage-persisted collapse, rename via `PATCH`, delete via `DELETE`.
- The skill system allows domain-specific rules to be loaded on demand. Extend with new skills as needed.
- The memory system supports persistent Agent knowledge with automated curation and evolution.
- Remaining frontend improvement: automatic title generation after the first meaningful Agent turn; do not overwrite manually renamed titles.
- Keep future loop ideas in `docs/design/agent-loop-improvement-notes.md`; do not prematurely hard-code them into the framework.
- The runtime task system enables post-download automation: download-watch polls qB for completion, organize-worker moves files into the media library. Extend with new task kinds and handlers as needed.
- The organize worker agent is a constrained single-use ToolCallingAgent per run. Future improvements could include parallel file operations, dry-run mode, and V2 reconciliation via the OperationJournal.
- Task events are injected into the Agent system prompt on each turn so the LLM is aware of background activity. Remaining: richer event rendering in the frontend (progress updates, retry status), and manual retrigger of failed organize tasks.
- Organization automation policy is path-prefix based and conservative (delete/overwrite permanently disabled). The `allow_delete` and `allow_overwrite` safety locks should remain forced `False`.
