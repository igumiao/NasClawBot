# fnOS Media Agent Phase 2A Search Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace raw-sentence M-Team search with a single-keyword LLM path, return the first 3 candidates without scoring, and approve by adding the selected torrent to qBittorrent in paused mode.

**Architecture:** Keep the existing FastAPI + LangGraph + adapter shape, but collapse the main path to `FindKeywordLLM -> single keyword search -> top 3 candidates -> confirmation -> paused qB add`. Remove unused scoring structures instead of preserving them for speculative reuse, and keep the workflow state as small as possible.

**Tech Stack:** Python 3.11+, FastAPI, LangGraph, Pydantic v2, LangChain OpenAI-compatible client, httpx, pytest

---

## File Map

- Create: `app/llm/find_keyword_llm.py`
- Create: `tests/test_find_keyword_llm.py`
- Modify: `app/config.py`
- Modify: `app/llm/client.py`
- Delete: `app/llm/prompts.py`
- Modify: `app/domain/models.py`
- Delete: `app/domain/scoring.py`
- Modify: `app/tools/search_tools.py`
- Modify: `app/workflow/state.py`
- Modify: `app/workflow/nodes.py`
- Modify: `app/workflow/graph.py`
- Modify: `app/api/schemas.py`
- Modify: `app/api/chat_routes.py`
- Modify: `app/adapters/qbittorrent.py`
- Modify: `tests/test_workflow.py`
- Modify: `tests/test_chat_api.py`
- Modify: `tests/test_qb_adapter.py`
- Delete: `tests/test_scoring.py`

## Task 1: Add `FindKeywordLLM` And Model Settings

**Files:**
- Create: `app/llm/find_keyword_llm.py`
- Create: `tests/test_find_keyword_llm.py`
- Modify: `app/config.py`
- Modify: `app/llm/client.py`
- Delete: `app/llm/prompts.py`
- Test: `tests/test_find_keyword_llm.py`

- [ ] **Step 1: Write the failing keyword-LLM tests**

```python
import pytest

from app.llm.find_keyword_llm import FindKeywordLLM


class StubJsonCaller:
    def __init__(self, response_text: str):
        self._response_text = response_text

    def __call__(self, *, system_prompt: str, user_prompt: str) -> str:
        assert "keyword" in system_prompt.lower()
        assert user_prompt == "帮我找沙丘2电影，今晚想看"
        return self._response_text


def test_find_keyword_llm_returns_trimmed_keyword():
    llm = FindKeywordLLM(
        call_json=StubJsonCaller('{"keyword": " 沙丘2 "}')
    )

    result = llm.invoke("帮我找沙丘2电影，今晚想看")

    assert result == {"keyword": "沙丘2"}


def test_find_keyword_llm_rejects_empty_keyword():
    llm = FindKeywordLLM(
        call_json=StubJsonCaller('{"keyword": "   "}')
    )

    with pytest.raises(ValueError, match="non-empty keyword"):
        llm.invoke("帮我找沙丘2电影，今晚想看")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_find_keyword_llm.py -q`
Expected: FAIL because `app.llm.find_keyword_llm` does not exist yet.

- [ ] **Step 3: Implement the smallest working LLM keyword layer**

```python
"""Centralized runtime settings loaded from environment variables.

The project is intentionally simple for now: one cached settings object shared
across adapters, API routes, and scripts.
"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel


def _read_project_env_defaults() -> dict[str, str]:
    """Read project-root `.env` into a plain defaults dict.

    Environment variables from the real process still have higher precedence.
    """

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return {}
    parsed = dotenv_values(env_path)
    return {
        key: value
        for key, value in parsed.items()
        if key and value is not None
    }


_ENV_DEFAULTS = _read_project_env_defaults()


def _get_env(name: str, default: str = "") -> str:
    """Resolve config value from process env first, then `.env`, then default."""
    return os.getenv(name, _ENV_DEFAULTS.get(name, default))


class Settings(BaseModel):
    """Typed configuration surface used by the application."""

    app_name: str = "fnOS Media Agent"
    mteam_base_url: str = _get_env("MTEAM_BASE_URL")
    mteam_api_key: str = _get_env("MTEAM_API_KEY")
    qb_base_url: str = _get_env("QB_BASE_URL")
    qb_username: str = _get_env("QB_USERNAME")
    qb_password: str = _get_env("QB_PASSWORD")
    database_path: str = _get_env("DATABASE_PATH", "nas_media_agent.db")
    llm_model: str = _get_env("LLM_MODEL", "gpt-4.1-mini")
    llm_api_key: str = _get_env("LLM_API_KEY")
    llm_base_url: str = _get_env("LLM_BASE_URL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached settings instance."""
    return Settings()
```

