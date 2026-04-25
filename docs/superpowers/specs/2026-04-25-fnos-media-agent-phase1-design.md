# fnOS Media Agent Phase 1 Design

## 1. Summary

Phase 1 builds a single-user, self-hosted, web-based media assistant for a personal NAS environment.
The goal is not to automate an entire media workflow, but to deliver one stable, explainable loop:

`natural language request -> M-Team search -> rule-based ranking -> human confirmation -> qBittorrent submission -> structured receipt`

This phase is intentionally narrow. It should demonstrate agent orchestration, human-in-the-loop confirmation, basic long-term preference memory, real external system integration, and recoverable workflow state without expanding into a full media platform.

## 2. Product Goal

The product should let a user open a local web page and type requests such as:

- "Help me find Dune Part Two in 4K and prepare the download."
- "I want to watch a movie tonight, prefer faster downloads."
- "These are wrong, I want the movie version, not the TV series."

The system should:

1. Interpret the request into structured constraints.
2. Search M-Team through a dedicated adapter.
3. Rank candidates using deterministic rules.
4. Explain the recommendation in natural language.
5. Pause for explicit user confirmation before any download side effect.
6. Submit the confirmed torrent to qBittorrent.
7. Return a structured receipt and persist minimal state.

## 3. Scope

### 3.1 In Scope

- Single-user, trusted intranet deployment.
- Chat-style single-page web UI.
- Backend implemented with FastAPI.
- Workflow orchestration implemented with LangGraph.
- M-Team integration for search, detail lookup, and download URL generation.
- qBittorrent integration for login, category/profile lookup, and adding torrent URLs.
- SQLite persistence for session state, preference profile, and task index.
- Human-in-the-loop confirmation with a reject-and-refine loop.
- Small set of long-term preferences.
- Rule-based ranking with LLM-generated explanation.
- Real connectivity exploration before mock contract creation.

### 3.2 Out of Scope

- Multi-user support and login/authentication.
- Multiple PT sites.
- Multiple downloaders.
- Full media library organization or metadata enrichment.
- Recommendation engine or auto-follow/auto-update workflows.
- MCP integrations.
- Multi-agent architecture.
- Complex frontend framework.
- Background worker platform, message queue, or distributed architecture.

## 4. Success Criteria

Phase 1 is successful when the following are true:

1. A user can enter a natural-language download intent from the web UI.
2. The system can derive structured constraints and situational signals from that request.
3. The system can query M-Team and return ranked candidates with a readable recommendation.
4. The user can reject the recommendation, refine the request in natural language, and trigger a new search.
5. The user can explicitly approve a candidate before any download side effect occurs.
6. The system can submit the confirmed resource to qBittorrent.
7. The system can return a structured receipt to the UI.
8. The system can persist enough session state to survive the confirmation boundary.
9. The M-Team to qBittorrent link is verified against the real environment before mock data is formalized.

## 5. Key Product Constraints

### 5.1 Minimal Closed Loop First

The phase must prioritize a stable, demonstrable loop over completeness.
Every architectural decision should favor:

- fewer moving parts,
- explicit state transitions,
- limited side effects,
- small testable units.

### 5.2 Human-in-the-Loop Boundary

No torrent submission may occur until the user explicitly confirms a recommendation.
The workflow must stop before download execution and require a separate confirmation action to continue.

### 5.3 Real Connectivity Before Mock Contracts

Although there is a reference project for the M-Team to qBittorrent chain, the integration still has uncertainty.
The project must first validate the actual behavior of:

- M-Team search,
- M-Team detail lookup,
- M-Team download URL generation,
- qBittorrent login,
- qBittorrent category listing,
- qBittorrent URL-based torrent submission.

Only after that real connectivity spike should mock data and adapter return contracts be frozen.

### 5.4 Early UI Shell

The chat page should be built early, using stubbed or mocked responses before the workflow is fully wired.
This allows product interaction testing in the browser before the entire backend is complete.

## 6. High-Level Architecture

The system should remain a single deployable application with clear internal boundaries.

```text
Chat Web UI
    |
FastAPI API Layer
    |
LangGraph Workflow
    |
Tools / Services
    |
Adapters / Stores
    |
SQLite + M-Team + qBittorrent
```

### 6.1 Web UI

Responsibilities:

- Render a chat-style single-page interface.
- Display user messages, assistant replies, ranked candidates, recommendation explanation, confirmation actions, and receipts.
- Provide the minimal actions required for Phase 1:
  - send message,
  - approve,
  - reject and refine,
  - cancel.

