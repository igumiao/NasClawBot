from __future__ import annotations

from fastapi import FastAPI
import httpx
from ipaddress import ip_address
import pytest
from starlette.requests import Request

from app import config as config_module
from app.api.auth_routes import build_auth_router
from app.services.experience_auth import (
    ClientAddressResolver,
    ExperienceAuth,
    ExperienceAuthMiddleware,
    ExperienceLoginRateLimitedError,
    InvalidExperienceCodeError,
    PersistentExperienceSessionStore,
    SESSION_TTL_SECONDS,
)


class FakeClock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_experience_code_setting_accepts_empty_or_five_ascii_alphanumerics(monkeypatch):
    monkeypatch.delenv("EXPERIENCE_ACCESS_CODE", raising=False)
    monkeypatch.setattr(config_module, "_ENV_DEFAULTS", {})
    assert config_module._get_experience_code_env() == ""

    monkeypatch.setenv("EXPERIENCE_ACCESS_CODE", "J4125")
    assert config_module._get_experience_code_env() == "J4125"


@pytest.mark.parametrize("value", ["J412", "J41256", "J4_25", "体验码12", "１２３４５"])
def test_experience_code_setting_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("EXPERIENCE_ACCESS_CODE", value)
    with pytest.raises(ValueError, match="five ASCII letters or digits"):
        config_module._get_experience_code_env()


def test_session_expires_and_logout_revokes_it():
    clock = FakeClock()
    auth = ExperienceAuth("J4125", clock=clock)

    session = auth.login("J4125", "client-a")
    assert auth.validate(session.token) == session

    auth.logout(session.token)
    assert auth.validate(session.token) is None

    session = auth.login("J4125", "client-a")
    clock.value += SESSION_TTL_SECONDS
    assert auth.validate(session.token) is None


def test_auth_module_rejects_invalid_config_even_without_settings_loader():
    with pytest.raises(ValueError, match="five ASCII letters or digits"):
        ExperienceAuth("J4_25")


def test_failed_logins_are_rate_limited_per_client():
    auth = ExperienceAuth("J4125")

    for _ in range(5):
        with pytest.raises(InvalidExperienceCodeError):
            auth.login("00000", "client-a")

    with pytest.raises(ExperienceLoginRateLimitedError) as exc_info:
        auth.login("00000", "client-a")
    assert exc_info.value.retry_after_seconds > 0

    # A different visitor is not locked out.
    assert auth.login("J4125", "client-b").token


def test_experience_code_is_case_sensitive():
    auth = ExperienceAuth("J4125")

    with pytest.raises(InvalidExperienceCodeError):
        auth.login("j4125", "client-a")


@pytest.mark.parametrize(
    "address",
    [
        "10.10.20.30",
        "192.168.1.20",
        "172.16.4.5",
        "fd12:3456:789a::20",
        "fe80::1234",
        "::1",
    ],
)
def test_common_local_ipv4_and_ipv6_ranges_get_long_sessions(tmp_path, address):
    auth = ExperienceAuth(
        "J4125",
        local_session_days=180,
        local_cidrs=(
            "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,"
            "fc00::/7,fe80::/10,::1/128"
        ),
        persistent_store=PersistentExperienceSessionStore(tmp_path / "sessions.json"),
    )

    session = auth.login("J4125", ip_address(address))

    assert session.local_long_session is True
    assert session.cookie_max_age == 180 * 86400


def test_public_login_remains_a_one_hour_in_memory_session(tmp_path):
    store_path = tmp_path / "sessions.json"
    auth = ExperienceAuth(
        "J4125",
        local_cidrs="10.0.0.0/8,fc00::/7",
        persistent_store=PersistentExperienceSessionStore(store_path),
    )

    session = auth.login("J4125", ip_address("203.0.113.8"))

    assert session.local_long_session is False
    assert session.cookie_max_age == SESSION_TTL_SECONDS
    assert not store_path.exists()


def test_local_long_session_survives_restart_but_only_works_from_local_network(tmp_path):
    store = PersistentExperienceSessionStore(tmp_path / "sessions.json")
    kwargs = {
        "local_cidrs": "192.168.0.0/16,fc00::/7",
        "persistent_store": store,
    }
    first_auth = ExperienceAuth("J4125", **kwargs)
    session = first_auth.login("J4125", ip_address("fd00::42"))

    stored_text = store.path.read_text(encoding="utf-8")
    assert session.token not in stored_text
    assert first_auth._token_hash(session.token) in stored_text

    restarted_auth = ExperienceAuth("J4125", **kwargs)
    assert restarted_auth.validate(session.token, ip_address("192.168.1.5")) is not None
    assert restarted_auth.validate(session.token, ip_address("2001:db8::5")) is None
    # Leaving the LAN does not destroy the device session; returning restores it.
    assert restarted_auth.validate(session.token, ip_address("fd00::99")) is not None

    restarted_auth.logout(session.token)
    assert ExperienceAuth("J4125", **kwargs).validate(
        session.token,
        ip_address("fd00::99"),
    ) is None


