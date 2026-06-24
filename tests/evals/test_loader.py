"""Test case and fixture loading."""

from pathlib import Path

import pytest
import yaml

from evals.loader import (
    LoadError,
    _apply_fixture_overrides,
    load_case,
    load_fixture,
    load_suite,
    get_fixture,
)
from evals.models import EvalCase, EvalCaseAdapter, Fixture, FixtureAdapter


# ── Helpers ────────────────────────────────────────────────────────────

def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


def _make_case_file(cases_dir: Path, filename: str, data: dict) -> Path:
    path = cases_dir / filename
    _write_yaml(path, data)
    return path


# ── Fixture loading ────────────────────────────────────────────────────

class TestLoadFixture:
    def test_load_valid_fixture(self, tmp_path: Path):
        fixtures_dir = tmp_path / "fixtures"
        _write_yaml(fixtures_dir / "base-world.yaml", {"name": "base-world"})
        fixture = load_fixture("base-world", fixtures_dir)
        assert isinstance(fixture, Fixture)
        assert fixture.name == "base-world"

    def test_missing_fixture(self, tmp_path: Path):
        fixtures_dir = tmp_path / "fixtures"
        with pytest.raises(LoadError, match="not found"):
            load_fixture("nonexistent", fixtures_dir)

    def test_fixture_not_a_mapping(self, tmp_path: Path):
        fixtures_dir = tmp_path / "fixtures"
        fixtures_dir.mkdir(parents=True)
        (fixtures_dir / "bad.yaml").write_text("- list\n- not\n- mapping\n")
        with pytest.raises(LoadError, match="must be a YAML mapping"):
            load_fixture("bad", fixtures_dir)

    def test_fixture_validation_error(self, tmp_path: Path):
        fixtures_dir = tmp_path / "fixtures"
        _write_yaml(fixtures_dir / "bad.yaml", {
            "name": "bad",
            "download_submit": {"torrent_id": "x", "outcome": "INVALID"},
        })
        with pytest.raises(LoadError, match="validation failed"):
            load_fixture("bad", fixtures_dir)


# ── Fixture overrides ──────────────────────────────────────────────────

class TestFixtureOverrides:
    def test_empty_overrides(self):
        fixture = FixtureAdapter.validate_python({"name": "test"})
        result = _apply_fixture_overrides(fixture, {})
        assert result.name == "test"

    def test_valid_override(self):
        fixture = FixtureAdapter.validate_python({"name": "test"})
        result = _apply_fixture_overrides(fixture, {"name": "overridden"})
        assert result.name == "overridden"

    def test_unknown_key_rejected(self):
        fixture = FixtureAdapter.validate_python({"name": "test"})
        with pytest.raises(LoadError, match="Unknown fixture override key"):
            _apply_fixture_overrides(fixture, {"typo_key": "value"})


# ── Case loading ───────────────────────────────────────────────────────

