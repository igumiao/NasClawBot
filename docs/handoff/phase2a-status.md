# Phase 2A Status Handoff

## Status

Phase 2A should now be treated as `DONE` for the current repository baseline.

That does not mean the product is finished. It means the current simplified search/confirm/download-management baseline is complete enough that the next work should be framed as a new phase, not as more cleanup inside Phase 2A.

## Purpose

This document is the current handoff baseline for `NasClawBot` after the Phase 2A search-path work and the first qBittorrent task-management expansion.

It answers four practical questions for the next agent or developer:

1. What is working right now?
2. What changed compared with the earlier Phase 1 baseline?
3. What was just added around qBittorrent?
4. What should the next phase focus on?

## Current Baseline

The repository now has a real end-to-end Phase 2A path:

- natural-language user input,
- one LLM-derived search keyword,
- M-Team search with that single keyword,
- first 3 candidates returned for confirmation,
- approval through the verified M-Team detail -> token URL -> qB add flow,
- qB add submitted in paused mode by default,
- structured receipt returned to the user.

In addition, the repository now exposes a first task-management surface for qBittorrent:

- list tasks,
- fetch one task detail,
- send supported control actions such as pause/resume/recheck/reannounce/delete.

This means the project is no longer only "search and prepare download". It now also has the backend boundaries needed for future downloader-management workflows.

## What Phase 2A Changed

Compared with the earlier Phase 1 MVP:

- the main path no longer depends on deterministic scoring,
- `FindKeywordLLM` replaced the previous raw-sentence search behavior on the main path,
- search now uses one extracted keyword rather than the entire user sentence,
- the confirmation payload is intentionally reduced to the first 3 items,
- qB approval is paused by default for safer testing and demos,
- `reject_and_refine` is intentionally not supported on `/confirm` in this phase.

The result is a narrower but much more reliable search loop.

## Verified Runtime Behavior

These behaviors should be treated as current facts unless re-tested:

- M-Team search uses `POST` with JSON.
- M-Team detail uses `POST` with form-data `id=...`.
- M-Team `genDlToken` uses `POST` with form-data `id=...`.
- `x-api-key` is required for M-Team requests.
- `genDlToken` returns a direct download URL.
- qB can receive that URL directly without downloading a `.torrent` file locally first.
- approval should add the torrent with paused semantics, so the task appears in qB without immediately starting download.
- qB add success should be judged by returned success text such as `Ok.` / `ok` / `true`, not by transport success alone.

## qBittorrent Changes Added After The Core Phase 2A Path

The recent qB-focused changes extend the adapter and API from "submit only" to "submit plus manage":

### Adapter Layer

`app/adapters/qbittorrent.py` now:

- uses the maintained `qbittorrent-api` client library,
- logs in through that client,
- keeps the paused add-by-URL path,
- lists categories,
- lists torrents with structured fields,
- gets one torrent plus merged property details,
- dispatches supported control actions.

### API Layer

qB management routes now live in `app/api/qb_routes.py` and are mounted by the main API app.

The current backend exposes:

- `GET /qb/torrents`
- `GET /qb/torrents/{torrent_hash}`
- `POST /qb/torrents/{torrent_hash}/actions`

These routes are backend-ready management surfaces for a later UI or agent tool layer.

### Schema Layer

`app/api/schemas.py` now includes typed response models for:

- torrent summary rows,
- torrent detail payloads,
- torrent action request/response payloads.

### Dependency Surface

`pyproject.toml` now includes `qbittorrent-api` as a project dependency.

## What Is Stable Enough To Rely On

The following areas are currently good enough to build on rather than rewrite immediately:

- M-Team adapter request shapes,
- the direct token URL -> qB submission chain,
- the paused approval path,
- the simplified LangGraph search/confirm path,
- qB task query and control boundaries,
- the project-local `.venv` workflow and `scripts/python.ps1`.

## Current Weaknesses

The project still has clear limitations:

- LLM understanding is still single-purpose and only extracts one keyword.
- Keyword normalization and fallback rewrite are still weak.
- Multi-turn refine is not implemented as state merge.
- Explanation generation is still thin.
- qB management exists as adapter/API capability, but there is no full UI management workflow yet.
- Memory and broader environment awareness are still shallow.
- The project still shows a fixed workflow better than it shows dynamic planning.

## Recommended Next Phase Focus

The next highest-value phase is not more downloader plumbing.

Recommended order:

1. Strengthen keyword normalization and fallback rewrite on top of the current single-keyword path.
2. Reintroduce refine as structured state merge rather than sentence replacement.
3. Improve explanation generation once search understanding is less fragile.
4. Decide how qB management should surface next:
   - as a lightweight UI management page,
   - as explicit workflow tools,
   - or as a coordinator/worker capability later.

## Practical Advice For The Next Agent

If you are extending this codebase next:

- read `AGENT.md`,
- read this handoff file,
- inspect `app/llm/find_keyword_llm.py`,
- inspect `app/workflow/graph.py` and `app/workflow/nodes.py`,
- inspect `app/adapters/qbittorrent.py`, `app/api/chat_routes.py`, and `app/api/qb_routes.py`,
- run the smallest relevant test slice first,
- prefer `.\scripts\python.ps1 ...` over bare `python` in PowerShell.

Recommended verification slices:

- `.\scripts\python.ps1 -m pytest tests/test_find_keyword_llm.py tests/test_workflow.py -q`
- `.\scripts\python.ps1 -m pytest tests/test_qb_adapter.py tests/test_chat_api.py -q`
- `.\scripts\python.ps1 -m pytest tests/test_mteam_adapter.py tests/integration/test_connectivity.py -q`

## Bottom Line

The current repository baseline is:

- Phase 2A search path complete and considered done,
- paused qB approval path working,
- first qB task-management backend surfaces present,
- next meaningful work centered on search/refine quality and stronger agent behavior, not basic integration plumbing.
