"""Tests for the organization automation policy domain model and JSON store.

Verifies default values, persistence round-trips, field normalization,
safety invariants (allow_delete/allow_overwrite forced to False), and
GET/PUT route behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.task_routes import build_task_router
from app.domain.organization import (
    OrganizationAutomationPolicy,
    default_organization_automation_policy,
)
from app.services.organization_policy_store import (
    OrganizationAutomationPolicyStore,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings_dir(tmp_path: Path) -> Path:
    """Scratch directory for the JSON store (no real memory/settings touched)."""
    return tmp_path / "memory" / "settings"


@pytest.fixture
def store(settings_dir: Path) -> OrganizationAutomationPolicyStore:
    return OrganizationAutomationPolicyStore(settings_dir)


# ---------------------------------------------------------------------------
# Default policy values
# ---------------------------------------------------------------------------


class TestDefaultPolicy:
    """default_organization_automation_policy returns sensible defaults."""

    def test_default_values(self) -> None:
        policy = default_organization_automation_policy()
        assert policy.enabled is False
        assert policy.default_after_download == "notify_only"
        assert policy.allowed_source_path_prefixes == []
        assert policy.destination_root == ""
        assert policy.allow_delete is False
        assert policy.allow_overwrite is False

    def test_factory_is_destructurable(self) -> None:
        """Calling the factory multiple times produces independent instances."""
        a = default_organization_automation_policy()
        b = default_organization_automation_policy()
        assert a is not b
        assert a.model_dump() == b.model_dump()

    def test_allow_delete_is_frozen(self) -> None:
        policy = OrganizationAutomationPolicy()
        assert policy.allow_delete is False
        with pytest.raises(ValueError):
            policy.allow_delete = True

    def test_allow_overwrite_is_frozen(self) -> None:
        policy = OrganizationAutomationPolicy()
        assert policy.allow_overwrite is False
        with pytest.raises(ValueError):
            policy.allow_overwrite = True


# ---------------------------------------------------------------------------
# Normalisation: empty strings and duplicates in allowed_source_path_prefixes
# ---------------------------------------------------------------------------


class TestNormalization:
    """allowed_source_path_prefixes strips empty entries and deduplicates."""

    def test_empty_strings_removed(self) -> None:
        policy = OrganizationAutomationPolicy(
            allowed_source_path_prefixes=["/volume1/影视", "", "/volume2/资源", " "]
        )
        assert policy.allowed_source_path_prefixes == [
            "/volume1/影视",
            "/volume2/资源",
        ]

    def test_duplicates_removed(self) -> None:
        policy = OrganizationAutomationPolicy(
            allowed_source_path_prefixes=[
                "/volume1/影视",
                "/volume1/影视",
                "/volume2/资源",
                "/volume1/影视",
            ]
        )
        assert policy.allowed_source_path_prefixes == [
            "/volume1/影视",
            "/volume2/资源",
        ]

    def test_whitespace_only_stripped_and_removed(self) -> None:
        policy = OrganizationAutomationPolicy(
            allowed_source_path_prefixes=["/data", "  ", "\t", "\n"]
        )
        assert policy.allowed_source_path_prefixes == ["/data"]

    def test_none_becomes_empty(self) -> None:
        policy = OrganizationAutomationPolicy(allowed_source_path_prefixes=None)
        assert policy.allowed_source_path_prefixes == []

    def test_non_list_becomes_empty(self) -> None:
        policy = OrganizationAutomationPolicy(allowed_source_path_prefixes=42)
        assert policy.allowed_source_path_prefixes == []

    def test_string_newlines_split_into_lines(self) -> None:
        policy = OrganizationAutomationPolicy(
            allowed_source_path_prefixes="/volume1/影视\n/volume2/资源\n"
        )
        assert policy.allowed_source_path_prefixes == [
            "/volume1/影视",
            "/volume2/资源",
        ]


# ---------------------------------------------------------------------------
# allow_delete / allow_overwrite forced to False
# ---------------------------------------------------------------------------


class TestForcedSafetyFields:
    """allow_delete and allow_overwrite are always False regardless of input."""

    def test_allow_delete_forced_false_on_construction(self) -> None:
        policy = OrganizationAutomationPolicy(
            enabled=True,
            allow_delete=True,  # type: ignore[arg-type]
        )
        assert policy.allow_delete is False

    def test_allow_overwrite_forced_false_on_construction(self) -> None:
        policy = OrganizationAutomationPolicy(
            enabled=True,
            allow_overwrite=True,  # type: ignore[arg-type]
        )
        assert policy.allow_overwrite is False

    def test_both_forced_false_when_submitted_via_model_validate(self) -> None:
        raw = {
            "enabled": True,
            "default_after_download": "auto_organize",
            "allowed_source_path_prefixes": ["/media"],
            "destination_root": "/media/organized",
            "allow_delete": True,
            "allow_overwrite": True,
        }
        policy = OrganizationAutomationPolicy.model_validate(raw)
        assert policy.allow_delete is False
        assert policy.allow_overwrite is False

    def test_model_dump_overwrites_as_false(self) -> None:
        raw = {
            "enabled": True,
            "allow_delete": True,
            "allow_overwrite": True,
        }
        policy = OrganizationAutomationPolicy.model_validate(raw)
        dumped = policy.model_dump()
        assert dumped["allow_delete"] is False
        assert dumped["allow_overwrite"] is False


# ---------------------------------------------------------------------------
# JSON store: load default (no file), save/load round-trip
# ---------------------------------------------------------------------------


class TestStoreDefaults:
    """Store.load() returns defaults when no file exists."""

    def test_load_returns_defaults_when_no_file(
        self, store: OrganizationAutomationPolicyStore
    ) -> None:
        policy = store.load()
        assert policy.enabled is False
        assert policy.default_after_download == "notify_only"

    def test_load_returns_defaults_when_file_has_garbage(
        self, store: OrganizationAutomationPolicyStore
    ) -> None:
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text("{invalid json", encoding="utf-8")
        policy = store.load()
        assert policy.enabled is False

    def test_load_returns_defaults_when_file_is_not_a_dict(
        self, store: OrganizationAutomationPolicyStore
    ) -> None:
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text('"just a string"', encoding="utf-8")
        policy = store.load()
        assert policy.enabled is False

    def test_load_returns_defaults_when_file_has_invalid_schema(
        self, store: OrganizationAutomationPolicyStore
    ) -> None:
        """default_after_download must be a valid literal."""
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text(
            json.dumps({"default_after_download": "bogus_value"}),
            encoding="utf-8",
        )
        policy = store.load()
        assert policy.default_after_download == "notify_only"


class TestStoreRoundTrip:
    """save() then load() returns identical policy."""

    def test_save_then_load_round_trips_all_fields(
        self, store: OrganizationAutomationPolicyStore
    ) -> None:
        original = OrganizationAutomationPolicy(
            enabled=True,
            default_after_download="auto_organize",
            allowed_source_path_prefixes=[
                "/volume1/影视/电影",
                "/volume1/影视/电视剧",
            ],
            destination_root="/volume1/organized",
        )
        store.save(original)
        restored = store.load()
        assert restored.enabled is True
        assert restored.default_after_download == "auto_organize"
        assert restored.allowed_source_path_prefixes == [
            "/volume1/影视/电影",
            "/volume1/影视/电视剧",
        ]
        assert restored.destination_root == "/volume1/organized"
        assert restored.allow_delete is False
        assert restored.allow_overwrite is False

    def test_save_persists_only_valid_fields(
        self, store: OrganizationAutomationPolicyStore
    ) -> None:
        """allow_delete and allow_overwrite are written as False even if submitted."""
        policy = OrganizationAutomationPolicy(
            enabled=True,
            allow_delete=True,  # type: ignore[arg-type]
            allow_overwrite=True,  # type: ignore[arg-type]
        )
        store.save(policy)
        raw = json.loads(store.path.read_text(encoding="utf-8"))
        assert raw["allow_delete"] is False
        assert raw["allow_overwrite"] is False

    def test_destination_root_empty_round_trips(
        self, store: OrganizationAutomationPolicyStore
    ) -> None:
        policy = OrganizationAutomationPolicy(enabled=True, destination_root="")
        store.save(policy)
        restored = store.load()
        assert restored.destination_root == ""

    def test_file_is_valid_json(
        self, store: OrganizationAutomationPolicyStore
    ) -> None:
        policy = OrganizationAutomationPolicy(
            enabled=True,
            allowed_source_path_prefixes=["/media"],
        )
        store.save(policy)
        data = json.loads(store.path.read_text(encoding="utf-8"))
        assert data["enabled"] is True
        assert "/media" in data["allowed_source_path_prefixes"]

    def test_save_returns_the_policy(
        self, store: OrganizationAutomationPolicyStore
    ) -> None:
        policy = OrganizationAutomationPolicy(enabled=True)
        result = store.save(policy)
        assert result is policy


# ---------------------------------------------------------------------------
# GET / PUT route behaviour via TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
def client(settings_dir: Path) -> TestClient:
    """TestClient with a router that uses the scratch settings_dir."""
    from fastapi import FastAPI

    app = FastAPI()
    # Monkey-patch the store factory inside task_routes so it uses our tmp_path.
    import app.api.task_routes as tr

    original_factory = tr._organization_policy_store

    def _test_store() -> OrganizationAutomationPolicyStore:
        return OrganizationAutomationPolicyStore(settings_dir)

    tr._organization_policy_store = _test_store  # type: ignore[assignment]
    app.include_router(build_task_router())
    yield TestClient(app)
    tr._organization_policy_store = original_factory


class TestGetRoute:
    """GET /settings/organization-automation returns the policy."""

    def test_get_returns_defaults_when_no_file(
        self, client: TestClient
    ) -> None:
        resp = client.get("/settings/organization-automation")
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is False
        assert body["default_after_download"] == "notify_only"
        assert body["allowed_source_path_prefixes"] == []
        assert body["destination_root"] == ""
        assert body["allow_delete"] is False
        assert body["allow_overwrite"] is False

    def test_get_returns_what_was_put(
        self, client: TestClient
    ) -> None:
        payload = {
            "enabled": True,
            "default_after_download": "auto_organize",
            "allowed_source_path_prefixes": ["/volume1/影视"],
            "destination_root": "/volume1/organized",
        }
        put_resp = client.put(
            "/settings/organization-automation",
            json=payload,
        )
        assert put_resp.status_code == 200
        get_resp = client.get("/settings/organization-automation")
        assert get_resp.status_code == 200
        assert get_resp.json() == put_resp.json()

    def test_get_returns_safety_fields_as_false(
        self, client: TestClient
    ) -> None:
        body = client.get("/settings/organization-automation").json()
        assert body["allow_delete"] is False
        assert body["allow_overwrite"] is False


class TestPutRoute:
    """PUT /settings/organization-automation persists and returns the policy."""

    def test_put_accepts_minimal_body(self, client: TestClient) -> None:
        resp = client.put(
            "/settings/organization-automation",
            json={"enabled": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is True
        assert body["allow_delete"] is False

    def test_put_forces_allow_delete_and_allow_overwrite(
        self, client: TestClient
    ) -> None:
        resp = client.put(
            "/settings/organization-automation",
            json={
                "enabled": True,
                "allow_delete": True,
                "allow_overwrite": True,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["allow_delete"] is False
        assert body["allow_overwrite"] is False

    def test_put_persists_across_calls(self, client: TestClient) -> None:
        client.put(
            "/settings/organization-automation",
            json={
                "enabled": True,
                "destination_root": "/persisted",
            },
        )
        resp = client.get("/settings/organization-automation")
        assert resp.json()["destination_root"] == "/persisted"

    def test_put_normalizes_source_prefixes(self, client: TestClient) -> None:
        resp = client.put(
            "/settings/organization-automation",
            json={
                "allowed_source_path_prefixes": [
                    "/a",
                    "",
                    "/b",
                    "/a",
                    " ",
                    "/b",
                ],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["allowed_source_path_prefixes"] == ["/a", "/b"]

    def test_put_rejects_unknown_default_after_download(
        self, client: TestClient
    ) -> None:
        resp = client.put(
            "/settings/organization-automation",
            json={"default_after_download": "invalid_option"},
        )
        assert resp.status_code == 422

    def test_put_returns_policy_response_type(
        self, client: TestClient
    ) -> None:
        resp = client.put(
            "/settings/organization-automation",
            json={},
        )
        body = resp.json()
        # Should contain all fields from the response model
        for key in (
            "enabled",
            "default_after_download",
            "allowed_source_path_prefixes",
            "destination_root",
            "allow_delete",
            "allow_overwrite",
        ):
            assert key in body, f"missing key {key} in response"
