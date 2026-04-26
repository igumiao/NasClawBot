# fnOS Media Agent Phase 2A Design

## 1. Summary

Phase 2A narrows the next stage of work to one goal:

`natural language request -> single LLM-derived keyword -> M-Team search -> top 3 candidates -> human confirmation -> qBittorrent add(paused=true) -> receipt`

This phase does not try to make the system broadly intelligent. It only aims to replace the current "raw sentence passed directly to M-Team" behavior with a much smaller and more reliable search-understanding path.

## 2. Why This Phase Exists

Phase 1 proved that the engineering loop is real:

- FastAPI app exists,
- LangGraph orchestration exists,
- M-Team integration is real,
- qBittorrent integration is real,
- confirmation and receipt flow exist.

The largest product gap is still at the front of the flow:

- user natural language is not reliably converted into a usable search term,
- the app often sends the full raw sentence directly to M-Team,
- long natural-language inputs therefore fail even when short keywords work.

Phase 2A exists to correct that bottleneck before adding more Agent complexity.

## 3. Product Goal

The product goal for Phase 2A is:

> A user can type a natural-language media request, the system extracts one usable search keyword with an LLM, searches M-Team using only that keyword, returns the first 3 candidates, and on approval safely adds the chosen resource to qBittorrent in paused mode.

This is intentionally a smaller target than the earlier Phase 2 discussion.

## 4. Scope

### 4.1 In Scope

- Replace heuristic multi-field constraint extraction on the main path with a single-keyword LLM step.
- Search M-Team with exactly one keyword per request.
- Return the first 3 normalized M-Team candidates without deterministic scoring.
- Preserve the confirmation boundary before any qB side effect.
- Submit approved items to qBittorrent with `paused=true`.
- Return a receipt that clearly reflects that the task was added in paused state.
- Remove Phase 1 scoring-related structures that are no longer part of the main path.

### 4.2 Out of Scope

- Multi-keyword fallback search.
- Structured refine-state merging.
- Ranking explanation generation.
- Season / episode / pack parsing.
- Coordinator-worker orchestration.
- Preference-memory expansion.
- Additional PT sites or downloader integrations.

## 5. User Experience Target

Phase 2A should make the following interaction work end-to-end:

1. User types: `帮我找沙丘2电影，今晚想看`
2. LLM returns: `沙丘2`
3. Backend searches M-Team with only `沙丘2`
4. Backend returns the top 3 normalized candidates
5. User confirms one result
6. Backend adds it to qBittorrent with `paused=true`
7. UI shows a receipt that the task was added and paused

The system does not need to explain why the result ranked first, because this phase does not rank.

## 6. High-Level Architecture

Phase 2A keeps the existing application structure but simplifies the main path:

```text
Chat Web UI
    |
FastAPI API
    |
LangGraph Workflow
    |
FindKeywordLLM
    |
M-Team Search (single keyword)
    |
Top 3 Candidate Projection
    |
Human Confirmation
    |
qB add(urls=..., paused=true)
```

The architecture stays single-app and stateful, but only the minimum required surfaces remain on the main path.

## 7. Workflow Design

### 7.1 Main Path

```text
find_keyword
  -> search_mteam
  -> build_confirmation_payload
  -> await_confirmation

await_confirmation
  -> approve -> execute_download(paused=true) -> build_receipt
  -> cancel -> end
```

### 7.2 Removed From The Main Path

The following Phase 1 ideas are deliberately removed from Phase 2A execution:

- multi-field `SearchConstraints`
- deterministic candidate scoring
- LLM explanation generation
- refine-and-research loop

Those may return in later phases only if they are directly required.

## 8. LLM Role

The LLM has one narrow job in Phase 2A:

- transform the raw user message into one M-Team-friendly search keyword

The LLM is not responsible for:

- searching M-Team directly,
- choosing among returned candidates,
- deciding whether a download should execute,
- controlling qBittorrent,
- generating ranking explanations.

### 8.1 Required Output Contract

The first implementation target is a very small JSON response:

```json
{
  "keyword": "沙丘2"
}
```

Rules:

- `keyword` is required
- `keyword` must be a non-empty string
- no extra fields are required for Phase 2A success

### 8.2 Prompting Intent

The LLM prompt should instruct the model to:

- extract the single most useful PT search keyword,
- prefer a title form that is likely to work directly on M-Team,
- avoid returning the full sentence,
- avoid adding extra descriptive text,
- return valid JSON only.

Few-shot examples should emphasize:

- Chinese movie titles,
- English movie titles,
- requests that contain urgency language but still need only a title-like keyword.

## 9. Data Structure Simplification

Phase 2A should remove unnecessary structures rather than preserve them for possible future use.

### 9.1 Keep

- `ResourceCandidate`
- confirmation payload
- receipt
- minimal workflow state

### 9.2 Remove From The Main Path

