"""Load and validate EvalCase YAML files and Fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from evals.models import EvalCase, EvalCaseAdapter, EvalStep, EvalStepAdapter, FixtureAdapter


class LoadError(Exception):
    """A case or fixture failed to load or validate."""


def _resolve_fixture_path(fixture_name: str, fixtures_dir: Path) -> Path:
    candidate = fixtures_dir / f"{fixture_name}.yaml"
    if not candidate.is_file():
        raise LoadError(
            f"Fixture '{fixture_name}' not found at {candidate}. "
            f"Looked in {fixtures_dir}"
        )
    return candidate


def load_fixture(fixture_name: str, fixtures_dir: Path) -> Fixture:
    """Load and validate a single fixture YAML file."""
    path = _resolve_fixture_path(fixture_name, fixtures_dir)
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise LoadError(f"Fixture '{fixture_name}' must be a YAML mapping, got {type(raw)}")
    try:
        return FixtureAdapter.validate_python(raw)
    except Exception as exc:
        raise LoadError(f"Fixture '{fixture_name}' validation failed: {exc}") from exc


def _apply_fixture_overrides(fixture: Fixture, overrides: dict[str, Any]) -> Fixture:
    """Apply per-case fixture overrides with strict key checking.

    Unknown top-level keys are rejected to avoid silent typos.
    """
    if not overrides:
        return fixture
    fixture_dict = fixture.model_dump()
    for key in overrides:
        if key not in fixture_dict:
            raise LoadError(
                f"Unknown fixture override key '{key}'. "
                f"Valid keys: {sorted(fixture_dict.keys())}"
            )
    fixture_dict.update(overrides)
    return FixtureAdapter.validate_python(fixture_dict)


def load_case(path: Path, fixtures_dir: Path) -> EvalCase:
    """Load and validate one YAML case file, resolving its fixture."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise LoadError(f"Case file {path} must be a YAML mapping, got {type(raw)}")

    # Validate the case first (including its steps list).
    try:
        case = EvalCaseAdapter.validate_python(raw)
    except Exception as exc:
        raise LoadError(
            f"Case {raw.get('id', path.stem)} validation failed: {exc}"
        ) from exc

    # Re-validate steps individually for better error messages on discriminated union.
    validated_steps: list[EvalStep] = []
    for i, step_raw in enumerate(case.steps):
        try:
            validated_steps.append(EvalStepAdapter.validate_python(step_raw))
        except Exception as exc:
            raise LoadError(
                f"Case '{case.id}' step {i} (kind={getattr(step_raw, 'kind', '?')!r}): {exc}"
            ) from exc

    case.steps = validated_steps

    # Apply fixture and its overrides.
    fixture = load_fixture(case.fixture, fixtures_dir)
    fixture = _apply_fixture_overrides(fixture, case.fixture_overrides)

    # Attach the resolved fixture to the case object as a private attribute.
    object.__setattr__(case, "_fixture", fixture)
    return case


def load_suite(suite_name: str, cases_dir: Path, fixtures_dir: Path) -> list[EvalCase]:
    """Load all YAML cases for a suite, sorted by filename.

    Case IDs must be unique within the suite.
    """
    suite_dir = cases_dir / suite_name
    if not suite_dir.is_dir():
        raise LoadError(f"Suite directory not found: {suite_dir}")

    paths = sorted(suite_dir.glob("*.yaml"))
    if not paths:
        raise LoadError(f"No YAML case files found in {suite_dir}")

    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    for path in paths:
        case = load_case(path, fixtures_dir)
        if case.id in seen_ids:
            raise LoadError(
                f"Duplicate case id '{case.id}' in suite '{suite_name}'. "
                f"File: {path.name}"
            )
        seen_ids.add(case.id)
        cases.append(case)
    return cases


def get_fixture(case: EvalCase) -> Fixture:
    """Retrieve the resolved fixture attached to a loaded case."""
    fixture = getattr(case, "_fixture", None)
    if fixture is None:
        raise LoadError(
            f"Case '{case.id}' has no resolved fixture — "
            f"was it loaded via load_case() or load_suite()?"
        )
    return fixture
