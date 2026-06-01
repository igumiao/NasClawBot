# AGENTS.md

## Project Summary

NasClawBot is a single-user, self-hosted NAS/PT media assistant and an Agent engineering playground.

The current codebase has been intentionally reset to a simpler baseline:

```text
chat request -> readonly M-Team search -> search results
explicit download action -> M-Team detail/token -> qB add paused
```

There is no active workflow runtime, no `/confirm` route, no `confirmation_payload`, and no server-side Agent session state. The next architectural step is to build a minimal context-aware Agent loop from this simpler base.

## Current Architecture

- `app/api/chat_routes.py`: FastAPI routes for `/chat`, `/download`, `/health`, `/`, and qB router inclusion.
- `/chat`: performs a direct `MTeamSearchTool` call and returns `results`. No Agent loop yet.
- `/download`: explicit user action; calls `QBAddTorrentTool` and submits to qBittorrent paused.
- `app/tools.py`: tool wrappers over existing adapters (MTeamSearchTool, QBAddTorrentTool).
- `app/adapters/mteam.py`: M-Team API boundary for search, detail, and download token generation.
- `app/adapters/qbittorrent.py`: qBittorrent API boundary for paused add, listing, detail, and control.
- `app/domain/models.py`: shared search result models.
- `frontend/`: React + Vite workspace with Chat, Downloads, and Settings tabs.
- `ref/mteam-api-reference.md`: authoritative local M-Team API reference.

### Tool Safety

- **Filter** (`hello_agents/tools/filter.py`): narrows tool list before sending to LLM. Controls context window and sub-agent capability scope.
- **Gate** (`hello_agents/tools/gate.py`): three-gate check (deny → confirm → allow) on each `ToolCall` before `tool.run()`. Parameter-aware — `bash("ls")` and `bash("sudo rm -rf /")` can have different outcomes.
- Factory functions: `deny_command()`, `deny_paths()`, `deny_outside_workspace()`, `deny_regex()`.
- `ToolPermission` and `ToolFilter` have been removed.

## Removed Architecture

The following are intentionally not part of the active implementation:

- LangGraph workflow wiring.
- HelloAgents workflow runtime migration.
- `HelloAgentWorkflowRunner`.
- `SequentialWorkflow`.
- `WorkflowEnvelope` / runtime session persistence.
- `/confirm`.
- `ConfirmationPayload`.
- Candidate approval card flow.

Historical design and research docs live under `docs/archive/`.

## Dev Commands

Run backend commands from repo root:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/test_chat_api.py tests/test_mteam_adapter.py tests/test_qb_adapter.py -q
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

Build the Agent loop that assembles Filter + Gate:

```text
POST /chat
  → Filter.apply(tool_names)     # tools visible to LLM
  → LLM → tool_call
  → Gate.check(tool_call)        # deny / confirm / allow
  → tool.run() or blocked
  → result → LLM → loop → final answer
```

Start with `mteam_search` as the only Agent-callable tool. Keep `/download` explicit until the confirm gate works end-to-end.