The UI does not perform business logic.

### 6.2 FastAPI Layer

Responsibilities:

- Expose a small HTTP API for chat, confirmation, session restore, and health checks.
- Translate browser requests into workflow events.
- Return a consistent session view model for the frontend.

### 6.3 LangGraph Workflow

Responsibilities:

- Own the shared workflow state for a session.
- Orchestrate the minimal search-confirm-download loop.
- Pause at confirmation.
- Resume on user feedback.
- Support a reject-and-refine cycle.

### 6.4 Tools / Services

Responsibilities:

- Expose a small set of callable capabilities to workflow nodes.
- Normalize inputs and outputs across adapters.
- Keep orchestration code from depending directly on low-level API details.

### 6.5 Adapters / Stores

Responsibilities:

- M-Team API integration.
- qBittorrent API integration.
- SQLite-backed persistence for sessions, preferences, and task index.

## 7. Recommended Module Layout

```text
app/
  main.py
  config.py

  api/
    chat_routes.py
    schemas.py

  workflow/
    graph.py
    state.py
    nodes.py

  tools/
    search_tools.py
    download_tools.py

  adapters/
    mteam.py
    qbittorrent.py

  domain/
    models.py
    scoring.py

  storage/
    db.py
    session_store.py
    preference_store.py
    task_index_store.py

  services/
    receipt_service.py

frontend/
  index.html
  app.js
  styles.css
```

This structure is intentionally small:

- `workflow` owns orchestration,
- `tools` expose capabilities,
- `adapters` talk to external systems,
- `storage` owns persistence,
- `domain` owns rules and data shapes.

## 8. Workflow Design

Phase 1 should use LangGraph as a stateful workflow engine, not as a free-form autonomous agent.
The purpose of LangGraph here is explicit control over:

- state transitions,
- pause/resume behavior,
- constrained tool usage,
- safe side-effect boundaries.

### 8.1 Minimal Shared State

The shared state should only include fields that later nodes actually need:

- `session_id`
- `user_message`
- `message_history`
- `constraints`
- `preference_snapshot`
- `search_results`
- `scored_results`
- `confirmation_payload`
- `confirmation_feedback`
- `selected_result`
- `download_target`
- `execution_result`
- `receipt`
- `error`

### 8.2 Workflow Nodes

#### `extract_constraints`

Uses the LLM to transform natural language into structured request data.
This includes both direct constraints and inferred situational signals.

#### `load_preferences`

Loads a small long-term preference profile from storage and merges it with the current request context.

#### `search_mteam`

Calls the M-Team adapter to retrieve candidate resources.

#### `score_results`

Applies deterministic ranking logic to the candidate list.

#### `build_confirmation_payload`

Builds the data returned to the frontend for the confirmation step.
It may use the LLM for explanation text, but the candidate order must come from deterministic scoring.

#### `await_confirmation`

Suspends the workflow before any external side effect.

#### `parse_confirmation_feedback`

Parses confirmation-stage user feedback such as:

- "not the TV version, I want the movie"
- "I want 4K"
- "do not use season packs"

This node updates constraints and prepares a new search cycle.

#### `execute_download`

Performs the fixed execution chain after approval:

1. fetch resource detail,
2. request download URL,
3. check duplicates,
4. submit to qBittorrent,
5. write task index,
6. persist execution result.

#### `build_receipt`

Builds a structured result for frontend display after execution or duplicate detection.

### 8.3 Minimal Graph Shape

```text
extract_constraints
  -> load_preferences
  -> search_mteam
  -> score_results
  -> build_confirmation_payload
  -> await_confirmation

await_confirmation
  -> approve -> execute_download -> build_receipt
  -> reject_and_refine -> parse_confirmation_feedback -> search_mteam
  -> cancel -> end
```

This graph is intentionally small.
It already demonstrates:

- natural language understanding,
- stateful orchestration,
- human confirmation,
- looped refinement,
- external tool use,
- controlled side effects.

## 9. LLM Usage Strategy

The system should use the LLM selectively.

### 9.1 LLM Responsibilities

- Interpret user natural language into structured constraints.
- Infer situational intent such as urgency and optimization goal.
- Parse natural language feedback during the confirmation stage.
- Generate a readable explanation of why a candidate was recommended.

### 9.2 Non-LLM Responsibilities

- M-Team API calls.
- qBittorrent API calls.
- Preference lookup.
- Session persistence.
- Duplicate detection.
- Core ranking score calculation.
- Receipt structure generation.

