# AGENT.md

## Project Summary

`NasClawBot` is a single-user, self-hosted MVP for a NAS media assistant.

The project has two parallel goals:

- become genuinely useful for the owner's daily NAS / PT / media workflow,
- become a strong portfolio project for AI application / Agent engineering roles.

Current implemented baseline:

- accept a natural-language media request,
- use an LLM to extract one search keyword,
- search M-Team with that single keyword,
- return the first 3 candidates for confirmation,
- on approval, execute the verified M-Team token URL -> qBittorrent add path in paused mode,
- return a structured receipt,
- expose qBittorrent task list / detail / control APIs for future management surfaces.

This repository is already beyond a pure prototype: adapters, workflow, API, UI, storage, tests, qB task-management routes, and real connectivity checks exist. The Phase 2A baseline should now be treated as complete and stable enough to build on, although the project still has a large gap to the intended full Agent product.

## Long-Term Agent Direction

Future work should keep the project centered on an observable Agent loop rather than turning it into a thin search form with helper scripts.

The long-term product direction is to progressively emphasize these capabilities:

- task planning and decomposition,
- tool calling plus environment awareness,
- explicit workflow state management,
- layered short-term context and long-term preference memory,
- deterministic core decisions with selective non-deterministic LLM reasoning,
- human-in-the-loop interruption, rejection, clarification, and resume.

In other words: the project should eventually show not just "it can search and download", but "it can understand intent, choose actions, coordinate tools, pause safely, remember preferences, and explain why it acted".

## What This Project Should Demonstrate

If you are extending this repository for portfolio value, prefer work that makes the following more visible:

- how the Agent decomposes a user request into smaller executable steps,
- how external systems such as M-Team and qBittorrent are exposed as explicit tool/adapter boundaries,
- how workflow state evolves across turns instead of being rebuilt from scratch,
- how deterministic ranking and safety rules coexist with LLM inference,
- how human feedback changes the plan instead of merely restarting the flow.

Do not optimize away these surfaces just because a shortcut is simpler internally. The project is meant to demonstrate Agent engineering judgment, not only successful API calls.

## Read These First

Before changing search, workflow, or adapter behavior, read:

1. `ref/feedback.md`
2. `ref/mt-helper-search-download-analysis.md`
3. `docs/handoff/phase2a-status.md`
4. `docs/superpowers/specs/2026-04-26-fnos-media-agent-phase2a-search-path-design.md`
5. `docs/superpowers/plans/2026-04-26-fnos-media-agent-phase2a-search-path-implementation-plan.md`

These files capture:

- the original product intent,
- what Phase 2A actually implemented,
- what qB task-management surfaces now exist,
- what real API experiments proved,
- and what still needs improvement.

## Current Architecture

Repository structure:

- `app/api/`
  FastAPI routes and request/response schemas, including qB task-management endpoints.
- `app/workflow/`
  LangGraph state, nodes, and workflow runner for the Phase 2A search/confirm path.
- `app/adapters/`
  M-Team and qBittorrent integration boundaries, including qB task queries and control actions.
- `app/domain/`
  typed models and deterministic ranking rules.
- `app/storage/`
  SQLite schema bootstrap and stores.
- `app/tools/`
  small workflow helper functions.
- `app/services/`
  receipt construction.
- `app/llm/`
  narrow OpenAI-compatible keyword extraction layer for the current search path.
- `frontend/`
  plain HTML/CSS/JS browser shell.
- `scripts/`
  connectivity and keyword probe utilities.
- `tests/`
  unit/integration coverage for the current MVP.

## Runtime Configuration

Configuration is loaded from:

1. process environment variables first
2. project-root `.env` second

Important keys:

- `MTEAM_BASE_URL`
- `MTEAM_API_KEY`
- `QB_BASE_URL`
- `QB_USERNAME`
- `QB_PASSWORD`
- `DATABASE_PATH`

The current loader lives in `app/config.py`.

Project Python environment:

- prefer the project-local `.venv` at `D:\Agent\NasClawBot\.venv`,
- create or refresh it with `C:\Users\10762\anaconda3\envs\python311\python.exe -m venv .venv`,
- prefer `.\scripts\python.ps1` over bare `python` in PowerShell so agents do not silently fall back to the shell default interpreter.

## Verified External Behavior

These points are verified and should be treated as facts unless re-tested:

- M-Team search uses `POST` with a JSON body.
- M-Team detail uses `POST` with form-data `id=...`.
- M-Team `genDlToken` uses `POST` with form-data `id=...`.
- `x-api-key` is required for M-Team calls.
- `genDlToken` returns a complete download URL.
- That URL can be passed directly to qBittorrent `torrents/add(urls=...)`.
- qB add success should still be judged by returned success text such as `Ok.` / `ok` / `true`, not by transport success alone.
- qB adapter behavior now goes through the `qbittorrent-api` client rather than hand-built `httpx` endpoint calls.

Do not regress these behaviors.

## Current Product Reality

The current system is technically working, but still has an important product gap:

