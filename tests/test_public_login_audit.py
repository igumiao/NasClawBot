from __future__ import annotations

from datetime import datetime, timezone
from ipaddress import ip_address
import json

from app.services.experience_auth import ExperienceAuth
from app.services.public_login_audit import PublicLoginAudit


def test_records_only_successful_public_login_shape(tmp_path):
    auth = ExperienceAuth("J4125", local_cidrs="192.168.0.0/16,fc00::/7,fe80::/10")
    audit = PublicLoginAudit(
        tmp_path / "public-login-audit.jsonl",
        is_local=auth.is_local,
        now=lambda: datetime(2026, 8, 13, 3, 20, tzinfo=timezone.utc),
    )

    assert audit.record_success(ip_address("203.0.113.8")) is True

    entry = json.loads(audit.path.read_text(encoding="utf-8"))
    assert entry == {
        "timestamp": "2026-08-13T03:20:00+00:00",
        "event": "login_success",
        "client_ip": "203.0.113.8",
    }
    assert audit.path.stat().st_mode & 0o777 == 0o600


def test_excludes_local_ipv4_and_ipv6(tmp_path):
    auth = ExperienceAuth(
        "J4125",
        local_cidrs="10.0.0.0/8,192.168.0.0/16,fc00::/7,fe80::/10,::1/128",
    )
    audit = PublicLoginAudit(tmp_path / "audit.jsonl", is_local=auth.is_local)

    assert audit.record_success(ip_address("10.10.1.2")) is False
    assert audit.record_success(ip_address("192.168.1.2")) is False
    assert audit.record_success(ip_address("fd12::2")) is False
    assert audit.record_success(ip_address("fe80::2")) is False
    assert not audit.path.exists()


def test_prunes_entries_older_than_retention_when_new_login_arrives(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text(
        '{"timestamp":"2026-01-01T00:00:00+00:00","event":"login_success","client_ip":"198.51.100.1"}\n'
        '{"timestamp":"2026-08-01T00:00:00+00:00","event":"login_success","client_ip":"198.51.100.2"}\n',
        encoding="utf-8",
    )
    audit = PublicLoginAudit(
        path,
        is_local=lambda _address: False,
        retention_days=180,
        now=lambda: datetime(2026, 8, 13, tzinfo=timezone.utc),
    )

    audit.record_success(ip_address("203.0.113.9"))

    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [entry["client_ip"] for entry in entries] == ["198.51.100.2", "203.0.113.9"]


def test_disabled_audit_writes_nothing(tmp_path):
    audit = PublicLoginAudit(
        tmp_path / "audit.jsonl",
        is_local=lambda _address: False,
        enabled=False,
    )

    assert audit.record_success(ip_address("203.0.113.8")) is False
    assert not audit.path.exists()


def test_storage_failure_does_not_break_login_flow(tmp_path, monkeypatch):
    audit = PublicLoginAudit(
        tmp_path / "audit.jsonl",
        is_local=lambda _address: False,
    )
    monkeypatch.setattr(
        audit,
        "_replace",
        lambda _entries: (_ for _ in ()).throw(OSError("read-only")),
    )

    assert audit.record_success(ip_address("203.0.113.8")) is False
