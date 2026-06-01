# HelloAgents Migration Plan

## Goal

Replace the current LangGraph workflow implementation with a NasClawBot-specific runtime built on top of HelloAgents, while preserving existing API/frontend behavior during migration.

## Phase 0: Capability Audit

Status: Done.

Deliverables:

- `report/07-HelloAgents框架能力审计.md`
- `docs/adr/002-helloagents-runtime-migration.md`
- `docs/adr/003-nasclawbot-domain-decisions.md`
- `docs/design/helloagents-runtime-architecture.md`
- `docs/plan/helloagents-migration-plan.md`

Decisions:

- Keep single Agent + multiple Tool as the near-term architecture.
- Do not use ReActAgent as the P0 download workflow controller.
- Build a small runtime/runner layer first.
- Keep LangGraph until HelloAgents runner reaches parity.

## Phase 1: Runner Parity Tracer Bullet (DONE)

Goal: make HelloAgents run the current search-confirm-download workflow without changing route contracts.

### Tactical Decisions

These implementation-level decisions are resolved before coding starts. They do not belong in ADRs but are recorded here so Phase 1 tasks have unambiguous targets.

#### Config Switch

Use a Settings field, not a bare environment variable:

```python
# app/config.py
workflow_runner: Literal["langgraph", "helloagents"] = "langgraph"
```

Route layer reads `settings.workflow_runner` and picks the runner. Default stays `"langgraph"` until Phase 5 cutover.

#### Runtime Sessions SQLite Schema

Extend `app/storage/db.py` `initialize_schema()` with:

```sql
CREATE TABLE IF NOT EXISTS runtime_sessions (
    session_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'in_progress',
    current_workflow TEXT NOT NULL DEFAULT 'search_download',
    domain_state_json TEXT,
    pending_approval_json TEXT,
    confirmation_payload_json TEXT,
    tool_trace_json TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

No foreign key to the existing `sessions` table — `runtime_sessions` replaces it for workflow state. The legacy `sessions` table is left untouched until Phase 5 cleanup.

`pending_approval_json` is the source of truth for approval state. `confirmation_payload_json` is a compatibility/debug projection of the API-visible confirmation payload. `tool_trace_json` holds serialized `ToolCallRecord` entries.

#### State Shapes

**SearchDownloadState** — domain state owned by the search-confirm-download workflow:

```python
# app/agent_runtime/state.py

class SearchDownloadState(TypedDict, total=False):
    user_message: str
    keyword: str
    search_results: list[ResourceCandidate]
    confirmation_payload: ConfirmationPayload | None
    receipt: dict[str, Any] | None
```

**WorkflowEnvelope** — runtime-owned envelope wrapping domain state:

```python
class WorkflowStatus(Enum):
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    CANCELED = "canceled"
    ERROR = "error"

class ApprovalState(TypedDict):
    approval_type: str                   # "download_confirmation"
    tool_name: str                       # which tool triggered the approval
    permission: str                      # SIDE_EFFECT | DESTRUCTIVE
    confirmation_payload: dict[str, Any] # serialized ConfirmationPayload
    resolved: bool
    resolved_at: str | None
    created_at: str

class WorkflowEnvelope(TypedDict):
    session_id: str
    status: str                          # WorkflowStatus value
    domain: SearchDownloadState | None
    pending_approval: ApprovalState | None
    error: str | None
    tool_trace: list[dict[str, Any]]
```

P0 uses `WorkflowEnvelope + SearchDownloadState`. `SharedContext` is a Phase 2 concern and is not added to the envelope yet.

#### Tool Wrapper Design

M-Team search and qB add are wrapped as HelloAgents `Tool` subclasses. Permission is declared on the class:

```python
# hello_agents/tools/permissions.py

class ToolPermission(Enum):
    READONLY = "readonly"
    SIDE_EFFECT = "side_effect"
    DESTRUCTIVE = "destructive"
```

```python
# app/agent_runtime/tools.py