- `SearchConstraints`
- `ScoredCandidate`
- scoring reasons
- search keyword planning structures
- multi-attempt search trace structures

### 9.3 Minimal Workflow State

The main workflow state should only contain:

- `session_id`
- `user_message`
- `keyword`
- `search_results`
- `confirmation_payload`
- `receipt`
- `status`
- `error`

If a field is not needed by this path, it should not be kept in the Phase 2A state.

## 10. Candidate Selection Behavior

Phase 2A does not score candidates.

After M-Team returns normalized results:

- keep the returned order,
- take the first 3 items,
- project them into the confirmation payload.

The confirmation payload should include only information that helps the user choose:

- `id`
- `title`
- `seeders`
- `resolution`
- `size`

The payload should not include:

- `score`
- `reasons`
- ranking explanation text

## 11. qBittorrent Safety Behavior

Phase 2A keeps the side-effect boundary but makes approval safer for development and demos.

### 11.1 Approval Semantics

For Phase 2A:

- `approve` means "add the selected torrent to qBittorrent in paused mode"
- `approve` does not mean "start downloading immediately"

### 11.2 qB Add Parameters

The qB adapter execution path should call torrent add with:

- direct M-Team download URL
- `paused=true`

### 11.3 Receipt Semantics

The receipt should make the paused state explicit.

Suggested status value:

- `submitted_paused`

The important point is clarity: the task was added successfully, but it is not actively downloading yet.

## 12. Module Changes

### 12.1 `app/llm/find_keyword_llm.py`

Create a dedicated module for this phase's LLM behavior.

Responsibilities:

- hold the keyword-extraction prompt,
- hold few-shot examples,
- call the model through a thin shared client layer,
- validate and return the JSON output,
- expose a simple interface such as `invoke(message) -> {"keyword": ...}`.

This file intentionally uses a specific name instead of a generic `prompts.py`, because the keyword-finding unit may later evolve into a more explicit Agent component.

### 12.2 `app/llm/client.py`

Simplify this module so it supports model invocation rather than owning broad constraint-extraction logic.

Responsibilities:

- shared model call helper,
- optional configuration lookup,
- parsing/validation helpers that are reusable by `FindKeywordLLM`.

The current heuristic extractor should not remain the main path behavior for Phase 2A.

### 12.3 `app/workflow/state.py`

Reduce the workflow state to the minimal fields listed in Section 9.3.

### 12.4 `app/workflow/nodes.py`

Reshape nodes into the small main path:

- `find_keyword_node`
- `search_node`
- `build_confirmation_payload_node`
- `execute_download_node`

Remove scoring-node usage from the active workflow.

### 12.5 `app/workflow/graph.py`

Rebuild the graph to match the simplified path in Section 7.

`reject_and_refine` is not part of Phase 2A.

### 12.6 `app/api/chat_routes.py`

Update route wiring so:

- the workflow uses `FindKeywordLLM`,
- M-Team search receives exactly one keyword,
- qB execution defaults to paused add.

The route layer must no longer pass the raw user sentence directly as the search keyword.

### 12.7 `app/domain/models.py`

Keep only the domain objects still required by the active path.

Expected to keep:

- `ResourceCandidate`

Expected to remove or stop using:

- `SearchConstraints`
- `ScoredCandidate`

### 12.8 `app/domain/scoring.py`

Delete this file in Phase 2A.

The project should not preserve unused scoring code in the live repository just because it might become useful later.

## 13. Testing Strategy

Phase 2A should prove the main-path correction, not broad semantic coverage.

### 13.1 Workflow Tests

Add or update workflow tests to verify:

- a natural-language message goes through `FindKeywordLLM`,
- the search tool receives the LLM-derived keyword,
- the workflow returns only the first 3 results,
- approve path returns a paused-submission receipt.

### 13.2 API Tests

Add or update API tests to verify:

- `/chat` no longer depends on raw-message search,
- the confirmation payload contains at most 3 results,
- `/confirm` approval returns a paused-submission receipt.

### 13.3 Adapter / Execution Tests

Update execution tests so approval semantics match:

- qB add is called with `paused=true`
- success status reflects paused submission

## 14. Acceptance Criteria

Phase 2A is successful when all of the following are true:

1. A natural-language request is transformed into one keyword by `FindKeywordLLM`.
2. M-Team search is called with that one keyword, not the raw user sentence.
3. The backend returns at most 3 candidates from the search response.
4. The user can approve one candidate through the existing confirmation flow.
5. Approval adds the selected resource to qBittorrent with `paused=true`.
6. The receipt clearly indicates the task was added in paused state.
7. The active main path no longer depends on scoring-related domain structures or files.

## 15. What Comes Next

After Phase 2A is implemented and stable, the next logical phase is Phase 2B:

- structured refine feedback,
- merge-on-top-of-existing-state behavior,
- re-search from updated state rather than a brand-new sentence.

That follow-up work should begin only after the Phase 2A path is working reliably.
