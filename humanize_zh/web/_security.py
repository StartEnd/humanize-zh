"""humanize_zh.web._security — opt-in auth + rate-limit middleware.

Both controls default to **off** so existing local-only deployments and
the test-suite keep working without env tweaks. They are activated by
setting environment variables at app-construction time:

- ``HUMANIZE_ZH_WEB_TOKEN`` — bearer token / query-string token. When set,
  every route except :data:`_PUBLIC_PATHS` requires either an
  ``Authorization: Bearer <token>`` header or a ``?token=<token>`` query
  parameter. Constant-time comparison prevents timing attacks.
- ``HUMANIZE_ZH_WEB_RATE_LIMIT_PER_MINUTE`` — positive int. When set, each
  client IP is limited to ``N`` requests per rolling 60-second window.
  Implementation is a tiny in-memory deque per IP, locked for thread safety
  (FastAPI sync routes run in a threadpool). When you exceed the budget the
  server returns ``429 Too Many Requests`` with a ``Retry-After`` header.

Threat model & limits (see ``SECURITY.md`` for the full picture):

- The rate limiter is **process-local**. If you run multiple uvicorn workers
  the budget is per worker, not global. For real abuse control put a
  reverse proxy (nginx ``limit_req``, Cloudflare, ...) in front.
- The token is checked verbatim. Rotate via env; there is no DB and no
  per-user token. This is meant for "make the local dev UI not trivially
  open to my LAN", not for multi-tenant hosting.
"""
from __future__ import annotations

import hmac
import logging
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

logger = logging.getLogger("humanize_zh.web._security")


# Routes that always pass through, even when auth is enabled — kept tiny so
# operators (and uptime checks) can still hit the service without a token.
_PUBLIC_PATHS: frozenset[str] = frozenset({"/health"})


@dataclass(frozen=True)
class AbuseControlConfig:
    """Resolved configuration for :class:`AbuseControlMiddleware`.

    Attributes:
        token: Bearer token; ``None`` disables auth entirely.
        rate_per_minute: Max requests per rolling 60-second window per IP;
            ``None`` (or non-positive) disables rate limiting.
    """
    token: str | None = None
    rate_per_minute: int | None = None

    @property
    def auth_enabled(self) -> bool:
        return bool(self.token)

    @property
    def rate_limit_enabled(self) -> bool:
        return bool(self.rate_per_minute and self.rate_per_minute > 0)

    @property
    def any_enabled(self) -> bool:
        return self.auth_enabled or self.rate_limit_enabled

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AbuseControlConfig:
        """Build a config from ``os.environ`` (or an injected dict for tests)."""
        src = env if env is not None else dict(os.environ)
        token = src.get("HUMANIZE_ZH_WEB_TOKEN") or None
        raw_rate = src.get("HUMANIZE_ZH_WEB_RATE_LIMIT_PER_MINUTE")
        rate: int | None
        try:
            rate = int(raw_rate) if raw_rate else None
        except ValueError:
            logger.warning(
                "[humanize_zh.web] HUMANIZE_ZH_WEB_RATE_LIMIT_PER_MINUTE=%r "
                "is not an integer — rate limiting disabled",
                raw_rate,
            )
            rate = None
        return cls(token=token, rate_per_minute=rate)


def _client_ip(request: Request) -> str:
    """Best-effort client IP. Honours ``X-Forwarded-For`` if present."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client is None:
        return "unknown"
    return request.client.host


def _extract_token(request: Request) -> str | None:
    """Pull a presented token from header or query string. Header wins."""
    auth = request.headers.get("authorization")
    if auth:
        scheme, _, value = auth.partition(" ")
        if scheme.lower() == "bearer" and value:
            return value
    return request.query_params.get("token")


class AbuseControlMiddleware(BaseHTTPMiddleware):
    """Combined auth + rate-limit gate. No-op when neither is configured."""

    def __init__(self, app: ASGIApp, config: AbuseControlConfig) -> None:
        super().__init__(app)
        self._config = config
        # Per-IP request timestamp deques, guarded by ``_lock`` since FastAPI
        # runs sync routes in a threadpool — concurrent updates are common.
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint,
    ) -> Response:
        path = request.url.path
        if path in _PUBLIC_PATHS:
            return await call_next(request)

        # 1. Auth.
        if self._config.auth_enabled:
            presented = _extract_token(request) or ""
            assert self._config.token is not None  # for mypy: auth_enabled gates this
            # constant-time comparison; both sides are utf-8 bytes
            if not hmac.compare_digest(presented.encode(), self._config.token.encode()):
                return JSONResponse(
                    {"detail": "missing or invalid token"},
                    status_code=401,
                    headers={"WWW-Authenticate": 'Bearer realm="humanize-zh"'},
                )

        # 2. Rate limit.
        if self._config.rate_limit_enabled:
            limit = self._config.rate_per_minute
            assert limit is not None  # for mypy: rate_limit_enabled gates this
            ip = _client_ip(request)
            now = time.monotonic()
            window_start = now - 60.0
            with self._lock:
                bucket = self._buckets[ip]
                while bucket and bucket[0] < window_start:
                    bucket.popleft()
                if len(bucket) >= limit:
                    oldest = bucket[0]
                    retry_after = max(1, int(60 - (now - oldest)) + 1)
                    return JSONResponse(
                        {
                            "detail": (
                                f"rate limit exceeded ({limit}/minute). "
                                f"Retry in {retry_after}s."
                            )
                        },
                        status_code=429,
                        headers={"Retry-After": str(retry_after)},
                    )
                bucket.append(now)

        return await call_next(request)


__all__ = [
    "AbuseControlConfig",
    "AbuseControlMiddleware",
]