class TestLoadCase:
    def test_load_valid_case(self, tmp_path: Path):
        cases_dir = tmp_path / "cases" / "test-suite"
        fixtures_dir = tmp_path / "fixtures"
        _write_yaml(fixtures_dir / "base-world.yaml", {"name": "base-world"})
        _make_case_file(cases_dir, "01-test.yaml", {
            "id": "test-case",
            "title": "测试",
            "category": "read_only",
            "steps": [{"kind": "user", "text": "搜索 Dune"}],
        })

        case = load_case(cases_dir / "01-test.yaml", fixtures_dir)
        assert isinstance(case, EvalCase)
        assert case.id == "test-case"
        fixture = get_fixture(case)
        assert fixture.name == "base-world"

    def test_case_missing_steps(self, tmp_path: Path):
        cases_dir = tmp_path / "cases" / "test-suite"
        fixtures_dir = tmp_path / "fixtures"
        _write_yaml(fixtures_dir / "base-world.yaml", {"name": "base-world"})
        _make_case_file(cases_dir, "01-bad.yaml", {
            "id": "bad",
            "title": "Bad",
            "category": "read_only",
        })

        with pytest.raises(LoadError, match="steps"):
            load_case(cases_dir / "01-bad.yaml", fixtures_dir)

    def test_case_invalid_step_kind(self, tmp_path: Path):
        cases_dir = tmp_path / "cases" / "test-suite"
        fixtures_dir = tmp_path / "fixtures"
        _write_yaml(fixtures_dir / "base-world.yaml", {"name": "base-world"})
        _make_case_file(cases_dir, "01-bad.yaml", {
            "id": "bad-step",
            "title": "Bad Step",
            "category": "read_only",
            "steps": [
                {"kind": "user", "text": "搜索"},
                {"kind": "nonexistent"},
            ],
        })

        with pytest.raises(LoadError, match="nonexistent"):
            load_case(cases_dir / "01-bad.yaml", fixtures_dir)

    def test_case_with_fixture_overrides(self, tmp_path: Path):
        cases_dir = tmp_path / "cases" / "test-suite"
        fixtures_dir = tmp_path / "fixtures"
        _write_yaml(fixtures_dir / "base-world.yaml", {"name": "base-world"})
        _make_case_file(cases_dir, "01-test.yaml", {
            "id": "with-override",
            "title": "覆盖测试",
            "category": "download_intent",
            "fixture_overrides": {"name": "custom-world"},
            "steps": [{"kind": "user", "text": "下载"}],
        })

        case = load_case(cases_dir / "01-test.yaml", fixtures_dir)
        assert case.fixture_overrides == {"name": "custom-world"}
        fixture = get_fixture(case)
        assert fixture.name == "custom-world"

    def test_case_override_unknown_key(self, tmp_path: Path):
        cases_dir = tmp_path / "cases" / "test-suite"
        fixtures_dir = tmp_path / "fixtures"
        _write_yaml(fixtures_dir / "base-world.yaml", {"name": "base-world"})
        _make_case_file(cases_dir, "01-bad.yaml", {
            "id": "bad-override",
            "title": "Bad Override",
            "category": "read_only",
            "fixture_overrides": {"invalid_key": "value"},
            "steps": [{"kind": "user", "text": "test"}],
        })

        with pytest.raises(LoadError, match="Unknown fixture override key"):
            load_case(cases_dir / "01-bad.yaml", fixtures_dir)


# ── Suite loading ──────────────────────────────────────────────────────

class TestLoadSuite:
    def test_load_suite(self, tmp_path: Path):
        cases_dir = tmp_path / "cases"
        fixtures_dir = tmp_path / "fixtures"
        _write_yaml(fixtures_dir / "base-world.yaml", {"name": "base-world"})
        _make_case_file(cases_dir / "test-suite", "01-a.yaml", {
            "id": "case-a",
            "title": "A",
            "category": "read_only",
            "steps": [{"kind": "user", "text": "test"}],
        })
        _make_case_file(cases_dir / "test-suite", "02-b.yaml", {
            "id": "case-b",
            "title": "B",
            "category": "safety",
            "steps": [{"kind": "user", "text": "test"}],
        })

        cases = load_suite("test-suite", cases_dir, fixtures_dir)
        assert len(cases) == 2
        assert cases[0].id == "case-a"
        assert cases[1].id == "case-b"

    def test_duplicate_ids_rejected(self, tmp_path: Path):
        cases_dir = tmp_path / "cases"
        fixtures_dir = tmp_path / "fixtures"
        _write_yaml(fixtures_dir / "base-world.yaml", {"name": "base-world"})
        _make_case_file(cases_dir / "test-suite", "01-a.yaml", {
            "id": "dup",
            "title": "A",
            "category": "read_only",
            "steps": [{"kind": "user", "text": "test"}],
        })
        _make_case_file(cases_dir / "test-suite", "02-b.yaml", {
            "id": "dup",
            "title": "B",
            "category": "safety",
            "steps": [{"kind": "user", "text": "test"}],
        })

        with pytest.raises(LoadError, match="Duplicate case id"):
            load_suite("test-suite", cases_dir, fixtures_dir)

    def test_missing_suite_directory(self, tmp_path: Path):
        cases_dir = tmp_path / "cases"
        fixtures_dir = tmp_path / "fixtures"
        with pytest.raises(LoadError, match="not found"):
            load_suite("nonexistent", cases_dir, fixtures_dir)

    def test_empty_suite_directory(self, tmp_path: Path):
        cases_dir = tmp_path / "cases"
        fixtures_dir = tmp_path / "fixtures"
        (cases_dir / "empty-suite").mkdir(parents=True)
        with pytest.raises(LoadError, match="No YAML case files"):
            load_suite("empty-suite", cases_dir, fixtures_dir)

    def test_get_fixture_unloaded_case(self):
        case = EvalCaseAdapter.validate_python({
            "id": "no-fixture",
            "title": "No Fixture",
            "category": "read_only",
            "steps": [{"kind": "user", "text": "test"}],
        })
        with pytest.raises(LoadError, match="no resolved fixture"):
            get_fixture(case)
