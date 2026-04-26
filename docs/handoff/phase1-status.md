# Phase 1 Status Handoff

> Historical note: this file captures the earlier Phase 1 / early transition baseline. For the current repository state, read `docs/handoff/phase2a-status.md` first.

## Purpose

This document is for the next Codex agent or developer who will continue work after the current Phase 1 MVP.

It answers three questions:

1. What has already been built?
2. What is still weak or incomplete?
3. What should the next major development phase focus on?

It also captures an important product framing point:

`NasClawBot` is not only a personal NAS helper. It is also intended to become a portfolio-grade Agent application that can demonstrate AI application engineering ability for job interviews.

That framing matters when choosing future work.

## Current State

Phase 1 is complete as an engineering MVP.

The project currently has:

- a working FastAPI app,
- a plain HTML/CSS/JS chat shell,
- a LangGraph workflow for search -> confirmation -> execution placeholder,
- real M-Team adapter logic,
- real qBittorrent adapter logic,
- SQLite stores,
- tests and connectivity checks,
- real M-Team -> qB token URL flow validation.

It does **not** yet fully satisfy the original product intent around LLM-driven understanding and refinement.

It also does not yet fully demonstrate the broader Agent capabilities the project wants to showcase over time, especially:

- task planning and decomposition,
- tool calling with environment awareness,
- stateful multi-turn refinement,
- layered memory,
- careful balancing of deterministic logic and LLM reasoning,
- human-in-the-loop interruption and recovery depth.

So the correct reading of the repository today is:

- the engineering base is real,
- the integration base is verified,
- the Agent story is only partially realized.

## What The Project Should Eventually Showcase

For future planning, keep these showcase goals explicit.

The project should gradually make it obvious that the system can:

1. understand a user goal from natural language,
2. transform that goal into structured constraints,
3. plan which tools or adapters to call,
4. inspect results and decide whether the next step is search, refine, confirm, or execute,
5. preserve state and preferences across turns,
6. ask for human confirmation when side effects or ambiguity matter,
7. explain the reasoning behind its choices.

This is a stronger narrative than "a chat UI that calls M-Team and qB".

## What Is Finished

### Core App Structure

Implemented:

- `app/main.py`
- `app/api/`
- `app/workflow/`
- `app/adapters/`
- `app/domain/`
- `app/storage/`
- `frontend/`

### Verified Integration Facts

Confirmed through real testing:

- M-Team search requires `POST + JSON`.
- M-Team detail requires `POST + form-data`.
- M-Team `genDlToken` requires `POST + form-data`.
- M-Team authentication requires `x-api-key`.
- `genDlToken` returns a direct download URL.
- qBittorrent can accept that URL directly via `torrents/add(urls=...)`.
- qB success must be checked via response body (`Ok.` / `ok`), not just HTTP 200.

### Real qB Connectivity

A real validation was completed using M-Team id `1163290`.

Verified chain:

`detail -> genDlToken -> validate torrent URL -> qB add(urls=...)`

This was tested using a paused add strategy to reduce side-effect risk.

### Test Status

The main test suite has passed recently:

- `tests/test_scoring.py`
- `tests/test_workflow.py`
- `tests/test_chat_api.py`
- `tests/test_mteam_adapter.py`
- `tests/test_qb_adapter.py`
- `tests/integration/test_connectivity.py` with gating enabled

Non-blocking warning still exists:

- pytest cache permission warnings on this machine

## What Is Not Finished

### 1. Real LLM Understanding

This is the biggest product gap.

Current reality:

- the workflow defaults to a local heuristic extractor,
- `query_text` often remains the raw sentence,
- title extraction is not truly implemented,
- year / resolution / richer attributes are mostly not parsed.

Result:

the project behaves like a technically working search shell, not yet like the intended Agent experience.

### 2. Search Quality For Natural-Language Requests

This is currently the biggest user-visible weakness.

Observed behavior:

- short, well-formed keywords can work,
- long natural-language requests often return zero results,
- weakly related candidates can rank too high,
- the current app path performs worse than the adapter path when keyword extraction is poor.

### 3. True Refine-State Merging

Current refine behavior is closer to:

- "run search again using a new sentence"

than:

- "update the previous structured request with new constraints"

So the human-in-the-loop experience is present structurally, but still shallow semantically.

### 3.5. Meaningful Agent State And Memory

The current LangGraph state is enough for the MVP loop, but not yet enough for the intended Agent-centric story.

Missing or weak areas:

- structured constraint state is still thin,
- short-term conversation memory is limited,
- long-term user preference memory is effectively absent,
- state updates are not yet the main driver of refinement behavior.

This matters because future interview / portfolio value depends on showing intentional state design, not just single-turn API orchestration.

### 4. Explanation Generation

The deterministic ranking core exists and is a good foundation.