### 9.3 Design Principle

The LLM is responsible for understanding and explanation.
The program is responsible for retrieval, validation, execution, and persistence.

## 10. Data Model Design

Phase 1 only needs a minimal set of domain objects.

### 10.1 `SearchConstraints`

Represents what the user wants in the current request.

Suggested fields:

- `query_text`
- `title`
- `year`
- `media_type`
- `preferred_resolution`
- `allow_season_pack`
- `urgency`
- `optimization_goal`

Field intent:

- `urgency` captures time sensitivity such as "I want to watch tonight".
- `optimization_goal` captures whether ranking should favor:
  - `speed`,
  - `quality`,
  - `balanced`.

### 10.2 `PreferenceProfile`

Represents small long-term user preferences.

Suggested fields:

- `default_media_type`
- `preferred_resolution`
- `subtitle_preference`
- `encoding_preference`
- `default_download_profile`

This is enough to demonstrate long-term memory without building a full recommendation system.

### 10.3 `DownloadProfile`

Represents the internal target configuration for qBittorrent.

Suggested fields:

- `profile_name`
- `qb_category`
- `save_path`

The UI should not force the user to manipulate qBittorrent-specific terms directly.
The frontend can refer to these as a recommended resource type or save target, while the backend maps them to qB fields.

### 10.4 `ConfirmationFeedback`

Represents user feedback at the confirmation boundary.

Suggested fields:

- `feedback_type`
- `selected_result_id`
- `refinement_text`
- `updated_constraints`

Allowed `feedback_type` values in Phase 1:

- `approve`
- `reject_and_refine`
- `cancel`

### 10.5 `TaskIndexRecord`

Represents the mapping between the external M-Team resource and the qBittorrent task.

Suggested fields:

- `external_source`
- `external_id`
- `resource_title`
- `qb_hash`
- `qb_name`
- `qb_category`
- `created_at`
- `status`

This record is important because Phase 1 should not rely only on qB task naming conventions for deduplication.

### 10.6 `SessionRecord`

Represents the minimal persisted workflow state needed for confirmation and restore.

Suggested fields:

- `session_id`
- `latest_user_message`
- `constraints_json`
- `confirmation_payload_json`
- `status`
- `updated_at`

This session model is intentionally small.
Phase 1 only needs enough persistence to survive the confirmation boundary and allow page refresh restore.

## 11. Ranking Strategy

The ranking design is:

- rule-based core ranking,
- LLM-generated explanation of that ranking.

### 11.1 Core Ranking Factors

The deterministic ranking should consider:

1. title match,
2. media type match,
3. year match,
4. resolution preference match,
5. season-pack allowance,
6. availability/download-speed signals.

### 11.2 Availability and Speed Signals

The ranking must support time-sensitive user intent.

If the LLM infers that the user wants to watch soon, for example:

- "I want to watch tonight,"
- "I need a faster download,"
- "I want to watch it this evening,"

then the ranking should increase the weight of availability metrics such as current seeder count.

This rule must remain subordinate to basic relevance.
A highly seeded but clearly irrelevant result must not outrank a correctly matched result.

### 11.3 Explanation Strategy

The explanation should describe why a result was prioritized in user language, for example:

- title and media type alignment,
- better match for the requested resolution,
- more seeders when the user expressed urgency.

The LLM should not invent ranking factors that were not part of the deterministic scoring.

## 12. Tool, Adapter, and External Integration Design

### 12.1 Tool / Service Exposure

Phase 1 should keep the callable capability set small.

Suggested capabilities:

- `search_mteam_candidates`
- `prepare_confirmation_payload`
- `prepare_download_execution`
- `execute_qb_download`
- `build_receipt`

These are capability boundaries, not necessarily one-to-one wrapper functions for every adapter method.

### 12.2 M-Team Adapter

Required minimum behavior:

- search resources by keyword and optional filters,
- fetch resource detail by torrent ID,
- generate a one-time download URL from torrent ID.

The adapter should return normalized domain data rather than raw API responses.

### 12.3 qBittorrent Adapter

Required minimum behavior:

- authenticate with the qB Web API,
- list categories or profiles,
- add a torrent from a direct URL,
- support rename/category/tag inputs needed by the execution step.

### 12.4 Side-Effect Safety

Read-only or preparatory calls may occur before confirmation.
Actual download submission must only occur inside the post-approval execution node.

## 13. API and Frontend Interaction Design

