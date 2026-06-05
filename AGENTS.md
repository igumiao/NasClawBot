# AGENTS.md

## Project Summary

NasClawBot is a single-user, self-hosted NAS/PT media assistant and an Agent engineering playground.

The current codebase has been intentionally reset to a simpler baseline:

```text
chat request -> readonly M-Team search -> search results
explicit download action -> M-Team detail/token -> qB add paused
```

There is no active workflow runtime, no `/confirm` route, and no `confirmation_payload`.

An experimental gated Agent loop now exists alongside the stable baseline:

```text
/chat/agent -> NasClawAgentRunner -> ToolCallingAgent + mteam_search + member_profile + gated qb_add_torrent -> JSON checkpoint persistence
```

This path is for learning and iteration. `/chat` remains the stable no-LLM baseline.

## Current Architecture

- `app/api/chat_routes.py`: FastAPI routes for `/chat`, `/download`, `/health`, `/`, and qB router inclusion.
- `/chat`: performs a direct `MTeamSearchTool` call and returns `results`. It does not call an LLM and does not persist Agent history.
- `/chat/agent`: experimental Agent route. It delegates conversation lifecycle to `NasClawAgentRunner`, registers `mteam_search`, read-only `member_profile`, and confirm-gated `qb_add_torrent`, supports multi-turn history, and persists JSON conversation checkpoints under `memory/agent-sessions/{session_id}.json`.
- `GET /chat/agent/sessions`: lists persisted Agent conversation checkpoint summaries. It does not call an LLM or tools.
- `GET /chat/agent/sessions/{session_id}`: returns one persisted Agent conversation checkpoint with renderable message history. It does not call an LLM or tools.
- `POST /chat/agent/sessions/{session_id}/approvals/{approval_id}/approve`: approves a pending `qb_add_torrent` call. For checkpoints with `paused_loop`, the runner validates the paused provider tool call against the approval record, executes the tool, appends the provider `tool` result, resumes the LLM with `tool_choice="none"`, and clears the pending approval. Legacy checkpoints without `paused_loop` fall back to the deterministic approval summary path.
- `POST /chat/agent/sessions/{session_id}/approvals/{approval_id}/deny`: denies a pending Agent tool call without executing the tool. For checkpoints with `paused_loop`, the runner resumes the provider tool-call protocol with a `USER_DENIED` tool error and a no-tools final LLM pass.
- `app/agent/runner.py`: application-level Agent runner that loads/saves conversation checkpoints, builds the current `ToolCallingAgent`, restores history, and extracts route-facing search results/tool calls.
- `ToolCallingLoop`: applies `Filter` before sending tool schemas to the LLM, applies `Gate` before `tool.run()`, returns `awaiting_approval` with `pending_approvals` for confirm-gated calls, and performs one forced final LLM pass with `tool_choice="none"` when `max_steps` is reached.
- `ToolObservation`: loop-level envelope for one tool call. It stores `tool_name`, `tool_call_id`, arguments, full structured `ToolResponse`, separate LLM-facing `observation_text`, and gate markers (`gate_result`, `gate_reason`, `approval_id`).
- `ContextWindowManager`: runs preflight context checks before LLM calls. NasClawBot currently uses a conservative 64K configured context window, enables smart compression at 70% context pressure, keeps the latest 4 rounds active, stores a `summary` message for the model, and preserves compressed-away originals in checkpoint `archives`.
- `hello_agents/checkpoints/`: framework-level `ConversationCheckpointStore` protocol plus the current JSON implementation.
- `/download`: explicit user action; calls `QBAddTorrentTool` and submits to qBittorrent paused.
- `app/tools/`: per-tool modules (`mteam_search.py`, `member_profile.py`, `qb_add_torrent.py`), re-exported via `__init__.py`.
- `app/adapters/mteam.py`: M-Team API boundary for search, detail, download token generation, and member profile.
- `app/adapters/qbittorrent.py`: qBittorrent API boundary for paused add, listing, detail, and control.
- `app/domain/models.py`: shared search result models.
- `frontend/`: React + Vite workspace with Chat, Downloads, and Settings tabs.
- `ref/mteam-api-reference.md`: authoritative local M-Team API reference.

### Tool Safety

- **Filter** (`hello_agents/tools/filter.py`): narrows tool list before sending to LLM. Controls context window and sub-agent capability scope.
- **Gate** (`hello_agents/tools/gate.py`): three-gate check (deny → confirm → allow) on each `ToolCall` before `tool.run()`. Parameter-aware — `bash("ls")` and `bash("sudo rm -rf /")` can have different outcomes.
- `ASK_USER` gate results pause the loop with `ToolCallingLoopResult.status == "awaiting_approval"` and route-facing `pending_approvals`. The loop saves the assistant tool-call message but does not write a provider `tool` result before approval. `pending_approvals` are persisted for UI/lifecycle recovery; `metadata["paused_loop"]` is persisted for provider protocol resume.
- While a session has a pending approval, new user messages are rejected. The current loop allows one pending approval at a time; multiple simultaneous `ASK_USER` tool calls return a controlled approval conflict.
- `app/agent/approvals.py`: application-level `ApprovalRecord` lifecycle for gated tool calls. Pending records live in checkpoint `metadata["pending_approvals"]`; resolved records move to `metadata["approvals"]` with `approved`, `denied`, `failed`, or `expired` status.
- Factory functions: `deny_command()`, `deny_paths()`, `deny_outside_workspace()`, `deny_regex()`.
- `ToolPermission` and `ToolFilter` have been removed.

## Removed Architecture

The following are intentionally not part of the active implementation:

- LangGraph workflow wiring.
- HelloAgents workflow runtime migration.
- `HelloAgentWorkflowRunner`.
- `SequentialWorkflow`.
- `WorkflowEnvelope` / runtime session persistence.
- `/confirm`.
- `ConfirmationPayload`.
- Candidate approval card flow.

Historical design and research docs live under `docs/archive/`.

Active design notes:

- `docs/design/helloagents-framework-reference.md`: current HelloAgents framework reference and boundaries.
- `docs/design/agent-loop-improvement-notes.md`: non-final notes for future Agent Loop improvements.

## Dev Commands

Run backend commands from repo root:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/test_chat_api.py tests/test_mteam_adapter.py tests/test_qb_adapter.py -q
.venv/bin/python -m compileall app hello_agents -q
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run frontend commands from `frontend/`:

```bash
npm test
npm run typecheck
npm run build
npm run dev
```

## Safety Rules

- Never trigger real downloads in tests or demos unless explicitly requested.
- qB download submissions must stay paused by default.
- Never log secrets, API keys, cookies, or full tokenized download URLs.
- Keep M-Team torrent id as the stable external identifier.
- Keep search, detail, and token generation as separate operations.
- Do not download `.torrent` files locally; pass token URLs directly to qB.
- Do not expose destructive file operations to an open Agent loop.

## Direction

Continue evolving the readonly Agent loop without replacing the stable baseline too early:

```text
POST /chat          # stable direct search baseline
POST /chat/agent    # experimental readonly Agent loop
GET  /chat/agent/sessions
GET  /chat/agent/sessions/{session_id}
```

Current Agent loop work may expose `qb_add_torrent` only behind approval gating. Keep `/download` as the stable explicit side-effect path, and keep qB submissions paused by default.

Future improvement ideas are intentionally not finalized. Preserve them in `docs/design/agent-loop-improvement-notes.md` rather than overfitting the first loop implementation.
