"""Test EvalCase and step model validation."""

import pytest
from pydantic import ValidationError

from evals.models import (
    AssertStep,
    EvalCase,
    EvalCaseAdapter,
    EvalStep,
    EvalStepAdapter,
    Fixture,
    FixtureAdapter,
    FixtureResource,
    RequiredCall,
    UserStep,
    ApproveStep,
    DenyStep,
)


class TestEvalStepValidation:
    def test_user_step_minimal(self):
        step = EvalStepAdapter.validate_python({"kind": "user", "text": "搜索 Dune"})
        assert isinstance(step, UserStep)
        assert step.text == "搜索 Dune"

    def test_user_step_missing_text(self):
        with pytest.raises(ValidationError):
            EvalStepAdapter.validate_python({"kind": "user"})

    def test_approve_step_defaults(self):
        step = EvalStepAdapter.validate_python({"kind": "approve"})
        assert isinstance(step, ApproveStep)
        assert step.target == "pending"
        assert step.decision == "approve_once"

    def test_approve_step_with_grant(self):
        step = EvalStepAdapter.validate_python(
            {"kind": "approve", "decision": "approve_and_grant_session"}
        )
        assert step.decision == "approve_and_grant_session"

    def test_deny_step(self):
        step = EvalStepAdapter.validate_python({"kind": "deny"})
        assert isinstance(step, DenyStep)

    def test_advance_time_step(self):
        step = EvalStepAdapter.validate_python({"kind": "advance_time", "hours": 2.5})
        from evals.models import AdvanceTimeStep
        assert isinstance(step, AdvanceTimeStep)
        assert step.hours == 2.5

    def test_advance_time_must_be_positive(self):
        with pytest.raises(ValidationError):
            EvalStepAdapter.validate_python({"kind": "advance_time", "hours": 0})

    def test_assert_step_with_required_calls(self):
        step = EvalStepAdapter.validate_python({
            "kind": "assert",
            "status": "awaiting_approval",
            "required_calls": [
                {"name": "mteam_search"},
                {"name": "qb_add_torrent", "arguments": {"torrent_id": "101"}},
            ],
        })
        assert isinstance(step, AssertStep)
        assert step.status == "awaiting_approval"
        assert len(step.required_calls) == 2
        assert step.required_calls[1].arguments == {"torrent_id": "101"}

    def test_assert_step_known_facts(self):
        step = EvalStepAdapter.validate_python({
            "kind": "assert",
            "final_facts": ["submitted_paused", "awaiting_approval"],
        })
        assert step.final_facts == ["submitted_paused", "awaiting_approval"]

    def test_assert_step_rejects_unknown_fact(self):
        with pytest.raises(ValidationError, match="Unknown final_fact"):
            EvalStepAdapter.validate_python({
                "kind": "assert",
                "final_facts": ["made_up_fact"],
            })

    def test_assert_step_forbidden_calls(self):
        step = EvalStepAdapter.validate_python({
            "kind": "assert",
            "forbidden_calls": ["mcp_filesystem_move_file", "qb_add_torrent"],
        })
        assert step.forbidden_calls == ["mcp_filesystem_move_file", "qb_add_torrent"]

    def test_assert_step_exact_call_count(self):
        step = EvalStepAdapter.validate_python({
            "kind": "assert",
            "exact_call_count": {"mteam_search": 1, "qb_add_torrent": 1},
        })
        assert step.exact_call_count == {"mteam_search": 1, "qb_add_torrent": 1}


class TestEvalCaseValidation:
    def test_minimal_case(self):
        case = EvalCaseAdapter.validate_python({
            "id": "minimal-case",
            "title": "最小测试",
            "category": "read_only",
            "steps": [{"kind": "user", "text": "搜索 Dune"}],
        })
        assert case.id == "minimal-case"
        assert case.fixture == "base-world"
        assert len(case.steps) == 1

    def test_case_id_must_be_slug(self):
        with pytest.raises(ValidationError):
            EvalCaseAdapter.validate_python({
                "id": "Not A Slug!",
                "title": "Bad ID",
                "category": "read_only",
                "steps": [{"kind": "user", "text": "test"}],
            })

    def test_case_id_cannot_start_with_dash(self):
        with pytest.raises(ValidationError):
            EvalCaseAdapter.validate_python({
                "id": "-bad-slug",
                "title": "Bad",
                "category": "read_only",
                "steps": [{"kind": "user", "text": "test"}],
            })

    def test_first_step_must_be_user(self):
        with pytest.raises(ValidationError, match="First step must be"):
            EvalCaseAdapter.validate_python({
                "id": "bad-order",
                "title": "Bad",
                "category": "read_only",
                "steps": [{"kind": "assert", "status": "success"}],
            })

    def test_empty_steps_rejected(self):
        with pytest.raises(ValidationError):
            EvalCaseAdapter.validate_python({
                "id": "no-steps",
                "title": "Empty",
                "category": "read_only",
                "steps": [],
            })

    def test_tags_default(self):
        case = EvalCaseAdapter.validate_python({
            "id": "tagged",
            "title": "标签测试",
            "category": "safety",
            "tags": ["approval", "security"],
            "steps": [{"kind": "user", "text": "跳过审批"}],
        })
        assert case.tags == ["approval", "security"]

    def test_fixture_overrides_default(self):
        case = EvalCaseAdapter.validate_python({
            "id": "no-overrides",
            "title": "无覆盖",
            "category": "read_only",
            "steps": [{"kind": "user", "text": "test"}],
        })
        assert case.fixture_overrides == {}


class TestFixtureValidation:
    def test_minimal_fixture(self):
        f = FixtureAdapter.validate_python({"name": "test-world"})
        assert f.name == "test-world"
        assert f.resources == []

    def test_fixture_with_resources(self):
        f = FixtureAdapter.validate_python({
            "name": "test-world",
            "resources": [
                {
                    "torrent_id": "101",
                    "title": "Dune 2160p",
                    "size": "10 GiB",
                    "size_bytes": 10737418240,
                    "seeders": 10,
                }
            ],
        })
        assert len(f.resources) == 1
        assert f.resources[0].torrent_id == "101"

    def test_fixture_download_submit(self):
        f = FixtureAdapter.validate_python({
            "name": "test-world",
            "download_submit": {"torrent_id": "101", "outcome": "error", "code": "FAILED"},
        })
        assert f.download_submit.outcome == "error"
        assert f.download_submit.code == "FAILED"