```python
"""Small helpers for OpenAI-compatible LLM invocation."""

from typing import Any, Protocol

from langchain_openai import ChatOpenAI

from app.config import Settings, get_settings


class JsonCaller(Protocol):
    def __call__(self, *, system_prompt: str, user_prompt: str) -> str:
        ...


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "".join(parts).strip()
    return str(content).strip()


def build_chat_model(settings: Settings | None = None) -> ChatOpenAI:
    resolved = settings or get_settings()
    kwargs: dict[str, Any] = {
        "model": resolved.llm_model,
        "temperature": 0,
    }
    if resolved.llm_api_key:
        kwargs["api_key"] = resolved.llm_api_key
    if resolved.llm_base_url:
        kwargs["base_url"] = resolved.llm_base_url
    return ChatOpenAI(**kwargs)


def build_json_caller(settings: Settings | None = None) -> JsonCaller:
    model = build_chat_model(settings=settings)

    def call_json(*, system_prompt: str, user_prompt: str) -> str:
        response = model.invoke(
            [
                ("system", system_prompt),
                ("human", user_prompt),
            ]
        )
        return _content_to_text(response.content)

    return call_json
```

```python
"""Single-purpose LLM unit for extracting one M-Team search keyword."""

import json
from textwrap import dedent

from app.llm.client import JsonCaller, build_json_caller

_SYSTEM_PROMPT = dedent(
    """
    You extract exactly one PT-search keyword from a user request.

    Rules:
    - Return valid JSON only.
    - Output shape: {"keyword": "<value>"}.
    - Return a short title-like keyword suitable for direct site search.
    - Do not return the full user sentence.
    - Do not add explanations.

    Examples:
    User: 帮我找沙丘2电影，今晚想看
    {"keyword": "沙丘2"}

    User: I want Dune Part Two movie
    {"keyword": "Dune Part Two"}

    User: 帮我下载安多第一季
    {"keyword": "安多"}
    """
).strip()


class FindKeywordLLM:
    def __init__(self, call_json: JsonCaller | None = None):
        self._call_json = call_json or build_json_caller()

    def invoke(self, message: str) -> dict[str, str]:
        raw = self._call_json(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=message,
        )
        payload = json.loads(raw)
        keyword = str(payload.get("keyword", "")).strip()
        if not keyword:
            raise ValueError("FindKeywordLLM must return a non-empty keyword.")
        return {"keyword": keyword}
```

Run: `git rm app/llm/prompts.py`

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_find_keyword_llm.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/llm/client.py app/llm/find_keyword_llm.py tests/test_find_keyword_llm.py
git rm app/llm/prompts.py
git commit -m "feat: add single-keyword llm extraction"
```

## Task 2: Collapse Workflow To A Single-Keyword Search Path And Remove Scoring

**Files:**
- Modify: `app/domain/models.py`
- Modify: `app/tools/search_tools.py`
- Modify: `app/workflow/state.py`
- Modify: `app/workflow/nodes.py`
- Modify: `app/workflow/graph.py`
- Modify: `tests/test_workflow.py`
- Delete: `app/domain/scoring.py`
- Delete: `tests/test_scoring.py`
- Test: `tests/test_workflow.py`

- [ ] **Step 1: Write the failing workflow tests for the new path**

```python
from app.domain.models import ResourceCandidate
from app.workflow.graph import build_workflow


class StubKeywordFinder:
    def invoke(self, message: str):
        assert message == "I want to watch Dune tonight"
        return {"keyword": "Dune Part Two"}


class CapturingSearchTool:
    def __init__(self):
        self.keyword = None

    def __call__(self, keyword: str):
        self.keyword = keyword
        return [
            ResourceCandidate(id="1", title="Dune Part Two 2024 2160p", media_type="movie", resolution="2160p", seeders=150, size="28 GB", source="mteam"),
            ResourceCandidate(id="2", title="Dune Part Two 2024 1080p", media_type="movie", resolution="1080p", seeders=120, size="12 GB", source="mteam"),
            ResourceCandidate(id="3", title="Dune Part Two 2024 BluRay", media_type="movie", resolution="1080p", seeders=90, size="18 GB", source="mteam"),
            ResourceCandidate(id="4", title="Dune 2021 1080p", media_type="movie", resolution="1080p", seeders=70, size="10 GB", source="mteam"),
        ]


