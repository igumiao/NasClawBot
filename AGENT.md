# AGENT.md

## Project Summary

`NasClawBot` is a single-user, self-hosted NAS / PT media assistant. It is also intended to be a portfolio-quality Agent engineering project, so future work should preserve visible workflow state, tool boundaries, human approval, and safe side-effect handling.

Current baseline:

- accept a natural-language media request,
- use an OpenAI-compatible LLM call to extract one search keyword,
- search M-Team with that keyword,
- return up to 3 candidates for confirmation,
- on approval, execute the verified M-Team `detail -> genDlToken -> qBittorrent add URL` path,
- submit qB tasks paused by default,
- return a structured receipt,
- expose qB task list / detail / control APIs for future management surfaces.

Phase 2A should be treated as done. The project is working as a narrow search-confirm-download baseline, not yet as a full dynamic planning agent.

## Current Architecture

- `app/api/`: FastAPI routes and request/response schemas.
- `app/workflow/`: LangGraph workflow state, nodes, and runner.
- `app/llm/`: OpenAI SDK based OpenAI-compatible chat adapter and keyword extraction.
- `app/adapters/`: M-Team and qBittorrent integration boundaries.
- `app/domain/`: shared typed models.
- `app/storage/`: SQLite schema and stores for sessions, preferences, and task index.
- `app/tools/`: small workflow helpers.
- `app/services/`: receipt construction.
- `frontend/`: React + Vite light-theme workbench for Chat, Downloads, and Settings.
- `ref/`: reference analysis notes. The key file is `ref/mteam-api-reference.md` — a probe-verified, curated M-Team API reference covering all endpoints, Content-Type requirements, parameter enums, the standard download chain, and a category ID quick-reference. Treat it as ground truth for M-Team integration work. Other files in this directory are supporting notes and may be stale.
- `scripts/`: connectivity and keyword probe utilities.
- `tests/`: unit and integration coverage.

Main dependencies:

- FastAPI / Pydantic
- LangGraph 1.x
- LangChain 1.x and `langchain-openai` 1.x kept available, but not on the main LLM call path
- OpenAI Python SDK 2.x for OpenAI-compatible chat completions
- `httpx` for M-Team
- `qbittorrent-api` for qBittorrent
- SQLite

## Runtime Configuration

Settings load from process environment first, then project-root `.env`.

Important keys:

- `MTEAM_BASE_URL`
- `MTEAM_API_KEY`
- `QB_BASE_URL`
- `QB_USERNAME`
- `QB_PASSWORD`
- `DATABASE_PATH`
- `LLM_MODEL` defaults to `deepseek-v4-pro`
- `LLM_BASE_URL` defaults to `https://api.deepseek.com`
- `LLM_API_KEY`
- `LLM_REASONING_SPLIT` defaults to `true`
- `LOG_LEVEL` defaults to `INFO`
- `LLM_LOG_RAW_OUTPUT` defaults to `false`

Logging is configured through `app/logging_config.py`. LLM raw output is only logged as a truncated preview when `LLM_LOG_RAW_OUTPUT=true`; never log API keys or full M-Team token URLs.

## Verified External Behavior

Treat these as facts unless re-tested:

- M-Team search uses `POST` with JSON.
- M-Team detail uses `POST` with form-data `id=...`.
- M-Team `genDlToken` uses `POST` with form-data `id=...`.
- M-Team requires `x-api-key`.
- `genDlToken` returns a complete download URL.
- qBittorrent can receive that URL directly through `torrents/add(urls=...)`.
- qB add success must be judged by returned success text such as `Ok.` / `ok` / `true`, not by HTTP transport success alone.
- Approval should submit qB tasks paused by default.

Do not regress these behaviors.

## Safety Rules

- Do not casually trigger real downloads.
- Keep qB submissions paused during tests and demos unless the user explicitly asks otherwise.
- Do not log secrets, API keys, or full tokenized download URLs.
- Keep M-Team torrent id as the stable external identifier.
- Keep search separate from detail and token generation.
- Do not download `.torrent` files locally just to upload them to qB.
- Use LLMs for understanding and explanation, not for unchecked side effects.

## Current Product Reality

Stable enough to build on:

- adapter request shapes,
- direct token URL -> qB submission,
- paused approval path,
- simplified LangGraph search/confirm path,
- qB task query and control boundaries,
- React chat workbench with approval cards, download controls, and a small status page,
- OpenAI-compatible LLM adapter via OpenAI SDK,
- readable diagnostics logging.

Known weaknesses:

- keyword extraction is still single-field and title-centric,
- keyword normalization and fallback rewrite are weak,
- compound natural-language constraints are fragile,
- `reject_and_refine` is intentionally blocked at the route layer and is not true state merge,
- explanation generation is thin,
- memory and environment awareness are shallow,
- qB management UI is intentionally lightweight and does not replace the backend workflow design.

## Recommended Next Work

Highest-value next phase:

1. strengthen keyword normalization and fallback rewrite,
2. implement structured refine feedback merging,
3. improve explanation generation,
4. decide how qB task management should surface in UI or agent tools,
5. introduce clearer structured constraints, tool traces, and limited memory.

When changing search quality, compare direct adapter behavior with app-level behavior and test both Chinese and English title cases.

When changing qB behavior, preserve paused-by-default approval and verify task listing/detail/control behavior.

## Validation

Useful checks:

- `.venv/bin/python -m pytest`
- `.venv/bin/python -m pytest tests/test_find_keyword_llm.py tests/test_workflow.py -q`
- `.venv/bin/python -m pytest tests/test_mteam_adapter.py tests/test_qb_adapter.py tests/test_chat_api.py -q`
- `cd frontend && npm test`
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`
- `.venv/bin/python scripts/keyword_probe.py`
- `.venv/bin/python scripts/connectivity_smoke.py`

The integration connectivity test may be skipped when real M-Team/qB credentials or network access are not available.
FastAPI serves the built Vite app from `frontend/dist/` when present; keep `/health`, `/chat`, and qB API routes intact when changing static serving.
