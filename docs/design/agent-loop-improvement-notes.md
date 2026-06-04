# Agent Loop Improvement Notes

This is an active idea log for improving NasClawBot's HelloAgents-based Agent
Loop. It is not a finalized implementation plan.

The goal is to preserve the design thinking while leaving details open until
the relevant topic becomes the next learning/development focus.

## Current Baseline

The current experimental loop is:

```text
/chat/agent
  -> NasClawAgentRunner
  -> load JSON checkpoint from memory/agent-sessions/{session_id}.json
  -> build ToolCallingAgent with mteam_search only
  -> run mteam_search-only tool loop
  -> save JSON checkpoint
```

Checkpoint read routes also exist:

```text
GET /chat/agent/sessions
  -> list checkpoint summaries

GET /chat/agent/sessions/{session_id}
  -> load one checkpoint with message history
```

This is good enough for proving:

- a normal tool-calling loop separate from teaching ReAct
- readonly tool execution
- multi-turn conversation history
- JSON checkpoint persistence through `ConversationCheckpointStore`
- browser-side session discovery and history restoration

It is not yet a full Agent runtime.

## Notes Worth Preserving

### Session Handling Has Moved Into A Runner

The first improvement moved session loading and saving out of the FastAPI route.
`NasClawAgentRunner` now owns the current conversation lifecycle:

```text
run_conversation(session_id, user_message)
  -> load checkpoint
  -> append user message
  -> run LLM/tool loop
  -> persist checkpoint
```

This keeps FastAPI routes thin and makes the loop reusable outside HTTP.

The current JSON implementation is useful for development. Later, the same
`ConversationCheckpointStore` abstraction can grow a SQLite implementation.

Open point: avoid forcing all future runtime state into plain chat history.
Pending approvals, trace summaries, and structured tool observations can be
added to checkpoint metadata or a richer checkpoint model when those features
become active work.

### Preflight Compression

`ToolCallingLoop` now uses `ContextWindowManager` to check context pressure
before model calls:

```text
before model call:
  estimate messages + tool schemas
  if over threshold:
    summarize old turns with LLM
    keep recent turns
    archive compressed-away original messages
    rebuild model messages
```

This better matches coding-agent style loops where context pressure can change
after tool observations, prompt layers, and previous assistant/tool messages.

Current placement:

- `ContextWindowManager`: preflight estimation and compression decision
- `HistoryManager`: active in-memory history only
- `ConversationCheckpoint.archives`: original messages removed from active
  history during preflight compression

NasClawBot's current Agent config enables smart preflight compression with a
0.7 threshold, uses a conservative configured context window of 64K tokens, and
keeps the most recent 4 rounds. The 100% budget is `Config.context_window`; it
is not auto-detected from the provider/model yet.

The summary is stored as a `role="summary"` message and is converted to a
system message when sent to the LLM. This is context-window management, not
long-term memory.

Checkpoint counters mean:

- `message_count`: number of active `checkpoint.history` messages available for
  normal conversation restoration.
- `archive_count`: number of compression archive batches.
- `archive.source_message_count`: number of original messages moved out of
  active history by one compression pass.

### Structured Tool Observations

`ToolCallingLoop` now keeps tool results structured through `ToolObservation`.

Separation of responsibilities:

```text
ToolResponse
  -> status/text/data/error/stats/context
  -> describes what the tool returned

ToolObservation
  -> tool_name/tool_call_id/arguments
  -> response: ToolResponse
  -> observation_text: string sent to the LLM
  -> truncated + stats: loop/truncation stats, not tool execution stats
```

This avoids damaging structured `ToolResponse.data` when the LLM-facing
observation text is truncated. Routes and tests should read
`observation.response.data`, not parse `observation_text`.

Future Gate/approval work should wrap pre-execution decisions into the
observation envelope without adding provider-specific fields such as
`tool_call_id` to `ToolResponse` itself.

### Permission And Approval Gate

Readonly tools can execute automatically. Side-effecting and destructive tools
need policy before execution.

