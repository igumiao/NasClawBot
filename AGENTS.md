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
- `/chat`: performs a readonly `MTeamSearchTool` call and returns `results`.
- `/download`: explicit user action; calls `QBAddTorrentTool` and submits to qBittorrent paused.
- `app/tools.py`: tool wrappers over existing adapters. Tool permission metadata is preserved for future Agent loop policy.
- `app/adapters/mteam.py`: M-Team API boundary for search, detail, and download token generation.
- `app/adapters/qbittorrent.py`: qBittorrent API boundary for paused add, listing, detail, and control.
- `app/domain/models.py`: currently only shared search result models.
- `frontend/`: React + Vite workspace with Chat, Downloads, and Settings tabs.
- `ref/mteam-api-reference.md`: authoritative local M-Team API reference.

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

The next step is not to reintroduce a workflow engine. Build from the smallest useful Agent shape:

```text
messages + tools -> minimal Agent loop -> tool call/result -> final answer
```

Start with readonly tools only, most likely `mteam_search`. Add context, persistence, approval, and write-tool policy only when a concrete interaction needs them.
