# HelloAgents Framework Reference

This document is the active reference for developing NasClawBot on top of
HelloAgents. It describes what the framework already provides, where the
boundaries are, and which parts should be extended instead of replaced.

## Why This Exists

NasClawBot is not trying to bypass HelloAgents with a separate agent framework.
The goal is to use NasClawBot requirements to drive second-phase development of
HelloAgents itself.

When a new runtime concept is needed, prefer this order:

1. Reuse an existing HelloAgents component.
2. Extend the HelloAgents component if the concept is framework-level.
3. Add an app-level adapter only when the concept is specific to NasClawBot.

## Current Active App Baseline

The active NasClawBot app is intentionally simple:

```text
/chat
  -> readonly M-Team search
  -> search results

/download
  -> explicit user action
  -> M-Team detail/token
  -> qB add paused
```

There is currently no active workflow runtime, no `/confirm` route, no
`confirmation_payload`, or production workflow runner. An experimental
cross-request Agent loop is active alongside `/chat`:

```text
/chat/agent
  -> NasClawAgentRunner
  -> ToolCallingAgent
  -> mteam_search + member_profile + confirm-gated qb_add_torrent
  -> JSON ConversationCheckpointStore
```

Readonly tools execute automatically. Side-effect tools remain behind `Gate`
approval and qB submissions remain paused by default.

## Module Map

```text
hello_agents/
  core/
    agent.py             Base Agent: history, compression, tracing, tools, sessions
    llm.py               Unified LLM facade
    llm_adapters.py      OpenAI / Anthropic / Gemini-compatible adapters
    message.py           Internal message object
    session_store.py     JSON file session persistence
    lifecycle.py         Lifecycle event hooks
    streaming.py         Streaming event model

  agents/
    tool_calling_agent.py
                         Production-oriented tool-calling preset
    teaching_react_agent.py
                         Teaching-oriented function-calling ReAct loop
    simple_agent.py      Basic one-shot agent
    reflection_agent.py  Reflection-style agent
    plan_solve_agent.py  Plan/solve style agent

  tools/
    base.py              Tool base class and parameters
    registry.py          Tool registration and lookup
    response.py          ToolResponse and ToolStatus
    filter.py            Tool allow/deny filtering
    gate.py              Tool execution gate concepts
    circuit_breaker.py   Failure protection

  context/
    history.py           Append-only HistoryManager with compression
    token_counter.py     Token estimation and cache
    truncator.py         Tool output truncation
    window_manager.py    Preflight context-window checks and compression
    builder.py           GSSC context builder, currently incomplete

  observability/
    trace_logger.py      JSONL / HTML trace output

  skills/
    loader.py            Skill file loading
```

## Existing Framework Capabilities

### Agent Base

`hello_agents/core/agent.py` is more capable than a minimal abstract base class.
It already owns several runtime-adjacent concerns:

- `HistoryManager`
- token counting and compression checks
- `ContextWindowManager` for preflight model-input compression
- tool schema construction
- tool execution helpers
- trace logging
- optional session persistence
- optional skills, subagents, todo, and devlog registration

The key point: if a new Agent loop needs history, compression, tracing, tool
schema building, or session persistence, the first move should be to reuse or
extend `Agent`, not create a parallel object model.

### SessionStore

`hello_agents/core/session_store.py` already provides session persistence:

- JSON file storage
- atomic write through temporary file + replace
- session listing
- config consistency checks
- tool schema hash consistency checks
- read cache restoration

`Agent.save_session()` and `Agent.load_session()` already integrate it with
`HistoryManager`.

Therefore, do not introduce a separate `AgentSession` just to represent normal
conversation persistence. The framework already has a session concept.

Use one of these names instead, depending on the need:

- `SessionStore`: existing persistence implementation.
- `HistoryManager`: in-memory message history.
- `ExecutionContext`: per-run execution metadata.
- `AgentRuntime`: long-running service/task coordinator, if added.
- `ConversationCheckpointStore`: durable cross-request conversation store
  boundary. NasClawBot currently uses a JSON-backed implementation and can add
  SQLite later without changing the route contract.

### ReActAgent

`hello_agents/agents/teaching_react_agent.py` implements a function-calling
ReAct loop:

```text
build messages
build tool schemas
while step < max_steps:
  call LLM with tools
  if text-only response:
    save user/assistant messages
    return
  append assistant tool_calls
  execute tool_calls
  append tool results
```

It also defines `Thought` and `Finish` as built-in tools.