def test_workflow_uses_single_keyword_and_returns_top_three():
    search_tool = CapturingSearchTool()
    graph = build_workflow(
        keyword_finder=StubKeywordFinder(),
        search_tool=search_tool,
    )

    result = graph.invoke(
        {
            "session_id": "s1",
            "user_message": "I want to watch Dune tonight",
        }
    )

    assert search_tool.keyword == "Dune Part Two"
    assert result["keyword"] == "Dune Part Two"
    assert result["status"] == "awaiting_confirmation"
    assert len(result["confirmation_payload"]["results"]) == 3
    assert "score" not in result["confirmation_payload"]["results"][0]
    assert "reasons" not in result["confirmation_payload"]["results"][0]


def test_workflow_returns_paused_receipt_for_approved_selection():
    graph = build_workflow(
        keyword_finder=StubKeywordFinder(),
        search_tool=CapturingSearchTool(),
    )

    result = graph.invoke(
        {
            "session_id": "s1",
            "confirmation_payload": {
                "recommended_result_id": "1",
                "results": [
                    {
                        "id": "1",
                        "title": "Dune Part Two 2024 2160p",
                        "seeders": 150,
                        "resolution": "2160p",
                        "size": "28 GB",
                    }
                ],
            },
        }
    )

    assert result["status"] == "completed"
    assert result["receipt"]["status"] == "submitted_paused"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_workflow.py -q`
Expected: FAIL because `build_workflow()` still expects the old extractor/constraints/scoring path.

- [ ] **Step 3: Implement the collapsed workflow and delete scoring**

```python
"""Domain models shared by workflow and adapters."""

from pydantic import BaseModel


class ResourceCandidate(BaseModel):
    """One normalized search result entry from an external source."""

    id: str
    title: str
    media_type: str
    year: int | None = None
    resolution: str | None = None
    seeders: int = 0
    size: str
    size_bytes: int | None = None
    source: str
```

```python
"""Search tool wrappers used by workflow nodes."""

from collections.abc import Callable
from typing import Protocol

from app.domain.models import ResourceCandidate


class SearchTool(Protocol):
    def __call__(self, keyword: str) -> list[ResourceCandidate]:
        ...


def search_mteam_candidates(
    search_tool: SearchTool | Callable[[str], list[ResourceCandidate]],
    keyword: str,
) -> list[ResourceCandidate]:
    return search_tool(keyword)
```

```python
"""Typed LangGraph state for the Phase 2A search path."""

from typing import TypedDict

from app.domain.models import ResourceCandidate


class AgentState(TypedDict, total=False):
    session_id: str
    user_message: str
    keyword: str
    search_results: list[ResourceCandidate]
    confirmation_payload: dict
    receipt: dict
    status: str
    error: str
```

```python
"""Workflow nodes for the Phase 2A single-keyword path."""

from collections.abc import Callable
from typing import Any

from app.domain.models import ResourceCandidate
from app.services.receipt_service import build_receipt
from app.tools.download_tools import prepare_download_execution
from app.tools.search_tools import search_mteam_candidates


def find_keyword_node(state: dict[str, Any], keyword_finder) -> dict[str, str]:
    payload = keyword_finder.invoke(state["user_message"])
    keyword = str(payload.get("keyword", "")).strip()
    if not keyword:
        raise ValueError("keyword_finder must return a non-empty keyword.")
    return {"keyword": keyword}


def search_node(state: dict[str, Any], search_tool) -> dict[str, list[ResourceCandidate]]:
    results = search_mteam_candidates(search_tool, state["keyword"])
    normalized_results = [
        item if isinstance(item, ResourceCandidate) else ResourceCandidate.model_validate(item)
        for item in results
    ]
    return {"search_results": normalized_results}


