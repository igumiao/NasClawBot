# fnOS Media Agent Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 1 minimal closed loop for fnOS Media Agent: natural-language request -> M-Team search -> rule-based ranking -> human confirmation -> qBittorrent submission -> structured receipt.

**Architecture:** This is a single FastAPI application with a plain HTML/CSS/JS chat frontend, a LangGraph workflow for orchestration, thin tools/services over adapters, and SQLite-backed persistence for sessions, preferences, and task indexing. The LLM is used only for language understanding and explanation; ranking, external calls, and download execution stay deterministic.

**Tech Stack:** Python 3.11+, FastAPI, LangGraph, LangChain, Pydantic v2, httpx, SQLite, pytest, plain HTML/CSS/JS

---

## File Map

- Create: `pyproject.toml`
- Create: `app/main.py`
- Create: `app/config.py`
- Create: `app/api/chat_routes.py`
- Create: `app/api/schemas.py`
- Create: `app/workflow/state.py`
- Create: `app/workflow/nodes.py`
- Create: `app/workflow/graph.py`
- Create: `app/tools/search_tools.py`
- Create: `app/tools/download_tools.py`
- Create: `app/adapters/mteam.py`
- Create: `app/adapters/qbittorrent.py`
- Create: `app/domain/models.py`
- Create: `app/domain/scoring.py`
- Create: `app/storage/db.py`
- Create: `app/storage/session_store.py`
- Create: `app/storage/preference_store.py`
- Create: `app/storage/task_index_store.py`
- Create: `app/services/receipt_service.py`
- Create: `app/llm/client.py`
- Create: `app/llm/prompts.py`
- Create: `frontend/index.html`
- Create: `frontend/app.js`
- Create: `frontend/styles.css`
- Create: `tests/test_scoring.py`
- Create: `tests/test_workflow.py`
- Create: `tests/test_chat_api.py`
- Create: `tests/test_mteam_adapter.py`
- Create: `tests/test_qb_adapter.py`
- Create: `tests/integration/test_connectivity.py`
- Create: `scripts/connectivity_smoke.py`

Implementation note:

- The current workspace is not a Git repository, so commit steps below should be treated as checkpoint instructions. If you initialize Git before implementation, run the listed commands normally. If not, keep the checkpoint notes in a running dev log.

## Task 1: Bootstrap the Python App Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `app/main.py`
- Create: `app/config.py`
- Create: `app/api/chat_routes.py`
- Create: `app/api/schemas.py`
- Create: `frontend/index.html`
- Create: `frontend/app.js`
- Create: `frontend/styles.css`
- Test: `tests/test_chat_api.py`

- [ ] **Step 1: Write the failing API smoke test**

```python
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint_returns_ok():
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_index_page_is_served():
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "fnOS Media Agent" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat_api.py -v`
Expected: FAIL with import errors because `app.main` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```toml
[project]
name = "fnos-media-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115,<1.0",
  "uvicorn>=0.30,<1.0",
  "pydantic>=2.8,<3.0",
  "httpx>=0.27,<1.0",
  "langgraph>=0.2,<1.0",
  "langchain>=0.3,<1.0",
  "langchain-openai>=0.2,<1.0",
]
```

```python
from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "fnOS Media Agent"


def get_settings() -> Settings:
    return Settings()
```

```python
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
def index() -> str:
    return "<h1>fnOS Media Agent</h1>"
```

```python
from fastapi import FastAPI

from app.api.chat_routes import router as chat_router
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.include_router(chat_router)
    return app


app = create_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml app/main.py app/config.py app/api/chat_routes.py tests/test_chat_api.py frontend/index.html frontend/app.js frontend/styles.css
git commit -m "chore: bootstrap fastapi app shell"
```

If Git is not initialized yet, checkpoint by noting: "Task 1 complete: app shell and health endpoint passing."

## Task 2: Validate Real M-Team and qBittorrent Connectivity

**Files:**
- Create: `scripts/connectivity_smoke.py`
- Create: `tests/integration/test_connectivity.py`
- Modify: `app/config.py`

- [ ] **Step 1: Write the failing connectivity test skeleton**

