# AGENTS.md

## Project Summary

NasClawBot is a single-user, self-hosted NAS/PT media assistant and an Agent engineering playground.

The current codebase has been intentionally reset to a simpler baseline:

```text
chat request -> readonly M-Team search -> search results
explicit download action -> M-Team detail/token -> qB add paused
```

There is no active workflow runtime, no `/confirm` route, and no `confirmation_payload`.

An experimental readonly Agent loop now exists alongside the stable baseline:

```text
/chat/agent -> NasClawAgentRunner -> ToolCallingAgent + mteam_search -> JSON checkpoint persistence
```

This path is for learning and iteration. `/chat` remains the stable no-LLM baseline.

## Current Architecture

- `app/api/chat_routes.py`: FastAPI routes for `/chat`, `/download`, `/health`, `/`, and qB router inclusion.
- `/chat`: performs a direct `MTeamSearchTool` call and returns `results`. It does not call an LLM and does not persist Agent history.
- `/chat/agent`: experimental Agent route. It delegates conversation lifecycle to `NasClawAgentRunner`, currently registers only `mteam_search`, supports multi-turn history, and persists JSON conversation checkpoints under `memory/agent-sessions/{session_id}.json`.
- `GET /chat/agent/sessions`: lists persisted Agent conversation checkpoint summaries. It does not call an LLM or tools.
- `GET /chat/agent/sessions/{session_id}`: returns one persisted Agent conversation checkpoint with renderable message history. It does not call an LLM or tools.
- `app/agent/runner.py`: application-level Agent runner that loads/saves conversation checkpoints, builds the current `ToolCallingAgent`, restores history, and extracts route-facing search results/tool calls.
- `ToolCallingLoop`: when `max_steps` is reached, performs one forced final LLM pass with `tool_choice="none"` to summarize current observations; falls back to the controlled max-steps message if that pass fails or returns tool calls.
- `ContextWindowManager`: runs preflight context checks before LLM calls. NasClawBot currently uses a conservative 64K configured context window, enables smart compression at 70% context pressure, keeps the latest 4 rounds active, stores a `summary` message for the model, and preserves compressed-away originals in checkpoint `archives`.
- `hello_agents/checkpoints/`: framework-level `ConversationCheckpointStore` protocol plus the current JSON implementation.
- `/download`: explicit user action; calls `QBAddTorrentTool` and submits to qBittorrent paused.
- `app/tools.py`: tool wrappers over existing adapters (MTeamSearchTool, QBAddTorrentTool).
- `app/adapters/mteam.py`: M-Team API boundary for search, detail, and download token generation.
- `app/adapters/qbittorrent.py`: qBittorrent API boundary for paused add, listing, detail, and control.
- `app/domain/models.py`: shared search result models.
- `frontend/`: React + Vite workspace with Chat, Downloads, and Settings tabs.
- `ref/mteam-api-reference.md`: authoritative local M-Team API reference.

### Tool Safety

- **Filter** (`hello_agents/tools/filter.py`): narrows tool list before sending to LLM. Controls context window and sub-agent capability scope.
- **Gate** (`hello_agents/tools/gate.py`): three-gate check (deny → confirm → allow) on each `ToolCall` before `tool.run()`. Parameter-aware — `bash("ls")` and `bash("sudo rm -rf /")` can have different outcomes.
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

Current Agent loop work should focus on `mteam_search` as the only Agent-callable tool. Keep `/download` explicit until approval/gating for side-effect tools is designed and tested.

Future improvement ideas are intentionally not finalized. Preserve them in `docs/design/agent-loop-improvement-notes.md` rather than overfitting the first loop implementation.
