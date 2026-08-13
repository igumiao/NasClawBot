"""HTTP interface for the public experience-code login."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.services.experience_auth import (
    EXPERIENCE_SESSION_COOKIE,
    ExperienceAuth,
    ExperienceLoginRateLimitedError,
    InvalidExperienceCodeError,
    SESSION_TTL_SECONDS,
)


class ExperienceLoginRequest(BaseModel):
    code: str = Field(pattern=r"^[0-9]{5}$")


def _iso_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _client_key(request: Request, *, trust_proxy_headers: bool) -> str:
    if trust_proxy_headers:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        addresses = [item.strip() for item in forwarded_for.split(",") if item.strip()]
        if addresses:
            return addresses[-1]
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip
    return request.client.host if request.client else "unknown"


def build_auth_router(
    auth: ExperienceAuth,
    *,
    trust_proxy_headers: bool,
) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.post("/login")
    async def login(body: ExperienceLoginRequest, request: Request) -> JSONResponse:
        try:
            session = auth.login(
                body.code,
                _client_key(request, trust_proxy_headers=trust_proxy_headers),
            )
        except ExperienceLoginRateLimitedError as exc:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many failed attempts. Try again later."},
                headers={"Retry-After": str(exc.retry_after_seconds), "Cache-Control": "no-store"},
            )
        except InvalidExperienceCodeError:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid experience code."},
                headers={"Cache-Control": "no-store"},
            )

        response = JSONResponse(
            content={
                "enabled": auth.enabled,
                "authenticated": True,
                "expires_at": _iso_timestamp(session.expires_at) if auth.enabled else None,
            },
            headers={"Cache-Control": "no-store"},
        )
        if auth.enabled:
            response.set_cookie(
                key=EXPERIENCE_SESSION_COOKIE,
                value=session.token,
                max_age=SESSION_TTL_SECONDS,
                path="/",
                secure=True,
                httponly=True,
                samesite="strict",
            )
        return response

    @router.get("/session")
    async def session_status(request: Request) -> JSONResponse:
        session = auth.validate(request.cookies.get(EXPERIENCE_SESSION_COOKIE))
        return JSONResponse(
            content={
                "enabled": auth.enabled,
                "authenticated": session is not None,
                "expires_at": (
                    _iso_timestamp(session.expires_at)
                    if auth.enabled and session is not None
                    else None
                ),
            },
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/logout", status_code=204)
    async def logout(request: Request) -> Response:
        auth.logout(request.cookies.get(EXPERIENCE_SESSION_COOKIE))
        response = Response(status_code=204, headers={"Cache-Control": "no-store"})
        response.delete_cookie(
            key=EXPERIENCE_SESSION_COOKIE,
            path="/",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return response

    return router
