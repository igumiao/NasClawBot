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

This is good enough for proving:

- a normal tool-calling loop separate from teaching ReAct
- readonly tool execution
- multi-turn conversation history
- JSON checkpoint persistence through `ConversationCheckpointStore`

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

Current compression is mostly write-triggered through `Agent.add_message()`.
That is useful, but a stronger loop should check context pressure before each
LLM call:

```text
before model call:
  estimate context tokens
  if over threshold:
    summarize old turns
    keep recent turns
    rebuild model messages
```

This better matches coding-agent style loops where context pressure can change
after tool observations, prompt layers, and previous assistant/tool messages.

Open point: decide whether compression belongs in `ToolCallingLoop`,
`HistoryManager`, or a small `ContextManager` wrapper.

### Structured Tool Observations

The current loop now feeds `ToolResponse.to_json()` back to the model, which is
better than returning only `response.text`.

The internal loop result is still too string-oriented. Later, tool observations
can become structured records:

```text
tool name
tool call id
arguments
status
text
data
error
stats
preview/raw output reference
```

This would help UI traces, retries, approval, memory extraction, and tests.

Open point: do not lock fields too early. Keep the idea, refine when trace or
approval work begins.

### Permission And Approval Gate

Readonly tools can execute automatically. Side-effecting and destructive tools
need policy before execution.

Future loop shape:

```text
model asks for tool
  -> permission policy checks tool risk
  -> READONLY executes
  -> SIDE_EFFECT creates approval request and pauses
  -> DESTRUCTIVE is blocked or requires stricter confirmation
```

This is central for NasClawBot because download and file operations must not be
open-loop actions.

Open point: permission metadata probably belongs to HelloAgents tool framework,
while concrete download/file policies belong to NasClawBot.

### Better Max-Steps Handling

The current max-steps behavior returns a controlled failure message.

A better agent harness can do a final no-tools pass:

```text
if max steps reached:
  call LLM one more time with tool_choice="none"
  ask it to summarize current observations and explain what remains unresolved
```

This gives users a useful answer instead of only a failure notice.

Open point: this should not allow more tool calls, and should be clearly marked
as a forced finalization step.

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
2. Add preflight compression before model calls.
3. Refine tool observations into structured records.
4. Add permission and approval gate for side-effect tools.
5. Improve max-steps finalization.
6. Add error recovery patterns.
7. Revisit lifecycle hooks and event streaming.
8. Study interrupt/cancel once long-running calls or streaming UX need it.
