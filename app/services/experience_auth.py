"""Authentication module for public demos and trusted local devices."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import hmac
from ipaddress import ip_address, ip_network, IPv4Address, IPv4Network, IPv6Address, IPv6Network
import json
import math
from pathlib import Path
import secrets
import threading
import time
from typing import Callable, Iterable

from starlette.requests import Request
from starlette.responses import JSONResponse


SESSION_TTL_SECONDS = 3600
FAILURE_WINDOW_SECONDS = 900
MAX_FAILURES_PER_WINDOW = 5
EXPERIENCE_SESSION_COOKIE = "nasclaw_experience_session"
SESSION_STORE_VERSION = 1

PUBLIC_EXPERIENCE_PATHS = {
    "/",
    "/auth/login",
    "/auth/logout",
    "/auth/session",
    "/brand-logo.png",
    "/favicon.png",
    "/health",
}

IPAddress = IPv4Address | IPv6Address
IPNetwork = IPv4Network | IPv6Network


def _parse_ip(value: str | None) -> IPAddress | None:
    if not value:
        return None
    # IPv6 link-local addresses may carry an interface scope (e.g. fe80::1%eth0).
    candidate = value.strip().split("%", 1)[0]
    try:
        return ip_address(candidate)
    except ValueError:
        return None


def parse_cidrs(raw: str, *, setting_name: str) -> tuple[IPNetwork, ...]:
    networks: list[IPNetwork] = []
    for item in raw.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            networks.append(ip_network(candidate, strict=False))
        except ValueError as exc:
            raise ValueError(f"{setting_name} contains invalid CIDR: {candidate}") from exc
    return tuple(networks)


def _in_networks(address: IPAddress | None, networks: Iterable[IPNetwork]) -> bool:
    if address is None:
        return False
    return any(address.version == network.version and address in network for network in networks)


class ClientAddressResolver:
    """Resolve one client address through an explicitly trusted proxy chain."""

    def __init__(self, *, trust_proxy_headers: bool, trusted_proxy_cidrs: str) -> None:
        self._trust_proxy_headers = trust_proxy_headers
        self._trusted_proxies = parse_cidrs(
            trusted_proxy_cidrs,
            setting_name="EXPERIENCE_TRUSTED_PROXY_CIDRS",
        )

    def resolve(self, request: Request) -> IPAddress | None:
        peer = _parse_ip(request.client.host if request.client else None)
        if not self._trust_proxy_headers:
            return peer
        # Only explicitly trusted proxies may supply the effective client
        # address. Direct clients keep their TCP peer address and any spoofed
        # forwarding headers are ignored.
        if not _in_networks(peer, self._trusted_proxies):
            return peer

        forwarded: list[IPAddress] = []
        for value in request.headers.get("x-forwarded-for", "").split(","):
            address = _parse_ip(value)
            if address is not None:
                forwarded.append(address)
        if not forwarded:
            real_ip = _parse_ip(request.headers.get("x-real-ip"))
            return real_ip

        # Walk towards the visitor. Trusted hops are skipped; the first
        # untrusted address is the effective client.
        for address in reversed([*forwarded, peer] if peer is not None else forwarded):
            if not _in_networks(address, self._trusted_proxies):
                return address
        return forwarded[0]


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
    local_long_session: bool = False
    cookie_max_age: int = SESSION_TTL_SECONDS


class PersistentExperienceSessionStore:
    """Persist only hashes of local long-session tokens in one JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, float]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}
            sessions = data.get("sessions", {})
            if data.get("version") != SESSION_STORE_VERSION or not isinstance(sessions, dict):
                return {}
            return {
                str(token_hash): float(expires_at)
                for token_hash, expires_at in sessions.items()
                if isinstance(token_hash, str) and isinstance(expires_at, (int, float))
            }
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def save(self, sessions: dict[str, float]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(
                {"version": SESSION_STORE_VERSION, "sessions": sessions},
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        temporary_path.chmod(0o600)
        temporary_path.replace(self.path)


class ExperienceAuth:
    """Authenticate one code and hide short/local session policy behind one interface."""

    def __init__(
        self,
        access_code: str,
        *,
        local_long_session: bool = True,
        local_session_days: int = 180,
        local_cidrs: str = "",
        persistent_store: PersistentExperienceSessionStore | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if access_code and (
            len(access_code) != 5
            or any(not (char.isascii() and char.isalnum()) for char in access_code)
        ):
            raise ValueError(
                "Experience access code must be exactly five ASCII letters or digits."
            )
        if local_session_days <= 0:
            raise ValueError("EXPERIENCE_LOCAL_SESSION_DAYS must be greater than zero.")
        self._access_code = access_code
        self._local_long_session = local_long_session
        self._local_session_ttl = local_session_days * 86400
        self._local_networks = parse_cidrs(
            local_cidrs,
            setting_name="EXPERIENCE_LOCAL_CIDRS",
        )
        self._persistent_store = persistent_store
        self._clock = clock
        self._sessions: dict[str, float] = {}
        self._persistent_sessions = persistent_store.load() if persistent_store else {}
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._access_code)

    def is_local(self, client_address: IPAddress | None) -> bool:
        return _in_networks(client_address, self._local_networks)

    def login(self, code: str, client_address: IPAddress | None = None) -> ExperienceSession:
        if not self.enabled:
            return ExperienceSession(token="", expires_at=self._clock() + SESSION_TTL_SECONDS)

        now = self._clock()
        client_key = str(client_address or "unknown")
        with self._lock:
            failures = self._active_failures(client_key, now)
            if len(failures) >= MAX_FAILURES_PER_WINDOW:
                retry_after = max(1, math.ceil(failures[0] + FAILURE_WINDOW_SECONDS - now))
                raise ExperienceLoginRateLimitedError(retry_after)
            if not hmac.compare_digest(code, self._access_code):
                failures.append(now)
                raise InvalidExperienceCodeError

            self._failures.pop(client_key, None)
            self._prune_expired(now)
            token = secrets.token_urlsafe(32)
            is_local_long = self._local_long_session and self.is_local(client_address)
            expires_at = now + (self._local_session_ttl if is_local_long else SESSION_TTL_SECONDS)
            if is_local_long:
                self._persistent_sessions[self._token_hash(token)] = expires_at
                self._save_persistent_sessions()
            else:
                self._sessions[token] = expires_at
            max_age = self._local_session_ttl if is_local_long else SESSION_TTL_SECONDS
            return ExperienceSession(token, expires_at, is_local_long, max_age)

    def validate(
        self,
        token: str | None,
        client_address: IPAddress | None = None,
    ) -> ExperienceSession | None:
        if not self.enabled:
            return ExperienceSession(token="", expires_at=self._clock() + SESSION_TTL_SECONDS)
        if not token:
            return None

        now = self._clock()
        with self._lock:
            expires_at = self._sessions.get(token)
            if expires_at is not None:
                if expires_at <= now:
                    self._sessions.pop(token, None)
                    return None
                return ExperienceSession(
                    token,
                    expires_at,
                    False,
                    max(1, math.ceil(expires_at - now)),
                )

            token_hash = self._token_hash(token)
            expires_at = self._persistent_sessions.get(token_hash)
            if expires_at is None:
                return None
            if expires_at <= now:
                self._persistent_sessions.pop(token_hash, None)
                self._save_persistent_sessions()
                return None
            if not self.is_local(client_address):
                return None
            return ExperienceSession(
                token,
                expires_at,
                True,
                max(1, math.ceil(expires_at - now)),
            )

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)
            if self._persistent_sessions.pop(self._token_hash(token), None) is not None:
                self._save_persistent_sessions()

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _active_failures(self, client_key: str, now: float) -> deque[float]:
        failures = self._failures[client_key]
        cutoff = now - FAILURE_WINDOW_SECONDS
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            self._failures.pop(client_key, None)
            failures = self._failures[client_key]
        return failures

    def _prune_expired(self, now: float) -> None:
        for token in [token for token, expiry in self._sessions.items() if expiry <= now]:
            self._sessions.pop(token, None)
        persistent_before = len(self._persistent_sessions)
        self._persistent_sessions = {
            token_hash: expiry
            for token_hash, expiry in self._persistent_sessions.items()
            if expiry > now
        }
        if len(self._persistent_sessions) != persistent_before:
            self._save_persistent_sessions()

    def _save_persistent_sessions(self) -> None:
        if self._persistent_store is not None:
            self._persistent_store.save(self._persistent_sessions)


class ExperienceAuthMiddleware:
    """Pure ASGI middleware that protects every non-public HTTP path."""

    def __init__(
        self,
        app,
        *,
        auth: ExperienceAuth,
        address_resolver: ClientAddressResolver,
    ) -> None:
        self.app = app
        self.auth = auth
        self.address_resolver = address_resolver

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
        session = self.auth.validate(
            request.cookies.get(EXPERIENCE_SESSION_COOKIE),
            self.address_resolver.resolve(request),
        )
        if not is_public and session is None:
            response = JSONResponse(
                status_code=401,
                content={"detail": "Authentication required."},
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