- adapters and connectivity are real,
- LangGraph orchestration exists,
- UI/API path exists,
- qB task-management API surfaces now exist,
- but natural-language understanding is still intentionally narrow.

This means the repository now demonstrates workflow scaffolding, integration reliability, and early downloader-management boundaries better than it demonstrates advanced Agent reasoning.

Specifically:

- `FindKeywordLLM` now performs real OpenAI-compatible keyword extraction for the main path.
- the LLM layer is still single-purpose and only returns one keyword, not richer structured intent.
- `reject_and_refine` is intentionally blocked at the route layer in Phase 2A rather than implemented as true state merge.
- qB management exists at the API/adapter layer, but not yet as a complete user-facing management workflow or UI.
- explanation text is not yet truly LLM-generated.

## Safety Rules

When testing anything that can create a real qBittorrent task:

- prefer `paused=true` when possible,
- explain the side effect before running it,
- do not perform real download submission casually.

When exploring M-Team behavior:

- validate assumptions with real calls,
- do not rely only on the reference project,
- record important findings into `ref/` if they change implementation assumptions.

## Development Rules

### Preserve These Design Decisions

- keep M-Team torrent id as the stable external identifier,
- keep search separate from detail / token generation,
- do not download `.torrent` files locally just to upload them again,
- keep the current search result projection simple unless a new phase explicitly brings back ranking,
- use LLMs for understanding and explanation, not for unchecked side effects.

### Prefer Mainstream SDKs And Libraries

- when an integration has a well-known, actively maintained SDK or community-standard client, prefer it over hand-written low-level HTTP glue,
- keep external dependencies behind local adapter boundaries so the rest of the app does not depend directly on vendor/client-library details,
- choose dependencies that improve readability, reduce protocol boilerplate, and expose business-level operations clearly,
- fall back to direct `httpx` or `requests` calls only when a suitable library does not exist or when the dependency would add more complexity than it removes,
- before adopting a new library, quickly check whether it is commonly used, actively maintained, and makes the codebase simpler rather than more magical.

### Avoid Regressions

Do not:

- reintroduce "HTTP 200 means qB add succeeded",
- send M-Team detail / token requests as JSON,
- route real search through brittle demo-only behavior,
- let workflow state depend entirely on UI payload shapes.

### Prefer These Validation Tools

- `scripts/connectivity_smoke.py`
- `scripts/keyword_probe.py`
- `tests/test_mteam_adapter.py`
- `tests/test_qb_adapter.py`
- `tests/test_workflow.py`
- `tests/test_chat_api.py`

## Important Current Weaknesses

These are known issues, not surprises:

- keyword extraction is better than Phase 1 but still single-field and title-centric,
- keyword normalization and fallback rewrite are still weak,
- full natural-language requests with compound constraints are still fragile,
- refine flow does not yet do true structured constraint merging,
- confirmation models are typed now, but execution/session data is still flatter than a future Agent-oriented state model will likely need,
- layered memory is not really present yet,
- "environment awareness" is still narrow and mostly adapter-level,
- qB management is exposed as endpoints but not yet integrated into a richer agent loop,
- the Agent currently does little visible task decomposition beyond the fixed workflow.

## Recommended Working Style For Future Agents

When starting a new change:

1. read `ref/feedback.md`,
2. inspect the relevant adapter / workflow / API files,
3. decide whether the problem is:
   - adapter correctness,
   - keyword extraction,
   - ranking,
   - refine-state handling,
   - or UI/API integration,
4. run the smallest relevant test set first,
5. only then widen to end-to-end checks.

Python command discipline:

- in PowerShell, prefer `.\scripts\python.ps1 ...` instead of bare `python`,
- if `.venv` is missing, create it before running install or test commands,
- keep commands project-local so sub agents do not drift onto another interpreter.

When changing search quality:

- compare direct adapter behavior and app-level behavior,
- use `scripts/keyword_probe.py`,
- keep at least one Chinese and one English title case in mind,
- test both short keywords and full-sentence inputs.

When changing qB behavior:

- preserve the current paused-by-default approval path,
- verify task listing / detail / control behavior through `tests/test_qb_adapter.py` and `tests/test_chat_api.py`,
- keep management actions explicit and auditable rather than hidden behind implicit workflow side effects.

## Current "Best Next Work"

The highest-value next stage is no longer basic download plumbing.

It is:

1. keyword normalization and fallback rewrite on top of the new single-keyword path,
2. structured refine feedback merging,
3. richer explanation generation,
4. then tighter integration between workflow state and qB task-management surfaces.

After that search-understanding stage becomes stable, the next worthwhile direction is to strengthen the project as an Agent showcase:

1. introduce clearer structured constraints in workflow state,
2. add visible tool-selection / execution traces,
3. add short-term session memory and limited long-term preference memory,
4. enrich human-in-the-loop branches beyond simple accept / reject,
5. decide whether qB task-management APIs should become an explicit worker/tool surface inside a broader agent workflow.

If you are a future Codex agent, treat Phase 2A as done, start from search/refine understanding unless the user explicitly redirects you, and keep the longer-term Agent showcase goal in mind while designing changes.
