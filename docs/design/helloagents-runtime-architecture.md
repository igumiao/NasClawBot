# HelloAgents Runtime Architecture

## Overview

NasClawBot builds a lightweight runtime on top of HelloAgents to replace current LangGraph wiring.

This runtime design follows:

- [ADR 002: HelloAgents Runtime Migration](../adr/002-helloagents-runtime-migration.md)
- [ADR 003: NasClawBot Domain Decisions](../adr/003-nasclawbot-domain-decisions.md)

P0 focuses on search-confirm-download with structured tool protocol, permission levels, HITL approval, pause/resume, production persistence, error handling, function-calling keyword extraction, and stable FastAPI/frontend contracts.

## Runtime, Agent, Runner

```text
FastAPI route
  -> Runner
    -> Runtime
      -> Workflow steps
        -> Tools
        -> Agent / LLM decision units
```

`HelloAgentWorkflowRunner` is an application adapter, not an Agent.

## State Layers

```text
WorkflowEnvelope
SharedContext
DomainState
```

P0 uses `WorkflowEnvelope + SearchDownloadState`.

## Persistence

Runtime state uses `runtime_sessions`.

Agent conversation checkpoints, if needed later, use `agent_conversation_checkpoints`.

P0 does not use Agent conversation checkpoints.

## Approval

Download confirmation is represented internally as an approval request and externally as the current `ConfirmationPayload` API contract.

## Permissions

Tool permission defaults to `SIDE_EFFECT`; only explicit `READONLY` tools execute automatically.

## Errors

Empty search results are business outcomes, not runtime errors. External failures are tool/runtime errors. Side-effecting tools do not auto-retry.
