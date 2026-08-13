"""HTTP interface for the public experience-code login."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.services.experience_auth import (
    ClientAddressResolver,
    EXPERIENCE_SESSION_COOKIE,
    ExperienceAuth,
    ExperienceLoginRateLimitedError,
    IPAddress,
    InvalidExperienceCodeError,
)
from app.services.public_login_audit import PublicLoginAudit


class ExperienceLoginRequest(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9]{5}$")


def _iso_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def build_auth_router(
    auth: ExperienceAuth,
    *,
    address_resolver: ClientAddressResolver,
    login_audit: PublicLoginAudit | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    def cookie_requires_secure_transport(
        request: Request,
        client_address: IPAddress | None,
    ) -> bool:
        # Permit direct LAN access over plain HTTP while keeping public and
        # HTTPS sessions restricted to secure transport. Persistent local
        # sessions are also rejected by ExperienceAuth outside local CIDRs.
        return request.url.scheme != "http" or not auth.is_local(client_address)

    @router.post("/login")
    async def login(body: ExperienceLoginRequest, request: Request) -> JSONResponse:
        client_address = address_resolver.resolve(request)
        try:
            session = auth.login(
                body.code,
                client_address,
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

        if auth.enabled and login_audit is not None:
            login_audit.record_success(client_address)

        response = JSONResponse(
            content={
                "enabled": auth.enabled,
                "authenticated": True,
                "expires_at": _iso_timestamp(session.expires_at) if auth.enabled else None,
                "local_long_session": session.local_long_session,
            },
            headers={"Cache-Control": "no-store"},
        )
        if auth.enabled:
            response.set_cookie(
                key=EXPERIENCE_SESSION_COOKIE,
                value=session.token,
                max_age=session.cookie_max_age,
                path="/",
                secure=cookie_requires_secure_transport(request, client_address),
                httponly=True,
                samesite="strict",
            )
        return response

    @router.get("/session")
    async def session_status(request: Request) -> JSONResponse:
        session = auth.validate(
            request.cookies.get(EXPERIENCE_SESSION_COOKIE),
            address_resolver.resolve(request),
        )
        return JSONResponse(
            content={
                "enabled": auth.enabled,
                "authenticated": session is not None,
                "expires_at": (
                    _iso_timestamp(session.expires_at)
                    if auth.enabled and session is not None
                    else None
                ),
                "local_long_session": bool(session and session.local_long_session),
            },
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/logout", status_code=204)
    async def logout(request: Request) -> Response:
        client_address = address_resolver.resolve(request)
        auth.logout(request.cookies.get(EXPERIENCE_SESSION_COOKIE))
        response = Response(status_code=204, headers={"Cache-Control": "no-store"})
        response.delete_cookie(
            key=EXPERIENCE_SESSION_COOKIE,
            path="/",
            secure=cookie_requires_secure_transport(request, client_address),
            httponly=True,
            samesite="strict",
        )
        return response

    return router
