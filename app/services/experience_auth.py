"""Small in-process authentication module for public experience deployments."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import hmac
import math
import secrets
import threading
import time
from typing import Callable

from starlette.requests import Request
from starlette.responses import JSONResponse


SESSION_TTL_SECONDS = 3600
FAILURE_WINDOW_SECONDS = 900
MAX_FAILURES_PER_WINDOW = 5
EXPERIENCE_SESSION_COOKIE = "nasclaw_experience_session"

PUBLIC_EXPERIENCE_PATHS = {
    "/",
    "/auth/login",
    "/auth/logout",
    "/auth/session",
    "/brand-logo.png",
    "/favicon.png",
    "/health",
}


class InvalidExperienceCodeError(Exception):
    """Raised when an experience code does not match."""


class ExperienceLoginRateLimitedError(Exception):
    """Raised when a client has made too many failed login attempts."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Too many failed login attempts")
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class ExperienceSession:
    token: str
    expires_at: float


class ExperienceAuth:
    """Authenticate one configured code and manage short-lived opaque sessions."""

    def __init__(
        self,
        access_code: str,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if access_code and (
            len(access_code) != 5
            or any(
                not (char.isascii() and char.isalnum())
                for char in access_code
            )
        ):
            raise ValueError(
                "Experience access code must be exactly five ASCII letters or digits."
            )
        self._access_code = access_code
        self._clock = clock
        self._sessions: dict[str, float] = {}
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._access_code)

    def login(self, code: str, client_key: str) -> ExperienceSession:
        if not self.enabled:
            return ExperienceSession(token="", expires_at=self._clock() + SESSION_TTL_SECONDS)

        now = self._clock()
        with self._lock:
            failures = self._active_failures(client_key, now)
            if len(failures) >= MAX_FAILURES_PER_WINDOW:
                retry_after = max(1, math.ceil(failures[0] + FAILURE_WINDOW_SECONDS - now))
                raise ExperienceLoginRateLimitedError(retry_after)

            if not hmac.compare_digest(code, self._access_code):
                failures.append(now)
                raise InvalidExperienceCodeError

            self._failures.pop(client_key, None)
            self._prune_expired_sessions(now)
            token = secrets.token_urlsafe(32)
            expires_at = now + SESSION_TTL_SECONDS
            self._sessions[token] = expires_at
            return ExperienceSession(token=token, expires_at=expires_at)

    def validate(self, token: str | None) -> ExperienceSession | None:
        if not self.enabled:
            return ExperienceSession(token="", expires_at=self._clock() + SESSION_TTL_SECONDS)
        if not token:
            return None

        now = self._clock()
        with self._lock:
            expires_at = self._sessions.get(token)
            if expires_at is None:
                return None
            if expires_at <= now:
                self._sessions.pop(token, None)
                return None
            return ExperienceSession(token=token, expires_at=expires_at)

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def _active_failures(self, client_key: str, now: float) -> deque[float]:
        failures = self._failures[client_key]
        cutoff = now - FAILURE_WINDOW_SECONDS
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            self._failures.pop(client_key, None)
            failures = self._failures[client_key]
        return failures

    def _prune_expired_sessions(self, now: float) -> None:
        expired = [token for token, expires_at in self._sessions.items() if expires_at <= now]
        for token in expired:
            self._sessions.pop(token, None)


class ExperienceAuthMiddleware:
    """Pure ASGI middleware that protects every non-public HTTP path."""

    def __init__(self, app, *, auth: ExperienceAuth) -> None:
        self.app = app
        self.auth = auth

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not self.auth.enabled:
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        path = request.url.path
        is_public = (
            path in PUBLIC_EXPERIENCE_PATHS
            or path.startswith("/assets/")
            or path.startswith("/static/")
        )
        if not is_public and self.auth.validate(
            request.cookies.get(EXPERIENCE_SESSION_COOKIE)
        ) is None:
            response = JSONResponse(
                status_code=401,
                content={"detail": "Authentication required."},
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