class MTeamSearchTool(Tool):
    permission = ToolPermission.READONLY
    # wraps app/adapters/mteam.py MTeamAdapter.search_torrents_by_keyword()

class QBAddTorrentTool(Tool):
    permission = ToolPermission.SIDE_EFFECT
    # wraps mteam detail + genDlToken + qB add, paused by default
```

`Tool.permission` defaults to `ToolPermission.SIDE_EFFECT` in the base class (per ADR 002).

#### Test Strategy

New test file `tests/test_helloagents_runner.py` covers:

1. **Behavioral parity**: same `(session_id, message)` → both runners produce equivalent `ConfirmationPayload` candidates and receipt shape. Comparison is on externally visible fields (status, candidate count, receipt keys), not internal state.
2. **Approval guard**: side-effect tool cannot execute without a resolved approval.
3. **Persistence round-trip**: pending approval survives save → load → resume.

Existing tests (`test_workflow.py`, `test_chat_api.py`, `test_find_keyword_llm.py`) continue to pass against the LangGraph runner throughout Phase 1. These tests are coupled to LangGraph internals (`build_workflow`, graph state shape) and are not expected to run against the HelloAgents runner directly. HelloAgents runner has its own dedicated parity and smoke tests.

---

### Task Checklist

Tasks are ordered by dependency. Tasks on the same level can be done in parallel.

#### Level 1 — Foundation (no dependencies)

- [x] **1.1** Add `ToolPermission` enum to `hello_agents/tools/permissions.py`. Add `permission` field to `Tool` base class, default `SIDE_EFFECT`.

- [x] **1.2** Add `runtime_sessions` DDL to `app/storage/db.py` `initialize_schema()`. Add a thin `RuntimeSessionStore` in `app/storage/runtime_session_store.py` with `save(session_id, envelope)` / `load(session_id)` / `delete(session_id)`.

- [x] **1.3** Add `app/agent_runtime/state.py` with `SearchDownloadState`, `WorkflowEnvelope`, `ApprovalState`, and `WorkflowStatus`.

- [x] **1.4** Add function-calling keyword extractor in `app/agent_runtime/keyword.py`. Keeps the same `invoke(message) -> dict` interface. Uses `HelloAgentsLLM.invoke_with_tools(tool_choice="auto")` because DeepSeek V4 thinking mode rejects `"required"`. Existing `FindKeywordLLM` remains available for the LangGraph fallback path.

#### Level 2 — Tools (depends on 1.1)

- [x] **2.1** Add `app/agent_runtime/tools.py` with `MTeamSearchTool(Tool)` and `QBAddTorrentTool(Tool)`. These wrap existing adapter calls inside `Tool.run() -> ToolResponse`.

#### Level 3 — Runtime (depends on 1.2, 1.3)

- [x] **3.1** Add `hello_agents/runtime/workflow.py` with a generic `SequentialWorkflow` that accepts a list of steps and a `WorkflowEnvelope`, executes steps in order, stops at terminal statuses (`awaiting_approval`, `error`, `completed`, `canceled`), and returns the envelope. No NasClawBot-specific logic.

- [x] **3.2** Add `app/agent_runtime/runner.py` with `HelloAgentWorkflowRunner` implementing the same `WorkflowRunner` protocol as `LangGraphWorkflowRunner`. Methods:

  - `run_chat(session_id, message)` — creates envelope, runs keyword → search → build_confirmation steps, persists pending approval, returns dict with `status` and `confirmation_payload`.
  - `run_confirm(session_id, action, confirmation_payload, selected_result_id)` — loads envelope, validates four-layer approval guard, runs execute_download step, persists result, returns dict with `status` and `receipt`.

  Internal status (`awaiting_approval`) is mapped to API status (`awaiting_confirmation`) via `_STATUS_TO_API` at the runner boundary.

#### Level 4 — Wiring (depends on 3.2)

- [x] **4.1** Add `workflow_runner` field to `app/config.py` Settings, default `"helloagents"`.

- [x] **4.2** Update `app/api/chat_routes.py` `_build_default_runner()` to read `settings.workflow_runner` and instantiate the correct runner. `WorkflowRunner` protocol already matches both.

#### Level 5 — Tests (depends on 3.2, can start after 3.1)

- [x] **5.1** Add `tests/test_helloagents_runner.py` (26 tests): tool permissions, search tool, SequentialWorkflow, build_confirmation step, execute_download step, runner chat/confirm, approval guards, config switch, runner protocol.

- [x] **5.2** Add API-boundary tests in `tests/test_chat_api.py` (4 tests): HelloAgents runner exercised through actual FastAPI `/chat` and `/confirm` endpoints. Existing full test suite passes — 113 passed, 0 failures, 2 skipped.

---

### Acceptance (all met)

- [x] `/chat` returns `status="awaiting_confirmation"` and a `ConfirmationPayload`.
- [x] `/confirm approve` returns `status="completed"` and receipt.
- [x] Existing API response models do not change.
- [x] LangGraph remains available as fallback.
- [x] `tests/test_helloagents_runner.py` passes (26 tests).
- [x] API-boundary tests pass (4 tests in `test_chat_api.py`).
- [x] Existing full test suite passes — no regressions (113 passed, 0 failures).
- [x] Config-switch tests verify app can instantiate and route to either runner.

## Phase 2: Harden and Generalize HITL and Permission

Goal: harden the Phase 1 approval primitives into production-grade, reusable framework mechanisms.

### Phase 1 → Phase 2 Handoff Notes

These are implementation realities discovered during Phase 1 that affect Phase 2 design. Do not re-litigate these decisions — build on them.

**Approval guard lives in the runner, not the framework.** Phase 1 implements a four-layer manual guard in `run_confirm()`: session exists, status is `awaiting_approval`, not already resolved, `approval_type` matches. Phase 2 should move these checks into the runtime policy layer so they apply automatically to any tool with `SIDE_EFFECT` or `DESTRUCTIVE` permission, without each workflow step repeating them.

**`confirmation_payload_json` is a derived column, not a source of truth.** `RuntimeSessionStore.save()` derives the top-level `confirmation_payload` from `domain["confirmation_payload"]` during save. The source of truth lives in `domain`. Phase 2 should keep this pattern — any new projections should derive from `domain`, not exist as independent top-level fields.

**Domain state stores dicts, not Pydantic objects.** `json.dumps()` fails on Pydantic model instances. All state written to `domain` must be plain dicts (via `.model_dump()`). Phase 2 tool output contracts and `MediaRequest` models must account for this — serialize before storing.

**`SequentialWorkflow` is intentionally simple.** It executes steps in order and halts at terminal statuses. It has no branching, no parallelism, no retry, no middleware hooks. Phase 2 should NOT expand `SequentialWorkflow` into a full workflow engine. Instead, add permission-checking middleware at the Runtime layer (before steps execute) or at the Tool execution layer.

**Approval state is a TypedDict, not a model.** `ApprovalState` is a plain dict shape. Phase 2 should replace it with proper `ApprovalRequest`/`ApprovalDecision` Pydantic models with an explicit resolution lifecycle (pending → approved | rejected). The `pending_approval_json` column can remain; just the in-memory representation should become typed.

**`reject_and_refine` is still blocked at the route layer.** The `/confirm` route returns `"Phase 2A does not support reject_and_refine"` before reaching the runner. Phase 2 should either implement true state merge (load existing envelope, refine keyword, re-search) or explicitly defer to Phase 3.

**Zero results returns `awaiting_approval`, not error.** When M-Team returns no candidates, the runner builds an empty `ConfirmationPayload` with status `awaiting_approval` — matching the old LangGraph behavior. Phase 2's UI should handle empty payloads gracefully (show "no results found, try refining" message).

**Internal→API status mapping is a runner responsibility.** `_STATUS_TO_API` maps `awaiting_approval` → `awaiting_confirmation`, etc. Phase 2 should keep this boundary — the Runtime speaks internal statuses; the Runner translates to API contract statuses. Never leak internal status strings to API responses.

**DeepSeek V4 thinking mode rejects `tool_choice="required"`.** Keyword extraction uses `tool_choice="auto"`. For any Phase 2 tool-calling Agent work, always test with `tool_choice="auto"` first; only use `"required"` if the model consistently fails to call tools, and be prepared to handle the 400 error.

### Tasks

Phase 1 already delivers `ToolPermission`, `Tool.permission`, `ToolStatus.PENDING_APPROVAL`, and basic approval guard behavior. Phase 2 generalizes these into deeper runtime integration.

- [ ] Generalize `ApprovalState` → `ApprovalRequest` / `ApprovalDecision` Pydantic models with explicit resolution lifecycle (pending → approved | rejected, with timestamps).
- [ ] Add approval events (`APPROVAL_REQUIRED`, `APPROVAL_RESOLVED`) to `hello_agents/core/lifecycle.py` `EventType`.
- [ ] Move approval guard logic from `runner.run_confirm()` into a Runtime policy layer — side-effect tools are automatically blocked pre-execution without manual guard code per workflow step.
- [ ] Add stricter confirmation path for `DESTRUCTIVE` tools (double-confirm or reject in P0).
- [ ] Convert any remaining ad-hoc confirmation checks to use the generalized approval flow.
- [ ] Implement `reject_and_refine` with true state merge (load envelope → refine keyword from feedback → re-search → build new confirmation).
- [ ] Handle empty `ConfirmationPayload` in frontend (show "no results" UI instead of blank cards).
- [ ] Add tests proving side-effect tools cannot execute before approval is resolved, and destructive tools are blocked.

### Acceptance

- Read-only tools execute automatically via runtime policy, not per-workflow code.
- Side-effect tools produce pending approval unless an approval decision exists.
- Destructive tools are blocked or require stricter confirmation.
- Approval lifecycle events are emitted and traceable.
- `reject_and_refine` triggers a new search within the same session.

## Phase 3: Structured Extraction and Tool Data Contracts

Goal: expand from P0 keyword extraction to richer structured media and tool data contracts.

Tasks:

- [ ] Expand keyword extraction toward `MediaRequest` when `SharedMediaContext` is introduced.
- [ ] Add Pydantic input/output models for key tools.
- [ ] Ensure `ToolResponse.data` is the business data source.
- [ ] Keep `ToolResponse.text` for LLM-readable summaries only.
- [ ] Add tests for malformed model/tool output.

Acceptance:

- Media request extraction no longer depends on regex fallback in the primary path.
- Search candidates and receipt data are carried through structured objects.

## Phase 4: Runtime Persistence and Observability

Goal: make the runtime service-friendly.

Tasks:

- [ ] Extend SQLite schema for approval/session runtime state.
- [ ] Align HelloAgents trace session id with NasClawBot `session_id`.
- [ ] Replace framework print calls on the production path with logger calls.
- [ ] Add tool trace records to response/debug surfaces where useful.

Acceptance:

- A pending confirmation can survive process-local object loss if stored state exists.
- Logs and traces can reconstruct a workflow run.

## Phase 5: Default Cutover and LangGraph Removal

Goal: make HelloAgents the default runner.

Tasks:

- [ ] Flip default runner to HelloAgents after parity.
- [ ] Keep a temporary fallback switch for one release.
- [ ] Remove LangGraph imports from production wiring.
- [ ] Remove `langgraph`, `langchain`, and `langchain-openai` dependencies when no longer used.
- [ ] Retire or archive `app/workflow/graph.py` if all behavior moved.

Acceptance:

- Test suite passes without LangGraph.
- Production route wiring no longer imports LangGraph.

## Deferred

- Multi-agent DAG orchestration.
- Semantic/vector memory.
- AgentRuntime background worker.
- Subscription and organize workflows.
- Frontend workflow debugger.