The Phase 1 frontend uses plain HTML/CSS/JS and should remain minimal.

### 13.1 Frontend Responsibilities

The page should support:

- sending a chat message,
- showing ranked candidates,
- showing the recommendation explanation,
- showing a small set of confirmation actions,
- showing the final receipt or error state.

### 13.2 API Surface

Phase 1 should expose four endpoints:

- `POST /chat`
- `POST /confirm`
- `GET /session/{id}`
- `GET /health`

### 13.3 Confirmation Actions

`POST /confirm` should support:

- `approve`
- `reject_and_refine`
- `cancel`

### 13.4 Session View Model

The backend should return a frontend-friendly session representation with:

- `status`
- `messages`
- `confirmation_payload`
- `receipt`
- `error`

This keeps the frontend independent from internal graph details.

## 14. Configuration Strategy

Phase 1 should use environment variables or a local configuration file.
No web settings page is required in this phase.

Configuration should cover at least:

- M-Team host,
- M-Team API key,
- qBittorrent URL,
- qBittorrent username,
- qBittorrent password,
- SQLite database path,
- predefined download profiles.

## 15. Error Handling

Phase 1 should classify errors into four groups:

1. request understanding errors,
2. search-stage errors,
3. execution-stage errors,
4. internal system errors.

The user-facing error response should always tell the user:

- what step failed,
- whether anything was actually executed,
- what they can do next.

Duplicate detection should be treated as a structured result, not a crash path.

## 16. Testing Strategy

### 16.1 Connectivity Spike First

The project should start with a real-environment connectivity spike that validates:

- M-Team authentication,
- M-Team search,
- M-Team detail lookup,
- M-Team download URL generation,
- qBittorrent login,
- qBittorrent category listing,
- qBittorrent URL-based task submission.

This spike should happen before adapter contracts and mock data are finalized.

### 16.2 Mock-First Daily Development After Spike

After the connectivity spike, the main development loop should rely on mocks/stubs for:

- adapter behavior,
- workflow tests,
- API tests,
- UI stubbed responses.

### 16.3 Unit Tests

Priority unit test targets:

- ranking rules,
- duplicate detection logic,
- receipt assembly,
- constraint merge behavior.

### 16.4 Workflow Tests

Priority workflow test scenarios:

- successful search to confirmation flow,
- reject-and-refine loop,
- cancel flow,
- no-result search,
- duplicate detection result,
- execution failure path.

### 16.5 API Tests

Priority API tests:

- `POST /chat` response structure,
- `POST /confirm` action handling,
- `GET /session/{id}` restore behavior.

## 17. Delivery Plan

The implementation should proceed in small stages.

### Phase 0a: Real Connectivity Exploration

Deliverables:

- scripts or focused tests for M-Team and qBittorrent connectivity,
- notes on actual request/response behavior,
- confirmation of the real URL-based download chain.

### Phase 0b: Early Chat UI Shell

Deliverables:

- plain HTML/CSS/JS chat page,
- stubbed candidate list rendering,
- stubbed recommendation explanation,
- approve/reject/cancel controls.

This UI shell should exist before the full backend flow is complete.

### Phase 1: Adapter and Storage Skeleton

Deliverables:

- M-Team adapter,
- qBittorrent adapter,
- SQLite storage skeleton,
- session/preference/task index stores.

### Phase 2: Minimal Workflow Through Confirmation

Deliverables:

- constraint extraction,
- preference loading,
- M-Team search,
- deterministic ranking,
- confirmation payload generation,
- confirmation-state persistence.

### Phase 3: Confirmation Loop and Download Execution

Deliverables:

- feedback parsing,
- refined re-search loop,
- post-approval execution chain,
- duplicate detection,
- receipt generation.

### Phase 4: End-to-End UI Wiring

Deliverables:

- frontend connected to real API,
- session restore behavior,
- end-to-end demo of the complete loop.

## 18. Why This Scope Is Appropriate

This design is intentionally narrow enough for an early-career engineer to complete while still demonstrating strong portfolio value:

- LangGraph-based orchestration,
- explicit human-in-the-loop control,
- selective LLM use,
- external tool integration,
- recoverable state,
- practical engineering tradeoffs.

It avoids the common failure mode of building too much system surface area before one complete loop works reliably.

## 19. Current Environment Note

The current workspace does not appear to be an initialized Git repository, so this design document can be written locally but cannot be committed from this location until the project is placed inside a Git repo or initialized as one.