def build_confirmation_payload_node(state: dict[str, Any]) -> dict[str, Any]:
    results = state.get("search_results", [])[:3]
    if not results:
        return {
            "confirmation_payload": {
                "summary": "I couldn't find matching candidates. Please try another title.",
                "recommended_result_id": None,
                "results": [],
            },
            "status": "awaiting_confirmation",
        }

    payload = {
        "summary": "I found matching candidates and paused for confirmation.",
        "recommended_result_id": results[0].id,
        "results": [
            {
                "id": item.id,
                "title": item.title,
                "seeders": item.seeders,
                "resolution": item.resolution,
                "size": item.size,
            }
            for item in results
        ],
    }
    return {"confirmation_payload": payload, "status": "awaiting_confirmation"}


def execute_download_node(state: dict[str, Any]) -> dict[str, Any]:
    return execute_download_with_executor_node(state, _default_download_executor)


def execute_download_with_executor_node(
    state: dict[str, Any],
    download_executor: Callable[[dict[str, Any], str], dict[str, Any]],
) -> dict[str, Any]:
    payload = state.get("confirmation_payload", {})
    selected_result = _resolve_selected_result(payload)
    selected_result_id = str(selected_result["id"])

    execution = prepare_download_execution(selected_result)
    qb_category = str(payload.get("qb_category", "movie"))
    execution_outcome = download_executor(selected_result, qb_category)
    qb_hash = execution_outcome.get("qb_hash")
    status = str(execution_outcome.get("status", "submitted_paused"))
    receipt = build_receipt(
        resource_title=execution["resource_title"],
        external_id=execution["external_id"],
        qb_category=qb_category,
        qb_hash=str(qb_hash) if qb_hash else None,
        status=status,
    )
    enriched_payload = {
        **payload,
        "selected_result_id": selected_result_id,
        "execution_result": execution,
        "receipt": receipt,
    }
    return {
        "confirmation_payload": enriched_payload,
        "receipt": receipt,
        "status": "completed" if status in {"submitted", "submitted_paused"} else status,
    }
