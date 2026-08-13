from __future__ import annotations

from fastapi import FastAPI
import httpx
import pytest

from app import config as config_module
from app.api.auth_routes import build_auth_router
from app.services.experience_auth import (
    ExperienceAuth,
    ExperienceAuthMiddleware,
    ExperienceLoginRateLimitedError,
    InvalidExperienceCodeError,
    SESSION_TTL_SECONDS,
)


class FakeClock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_experience_code_setting_accepts_empty_or_five_ascii_digits(monkeypatch):
    monkeypatch.delenv("EXPERIENCE_ACCESS_CODE", raising=False)
    monkeypatch.setattr(config_module, "_ENV_DEFAULTS", {})
    assert config_module._get_experience_code_env() == ""

    monkeypatch.setenv("EXPERIENCE_ACCESS_CODE", "12345")
    assert config_module._get_experience_code_env() == "12345"


@pytest.mark.parametrize("value", ["1234", "123456", "abcde", "１２３４５"])
def test_experience_code_setting_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("EXPERIENCE_ACCESS_CODE", value)
    with pytest.raises(ValueError, match="five ASCII digits"):
        config_module._get_experience_code_env()


def test_session_expires_and_logout_revokes_it():
    clock = FakeClock()
    auth = ExperienceAuth("12345", clock=clock)

    session = auth.login("12345", "client-a")
    assert auth.validate(session.token) == session

    auth.logout(session.token)
    assert auth.validate(session.token) is None

    session = auth.login("12345", "client-a")
    clock.value += SESSION_TTL_SECONDS
    assert auth.validate(session.token) is None


def test_auth_module_rejects_invalid_config_even_without_settings_loader():
    with pytest.raises(ValueError, match="five ASCII digits"):
        ExperienceAuth("abcde")


def test_failed_logins_are_rate_limited_per_client():
    auth = ExperienceAuth("12345")

    for _ in range(5):
        with pytest.raises(InvalidExperienceCodeError):
            auth.login("00000", "client-a")

    with pytest.raises(ExperienceLoginRateLimitedError) as exc_info:
        auth.login("00000", "client-a")
    assert exc_info.value.retry_after_seconds > 0

    # A different visitor is not locked out.
    assert auth.login("12345", "client-b").token


def _test_app(access_code: str = "12345") -> FastAPI:
    app = FastAPI()
    auth = ExperienceAuth(access_code)
    app.add_middleware(ExperienceAuthMiddleware, auth=auth)
    app.include_router(build_auth_router(auth, trust_proxy_headers=True))

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

        login = await client.post("/auth/login", json={"code": "12345"})
        assert login.status_code == 200
        assert login.json()["authenticated"] is True
        cookie = login.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "secure" in cookie
        assert "samesite=strict" in cookie
        assert "max-age=3600" in cookie
        assert "12345" not in cookie

        assert (await client.get("/auth/session")).json()["authenticated"] is True
        assert (await client.get("/protected")).status_code == 200

        logout = await client.post("/auth/logout")
        assert logout.status_code == 204
        assert (await client.get("/auth/session")).json()["authenticated"] is False
        assert (await client.get("/protected")).status_code == 401


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
        }
        assert (await client.get("/protected")).status_code == 200
