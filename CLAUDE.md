# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

NasClawBot is a single-user, self-hosted NAS/PT media assistant. The baseline flow: natural-language media request → LLM keyword extraction → M-Team search → up to 3 confirmation candidates → paused qBittorrent download → structured receipt. A React + Vite frontend provides a chat workbench with approval cards, download controls, and a settings panel.

See `AGENT.md` for the full project summary, known weaknesses, recommended next work, and validated external behavior rules that must not regress.

## Dev commands

All commands run from repo root.

**Backend (Python):**
```bash
.venv/bin/python -m pytest                          # all tests
.venv/bin/python -m pytest tests/test_find_keyword_llm.py tests/test_workflow.py -q   # core workflow
.venv/bin/python -m pytest tests/test_mteam_adapter.py tests/test_qb_adapter.py tests/test_chat_api.py -q  # adapters + API
.venv/bin/python scripts/connectivity_smoke.py       # check env config is complete
.venv/bin/python scripts/keyword_probe.py "keyword"  # probe M-Team search directly
```

There is no formal linter/formatter configured yet.

**Frontend (TypeScript/React):**
```bash
cd frontend && npm test              # vitest
cd frontend && npm run test:watch    # vitest watch mode
cd frontend && npm run typecheck     # tsc -b (noEmit)
cd frontend && npm run build         # typecheck + vite build → dist/
cd frontend && npm run dev           # Vite dev server on :5173, proxies /chat etc. to :8000
```

Start the backend with uvicorn:
```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Architecture

**Request flow:** FastAPI routes (`app/api/chat_routes.py`) receive `/chat` and `/confirm` requests, delegate to a `LangGraphWorkflowRunner` that drives a compiled LangGraph `StateGraph`. The graph has four nodes wired sequentially with a conditional start edge:

1. `keyword_finder` — `FindKeywordLLM` calls an OpenAI-compatible API to extract a single search keyword from the user message.
2. `search_mteam` — The `AdapterSearchTool` wraps `MTeamAdapter.search_torrents_by_keyword()` and returns `list[ResourceCandidate]`.
3. `build_confirmation_payload` — Converts top 3 results into a `ConfirmationPayload` with summary, recommended id, and candidate list. State becomes `awaiting_confirmation`.
4. `execute_download` — On approve, resolves the selected candidate, calls M-Team `detail → genDlToken`, then qBittorrent `torrents/add(urls=…)` (paused, tagged `mteam`).

The conditional edge at `START` checks whether `confirmation_payload` is already present — if so, it routes directly to `execute_download` (confirm path); otherwise to `keyword_finder` (chat path).

**Adapters as dependency-injected boundaries:**
- `app/adapters/mteam.py` — `MTeamAdapter`: search (POST JSON), detail (POST form-data), genDlToken (POST form-data). All authenticated via `x-api-key` header. The base class is a `@dataclass(slots=True)` — no framework coupling.
- `app/adapters/qbittorrent.py` — `QBittorrentAdapter`: wraps `qbittorrent-api`, handles add/list/detail/control. `add_torrent_url` judges success by text response (`Ok.`/`ok`/`true`), not HTTP status.

Both adapters are configured from `app/config.py` (`Settings` via Pydantic, loaded from env vars then `.env` file, cached via `@lru_cache`).

**M-Team API reference:** `ref/mteam-api-reference.md` is the authoritative, probe-verified API reference for all M-Team endpoints (search, detail, genDlToken, files, mediaInfo, peers, Douban/IMDB media info, category lists). It documents Content-Type requirements per endpoint, parameter tables, sort/filter/mode enums, the standard download chain, and a category ID quick-reference. Treat it as ground truth for any M-Team integration work.

**Shared types:** `app/domain/models.py` defines `ResourceCandidate`, `ConfirmationCandidate`, and `ConfirmationPayload`. API schemas in `app/api/schemas.py` include `ChatRequest`/`ChatResponse`, `ConfirmRequest`/`ConfirmResponse`, and qB types.

**LLM layer:** `app/llm/client.py` provides `call_openai_compatible_chat()` — a single function using the OpenAI Python SDK. Supports reasoning_split (for MiniMax). `app/llm/find_keyword_llm.py` wraps it with a Chinese/English system prompt for keyword extraction. JSON parsing handles `\<think>` blocks and markdown code fences defensively.

**Storage:** SQLite via `app/storage/db.py` with three tables: `sessions`, `preferences`, `task_index`. Stores are used by the route layer; the workflow itself is stateless (LangGraph state lives per-invocation).

**Frontend:** React 19 SPA in `frontend/`. Key dependencies: `@assistant-ui/react` (chat UI primitives), `lucide-react` (icons). State lives in `src/state/` (chatState, downloadsState, uiState) using React hooks. API calls go through thin wrappers in `src/api/`. Three workspace tabs: Chat, Downloads, Settings. Vite proxies `/chat`, `/confirm`, `/health`, `/qb` to the FastAPI backend.

## Safety rules

- Never trigger real downloads during tests/demos; always submit paused.
- Never log secrets, API keys, or full tokenized download URLs.
- Keep M-Team torrent id as the stable external identifier.
- Keep search, detail, and token generation as separate operations.
- Do not download `.torrent` files locally — pass the token URL directly to qB.
- `reject_and_refine` is intentionally blocked at the route layer (not true state merge yet).
