# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Project Overview

NasClawBot is a single-user NAS/PT media assistant. The active implementation is intentionally simple:

```text
/chat     -> readonly M-Team search -> search results
/download -> explicit user action -> qB add paused
/qb/*     -> qB task management
```

The project is being reset toward a minimal context-aware Agent loop. Do not assume the older workflow/runtime design is still active.

## Important Current Facts

- There is no `/confirm` route.
- There is no `confirmation_payload`.
- There is no `HelloAgentWorkflowRunner`.
- There is no `SequentialWorkflow`.
- There is no active runtime session store.
- Tool wrappers live in `app/tools.py`.
- M-Team and qB integration lives behind adapters in `app/adapters/`.
- Historical LangGraph and HelloAgents runtime docs are archived under `docs/archive/`.

## Dev Commands

Backend, from repo root:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/test_chat_api.py tests/test_mteam_adapter.py tests/test_qb_adapter.py -q
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
- `POST /download`: accepts a torrent id, calls `QBAddTorrentTool`, submits to qB paused, and returns a receipt.
- qB management routes are included from `app/api/qb_routes.py`.

`frontend/src/components/chat/ChatPanel.tsx` renders chat messages and search results. Search results are displayed with `SearchResultCard`; clicking "加入 qB" calls `/download`.

`ref/mteam-api-reference.md` is the local source of truth for M-Team endpoints.

## Safety Rules

- Never trigger real downloads in tests/demos unless explicitly requested.
- Download submissions must remain paused by default.
- Never log secrets or full tokenized download URLs.
- Keep search, detail, and token generation separate.
- Do not download `.torrent` files locally.
- Do not expose destructive file operations to an open Agent loop.

## Next Direction

Prefer a minimal Agent loop over a workflow engine:

```text
messages + readonly tools -> Agent loop -> tool result -> final answer
```

Start with `mteam_search` as the only Agent-callable tool. Keep `/download` as an explicit user action until there is a concrete need for approval/policy machinery.