This is a valid inner Agent loop. It is not yet a full product runtime because
cross-request task control, approval pause/resume, durable server session
management, and permission policy are not first-class concepts.

### ToolCallingAgent

`hello_agents/agents/tool_calling_agent.py` is the production-oriented preset
for a normal tool-calling assistant. It does not add teaching ReAct conventions
such as `Thought` and `Finish`.

It delegates loop mechanics to `hello_agents/loop/tool_calling_loop.py`.

Related design notes:

- [Agent Loop Improvement Notes](agent-loop-improvement-notes.md)

### Tool Schema And M-Team Search Boundary

`ToolParameter` supports optional enum values, allowing app tools to give the
LLM a constrained JSON Schema without exposing provider-specific API fields.
Runtime validation still belongs in the concrete tool because schema guidance
alone does not guarantee valid model arguments.

The current Agent-facing `mteam_search` surface is:

```text
keyword?   sort_by?   imdb?   douban?
```

It intentionally does not expose M-Team pagination, categories, discounts,
raw sort fields, media modes, or local hard filters. The tool always uses
M-Team `normal` mode. The app adapter maps the semantic sort presets to M-Team
fields, returns the full first-page pool, and the tool returns at most 10
normalized candidates.

This is an app-level boundary:

- provider request/response semantics and normalization belong in
  `app/adapters/mteam.py`
- Agent-facing parameters, runtime validation, and the 10-result product limit
  belong in `app/tools/mteam_search.py`
- reusable JSON Schema enum support belongs in `hello_agents/tools/base.py`

## Important Distinctions

### SessionStore vs AgentRuntime

`SessionStore` answers:

```text
How do I save and restore an Agent's history/config/cache?
```

`AgentRuntime` would answer:

```text
How do I accept tasks, cancel them, resume approvals, coordinate concurrent
sessions, persist task status, and expose stable service-level APIs?
```

These are different layers. A future `AgentRuntime` should use `SessionStore`
or a compatible store; it should not duplicate session persistence.

### History vs Business State

HelloAgents history stores conversation messages.

NasClawBot business state is different:

- selected torrent
- candidate search results
- pending approval
- qB receipt
- user preference
- active media task

Do not hide business state inside chat history. Business state should live in
typed app/domain models or a framework-level typed runtime state if that is
added to HelloAgents.

### Tool Loop vs Workflow

`ReActAgent` is good for:

- readonly search and lookup
- dynamic tool composition
- exploratory reasoning
- structured extraction through function calling

Fixed workflows are better for:

- download confirmation
- write operations
- file organization
- destructive actions
- routes with strict frontend/API contracts

For NasClawBot, readonly tools can execute automatically. Side-effecting
actions should go through explicit approval.

## Gaps To Extend In HelloAgents

### 1. Permission Policy

`ToolCallingLoop` now supports two policy layers:

```text
Filter -> before model call, controls visible tool schemas
Gate   -> after model tool_call, before tool.run()
```

The current Gate result handling is deliberately thin:

```text
ALLOW    execute tool
DENY     do not execute; return PERMISSION_DENIED observation
ASK_USER do not execute; return awaiting_approval and pending approval data
```

Future framework-level permission metadata can sit on top of this:

```text
READONLY      auto executable
SIDE_EFFECT   approval required
DESTRUCTIVE   stricter approval or unavailable to open loops
```

NasClawBot mapping:

```text
mteam_search        READONLY
mteam_detail        READONLY
mteam_download_url  SIDE_EFFECT or gated readonly, depending on site semantics
qb_add_torrent      SIDE_EFFECT, paused by default
file delete/move    DESTRUCTIVE, do not expose to open Agent loop
```

### 2. Approval Pause/Resume

HelloAgents should support a general human-in-the-loop state:

```text
tool call requested
  -> policy says approval required
  -> emit approval_required
  -> persist pending approval
  -> pause run
  -> external decision arrives
  -> resume or reject
```

This belongs in the framework because many tools can need it, not just
NasClawBot downloads.

Current status: the framework loop has an MVP pause/resume path for `ASK_USER`.
The loop returns `ToolCallingLoopResult.pending_approvals`, stores
`paused_loop` resume state, and records gate markers on `ToolObservation`.
NasClawBot persists `metadata["pending_approvals"]` for UI/lifecycle recovery
and `metadata["paused_loop"]` for provider protocol resume.

