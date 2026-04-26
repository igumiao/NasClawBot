# AGENT.md

## Project Summary

`NasClawBot` is a single-user, self-hosted MVP for a NAS media assistant.

The project has two parallel goals:

- become genuinely useful for the owner's daily NAS / PT / media workflow,
- become a strong portfolio project for AI application / Agent engineering roles.

Current Phase 1 goal:

- accept a natural-language media request,
- search M-Team,
- rank candidates with deterministic rules,
- pause for human confirmation,
- optionally execute a qBittorrent add-by-URL path,
- return a structured receipt.

This repository is already beyond a pure prototype: adapters, workflow, API, UI, storage, tests, and real connectivity checks exist. However, the project is still in a "Phase 1 engineering MVP" state rather than the full intended "Agent product" state.

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
3. `docs/superpowers/specs/2026-04-25-fnos-media-agent-phase1-design.md`
4. `docs/superpowers/plans/2026-04-25-fnos-media-agent-phase1-implementation-plan.md`

These files capture:

- the original product intent,
- what was actually implemented,
- what real API experiments proved,
- and what still needs improvement.

## Current Architecture

Repository structure:

- `app/api/`
  FastAPI routes and request/response schemas.
- `app/workflow/`
  LangGraph state, nodes, and workflow runner.
- `app/adapters/`
  M-Team and qBittorrent integration boundaries.
- `app/domain/`
  typed models and deterministic ranking rules.
- `app/storage/`
  SQLite schema bootstrap and stores.
- `app/tools/`
  small workflow helper functions.
- `app/services/`
  receipt construction.
- `app/llm/`
  currently placeholder / heuristic LLM layer.
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

## Verified External Behavior

These points are verified and should be treated as facts unless re-tested:

- M-Team search uses `POST` with a JSON body.
- M-Team detail uses `POST` with form-data `id=...`.
- M-Team `genDlToken` uses `POST` with form-data `id=...`.
- `x-api-key` is required for M-Team calls.
- `genDlToken` returns a complete download URL.
- That URL can be passed directly to qBittorrent `torrents/add(urls=...)`.
- qB add success should be judged by body text like `Ok.` / `ok`, not just HTTP 200.

Do not regress these behaviors.

## Current Product Reality

The current system is technically working, but still has an important product gap:

- adapters and connectivity are real,
- LangGraph orchestration exists,
- UI/API path exists,
- but natural-language understanding is still mostly heuristic.

This means the repository currently demonstrates workflow scaffolding and integration reliability better than it demonstrates advanced Agent reasoning.

Specifically:

- `app/llm/client.py` still defaults to a local heuristic extractor.
- long natural-language requests often fail because the full sentence is effectively used as the search keyword.
- `reject_and_refine` is still closer to "search again with a new sentence" than "merge structured feedback into the current request state".
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
- keep ranking deterministic at the core,
- use LLMs for understanding and explanation, not for unchecked side effects.

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

- keyword extraction is weak,
- keyword normalization is weak,
- full natural-language sentence search performs poorly,
- refine flow does not yet do true structured constraint merging,
- `confirmation_payload` still carries some data that should eventually become proper state fields,
- layered memory is not really present yet,
- "environment awareness" is still narrow and mostly adapter-level,
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

When changing search quality:

- compare direct adapter behavior and app-level behavior,
- use `scripts/keyword_probe.py`,
- keep at least one Chinese and one English title case in mind,
- test both short keywords and full-sentence inputs.

## Current "Best Next Work"

The highest-value next stage is not more download plumbing.

It is:

1. title extraction from natural-language requests,
2. keyword normalization and fallback rewrite,
3. structured refine feedback merging,
4. then better explanation generation.

After that search-understanding stage becomes stable, the next worthwhile direction is to strengthen the project as an Agent showcase:

1. introduce clearer structured constraints in workflow state,
2. add visible tool-selection / execution traces,
3. add short-term session memory and limited long-term preference memory,
4. enrich human-in-the-loop branches beyond simple accept / reject.

If you are a future Codex agent, start with search understanding unless the user explicitly redirects you, but keep the longer-term Agent showcase goal in mind while designing changes.