But explanation text is still not a real LLM-generated explanation layer.

## Findings From Feedback And Search Testing

### From `ref/feedback.md`

Main takeaway:

The project's biggest weakness is not adapter correctness anymore.
It is the gap between:

- the intended LLM-based Agent design,
- and the current heuristic extraction behavior.

### From keyword sensitivity testing

Robust or mostly usable forms:

- `沙丘2`
- `Dune: Part Two`
- `沙丘：第二部`
- `dune part 2`
- `dune part two`
- `Dune II`
- `沙丘II`

Fragile forms:

- `dune2`
- `dune-2`
- `沙丘第二部`

Very important finding:

full natural-language sentences remain a major failure mode.

That means search quality is currently bottlenecked more by:

- keyword extraction,
- query normalization,
- and fallback rewrite

than by adapter behavior.

## Recommended Next Major Phase

The next major phase should focus on **search understanding quality**, not on adding more execution plumbing.

But it should do so in a way that strengthens the project's Agent identity rather than merely improving search recall.

### Recommended order

#### Stage A: Minimal Real LLM Title Extraction

Scope:

- integrate a real LLM-backed extractor,
- extract only the most important value first: title-like keyword,
- stop sending the entire sentence directly to M-Team search.

Why it matters:

- it is the smallest change that makes the system feel more like an Agent and less like a raw keyword pass-through.

Suggested first structured output:

```json
{
  "title_keyword": "沙丘2",
  "intent": "search_and_prepare_download"
}
```

Keep this stage narrow.
Do not try to solve every attribute at once.

#### Stage B: Keyword Normalization And Fallback

Add a search preparation layer that can normalize variants such as:

- `dune2 -> dune 2`
- `dune-2 -> dune 2`
- `沙丘第二部 -> 沙丘2` or `沙丘：第二部`

If the first search returns no results, retry a small number of normalized alternatives.

This stage is still mostly deterministic, which is good. It preserves reliability while letting LLM reasoning stay narrow and auditable.

#### Stage C: Structured Refine Merging

Upgrade `reject_and_refine` from:

- new sentence -> new search

to:

- preserve previous constraints,
- parse new user feedback,
- merge constraints,
- search again.

This is the point where human-in-the-loop stops being a UI checkpoint and starts becoming real stateful correction.

#### Stage D: Better Explanation Generation

After search quality is no longer dominated by bad keywords:

- keep ranking deterministic,
- let the LLM explain why a result ranked first.

This preserves the engineering choice already agreed with the user:

- deterministic ranking core,
- LLM for understanding and explanation.

## Recommended Phase 2 Framing

If the next agent writes a new spec or plan, frame Phase 2 as:

- "make the existing MVP understand and refine better"

not:

- "add more integrations"
- "rewrite the architecture"
- "turn everything into LLM decisions"

The most valuable balance for this project is:

- deterministic where correctness and safety matter,
- LLM-assisted where ambiguity and natural language matter.

That balance is part of the product's intended identity.

## Areas That Likely Need Code Changes First

If the next agent starts Phase 2 planning, these are the highest-value files to inspect first:

- `app/llm/client.py`
- `app/llm/prompts.py`
- `app/workflow/graph.py`
- `app/workflow/nodes.py`
- `app/api/chat_routes.py`
- `app/domain/scoring.py`
- `scripts/keyword_probe.py`

These are the files closest to the current product bottleneck.

## Areas That Are Stable Enough To Leave Alone For Now

Unless a new requirement forces it, do not start by rewriting:

- `app/adapters/mteam.py`
- `app/adapters/qbittorrent.py`
- `app/storage/`
- the SQLite schema
- the basic FastAPI/HTML setup

These parts are already good enough for the next phase to build on.

## Suggested Acceptance Criteria For The Next Phase

The next phase should be considered successful when:

1. Full-sentence search requests no longer depend on sending the raw sentence directly to M-Team.
2. At least one title extraction path uses a real LLM rather than only heuristics.
3. Search keyword normalization handles common fragile variants.
4. Refine flow updates previous intent instead of discarding it.
5. Search quality improves measurably on known probe cases.

## Bottom Line

This repository now has a credible engineering MVP and validated download-chain foundations.

The next phase should treat the system's main bottleneck as:

- **language understanding quality**

not:

- download integration
- storage
- basic web/API scaffolding

At the same time, future work should deliberately strengthen the parts that make this a strong Agent project on a resume:

- planning and decomposition,
- tool invocation boundaries,
- state and memory design,
- human-in-the-loop control,
- deterministic / non-deterministic balance.

If a future Codex agent needs a single sentence to guide its next work, use this:

> Keep the verified M-Team/qB chain intact, and spend the next phase making the system understand title intent, rewrite keywords better, and refine search state across turns.