```

```python
def _resolve_selected_result(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results", [])
    selected_result_id = payload.get("selected_result_id") or payload.get("recommended_result_id")
    if not selected_result_id and results:
        selected_result_id = results[0].get("id")
    if not selected_result_id:
        raise ValueError("confirmation_payload must contain at least one selectable result.")

    selected = next((item for item in results if item.get("id") == selected_result_id), None)
    if selected is None:
        raise ValueError(f"Selected result id '{selected_result_id}' was not found in results.")
    return selected


def _default_download_executor(selected_result: dict[str, Any], qb_category: str) -> dict[str, Any]:
    _ = selected_result
    _ = qb_category
    return {"status": "submitted_paused", "qb_hash": "stub-hash"}
```

```python
"""LangGraph wiring for the Phase 2A single-keyword path."""

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.tools.search_tools import SearchTool
from app.workflow.nodes import (
    build_confirmation_payload_node,
    execute_download_with_executor_node,
    find_keyword_node,
    search_node,
)
from app.workflow.state import AgentState


def build_workflow(
    keyword_finder=None,
    search_tool: SearchTool | None = None,
    download_executor: Callable[[dict[str, Any], str], dict[str, Any]] | None = None,
):
    if keyword_finder is None:
        raise ValueError("keyword_finder is required to build workflow.")
    if search_tool is None:
        raise ValueError("search_tool is required to build workflow.")
    if download_executor is None:
        download_executor = lambda _selected, _category: {
            "status": "submitted_paused",
            "qb_hash": "stub-hash",
        }

    def route_start(state: dict) -> str:
        if state.get("confirmation_payload"):
            return "execute_download"
        return "find_keyword"

    graph = StateGraph(AgentState)
    graph.add_node(
        "execute_download",
        lambda state: execute_download_with_executor_node(state, download_executor),
    )
    graph.add_node(
        "find_keyword",
        lambda state: find_keyword_node(state, keyword_finder),
    )
    graph.add_node(
        "search_mteam",
        lambda state: search_node(state, search_tool),
    )
    graph.add_node("build_confirmation_payload", build_confirmation_payload_node)

    graph.add_conditional_edges(
        START,
        route_start,
        {
            "execute_download": "execute_download",
            "find_keyword": "find_keyword",
        },
    )
    graph.add_edge("execute_download", END)
    graph.add_edge("find_keyword", "search_mteam")
    graph.add_edge("search_mteam", "build_confirmation_payload")
    graph.add_edge("build_confirmation_payload", END)

    return graph.compile()


class LangGraphWorkflowRunner:
    def __init__(self, graph):
        self._graph = graph

    def run_chat(self, session_id: str, message: str) -> dict[str, Any]:
        return self._graph.invoke({"session_id": session_id, "user_message": message})

    def run_confirm(
        self,
        session_id: str,
        *,
        action: str,
        confirmation_payload: dict[str, Any] | None,
        selected_result_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_action = action.strip().lower()
        if normalized_action == "cancel":
            return {
                "session_id": session_id,
                "status": "canceled",
                "messages": ["Request canceled by user."],
            }
        if normalized_action != "approve":
            return {
                "session_id": session_id,
                "status": "error",
                "error": f"Unsupported action: {action}",
            }
        if not confirmation_payload:
            return {
                "session_id": session_id,
                "status": "error",
                "error": "confirmation_payload is required for approve.",
            }
        payload = dict(confirmation_payload)
        if selected_result_id:
            payload["selected_result_id"] = selected_result_id
        return self._graph.invoke({"session_id": session_id, "confirmation_payload": payload})
```

Run:

```bash
git rm app/domain/scoring.py
git rm tests/test_scoring.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_workflow.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/domain/models.py app/tools/search_tools.py app/workflow/state.py app/workflow/nodes.py app/workflow/graph.py tests/test_workflow.py
git rm app/domain/scoring.py
git rm tests/test_scoring.py
git commit -m "refactor: collapse workflow to single keyword path"
```

## Task 3: Wire The API To `FindKeywordLLM` And Make Approval Submit Paused qB Tasks

**Files:**
- Modify: `app/api/schemas.py`
- Modify: `app/api/chat_routes.py`
- Modify: `app/adapters/qbittorrent.py`
- Modify: `tests/test_chat_api.py`
- Modify: `tests/test_qb_adapter.py`
- Test: `tests/test_chat_api.py`
- Test: `tests/test_qb_adapter.py`

- [ ] **Step 1: Write the failing API and paused-submission tests**

```python
from fastapi.testclient import TestClient
from pathlib import Path
from uuid import uuid4

from app.api.chat_routes import AdapterDownloadExecutor
from app.main import create_app
from app.storage.session_store import SessionStore


class FakeRunner:
    def run_chat(self, session_id: str, message: str) -> dict:
        return {
            "session_id": session_id,
            "status": "awaiting_confirmation",
            "confirmation_payload": {
                "summary": f"fake:{message}",
                "recommended_result_id": "x1",
                "results": [
                    {
                        "id": "x1",
                        "title": "Fake Item",
                        "seeders": 0,
                        "resolution": "1080p",
                        "size": "10 GB",
                    }
                ],
            },
        }

    def run_confirm(
        self,
        session_id: str,
        *,
        action: str,
        confirmation_payload: dict | None,
        selected_result_id: str | None = None,
    ) -> dict:
        if action == "approve":
            chosen_id = selected_result_id or (confirmation_payload or {}).get("recommended_result_id", "x1")
            return {
                "session_id": session_id,
                "status": "completed",
                "confirmation_payload": confirmation_payload,
                "receipt": {
                    "resource_title": "Fake Item",
                    "external_id": chosen_id,
                    "qb_category": "movie",
                    "qb_hash": "fake-hash",
                    "status": "submitted_paused",
                },
            }
        return {"session_id": session_id, "status": "canceled", "messages": ["Request canceled by user."]}


def test_confirm_approve_returns_completed_with_paused_receipt():
    client = TestClient(create_app(workflow_runner=FakeRunner()))
    chat = client.post(
        "/chat",
        json={"session_id": "s1", "message": "I want to watch Dune tonight"},
    )
    payload = chat.json()["confirmation_payload"]
    response = client.post(
        "/confirm",
        json={
            "session_id": "s1",
            "action": "approve",
            "selected_result_id": payload["recommended_result_id"],
            "confirmation_payload": payload,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["receipt"]["status"] == "submitted_paused"
```

```python
def test_adapter_download_executor_submits_qb_task_paused():
    captured: dict[str, object] = {}

    class FakeMTeamAdapter:
        def get_torrent_details(self, torrent_id: str):
            _ = torrent_id
            return {"smallDescr": "沙丘2"}

        def get_torrent_download_url(self, torrent_id: str):
            _ = torrent_id
            return "https://download.local/file.torrent"

        def is_download_url_torrent(self, url: str) -> bool:
            _ = url
            return True

    class FakeQBAdapter:
        def generate_mteam_torrent_name(self, mteam_id, detail, qb_category):
            _ = mteam_id
            _ = detail
            _ = qb_category
            return "[fake]"

        def add_torrent_url(self, **kwargs):
            captured.update(kwargs)
            return {"ok": True, "status": "submitted_paused", "qb_hash": None}

    executor = AdapterDownloadExecutor(FakeMTeamAdapter(), FakeQBAdapter())
    result = executor({"id": "1172412", "title": "Fake"}, "movie")

    assert captured["paused"] is True
    assert result["status"] == "submitted_paused"
```

```python
import httpx

import app.adapters.qbittorrent as qb_module
from app.adapters.qbittorrent import QBittorrentAdapter


def test_add_torrent_url_reports_paused_submission(monkeypatch):
    class FakeResponse:
        def __init__(self, text: str):
            self.status_code = 200
            self.text = text

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            _ = args
            _ = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type
            _ = exc
            _ = tb
            return False

        def post(self, *args, **kwargs):
            _ = args
            _ = kwargs
            return FakeResponse("Ok.")

    adapter = QBittorrentAdapter(base_url="http://qb.local", username="u", password="p")
    monkeypatch.setattr(QBittorrentAdapter, "login", lambda self: httpx.Cookies())
    monkeypatch.setattr(qb_module.httpx, "Client", FakeClient)

    result = adapter.add_torrent_url(
        url="https://download.local/token",
        category="movie",
        rename="[123][movie][title]",
        paused=True,
    )

    assert result["ok"] is True
    assert result["status"] == "submitted_paused"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_chat_api.py tests/test_qb_adapter.py -q`
Expected: FAIL because the route protocol still includes refine fields and qB success still reports `submitted`.

- [ ] **Step 3: Implement the API wiring and paused semantics**

```python
"""Request/response payload schemas for the API layer."""

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ConfirmRequest(BaseModel):
    session_id: str
    action: str
    selected_result_id: str | None = None
    confirmation_payload: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    session_id: str
    status: str
    confirmation_payload: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None
    error: str | None = None


class ConfirmResponse(BaseModel):
    session_id: str
    status: str
    confirmation_payload: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None
    error: str | None = None
    messages: list[str] = Field(default_factory=list)
```

```python
"""HTTP routes for chat and confirmation against the workflow runner."""

from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.api.schemas import ChatRequest, ChatResponse, ConfirmRequest, ConfirmResponse
from app.config import get_settings
from app.domain.models import ResourceCandidate
from app.llm.find_keyword_llm import FindKeywordLLM
from app.workflow.graph import LangGraphWorkflowRunner, build_workflow

_FRONTEND_INDEX = Path(__file__).resolve().parents[2] / "frontend" / "index.html"


class WorkflowRunner(Protocol):
    def run_chat(self, session_id: str, message: str) -> dict[str, Any]:
        ...

    def run_confirm(
        self,
        session_id: str,
        *,
        action: str,
        confirmation_payload: dict[str, Any] | None,
        selected_result_id: str | None = None,
    ) -> dict[str, Any]:
        ...


class AdapterSearchTool:
    def __init__(self, adapter: MTeamAdapter):
        self._adapter = adapter

    def __call__(self, keyword: str) -> list[ResourceCandidate]:
        rows = self._adapter.search_torrents_by_keyword(
            keyword=keyword,
            page=1,
            page_size=20,
        )
        candidates: list[ResourceCandidate] = []
        for row in rows:
            title = str(row.get("title") or row.get("name") or f"M-Team {row.get('id', '')}")
            lowered_title = title.lower()
            media_type = "movie"
            if "s01" in lowered_title or "season" in lowered_title:
                media_type = "tv"
            candidates.append(
                ResourceCandidate(
                    id=str(row.get("id")),
                    title=title,
                    media_type=media_type,
                    resolution="2160p" if "2160" in lowered_title or "4k" in lowered_title else "1080p",
                    seeders=int(row.get("seeders", 0) or 0),
                    size=str(row.get("size", "unknown")),
                    size_bytes=int(row["size_bytes"]) if row.get("size_bytes") is not None else None,
                    source="mteam",
                )
            )
        return candidates


class AdapterDownloadExecutor:
    def __init__(self, mteam_adapter: MTeamAdapter, qb_adapter: QBittorrentAdapter):
        self._mteam_adapter = mteam_adapter
        self._qb_adapter = qb_adapter

    def __call__(self, selected_result: dict[str, Any], qb_category: str) -> dict[str, Any]:
        external_id = str(selected_result["id"])
        detail = self._mteam_adapter.get_torrent_details(external_id)
        if not detail:
            return {"status": "detail_failed", "qb_hash": None}
        download_url = self._mteam_adapter.get_torrent_download_url(external_id)
        if not download_url:
            return {"status": "download_url_failed", "qb_hash": None}
        if not self._mteam_adapter.is_download_url_torrent(download_url):
            return {"status": "download_url_invalid", "qb_hash": None}
        rename = self._qb_adapter.generate_mteam_torrent_name(external_id, detail, qb_category)
        add_result = self._qb_adapter.add_torrent_url(
            url=download_url,
            category=qb_category,
            rename=rename,
            tags=["mteam"],
            paused=True,
        )
        if add_result.get("ok"):
            return {"status": str(add_result.get("status", "submitted_paused")), "qb_hash": add_result.get("qb_hash")}
        return {
            "status": str(add_result.get("status", "submit_failed")),
            "qb_hash": add_result.get("qb_hash"),
        }


def _build_default_runner() -> WorkflowRunner:
    settings = get_settings()
    mteam_adapter = MTeamAdapter(
        base_url=settings.mteam_base_url,
        api_key=settings.mteam_api_key,
    )
    qb_adapter = QBittorrentAdapter(
        base_url=settings.qb_base_url,
        username=settings.qb_username,
        password=settings.qb_password,
    )
    graph = build_workflow(
        keyword_finder=FindKeywordLLM(),
        search_tool=AdapterSearchTool(mteam_adapter),
        download_executor=AdapterDownloadExecutor(mteam_adapter, qb_adapter),
    )
    return LangGraphWorkflowRunner(graph)


def build_router(workflow_runner: WorkflowRunner | None = None) -> APIRouter:
    runner = workflow_runner or _build_default_runner()
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        result = runner.run_chat(request.session_id, request.message)
        return ChatResponse(
            session_id=request.session_id,
            status=result.get("status", "error"),
            confirmation_payload=result.get("confirmation_payload"),
            receipt=result.get("receipt"),
            error=result.get("error"),
        )

    @router.post("/confirm", response_model=ConfirmResponse)
    def confirm(request: ConfirmRequest) -> ConfirmResponse:
        result = runner.run_confirm(
            request.session_id,
            action=request.action,
            confirmation_payload=request.confirmation_payload,
            selected_result_id=request.selected_result_id,
        )
        confirmation_payload = result.get("confirmation_payload")
        receipt = result.get("receipt")
        if receipt is None and isinstance(confirmation_payload, dict):
            receipt = confirmation_payload.get("receipt")
        messages = result.get("messages") or []
        return ConfirmResponse(
            session_id=request.session_id,
            status=result.get("status", "error"),
            confirmation_payload=confirmation_payload,
            receipt=receipt,
            error=result.get("error"),
            messages=[str(msg) for msg in messages],
        )

    @router.get("/", response_class=HTMLResponse)
    def index() -> str:
        if _FRONTEND_INDEX.exists():
            return _FRONTEND_INDEX.read_text(encoding="utf-8")
        return "<h1>fnOS Media Agent</h1>"

    return router


router = build_router()
```

```python
"""qBittorrent adapter for URL-based torrent submission."""

from dataclasses import dataclass
import re
from typing import Any

import httpx


@dataclass(slots=True)
class QBittorrentAdapter:
    base_url: str
    username: str
    password: str
    timeout_seconds: float = 10.0

    def _normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")

    def login_endpoint(self) -> str:
        return f"{self._normalized_base_url()}/api/v2/auth/login"

    def add_torrent_endpoint(self) -> str:
        return f"{self._normalized_base_url()}/api/v2/torrents/add"

    def categories_endpoint(self) -> str:
        return f"{self._normalized_base_url()}/api/v2/torrents/categories"

    def build_login_payload(self) -> dict[str, str]:
        return {"username": self.username, "password": self.password}

    def build_add_payload(
        self,
        url: str,
        category: str,
        rename: str,
        paused: bool = False,
        tags: list[str] | None = None,
    ) -> dict[str, str]:
        clean_url = url.strip()
        clean_category = category.strip()
        clean_rename = rename.strip()
        if not clean_url:
            raise ValueError("url must not be empty")
        if not clean_category:
            raise ValueError("category must not be empty")
        if not clean_rename:
            raise ValueError("rename must not be empty")

        payload: dict[str, str] = {
            "urls": clean_url,
            "category": clean_category,
            "rename": clean_rename,
            "paused": "true" if paused else "false",
        }
        if tags:
            payload["tags"] = ",".join(tag.strip() for tag in tags if tag.strip())
        return payload

    def _is_configured(self) -> bool:
        return bool(self.base_url.strip() and self.username.strip() and self.password.strip())

    def login(self) -> httpx.Cookies | None:
        if not self._is_configured():
            return None
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(self.login_endpoint(), data=self.build_login_payload())
            response.raise_for_status()
            return response.cookies

    def list_categories(self) -> dict[str, Any]:
        cookies = self.login()
        if cookies is None:
            return {}
        with httpx.Client(timeout=self.timeout_seconds, cookies=cookies) as client:
            response = client.get(self.categories_endpoint())
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}

    def add_torrent_url(
        self,
        url: str,
        category: str,
        rename: str,
        paused: bool = False,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        cookies = self.login()
        if cookies is None:
            return {"ok": False, "status": "not_configured", "qb_hash": None}
        payload = self.build_add_payload(
            url=url,
            category=category,
            rename=rename,
            paused=paused,
            tags=tags,
        )
        with httpx.Client(timeout=self.timeout_seconds, cookies=cookies) as client:
            response = client.post(self.add_torrent_endpoint(), data=payload)
            response.raise_for_status()
            body = response.text.strip().lower()
            ok = body in {"ok.", "ok"}
            if not ok:
                status = "unknown"
            else:
                status = "submitted_paused" if paused else "submitted"
            return {
                "ok": ok,
                "status": status,
                "qb_hash": None,
                "raw_response": response.text,
            }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_chat_api.py tests/test_qb_adapter.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/schemas.py app/api/chat_routes.py app/adapters/qbittorrent.py tests/test_chat_api.py tests/test_qb_adapter.py
git commit -m "feat: wire paused qB approval path"
```

## Task 4: Verify The Phase 2A Path End-To-End At The Test Level

**Files:**
- Modify as needed based on verification results

- [ ] **Step 1: Run the focused Phase 2A test suite**

Run:

```bash
python -m pytest tests/test_find_keyword_llm.py tests/test_workflow.py tests/test_chat_api.py tests/test_qb_adapter.py tests/test_mteam_adapter.py -q
```

Expected: PASS

- [ ] **Step 2: Run the integration connectivity test intentionally**

Run:

```bash
python -m pytest tests/integration/test_connectivity.py -q
```

Expected:
- SKIP when `RUN_CONNECTIVITY_TESTS` is not enabled
- PASS when enabled and real credentials are configured

- [ ] **Step 3: Confirm the old scoring path is gone from active code**

Run:

```bash
rg -n "SearchConstraints|ScoredCandidate|score_results_node|score_candidates|test_scoring" app tests
```

Expected: no matches inside active application and test code.

- [ ] **Step 4: Fix any failures before claiming success**

Use targeted reruns, for example:

```bash
python -m pytest tests/test_workflow.py -q
python -m pytest tests/test_chat_api.py::test_confirm_approve_returns_completed_with_paused_receipt -q
python -m pytest tests/test_qb_adapter.py::test_add_torrent_url_reports_paused_submission -q
```

Expected: all failures resolved before completion.

- [ ] **Step 5: Commit**

```bash
git add app tests
git commit -m "test: verify phase 2a single keyword path"
```

## Self-Review

### Spec Coverage

This plan covers the approved Phase 2A scope:

- single-keyword LLM extraction,
- no raw-sentence M-Team search,
- top-3 candidate projection,
- removal of scoring structures,
- paused qB approval semantics,
- receipt clarity for paused submission.

### Placeholder Scan

The plan avoids `TBD`, `TODO`, and vague deferral steps. The only follow-up intentionally deferred is Phase 2B refine-state work, which is explicitly outside this plan.

### Type Consistency

Keep these names consistent throughout implementation:

- `FindKeywordLLM`
- `keyword`
- `ResourceCandidate`
- `build_confirmation_payload_node`
- `submitted_paused`

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-26-fnos-media-agent-phase2a-search-path-implementation-plan.md`.

Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using the plan directly, with checkpoints as we go.
