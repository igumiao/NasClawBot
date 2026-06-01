# ADR 002: HelloAgents Runtime Migration

## Status

Accepted (2026-05-30)

## Context

NasClawBot is migrating from the current LangGraph workflow implementation toward a lightweight runtime built on top of HelloAgents. The goal is to demonstrate direct understanding of Agent framework/runtime design while keeping the existing `/chat` and `/confirm` contracts stable during migration.

HelloAgents already provides useful Agent/Tool foundations, but it does not yet provide the runtime capabilities NasClawBot needs: permission policy, HITL approval, pause/resume, typed workflow state, production persistence, error handling, and workflow execution semantics.

Active product/domain decisions are maintained in [ADR 003: NasClawBot Domain Decisions](003-nasclawbot-domain-decisions.md). This ADR owns runtime/framework migration mechanics.

## Decisions

### Runtime / Agent / Runner

Runtime, Agent, and Runner are layered collaborators:

```text
FastAPI route
  -> Runner
    -> Runtime
      -> Workflow steps
        -> Tools
        -> Agent / LLM decision units
```

`HelloAgentWorkflowRunner` is not an Agent. P0 search-confirm-download remains a fixed workflow and only calls Agent/LLM units where needed.

### Framework / Application Boundary

If a module would still make sense copied into another Agent application, it belongs in `hello_agents`. If it mentions NAS, media, M-Team, qBittorrent, Emby, candidates, download confirmation, or current API response models, it belongs in `app`.

### State Expansion Strategy

Do not jump from P0 state to the full ADR 001 `AgentState`. State expands in three layers:

```text
WorkflowEnvelope
SharedContext
DomainState
```

Workflow-only fields stay in `DomainState`. Shared concepts move to `SharedContext` only when two or more workflows need them. Recovery, safety, approval, trace, and error fields belong in `WorkflowEnvelope`.

### Confirmation / Approval Relationship

Approval is runtime safety. Confirmation is app-level user interaction payload.

P0 keeps API `status="awaiting_confirmation"` and `confirmation_payload`. Internally this maps to `WorkflowStatus.AWAITING_APPROVAL` with `approval_type="download_confirmation"`.

### Session Persistence Strategy

Production HTTP workflow persistence is runtime-owned and SQLite-backed.

`HelloAgentWorkflowRunner` must disable HelloAgents JSON conversation checkpointing for P0 production workflows:

```python
Config(
    session_enabled=False,
    auto_save_enabled=False,
)
```

Runtime state uses `runtime_sessions`, backed by `app/storage/db.py`.

Agent conversation checkpointing is a separate optional concern. If Phase 2 Agent loops need cross-request message history, introduce an `AgentConversationStore` protocol and an app-level SQLite implementation named `agent_conversation_checkpoints`.

### Tool Permission Default Policy

Tool permission defaults are conservative:

```text
READONLY     -> execute automatically
SIDE_EFFECT  -> require approval
DESTRUCTIVE  -> require stricter approval or reject in P0
```

`Tool.permission` defaults to `ToolPermission.SIDE_EFFECT`. Only explicitly declared `READONLY` tools may execute automatically.

### Error Handling Policy

Runtime error handling distinguishes business outcomes from execution failures.

- Empty search results are not runtime errors.
- External system failures are tool/runtime errors.
- Side-effect and destructive tools are not automatically retried.
- Read-only tools may be retried for transient failures.
- Ambiguous side-effect outcomes require human inspection rather than automatic retry.

### Keyword Extraction Function Calling

Function-calling keyword extraction is included in Phase 1, but it does not block runner parity.

The P0 output contract remains:

```json
{"keyword": "沙丘2"}
```

Full media request extraction belongs with Phase 2 shared media context.

## Migration Strategy

- Keep current FastAPI/frontend contracts unchanged.
- Add `HelloAgentWorkflowRunner` alongside `LangGraphWorkflowRunner`.
- Use search-confirm-download as the first tracer bullet.
- Switch default runner only after parity tests pass.
- Remove LangGraph only after production wiring no longer imports it.