For `qb_add_torrent`, approve validates the paused provider tool call against
the application approval record, executes the saved tool arguments, appends the
provider `tool` result with the original `tool_call_id`, and resumes the LLM
with `tool_choice="none"`. Deny resumes with a `USER_DENIED` tool error without
executing the tool. The deterministic approval summary path remains as a
compatibility fallback for legacy checkpoints without `paused_loop`.

Application-level approval records currently live in `app/agent/approvals.py`,
not the HelloAgents framework. They add lifecycle fields such as `expires_at`,
`expired_at`, `decision`, `result`, `error`, and enum-backed `risk` while
keeping JSON checkpoint storage. Broader framework-level policy is still open:
the current branch supports one pending approval at a time, rejects new user
messages while a non-expired approval is pending, resolves expired approvals
before the next turn without executing the tool, and treats multiple
simultaneous `ASK_USER` calls as a controlled conflict.

NasClawBot currently serializes `run/approve/deny` per session inside one
server process. Cross-process approval coordination remains outside the JSON
checkpoint store's guarantees and belongs in a future transactional store.

### 3. Durable Server Conversation Store

The current `SessionStore` is useful for local/demo/development. For the
FastAPI Agent route, cross-request recovery now goes through a thinner
checkpoint boundary:

```python
class ConversationCheckpointStore:
    def load(self, session_id: str): ...
    def save(self, checkpoint): ...
    def list(self): ...
    def delete(self, session_id: str): ...
```

Current implementation:

- JSON-backed `JSONConversationCheckpointStore`
- `NasClawAgentRunner` loads/saves checkpoints around one Agent turn

Future implementation:

- SQLite implementation for session listing, stronger durability, and better
  server coordination

```python
run_conversation(session_id, user_message)
  -> load checkpoint
  -> restore history
  -> run LLM/tool loop
  -> save checkpoint
```

This preserves the framework abstraction and avoids inventing an app-only
`AgentSession`.

### 4. Context Builder

`ContextBuilder` exists, but it is currently not ready to be the main context
engineering layer. It should be either completed or narrowed.

Expected responsibilities:

- gather system prompt, current task, recent history, memory, and tool evidence
- select according to relevance and budget
- structure into model input
- compress before context pressure becomes failure

### 5. Interruptible API Calls

A coding-agent-style loop needs cancellation around model calls and tool calls.
This is a runtime concern, not just a ReAct concern.

The framework should expose cancellation semantics at the task/runtime layer.

## Recommended Development Direction

### Phase 1: Document And Align

Keep this file as the active reference. When a new concept is proposed, classify
it as one of:

- existing HelloAgents capability
- HelloAgents framework extension
- NasClawBot app adapter
- archived design no longer active

### Phase 2: Minimal Agent Loop

Implemented a small gated loop using existing pieces:

- `Agent` base where possible
- `HistoryManager`
- `ToolRegistry`
- `ToolResponse`
- `ToolObservation` as the loop envelope around structured `ToolResponse`
- `HelloAgentsLLM.invoke_with_tools`
- `ConversationCheckpointStore` for cross-request persistence

Current tool set:

```text
mteam_search        READONLY
member_profile      READONLY
qb_add_torrent      SIDE_EFFECT, confirm-gated
```

Do not add ungated qB write tools to the open loop.

### Phase 3: Framework-Level Policy And Approval

The initial Filter/Gate and pause/resume path is implemented. Future refinement
may extend HelloAgents with:

- richer permission metadata
- broader approval events and policy composition
- multiple pending approvals or stronger runtime coordination
- tests against side-effect tool execution

### Phase 4: Durable Runtime Store

Cross-request recovery now has a store protocol and JSON implementation. Add a
SQLite implementation later when session listing, approval pause/resume, or
server coordination needs it. Keep compatibility with `SessionStore` instead of
replacing it.

## Naming Guidance

Avoid introducing `AgentSession` unless it has a meaning distinct from the
existing `SessionStore` and `HistoryManager`.

Preferred names:

- `ConversationCheckpoint`: serialized conversation/history snapshot
- `ConversationCheckpointStore`: storage protocol
- `RuntimeTask`: externally submitted task
- `RuntimeState`: pause/resume/cancel/status state
- `ApprovalRequest`: user decision request
- `ApprovalDecision`: user decision result

## Design Rule

When in doubt:

```text
Conversation persistence belongs to HelloAgents.
Business state belongs to NasClawBot domain models.
Task orchestration belongs to a runtime layer that reuses HelloAgents.
Tool permissions belong to HelloAgents because tools are framework concepts.
```
