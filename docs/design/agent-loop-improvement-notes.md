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
  -> build ToolCallingAgent with readonly tools + gated qB action tools
  -> run filtered/gated tool loop
  -> save JSON checkpoint
```

Checkpoint read routes also exist:

```text
GET /chat/agent/sessions
  -> list checkpoint summaries

GET /chat/agent/sessions/{session_id}
  -> load one checkpoint with message history
```

The browser Chat tab now exercises this Agent path directly:

```text
natural-language request
  -> /chat/agent
  -> assistant answer + tool activity + search candidates
  -> selected candidate sent back through /chat/agent
  -> gated qb_add_torrent or qb_add_torrents approval card
  -> approve or deny endpoint
```

The browser keeps the active Agent session id in session storage and restores
the checkpoint after a page refresh. The current UI derives display messages
from raw checkpoint history; a dedicated backend display-message projection
remains a possible future improvement.

This is good enough for proving:

- a normal tool-calling loop separate from teaching ReAct
- automatic readonly tool execution plus approval-gated side effects
- multi-turn conversation history
- JSON checkpoint persistence through `ConversationCheckpointStore`
- browser-side session discovery and history restoration

It is not yet a full Agent runtime.

### Current M-Team Search Surface

The first search-tool refinement deliberately exposes a small semantic query
surface instead of the full M-Team Swagger request:

```text
keyword?   free-text search; empty is valid
sort_by?   smallest | largest | most_seeded
imdb?      exact external id
douban?    exact external id
```

Important current decisions:

- `MTeamSearchTool` always uses M-Team `normal` mode; media mode selection is
  not exposed to the Agent.
- Omitting `sort_by` preserves M-Team's default newest-first ordering.
- `discount` remains candidate metadata, not a search parameter, because the
  API accepts only one discount value and overlapping meanings such as `FREE`
  and `_2X_FREE` are ambiguous for natural-language requests.
- Pagination, categories, raw sort fields, and local hard filters are not
  exposed to the Agent in this phase.
- The adapter requests page 1 with 20 rows. `MTeamSearchTool` returns the first
  10 normalized candidates so the model can judge more M-Team title variants.
- Dynamic state comes from `status.seeders`, `status.leechers`, and
  `status.discount`; top-level fields with the same names are not authoritative.
- Display titles prefer release `name`. Resolution detection prefers
  `smallDescr`, falls back to `name` only when the description is absent, and
  currently recognizes 4320p/8K, 2160p/4K, 1080p, and 720p.

Possible future refinements such as local hard filters, richer ranking, or a
separate detail-verification tool should be justified by concrete user
scenarios rather than added to the first search schema by default.

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
`metadata["pending_approvals"]` for UI/lifecycle recovery and
`metadata["paused_loop"]` for provider tool-call resume.

At the NasClawBot layer, loop-level pending approvals are normalized into
`app/agent/approvals.py` `ApprovalRecord` entries. Pending records include
`session_id`, `expires_at`, `risk`, `decision`, `result`, and `error`. Resolved
records move to `metadata["approvals"]` with `approved`, `denied`, `failed`, or
`expired` status. Expiration is lazy: approve/deny check `expires_at`, and the
runner also resolves expired approvals before accepting a new Agent turn.
Expiration never executes the tool. It removes the unresolved provider
assistant tool-call message before continuing so later model calls do not see
an orphaned tool-call protocol entry. Expiration is not a user decision, so it
does not set `decided_at`.

NasClawBot now registers `qb_add_torrent` and `qb_add_torrents` in
`/chat/agent`, and both are confirm-gated unless covered by an active session
download authorization grant. `qb_add_torrents` is a batch form of the same
download-add operation: each item has a `torrent_id`, optional `qb_category`,
and optional `save_path`; a single batch is capped at 10 items and all qB adds
remain paused.

On `ASK_USER`, the loop saves the assistant tool-call message and pauses before
writing any provider `tool` result. Approving a pending action validates
`paused_loop` against the `ApprovalRecord`, executes the saved `tool_name +
arguments`, appends the real provider `tool` result with the original
`tool_call_id`, and resumes the normal tool loop with `tool_choice="auto"`.
Denying a pending action does not execute the tool; it resumes the provider
protocol with a `USER_DENIED` tool error and also continues the normal loop.
That lets the model request the next gated operation, run read-only tools, or
change its plan after a denial.

The current serial approval shape is:

```text
pause at assistant tool_call
  -> external approval or denial
  -> execute tool or append USER_DENIED tool result
  -> append provider tool result
  -> continue the normal tool loop
  -> either final answer or next awaiting_approval
```

The deterministic approval summary path remains as a compatibility fallback for
legacy checkpoints that do not have `paused_loop`. Current limitations are
intentional: a session rejects new user messages while a non-expired approval
is pending, and the loop supports one pending approval at a time. Multiple
simultaneous `ASK_USER` tool calls are fed back to the model as replan feedback
instead of being surfaced as a user-visible conflict; the invalid assistant
tool-call message is not persisted.

Download session authorization is deliberately application-level, not
framework-level policy. Settings persist the boundary in
`memory/settings/download-authorization.json`: enabled flag, allowed categories,
allowed save path prefixes, max items per batch, max total items per session,
and `paused_required=true`. Approving an eligible `qb_add_torrent` or
`qb_add_torrents` call with `approve_and_grant_session` creates
`metadata["authorization_grants"]` on that conversation checkpoint. Other
ASK_USER tools are not eligible for this grant and continue to require explicit
approval.

TMDB network overrides are also Settings-backed but service-scoped. The UI writes
`memory/settings/tmdb-network.json` through `GET/PUT /settings/tmdb-network`.
When enabled, TMDB adapter calls pass the configured HTTP/HTTPS proxy directly to
HTTPX with `trust_env=false`; when disabled, TMDB keeps HTTPX's normal process
environment proxy behavior. The override intentionally does not affect qB,
M-Team, Tavily, LLM, MCP, or local NAS requests.

`NasClawAgentRunner.run/approve/deny` are serialized by session inside the
current server process. This closes the local race where two concurrent
approval decisions could both observe `pending` and execute the same download.
This is intentionally not presented as distributed coordination; a future
SQLite/transactional store must provide the equivalent guard across processes.

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
4. Add permission and approval gate for side-effect tools. Done for the current `Filter` + `Gate` + approval pause/resume path.
5. Improve max-steps finalization. Done for `ToolCallingLoop`; it now performs a forced no-tools summary pass.
6. Add error recovery patterns.
7. Revisit lifecycle hooks and event streaming.
8. Study interrupt/cancel once long-running calls or streaming UX need it.
