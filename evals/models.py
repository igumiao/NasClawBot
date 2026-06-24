"""Pydantic models for the Agent Behavioral Evaluation system.

Schema ownership:
  YAML  -> describes scenario, steps, and expectations
  Pydantic -> validates before any LLM call
  Python -> executes complex scoring and metric aggregation
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator


# ── Step models (discriminated union via `kind`) ──────────────────────

class UserStep(BaseModel):
    """A user message that enters the conversation history and calls runner.run()."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["user"] = "user"
    text: str = Field(..., description="User message text (Chinese).")


class ApproveStep(BaseModel):
    """Harness deterministically approves the current pending approval."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["approve"] = "approve"
    target: Literal["pending"] = "pending"
    decision: Literal["approve_once", "approve_and_grant_session"] = "approve_once"


class DenyStep(BaseModel):
    """Harness deterministically denies the current pending approval."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["deny"] = "deny"
    target: Literal["pending"] = "pending"


class AdvanceTimeStep(BaseModel):
    """Advance the logical clock (reserved for approval-expiry / future Contract cases).

    Must NOT be implemented via real sleep.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["advance_time"] = "advance_time"
    hours: float = Field(..., gt=0, description="Hours to advance the logical clock.")


class RequiredCall(BaseModel):
    """A tool call that MUST appear in the trial."""

    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, Any] | None = Field(
        default=None,
        description="Subset of arguments that must match. Omit to only require presence.",
    )


class OrderingConstraint(BaseModel):
    """Ordering constraint between two tool calls."""

    model_config = ConfigDict(extra="forbid")

    before: str
    after: str


class AssertStep(BaseModel):
    """Deterministic assertions consumed by the harness (never enter model context)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["assert"] = "assert"
    status: str | None = Field(
        default=None,
        description="Expected runner status, e.g. 'awaiting_approval' or 'success'.",
    )
    required_calls: list[RequiredCall] = Field(default_factory=list)
    exact_call_count: dict[str, int] = Field(
        default_factory=dict,
        description="Exact count of each tool name required.",
    )
    forbidden_calls: list[str] = Field(
        default_factory=list,
        description="Tool names that must NOT appear.",
    )
    ordering: list[OrderingConstraint] = Field(default_factory=list)
    recorded_effects: int | None = Field(
        default=None,
        description="Expected number of entries in the CallJournal (0 before approval, "
        "≥1 after).",
    )
    final_facts: list[str] = Field(
        default_factory=list,
        description="Semantic fact names that must be true, e.g. 'submitted_paused', "
        "'operation_failed', 'not_executed'.",
    )

    @field_validator("final_facts")
    @classmethod
    def _check_known_facts(cls, v: list[str]) -> list[str]:
        known = {
            "awaiting_approval",
            "submitted_paused",
            "operation_failed",
            "not_executed",
            "batch_partial_success",
            "organization_scheduled",
            "monitor_created",
        }
        for fact in v:
            if fact not in known:
                raise ValueError(
                    f"Unknown final_fact '{fact}'. Known facts: {sorted(known)}"
                )
        return v


EvalStep = Annotated[
    UserStep | ApproveStep | DenyStep | AdvanceTimeStep | AssertStep,
    Field(discriminator="kind"),
]


# ── Case model ────────────────────────────────────────────────────────

class EvalCase(BaseModel):
    """One behavioral evaluation scenario."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ...,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
        description="Stable slug, unique within a suite.",
    )
    title: str = Field(..., description="Short Chinese title for reports.")
    category: str = Field(
        ...,
        description="Grouping: read_only, download_intent, multiturn, safety, ambiguity.",
    )
    fixture: str = Field(
        default="base-world",
        description="Fixture file name (without .yaml) under fixtures/.",
    )
    fixture_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-case fixture overrides. Unknown keys are rejected at load time.",
    )
    tags: list[str] = Field(default_factory=list)
    steps: list[EvalStep] = Field(..., min_length=1)

    @field_validator("steps")
    @classmethod
    def _first_step_must_be_user(cls, v: list[EvalStep]) -> list[EvalStep]:
        if v and v[0].kind != "user":
            raise ValueError("First step must be a 'user' step.")
        return v


# ── Fixture models ────────────────────────────────────────────────────

class FixtureResource(BaseModel):
    """A synthetic M-Team search result."""

    model_config = ConfigDict(extra="forbid")

    torrent_id: str
    title: str
    size: str
    size_bytes: int
    seeders: int
    leechers: int = 0
    discount: str = "NORMAL"
    resolution: str | None = None
    has_chinese_subtitle: bool = False
    labels_new: list[str] = Field(default_factory=list)


class FixtureQbTask(BaseModel):
    """A synthetic qBittorrent download task."""

    model_config = ConfigDict(extra="forbid")

    hash: str
    name: str
    size_bytes: int
    progress: float = 0.0
    state: str = "pausedUP"
    category: str = ""
    tags: list[str] = Field(default_factory=list)


class FixtureBackgroundTask(BaseModel):
    """A synthetic background runtime task."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    kind: str
    status: str
    title: str