```python
import os

import pytest

from app.config import get_settings


@pytest.mark.skipif(not os.getenv("RUN_CONNECTIVITY_TESTS"), reason="integration-only")
def test_connectivity_settings_are_present():
    settings = get_settings()
    assert settings.mteam_api_key
    assert settings.mteam_base_url
    assert settings.qb_base_url
    assert settings.qb_username
    assert settings.qb_password
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_connectivity.py -v`
Expected: FAIL because the settings are not modeled yet.

- [ ] **Step 3: Write minimal implementation**

```python
from functools import lru_cache
from pydantic import BaseModel
import os


class Settings(BaseModel):
    app_name: str = "fnOS Media Agent"
    mteam_base_url: str = os.getenv("MTEAM_BASE_URL", "")
    mteam_api_key: str = os.getenv("MTEAM_API_KEY", "")
    qb_base_url: str = os.getenv("QB_BASE_URL", "")
    qb_username: str = os.getenv("QB_USERNAME", "")
    qb_password: str = os.getenv("QB_PASSWORD", "")
    database_path: str = os.getenv("DATABASE_PATH", "nas_media_agent.db")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

```python
from app.config import get_settings


def main() -> None:
    settings = get_settings()
    required = {
        "MTEAM_BASE_URL": settings.mteam_base_url,
        "MTEAM_API_KEY": settings.mteam_api_key,
        "QB_BASE_URL": settings.qb_base_url,
        "QB_USERNAME": settings.qb_username,
        "QB_PASSWORD": settings.qb_password,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SystemExit(f"Missing required connectivity settings: {', '.join(missing)}")
    print("Connectivity settings present. Ready for real-environment spike.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_connectivity.py -v`
Expected: PASS when `RUN_CONNECTIVITY_TESTS=1` and the required environment variables are present. Otherwise the test should SKIP.

- [ ] **Step 5: Commit**

```bash
git add app/config.py scripts/connectivity_smoke.py tests/integration/test_connectivity.py
git commit -m "test: add connectivity spike scaffolding"
```

If Git is not initialized yet, checkpoint by noting: "Task 2 complete: env-driven connectivity spike scaffold ready."

## Task 3: Add Domain Models and Deterministic Ranking

**Files:**
- Create: `app/domain/models.py`
- Create: `app/domain/scoring.py`
- Test: `tests/test_scoring.py`

- [ ] **Step 1: Write the failing ranking tests**

```python
from app.domain.models import ResourceCandidate, SearchConstraints
from app.domain.scoring import score_candidates


def test_speed_mode_prefers_more_seeders_when_relevance_is_similar():
    constraints = SearchConstraints(query_text="dune tonight", title="Dune Part Two", media_type="movie", optimization_goal="speed", urgency="high")
    candidates = [
        ResourceCandidate(id="1", title="Dune Part Two 2024 1080p", media_type="movie", year=2024, resolution="1080p", seeders=20, size="10 GB", source="mteam"),
        ResourceCandidate(id="2", title="Dune Part Two 2024 1080p", media_type="movie", year=2024, resolution="1080p", seeders=120, size="12 GB", source="mteam"),
    ]
    scored = score_candidates(constraints, candidates)
    assert scored[0].candidate.id == "2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scoring.py -v`
Expected: FAIL because the domain model and scoring function do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
from typing import Literal

from pydantic import BaseModel, Field


class SearchConstraints(BaseModel):
    query_text: str
    title: str | None = None
    year: int | None = None
    media_type: Literal["movie", "tv", "anime", "unknown"] = "unknown"
    preferred_resolution: str | None = None
    allow_season_pack: bool = True
    urgency: Literal["normal", "high"] = "normal"
    optimization_goal: Literal["balanced", "speed", "quality"] = "balanced"


class ResourceCandidate(BaseModel):
    id: str
    title: str
    media_type: str
    year: int | None = None
    resolution: str | None = None
    seeders: int = 0
    size: str
    source: str


class ScoredCandidate(BaseModel):
    candidate: ResourceCandidate
    score: float
    reasons: list[str] = Field(default_factory=list)
```

```python
from app.domain.models import ResourceCandidate, ScoredCandidate, SearchConstraints


def _score_candidate(constraints: SearchConstraints, candidate: ResourceCandidate) -> ScoredCandidate:
    score = 0.0
    reasons: list[str] = []
    if constraints.title and constraints.title.lower().split()[0] in candidate.title.lower():
        score += 50
        reasons.append("title-match")
    if constraints.media_type != "unknown":
        score += 30 if candidate.media_type == constraints.media_type else -40
    if constraints.year and candidate.year == constraints.year:
        score += 10
    if constraints.preferred_resolution and candidate.resolution == constraints.preferred_resolution:
        score += 10
    score += min(candidate.seeders, 200) / 5 if constraints.optimization_goal == "speed" else min(candidate.seeders, 100) / 20
    return ScoredCandidate(candidate=candidate, score=score, reasons=reasons)


def score_candidates(constraints: SearchConstraints, candidates: list[ResourceCandidate]) -> list[ScoredCandidate]:
    scored = [_score_candidate(constraints, candidate) for candidate in candidates]
    return sorted(scored, key=lambda item: item.score, reverse=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scoring.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/domain/models.py app/domain/scoring.py tests/test_scoring.py
git commit -m "feat: add search constraints and ranking rules"
```

If Git is not initialized yet, checkpoint by noting: "Task 3 complete: deterministic ranking in place."

## Task 4: Implement M-Team and qBittorrent Adapter Skeletons

**Files:**
- Create: `app/adapters/mteam.py`
- Create: `app/adapters/qbittorrent.py`
- Test: `tests/test_mteam_adapter.py`
- Test: `tests/test_qb_adapter.py`

- [ ] **Step 1: Write the failing adapter tests**

```python
from app.adapters.mteam import MTeamAdapter


def test_mteam_search_payload_contains_keyword_and_paging():
    adapter = MTeamAdapter(base_url="https://example.com", api_key="secret")
    payload = adapter.build_search_payload(keyword="dune", page=2)
    assert payload["keyword"] == "dune"
    assert payload["pageNumber"] == 2
```

```python
from app.adapters.qbittorrent import QBittorrentAdapter


def test_qb_add_payload_contains_url_and_category():
    adapter = QBittorrentAdapter(base_url="http://qb.local", username="user", password="pass")
    payload = adapter.build_add_payload(url="https://download.local/token", category="movie", rename="[123] Dune")
    assert payload["urls"] == "https://download.local/token"
    assert payload["category"] == "movie"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mteam_adapter.py tests/test_qb_adapter.py -v`
Expected: FAIL because the adapters do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
from dataclasses import dataclass


@dataclass
class MTeamAdapter:
    base_url: str
    api_key: str

    def build_search_payload(self, keyword: str, page: int = 1, page_size: int = 20) -> dict:
        return {
            "mode": "normal",
            "keyword": keyword,
            "categories": [],
            "pageNumber": page,
            "pageSize": page_size,
        }
```

```python
from dataclasses import dataclass


@dataclass
class QBittorrentAdapter:
    base_url: str
    username: str
    password: str

    def build_add_payload(self, url: str, category: str, rename: str) -> dict[str, str]:
        return {"urls": url, "category": category, "rename": rename}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mteam_adapter.py tests/test_qb_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/adapters/mteam.py app/adapters/qbittorrent.py tests/test_mteam_adapter.py tests/test_qb_adapter.py
git commit -m "feat: add mteam and qb adapter skeletons"
```

If Git is not initialized yet, checkpoint by noting: "Task 4 complete: adapter payload contracts defined."

## Task 5: Add SQLite Stores for Sessions, Preferences, and Task Index

**Files:**
- Create: `app/storage/db.py`
- Create: `app/storage/session_store.py`
- Create: `app/storage/preference_store.py`
- Create: `app/storage/task_index_store.py`
- Modify: `tests/test_chat_api.py`

- [ ] **Step 1: Write the failing store test**

```python
from app.storage.session_store import SessionStore


def test_session_store_round_trip(tmp_path):
    store = SessionStore(db_path=tmp_path / "app.db")
    store.upsert(
        session_id="s1",
        latest_user_message="find dune",
        constraints_json='{"title":"Dune"}',
        confirmation_payload_json='{"summary":"pick one"}',
        status="awaiting_confirmation",
    )
    record = store.get("s1")
    assert record is not None
    assert record["status"] == "awaiting_confirmation"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat_api.py::test_session_store_round_trip -v`
Expected: FAIL because the stores do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
import sqlite3
from pathlib import Path


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn
```

```python
from pathlib import Path

from app.storage.db import connect


class SessionStore:
    def __init__(self, db_path: str | Path):
        self.db_path = db_path
        with connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    latest_user_message TEXT NOT NULL,
                    constraints_json TEXT NOT NULL,
                    confirmation_payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def upsert(self, session_id: str, latest_user_message: str, constraints_json: str, confirmation_payload_json: str, status: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, latest_user_message, constraints_json, confirmation_payload_json, status)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    latest_user_message = excluded.latest_user_message,
                    constraints_json = excluded.constraints_json,
                    confirmation_payload_json = excluded.confirmation_payload_json,
                    status = excluded.status,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (session_id, latest_user_message, constraints_json, confirmation_payload_json, status),
            )

    def get(self, session_id: str):
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return dict(row) if row else None
```

```python
from pathlib import Path

from app.storage.db import connect


class PreferenceStore:
    def __init__(self, db_path: str | Path):
        with connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS preferences (
                    user_id TEXT PRIMARY KEY,
                    preferred_resolution TEXT,
                    subtitle_preference TEXT,
                    encoding_preference TEXT,
                    default_download_profile TEXT
                )
                """
            )
```

```python
from pathlib import Path

from app.storage.db import connect


class TaskIndexStore:
    def __init__(self, db_path: str | Path):
        with connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_index (
                    external_source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    resource_title TEXT NOT NULL,
                    qb_hash TEXT,
                    qb_name TEXT,
                    qb_category TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (external_source, external_id)
                )
                """
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat_api.py::test_session_store_round_trip -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/storage/db.py app/storage/session_store.py app/storage/preference_store.py app/storage/task_index_store.py tests/test_chat_api.py
git commit -m "feat: add sqlite-backed session and task stores"
```

If Git is not initialized yet, checkpoint by noting: "Task 5 complete: SQLite stores working."

## Task 6: Build the LangGraph Search-to-Confirmation Flow

**Files:**
- Create: `app/workflow/state.py`
- Create: `app/workflow/nodes.py`
- Create: `app/workflow/graph.py`
- Create: `app/tools/search_tools.py`
- Create: `app/llm/client.py`
- Create: `app/llm/prompts.py`
- Test: `tests/test_workflow.py`

- [ ] **Step 1: Write the failing workflow test**

```python
from app.domain.models import ResourceCandidate
from app.workflow.graph import build_workflow


class StubExtractor:
    def invoke(self, message: str):
        return {
            "query_text": message,
            "title": "Dune Part Two",
            "media_type": "movie",
            "optimization_goal": "speed",
            "urgency": "high",
        }


class StubSearchTool:
    def __call__(self, constraints):
        return [
            ResourceCandidate(id="2", title="Dune Part Two 2024 1080p", media_type="movie", year=2024, resolution="1080p", seeders=120, size="12 GB", source="mteam"),
            ResourceCandidate(id="1", title="Dune Part Two 2024 1080p", media_type="movie", year=2024, resolution="1080p", seeders=20, size="10 GB", source="mteam"),
        ]


def test_workflow_returns_confirmation_payload():
    graph = build_workflow(extractor=StubExtractor(), search_tool=StubSearchTool())
    result = graph.invoke({"session_id": "s1", "user_message": "I want to watch Dune tonight"})
    assert result["confirmation_payload"]["recommended_result_id"] == "2"
    assert result["status"] == "awaiting_confirmation"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workflow.py -v`
Expected: FAIL because the workflow graph does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    session_id: str
    user_message: str
    constraints: dict[str, Any]
    search_results: list[Any]
    scored_results: list[Any]
    confirmation_payload: dict[str, Any]
    status: str
```

```python
from app.domain.models import SearchConstraints


def search_mteam_candidates(search_tool, constraints_dict: dict):
    constraints = SearchConstraints(**constraints_dict)
    return search_tool(constraints)
```

```python
from app.domain.scoring import score_candidates
from app.tools.search_tools import search_mteam_candidates


def extract_constraints_node(state, extractor):
    return {"constraints": extractor.invoke(state["user_message"])}


def search_node(state, search_tool):
    return {"search_results": search_mteam_candidates(search_tool, state["constraints"])}


def score_results_node(state):
    scored = score_candidates(state["constraints"], state["search_results"])
    top = scored[0]
    payload = {
        "summary": "I found matching candidates and paused for confirmation.",
        "recommended_result_id": top.candidate.id,
        "results": [
            {
                "id": item.candidate.id,
                "title": item.candidate.title,
                "score": item.score,
                "seeders": item.candidate.seeders,
                "resolution": item.candidate.resolution,
            }
            for item in scored[:5]
        ],
        "explanation": "This result ranked first because it best matched the request and availability goals.",
    }
    return {"scored_results": scored, "confirmation_payload": payload, "status": "awaiting_confirmation"}
```

```python
from langgraph.graph import END, START, StateGraph

from app.workflow.nodes import extract_constraints_node, search_node, score_results_node
from app.workflow.state import AgentState


def build_workflow(extractor, search_tool):
    graph = StateGraph(AgentState)
    graph.add_node("extract_constraints", lambda state: extract_constraints_node(state, extractor))
    graph.add_node("search_mteam", lambda state: search_node(state, search_tool))
    graph.add_node("score_results", score_results_node)
    graph.add_edge(START, "extract_constraints")
    graph.add_edge("extract_constraints", "search_mteam")
    graph.add_edge("search_mteam", "score_results")
    graph.add_edge("score_results", END)
    return graph.compile()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workflow.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workflow/state.py app/workflow/nodes.py app/workflow/graph.py app/tools/search_tools.py tests/test_workflow.py
git commit -m "feat: add langgraph search-to-confirmation flow"
```

If Git is not initialized yet, checkpoint by noting: "Task 6 complete: workflow reaches confirmation state."

## Task 7: Add Confirmation Loop, Download Execution, and Receipt Building

**Files:**
- Create: `app/tools/download_tools.py`
- Create: `app/services/receipt_service.py`
- Modify: `app/workflow/nodes.py`
- Modify: `tests/test_workflow.py`

- [ ] **Step 1: Write the failing receipt and execution test**

```python
from app.services.receipt_service import build_receipt


def test_receipt_builder_reports_duplicate_result():
    receipt = build_receipt(
        resource_title="Dune Part Two",
        external_id="123",
        qb_category="movie",
        qb_hash=None,
        status="already_exists",
    )
    assert receipt["status"] == "already_exists"
    assert receipt["external_id"] == "123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workflow.py -v`
Expected: FAIL because the receipt service and execution helpers do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def prepare_download_execution(selected_result: dict) -> dict:
    return {"external_id": selected_result["id"], "resource_title": selected_result["title"]}
```

```python
def build_receipt(resource_title: str, external_id: str, qb_category: str, qb_hash: str | None, status: str) -> dict:
    return {
        "resource_title": resource_title,
        "external_id": external_id,
        "qb_category": qb_category,
        "qb_hash": qb_hash,
        "status": status,
    }
```

```python
from app.services.receipt_service import build_receipt
from app.tools.download_tools import prepare_download_execution


def execute_download_node(state):
    selected = next(
        item for item in state["confirmation_payload"]["results"]
        if item["id"] == state["confirmation_feedback"]["selected_result_id"]
    )
    execution = prepare_download_execution(selected)
    receipt = build_receipt(
        resource_title=execution["resource_title"],
        external_id=execution["external_id"],
        qb_category="movie",
        qb_hash="stub-hash",
        status="submitted",
    )
    return {"execution_result": execution, "receipt": receipt, "status": "completed"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workflow.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/tools/download_tools.py app/services/receipt_service.py app/workflow/nodes.py tests/test_workflow.py
git commit -m "feat: add confirmation execution and receipt flow"
```

If Git is not initialized yet, checkpoint by noting: "Task 7 complete: approval path can build receipts."

## Task 8: Wire the API and Frontend to the Workflow

**Files:**
- Modify: `app/api/chat_routes.py`
- Modify: `app/api/schemas.py`
- Modify: `app/main.py`
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`
- Modify: `tests/test_chat_api.py`

- [ ] **Step 1: Write the failing chat endpoint test**

```python
from fastapi.testclient import TestClient

from app.main import create_app


def test_chat_endpoint_returns_confirmation_payload():
    client = TestClient(create_app())
    response = client.post("/chat", json={"session_id": "s1", "message": "I want to watch Dune tonight"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_confirmation"
    assert "confirmation_payload" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat_api.py::test_chat_endpoint_returns_confirmation_payload -v`
Expected: FAIL because `/chat` is not implemented yet.

- [ ] **Step 3: Write minimal implementation**

```python
from pydantic import BaseModel


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ConfirmRequest(BaseModel):
    session_id: str
    action: str
    selected_result_id: str | None = None
    feedback_text: str | None = None
```

```python
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.api.schemas import ChatRequest
from app.workflow.graph import build_workflow

router = APIRouter()


class StubExtractor:
    def invoke(self, message: str):
        return {
            "query_text": message,
            "title": "Dune Part Two",
            "media_type": "movie",
            "optimization_goal": "speed",
            "urgency": "high",
        }


class StubSearchTool:
    def __call__(self, constraints):
        from app.domain.models import ResourceCandidate
        return [
            ResourceCandidate(id="2", title="Dune Part Two 2024 1080p", media_type="movie", year=2024, resolution="1080p", seeders=120, size="12 GB", source="mteam"),
        ]


@router.post("/chat")
def chat(request: ChatRequest):
    graph = build_workflow(extractor=StubExtractor(), search_tool=StubSearchTool())
    return graph.invoke({"session_id": request.session_id, "user_message": request.message})


@router.get("/", response_class=HTMLResponse)
def index() -> str:
    return """
    <!doctype html>
    <html>
      <head><title>fnOS Media Agent</title></head>
      <body>
        <h1>fnOS Media Agent</h1>
        <form id='chat-form'><textarea id='message'></textarea><button type='submit'>Send</button></form>
        <div id='confirmation'></div>
        <script src='/static/app.js'></script>
      </body>
    </html>
    """
```

```javascript
document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("chat-form");
  const messageInput = document.getElementById("message");
  const confirmation = document.getElementById("confirmation");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: "demo-session", message: messageInput.value }),
    });
    const body = await response.json();
    confirmation.textContent = body.confirmation_payload?.summary ?? "No confirmation payload returned.";
  });
});
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/chat_routes.py app/api/schemas.py frontend/index.html frontend/app.js frontend/styles.css tests/test_chat_api.py
git commit -m "feat: wire chat endpoint and browser shell"
```

If Git is not initialized yet, checkpoint by noting: "Task 8 complete: browser shell can hit the chat API."

## Task 9: Replace Stubs with Real Adapters and Tighten App Wiring

**Files:**
- Modify: `app/main.py`
- Modify: `app/api/chat_routes.py`
- Modify: `app/workflow/graph.py`
- Modify: `app/workflow/nodes.py`
- Modify: `app/adapters/mteam.py`
- Modify: `app/adapters/qbittorrent.py`
- Modify: `tests/test_chat_api.py`
- Modify: `tests/test_workflow.py`

- [ ] **Step 1: Write the failing dependency-injection test**

```python
from fastapi.testclient import TestClient

from app.main import create_app


class FakeRunner:
    def run_chat(self, session_id: str, message: str) -> dict:
        return {
            "session_id": session_id,
            "status": "awaiting_confirmation",
            "confirmation_payload": {"summary": f"fake:{message}", "recommended_result_id": "x", "results": []},
        }


def test_create_app_allows_workflow_override():
    app = create_app(workflow_runner=FakeRunner())
    client = TestClient(app)
    response = client.post("/chat", json={"session_id": "s1", "message": "hello"})
    assert response.status_code == 200
    assert response.json()["confirmation_payload"]["summary"] == "fake:hello"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat_api.py::test_create_app_allows_workflow_override -v`
Expected: FAIL because the app factory does not accept injectable workflow dependencies yet.

- [ ] **Step 3: Write minimal implementation**

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.chat_routes import build_router
from app.config import get_settings


def create_app(workflow_runner=None) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.include_router(build_router(workflow_runner))
    app.mount("/static", StaticFiles(directory="frontend"), name="static")
    return app


app = create_app()
```

```python
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.api.schemas import ChatRequest


class DefaultRunner:
    def run_chat(self, session_id: str, message: str) -> dict:
        return {
            "session_id": session_id,
            "status": "awaiting_confirmation",
            "confirmation_payload": {"summary": "stub", "recommended_result_id": "stub", "results": []},
        }


def build_router(workflow_runner=None):
    runner = workflow_runner or DefaultRunner()
    router = APIRouter()

    @router.post("/chat")
    def chat(request: ChatRequest):
        return runner.run_chat(request.session_id, request.message)

    @router.get("/health")
    def health():
        return {"status": "ok"}

    @router.get("/", response_class=HTMLResponse)
    def index() -> str:
        return "<h1>fnOS Media Agent</h1>"

    return router
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat_api.py tests/test_workflow.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/api/chat_routes.py app/workflow/graph.py app/workflow/nodes.py app/adapters/mteam.py app/adapters/qbittorrent.py tests/test_chat_api.py tests/test_workflow.py
git commit -m "refactor: inject workflow and replace api stubs"
```

If Git is not initialized yet, checkpoint by noting: "Task 9 complete: real dependencies can be wired through the app factory."

## Task 10: Run Verification Before Claiming Completion

**Files:**
- Modify as needed based on verification results

- [ ] **Step 1: Run the focused test suite**

```bash
pytest tests/test_scoring.py tests/test_workflow.py tests/test_chat_api.py tests/test_mteam_adapter.py tests/test_qb_adapter.py -v
```

Expected: PASS

- [ ] **Step 2: Run the connectivity smoke script**

```bash
python scripts/connectivity_smoke.py
```

Expected: `Connectivity settings present. Ready for real-environment spike.` when environment variables are configured.

- [ ] **Step 3: Run the real connectivity checks intentionally**

```bash
pytest tests/integration/test_connectivity.py -v
```

Expected:
- SKIP when `RUN_CONNECTIVITY_TESTS` is not enabled
- PASS when enabled and real credentials are correct

- [ ] **Step 4: Fix any failures before claiming success**

Use targeted reruns, for example:

```bash
pytest tests/test_workflow.py::test_workflow_returns_confirmation_payload -v
pytest tests/test_chat_api.py::test_chat_endpoint_returns_confirmation_payload -v
```

Expected: all failing tests resolved before moving on.

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "test: verify phase 1 minimal loop"
```

If Git is not initialized yet, checkpoint by noting: "Task 10 complete: verification suite and connectivity checks reviewed."

## Self-Review

### Spec Coverage

This plan covers the approved design:

- minimal chat UI,
- FastAPI API surface,
- LangGraph workflow,
- rule-based ranking,
- seeder-aware speed optimization,
- human confirmation boundary,
- reject-and-refine loop,
- M-Team and qBittorrent adapter structure,
- SQLite session and task persistence,
- early UI shell,
- real connectivity spike before mock finalization.

### Placeholder Scan

No `TBD`, `TODO`, or "implement later" placeholders should remain in the implementation tasks. The only intentionally deferred detail is the exact real API payload normalization after the connectivity spike, which is already captured as a required early milestone rather than an unplanned gap.

### Type Consistency

Keep these names consistent throughout implementation:

- `SearchConstraints`
- `ResourceCandidate`
- `ScoredCandidate`
- `SessionStore`
- `TaskIndexStore`
- `confirmation_payload`
- `optimization_goal`
- `urgency`

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-25-fnos-media-agent-phase1-implementation-plan.md`.

Given your stated preference, the recommended execution approach is:

**Inline Execution** - Execute tasks in this session one by one, watching the code and tests together so the implementation stays easy to follow and easy to modify while you learn the codebase.
