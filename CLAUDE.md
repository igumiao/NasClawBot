# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Project Overview

NasClawBot is a single-user NAS/PT media assistant. The active implementation is intentionally simple:

```text
/chat     -> readonly M-Team search -> search results
/chat/agent -> experimental NasClawAgentRunner + ToolCallingAgent + JSON checkpoints
/download -> explicit user action -> qB add paused
/qb/*     -> qB task management
```

The project is building a minimal context-aware Agent loop from this baseline. Do not assume the older workflow/runtime design is still active.

## Important Current Facts

- There is no `/confirm` route.
- There is no `confirmation_payload`.
- There is no `HelloAgentWorkflowRunner`.
- There is no `SequentialWorkflow`.
- There is no active workflow runtime.
- `/chat` still calls `MTeamSearchTool` directly and does not use LLM/session history.
- `/chat/agent` is the experimental Agent route. It delegates to `NasClawAgentRunner`, currently uses `ToolCallingAgent` with only `mteam_search`, supports multi-turn history, and persists JSON conversation checkpoints under `memory/agent-sessions/{session_id}.json`.
- `GET /chat/agent/sessions` lists persisted Agent checkpoint summaries without calling an LLM or tools.
- `GET /chat/agent/sessions/{session_id}` returns one persisted Agent checkpoint with renderable message history, also without calling an LLM or tools.
- `hello_agents/checkpoints/` defines the thin `ConversationCheckpointStore` boundary and the current JSON implementation.
- Tool wrappers live in `app/tools.py`.
- M-Team and qB integration lives behind adapters in `app/adapters/`.
- `hello_agents/tools/` provides `Filter` (pre-LLM tool selection) and `Gate` (pre-execution deny/confirm).
- `ToolPermission` and `ToolFilter` have been removed in favor of `Filter` + `Gate`.
- Historical LangGraph and HelloAgents runtime docs are archived under `docs/archive/`.

## Dev Commands

Backend, from repo root:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/test_chat_api.py tests/test_mteam_adapter.py tests/test_qb_adapter.py -q
.venv/bin/python -m compileall app hello_agents -q
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend, from `frontend/`:

```bash
npm test
npm run typecheck
npm run build
npm run dev
```

There is no formal Python formatter configured yet.

## Architecture Notes

`app/api/chat_routes.py` owns the current interaction surface:

- `POST /chat`: trims the user message, calls `MTeamSearchTool`, returns `ChatResponse.results`.
- `POST /chat/agent`: validates the request, delegates to `NasClawAgentRunner`, and returns a normal `ChatResponse`.
- `GET /chat/agent/sessions`: lists persisted Agent conversation summaries.
- `GET /chat/agent/sessions/{session_id}`: loads one persisted Agent conversation checkpoint.
- `POST /download`: accepts a torrent id, calls `QBAddTorrentTool`, submits to qB paused, and returns a receipt.
- qB management routes are included from `app/api/qb_routes.py`.

`app/agent/runner.py` owns the experimental Agent conversation lifecycle: load checkpoint, build the current tool-calling agent, restore history, run one turn, save checkpoint, and extract route-facing search results/tool calls.

`ToolCallingLoop` applies `Filter` before sending tool schemas to the LLM and applies `Gate` before `tool.run()`. `DENY` produces a permission-denied observation without executing the tool. `ASK_USER` pauses the loop with `status="awaiting_approval"` and route-facing `pending_approvals`, which NasClawBot persists in checkpoint metadata. Approval resume/reject endpoints are not implemented yet.

`ToolCallingLoop` performs one forced final LLM pass with `tool_choice="none"` when `max_steps` is reached. That pass summarizes current observations without executing more tools; if it fails or returns tool calls, the loop falls back to the controlled max-steps message.

`ToolObservation` is the loop-level envelope for one tool call. It stores `tool_name`, `tool_call_id`, arguments, full structured `ToolResponse`, separate LLM-facing `observation_text`, and gate markers (`gate_result`, `gate_reason`, `approval_id`); routes should read `observation.response.data` rather than parsing tool-message text.

`ContextWindowManager` performs preflight context checks before LLM calls. NasClawBot currently uses a conservative 64K configured context window, enables smart compression at 70% context pressure, keeps the latest 4 rounds active, writes a `summary` message into active history, and preserves compressed-away originals in checkpoint `archives`.

`frontend/src/components/chat/ChatPanel.tsx` renders chat messages and search results. Search results are displayed with `SearchResultCard`; clicking "加入 qB" calls `/download`.

`ref/mteam-api-reference.md` is the local source of truth for M-Team endpoints.

### Tool Safety: Filter + Gate

Two independent layers, no `ToolPermission` enum:

- **Filter** (`hello_agents/tools/filter.py`): runs **before** tools are sent to the LLM. Narrows the tool list to control context window usage and sub-agent capability scope. `Filter(allow=["mteam_search"])` or `Filter(allow=lambda name: ...)`.
- **Gate** (`hello_agents/tools/gate.py`): runs **after** LLM returns a tool call, **before** `tool.run()`. Three gates: deny_rules → confirm_rules → default allow. Works on `ToolCall` (tool_name + params), so decisions can be parameter-aware (`bash("ls")` passes, `bash("sudo rm -rf /")` denied).

Factory functions for common deny rules: `deny_command()`, `deny_paths()`, `deny_outside_workspace()`, `deny_regex()`.

### Current Experimental Agent Loop

The first loop is intentionally narrow:

```text
POST /chat/agent
  -> NasClawAgentRunner
  -> load JSON checkpoint
  -> ToolCallingAgent
  -> mteam_search only
  -> tool result back to LLM
  -> save JSON checkpoint
```

`/chat` remains the stable no-LLM route. Do not replace it until the Agent path is proven.

## Safety Rules

- Never trigger real downloads in tests/demos unless explicitly requested.
- Download submissions must remain paused by default.
- Never log secrets or full tokenized download URLs.
- Keep search, detail, and token generation separate.
- Do not download `.torrent` files locally.
- Do not expose destructive file operations to an open Agent loop.

## Next Direction

Continue evolving the readonly Agent loop while keeping `/chat` stable.

- Start with `mteam_search` as the only Agent-callable tool.
- Keep `/download` as an explicit user action until approval/gating for side-effect tools is designed and tested.
- Keep future loop ideas in `docs/design/agent-loop-improvement-notes.md`; do not prematurely hard-code them into the framework.
