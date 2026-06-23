"""Organization authorization domain and one-way migration tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.organization import (
    OrganizationAuthorizationPolicy,
    default_organization_authorization_policy,
)
from app.services.organization_policy_store import (
    OrganizationAuthorizationPolicyStore,
)


@pytest.fixture
def store(tmp_path: Path) -> OrganizationAuthorizationPolicyStore:
    return OrganizationAuthorizationPolicyStore(tmp_path / "settings")


def test_default_is_fail_closed() -> None:
    value = default_organization_authorization_policy()
    assert value.background_organization_allowed is False
    assert value.allowed_source_path_prefixes == []
    assert value.destination_root == ""
    assert "default_after_download" not in value.model_dump()


def test_paths_are_normalized_and_safety_locks_forced() -> None:
    value = OrganizationAuthorizationPolicy.model_validate(
        {
            "background_organization_allowed": True,
            "allowed_source_path_prefixes": "/downloads\n\n/downloads\n/media",
            "destination_root": " /library ",
            "allow_delete": True,
            "allow_overwrite": True,
        }
    )
    assert value.allowed_source_path_prefixes == ["/downloads", "/media"]
    assert value.destination_root == "/library"
    assert value.allow_delete is False
    assert value.allow_overwrite is False
    with pytest.raises(ValidationError):
        value.allow_delete = True  # type: ignore[assignment]


def test_round_trip_uses_new_authoritative_file(
    store: OrganizationAuthorizationPolicyStore,
) -> None:
    expected = OrganizationAuthorizationPolicy(
        background_organization_allowed=True,
        allowed_source_path_prefixes=["/downloads"],
        destination_root="/media",
    )
    store.save(expected)
    assert store.load() == expected
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["background_organization_allowed"] is True
    assert "enabled" not in raw
    assert "default_after_download" not in raw


def test_legacy_file_migrates_authority_but_drops_behavior_default(
    store: OrganizationAuthorizationPolicyStore,
) -> None:
    store.settings_dir.mkdir(parents=True)
    store.legacy_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "default_after_download": "auto_organize",
                "allowed_source_path_prefixes": ["/downloads"],
                "destination_root": "/media",
                "allow_delete": True,
            }
        ),
        encoding="utf-8",
    )
    migrated = store.load()
    assert migrated.background_organization_allowed is True
    assert migrated.allowed_source_path_prefixes == ["/downloads"]
    assert migrated.destination_root == "/media"
    assert store.path.exists()
    assert store.legacy_path.exists()
    assert "default_after_download" not in migrated.model_dump()
    assert migrated.allow_delete is False


def test_new_file_is_authoritative_even_when_legacy_differs(
    store: OrganizationAuthorizationPolicyStore,
) -> None:
    store.settings_dir.mkdir(parents=True)
    store.legacy_path.write_text(
        json.dumps({"enabled": True, "destination_root": "/legacy"}),
        encoding="utf-8",
    )
    store.path.write_text("{corrupt", encoding="utf-8")
    loaded = store.load()
    assert loaded.background_organization_allowed is False
    assert loaded.destination_root == ""


@pytest.mark.parametrize("contents", ["{bad", "[]", '"text"'])
def test_corrupt_current_policy_fails_closed(
    store: OrganizationAuthorizationPolicyStore, contents: str
) -> None:
    store.settings_dir.mkdir(parents=True)
    store.path.write_text(contents, encoding="utf-8")
    assert store.load() == default_organization_authorization_policy()


def test_missing_files_return_closed_default_without_creating_authority(
    store: OrganizationAuthorizationPolicyStore,
) -> None:
    assert store.load() == default_organization_authorization_policy()
    assert not store.path.exists()