Current loop shape:

```text
model asks for tool
  -> Filter decides which tool schemas are visible before the model call
  -> Gate checks the concrete tool call before tool.run()
  -> ALLOW executes
  -> DENY records a ToolObservation with PERMISSION_DENIED and continues
  -> ASK_USER records a pending approval and pauses with awaiting_approval
```

This is central for NasClawBot because download and file operations must not be
open-loop actions.

`ToolCallingLoopResult.pending_approvals` is route-facing so the API can decide
whether the frontend should render a confirmation affordance without reading
checkpoint internals. `ToolObservation` stores gate markers (`gate_result`,
`gate_reason`, `approval_id`) at the loop envelope level. The checkpoint keeps
`metadata["pending_approvals"]` for durable recovery.

The first implementation does not register `qb_add_torrent` in `/chat/agent`.
Approval resume endpoints are still future work; `/download` remains the
explicit side-effect boundary.

### Better Max-Steps Handling

The current `ToolCallingLoop` does a final no-tools pass when tool-calling steps
reach the configured limit:

```text
if max steps reached:
  call LLM one more time with tool_choice="none"
  ask it to summarize current observations and explain what remains unresolved
```

This gives users a useful answer instead of only a failure notice.

If the forced finalization call still returns tool calls or fails, the loop
falls back to the controlled max-steps failure message. The finalization prompt
is ephemeral and is not saved as normal conversation history; only the final
assistant answer is persisted.

### Interrupt And Cancel

Interruptible API/tool calls are useful but lower priority for this project.

The concept is:

```text
RuntimeTask
  task_id
  status
  cancel token
```

Model calls and tool calls would periodically respect cancellation. This matters
more for long-running tools, streaming UI, and "stop generating" controls.

Open point: learn and design this later; do not add premature complexity now.

### Error Recovery And Agent Harness Stability

This is high-value engineering work for demonstrating production thinking.

Possible recovery patterns:

- JSON argument parse failure -> ask model to repair arguments
- missing tool -> return available tool list to model
- readonly tool error -> allow bounded retry
- side-effect tool error -> avoid automatic retry
- repeated tool failure -> circuit breaker or stop condition

This belongs to an "Agent Harness" layer: not the model's reasoning style, but
the engineering wrapper that makes agent execution reliable.

Open point: define retry limits and side-effect safety only when implementing.

### Ephemeral Prompt Layers

Ephemeral prompt layers can improve behavior without polluting persistent
history.

Examples:

- remaining step budget
- readonly policy reminder
- context pressure warning
- current tool subset
- temporary task constraints

This is useful but lower priority than session/checkpoint, compression, and
permission policy.

Open point: these layers should be injected only for the current model call,
not saved as normal chat history unless explicitly intended.

### Trace And Event Stream

HelloAgents already has lifecycle concepts and hooks. Later, the loop can emit
clear events:

```text
agent_started
llm_started
llm_finished
tool_call_started
tool_call_finished
session_saved
agent_finished
```

This would support UI progress, debugging, tests, and trace replay.

Open point: reuse or extend existing HelloAgents lifecycle hooks instead of
creating a separate event system too early.

## Explicitly Deferred

Provider message adapters are not a priority for this project.

This is a resume/learning project, not an enterprise platform that needs broad
API-provider compatibility. It is enough to show good internal boundaries and
design awareness without fully implementing adapters for every model API.

## Suggested Learning-Oriented Sequence

This is only a suggestion, not a committed roadmap:

1. Move session load/save into the loop or a small runtime wrapper.
2. Add preflight compression before model calls. Done for `ToolCallingLoop` through `ContextWindowManager`.
3. Refine tool observations into structured records. Done through `ToolObservation`.
4. Add permission and approval gate for side-effect tools.
5. Improve max-steps finalization. Done for `ToolCallingLoop`; it now performs a forced no-tools summary pass.
6. Add error recovery patterns.
7. Revisit lifecycle hooks and event streaming.
8. Study interrupt/cancel once long-running calls or streaming UX need it.