def _request(client: str, *, forwarded_for: str | None = None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": headers,
            "client": (client, 1234),
            "server": ("testserver", 443),
            "scheme": "https",
        }
    )


def test_client_address_resolver_walks_trusted_proxy_chain_from_the_right():
    resolver = ClientAddressResolver(
        trust_proxy_headers=True,
        trusted_proxy_cidrs="127.0.0.0/8,172.16.0.0/12",
    )

    resolved = resolver.resolve(
        _request("172.16.0.2", forwarded_for="198.51.100.9, 127.0.0.1")
    )

    assert resolved == ip_address("198.51.100.9")


def test_client_address_resolver_ignores_forwarded_header_from_untrusted_peer():
    resolver = ClientAddressResolver(
        trust_proxy_headers=True,
        trusted_proxy_cidrs="127.0.0.0/8",
    )

    resolved = resolver.resolve(
        _request("203.0.113.25", forwarded_for="192.168.1.2")
    )

    assert resolved is None


def test_proxy_mode_without_forwarded_client_never_treats_proxy_as_local():
    resolver = ClientAddressResolver(
        trust_proxy_headers=True,
        trusted_proxy_cidrs="172.16.0.0/12",
    )

    assert resolver.resolve(_request("172.16.0.2")) is None


def _test_app(access_code: str = "J4125") -> FastAPI:
    app = FastAPI()
    auth = ExperienceAuth(access_code)
    address_resolver = ClientAddressResolver(
        trust_proxy_headers=True,
        trusted_proxy_cidrs="127.0.0.0/8,::1/128",
    )
    app.add_middleware(
        ExperienceAuthMiddleware,
        auth=auth,
        address_resolver=address_resolver,
    )
    app.include_router(build_auth_router(auth, address_resolver=address_resolver))

    @app.get("/protected")
    async def protected():
        return {"status": "ok"}

    return app


@pytest.mark.asyncio
async def test_middleware_protects_business_routes_but_keeps_auth_bootstrap_public():
    transport = httpx.ASGITransport(app=_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        assert (await client.get("/auth/session")).status_code == 200
        protected = await client.get("/protected")
        assert protected.status_code == 401
        assert protected.json() == {"detail": "Authentication required."}


@pytest.mark.asyncio
async def test_login_sets_secure_cookie_and_unlocks_protected_routes():
    transport = httpx.ASGITransport(app=_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        invalid = await client.post("/auth/login", json={"code": "00000"})
        assert invalid.status_code == 401
        assert "00000" not in invalid.text

        login = await client.post("/auth/login", json={"code": "J4125"})
        assert login.status_code == 200
        assert login.json()["authenticated"] is True
        cookie = login.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "secure" in cookie
        assert "samesite=strict" in cookie
        assert "max-age=3600" in cookie
        assert "J4125" not in cookie

        assert (await client.get("/auth/session")).json()["authenticated"] is True
        assert (await client.get("/protected")).status_code == 200

        logout = await client.post("/auth/logout")
        assert logout.status_code == 204
        assert (await client.get("/auth/session")).json()["authenticated"] is False
        assert (await client.get("/protected")).status_code == 401


@pytest.mark.asyncio
async def test_local_login_sets_persistent_cookie_metadata(tmp_path):
    app = FastAPI()
    resolver = ClientAddressResolver(
        trust_proxy_headers=False,
        trusted_proxy_cidrs="",
    )
    auth = ExperienceAuth(
        "J4125",
        local_session_days=180,
        local_cidrs="192.168.0.0/16,fc00::/7,fe80::/10",
        persistent_store=PersistentExperienceSessionStore(tmp_path / "sessions.json"),
    )
    app.include_router(build_auth_router(auth, address_resolver=resolver))
    transport = httpx.ASGITransport(app=app, client=("192.168.1.9", 1234))

    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://testserver",
    ) as client:
        login = await client.post("/auth/login", json={"code": "J4125"})

    assert login.json()["local_long_session"] is True
    assert "max-age=15552000" in login.headers["set-cookie"].lower()


@pytest.mark.asyncio
async def test_login_endpoint_returns_retry_after_when_rate_limited():
    transport = httpx.ASGITransport(app=_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        headers = {"X-Forwarded-For": "203.0.113.10"}
        for _ in range(5):
            response = await client.post("/auth/login", json={"code": "00000"}, headers=headers)
            assert response.status_code == 401
        limited = await client.post("/auth/login", json={"code": "00000"}, headers=headers)
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) > 0


@pytest.mark.asyncio
async def test_unconfigured_auth_preserves_existing_development_behavior():
    transport = httpx.ASGITransport(app=_test_app(access_code=""))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/auth/session")).json() == {
            "enabled": False,
            "authenticated": True,
            "expires_at": None,
            "local_long_session": False,
        }
        assert (await client.get("/protected")).status_code == 200
