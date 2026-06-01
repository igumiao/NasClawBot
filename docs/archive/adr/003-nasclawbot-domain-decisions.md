# ADR 003: NasClawBot Domain Decisions

## Status

Accepted (2026-05-30)

## Context

ADR 001 mixed two kinds of decisions:

- framework implementation decisions from the LangGraph era
- domain/product decisions that remain valid for NasClawBot

ADR 002 supersedes the LangGraph-specific runtime implementation. This ADR preserves the active domain decisions so readers do not need to mine a legacy document to understand the current product architecture.

## Decisions

### Single Agent + Multiple Tools First

NasClawBot remains a single-Agent, multiple-Tool system for the near term.

Multi-agent decomposition is deferred until there is real pressure from tool count, prompt length, independent state spaces, or conflicting goals that need coordination. Planner/Library/Recommendation/Subscription roles are currently better treated as workflow/tool areas than as separate autonomous Agents.

### Fixed Workflow + Local LLM Decision Units

Predictable side-effecting flows use fixed workflows. LLMs are used for local ambiguity-handling tasks such as structured extraction, ranking, candidate judgement, and explanation.

Downloads, subscriptions, organization, and destructive actions should not be controlled by an open-ended ReAct loop.

### Fine-Grained Reads, Coarse-Grained Writes

Read tools can be fine-grained because they are low risk and useful for flexible reasoning.

Write or side-effect tools must be coarse-grained and confirmation-aware. They should encapsulate transaction boundaries, permission checks, receipts, rollback or inspection guidance, and logging.

Examples:

- Read tools: search M-Team, query Emby, search TMDB, inspect qB tasks.
- Write tools: add torrent, apply organize plan, create subscription, save preference.

### Candidate Resolver Is a Distinct Concept

Candidate disambiguation happens after search results exist. The system should not ask the LLM to guess ambiguity before seeing candidates.

Candidate resolution combines deterministic rules and, when needed, an LLM judge:

- score gaps
- near-duplicate titles
- conflicting media types
- region/year/title ambiguity
- user clarification mapping

The LLM judge may decide whether clarification is needed and how to ask, but it must not bypass safety rules.

### Memory Is Structured First

Memory should begin with structured storage:

- explicit preferences
- avoidance rules
- quality preferences
- behavior events
- user profile summary
- workflow preferences

Vector or semantic memory is deferred until structured memory proves insufficient. Memory context should be intent-aware and compact; it should not dump full chat history or full task history into prompts.

### TMDB Is the Default Metadata Source

TMDB remains the default external metadata API for movie/TV metadata because it is stable, accessible, and broadly useful for Chinese and international media lookup.

Other metadata sources can be added later only when a workflow proves the need.

### File Organization Uses Detect -> Report -> Confirm -> Execute

File organization must not expose raw file mutation tools directly to an Agent loop.

The workflow is:

```text
scan/detect
  -> generate organize report/plan
  -> human confirmation
  -> execute approved plan
```

Destructive or irreversible file operations require stricter approval than ordinary side-effect tools.

### V1 Notifications Are Web-Only

V1 notifications are shown in the Web UI.

Telegram, WeChat, email, and other external notification channels are deferred until the Web workflow is stable.

### Emby Is a Read-Only Query Layer

Emby is used as a read-only media library query layer. It is not responsible for scraping in NasClawBot's architecture; scraping remains owned by the NAS/media environment.

If Emby is unavailable, the fallback is a filesystem or index scan workflow.

## Consequences

- ADR 001 is now historical context for the LangGraph-era architecture discussion.
- ADR 002 owns the active HelloAgents runtime migration.
- This ADR owns active NasClawBot domain architecture decisions.
- Future implementation plans should reference ADR 002 for runtime mechanics and ADR 003 for product/domain constraints.
