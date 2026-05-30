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

## Phase 1: Runner Parity Tracer Bullet

Goal: make HelloAgents run the current search-confirm-download workflow without changing route contracts.

Tasks:

- [ ] Add `app/agent_runtime/runner.py` with `HelloAgentWorkflowRunner`.
- [ ] Add `app/agent_runtime/state.py` with minimal `WorkflowState`.
- [ ] Add HelloAgents tool wrappers for M-Team search and qB add.
- [ ] Add function-calling keyword extractor with the same output as `FindKeywordLLM`.
- [ ] Persist pending confirmation state using the existing SQLite storage layer.
- [ ] Add `tests/test_helloagents_runner.py`.
- [ ] Add a config switch to choose `langgraph` or `helloagents` runner.

Acceptance:

- `/chat` returns `status="awaiting_confirmation"` and a `ConfirmationPayload`.
- `/confirm approve` returns `status="completed"` and receipt.
- Existing API response models do not change.
- LangGraph remains available as fallback.

## Phase 2: Framework-Level HITL and Permission

Goal: move confirmation from business-specific route behavior into reusable HelloAgents runtime primitives.

Tasks:

- [ ] Add `ToolPermission` enum.
- [ ] Add default `Tool.permission`.
- [ ] Add `ToolStatus.PENDING_APPROVAL`.
- [ ] Add approval request/decision models.
- [ ] Add approval events to lifecycle.
- [ ] Teach `ToolRegistry` or runtime policy to block side-effect/destructive tools without approval.
- [ ] Convert qB add tool to `SIDE_EFFECT`.
- [ ] Add tests proving side-effect tools cannot execute before approval.

Acceptance:

- Read-only tools execute automatically.
- Side-effect tools produce pending approval unless approval exists.
- Destructive tools are blocked or require stricter confirmation.

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