class DownloadSubmitResult(BaseModel):
    """A synthetic download submission result."""

    model_config = ConfigDict(extra="forbid")

    torrent_id: str
    outcome: Literal["success", "error", "timeout"] = "success"
    code: str | None = None
    status: str = "submitted_paused"


class Fixture(BaseModel):
    """A self-contained, anonymous test world for evaluation."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    resources: list[FixtureResource] = Field(default_factory=list)
    qb_tasks: list[FixtureQbTask] = Field(default_factory=list)
    background_tasks: list[FixtureBackgroundTask] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)
    out_of_bounds_paths: list[str] = Field(default_factory=list)
    download_submit: DownloadSubmitResult | None = None
    download_submit_error: DownloadSubmitResult | None = None
    tmdb_search_results: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    tmdb_details: dict[str, dict[str, Any]] = Field(default_factory=dict)


# ── Call Journal ──────────────────────────────────────────────────────

class CallJournalEntry(BaseModel):
    """One recorded dependency call during a trial."""

    sequence: int
    kind: Literal["read", "effect"] = Field(
        default="read",
        description="'read' for queries, 'effect' for state-changing mutations.",
    )
    dependency: str = Field(..., description="e.g. 'mteam', 'qb', 'tmdb', 'tavily'.")
    operation: str = Field(..., description="e.g. 'search_torrents', 'add_torrent_url'.")
    arguments: dict[str, Any] = Field(default_factory=dict)
    outcome: str = Field(..., description="'success', 'error', or 'timeout'.")
    started_at: str = ""
    duration_ms: float = 0.0


# ── Trial result ──────────────────────────────────────────────────────

class TrialStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INVALID = "INVALID"


class FailureCategory(str, Enum):
    TOOL_SELECTION = "tool_selection"
    ARGUMENTS = "arguments"
    APPROVAL_BEHAVIOR = "approval_behavior"
    CONVERSATION_CONTEXT = "conversation_context"
    FACTUAL_CONSISTENCY = "factual_consistency"
    MAX_STEPS = "max_steps"
    INFRASTRUCTURE = "infrastructure"


class FailedAssertion(BaseModel):
    category: FailureCategory
    detail: str
    expected: Any | None = None
    actual: Any | None = None


class TrialResult(BaseModel):
    """Result of one case × one repetition."""

    run_id: str
    suite: str
    case_id: str
    repetition: int
    label: str
    status: TrialStatus
    primary_failure: FailureCategory | None = None
    failed_assertions: list[FailedAssertion] = Field(default_factory=list)
    session_id: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    call_journal: list[CallJournalEntry] = Field(default_factory=list)
    final_answer: str = ""
    token_usage: dict[str, int] = Field(default_factory=dict)
    model_calls: int = 0
    tool_call_count: int = 0
    redundant_tool_calls: int = 0
    latency_ms: float = 0.0
    llm_request_latency_ms: float = 0.0
    tool_exec_latency_ms: float = 0.0
    approval_latency_ms: float = 0.0
    error: str | None = None
    attempt: int = 1
    started_at: str = ""
    finished_at: str = ""


# ── Suite report ──────────────────────────────────────────────────────

class SuiteReport(BaseModel):
    """Aggregated report for one full suite run."""

    run_id: str
    suite: str
    suite_version: str = "1.0"
    label: str
    git_branch: str = ""
    git_commit: str = ""
    worktree_dirty: bool = False
    model: str = ""
    temperature: float = 0.2
    max_steps: int = 30
    repetitions: int = 3
    started_at: str = ""
    finished_at: str = ""
    trials: list[TrialResult] = Field(default_factory=list)

    # Hashes for reproducibility
    suite_hash: str = ""
    fixture_hash: str = ""
    prompt_template_hash: str = ""
    rendered_prompt_hash: str = ""
    tool_schema_hash: str = ""
    fixed_date: str = ""
    fixed_timezone: str = ""
    fixed_download_path: str = ""
    profile_fixture: str = ""

    # Aggregate metrics
    total: int = 0
    passed: int = 0
    failed: int = 0
    invalid: int = 0
    success_rate: float | None = None
    case_consistency: float | None = None
    safety_violations: int = 0
    failure_by_category: dict[str, int] = Field(default_factory=dict)
    case_results: dict[str, list[str]] = Field(
        default_factory=dict,
        description="case_id -> [PASS/FAIL/INVALID per repetition]",
    )
    tokens_per_success: float | None = None
    total_tokens: int = 0
    total_model_calls: int = 0
    total_tool_calls: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    latency_n: int = 0


# ── Type adapters for standalone validation ────────────────────────────
# These must come after all class definitions so the forward references
# (e.g. in discriminated unions) are resolvable.

EvalStepAdapter = TypeAdapter(EvalStep)
EvalCaseAdapter = TypeAdapter(EvalCase)
FixtureAdapter = TypeAdapter(Fixture)
