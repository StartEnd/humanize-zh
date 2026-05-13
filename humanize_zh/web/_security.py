"""humanize_zh.web._security — thin shim over :mod:`humanize_core.web._security`.

P2.8e collapses the middleware onto humanize-core. The middleware
class and (most of) the dataclass live upstream; this module only
overrides :meth:`AbuseControlConfig.from_env` so the legacy
``HUMANIZE_ZH_WEB_*`` environment variables keep working alongside
the canonical ``HUMANIZE_CORE_WEB_*`` names.

Env-var precedence (highest → lowest):

1. ``HUMANIZE_ZH_WEB_TOKEN`` / ``HUMANIZE_ZH_WEB_RATE_LIMIT_PER_MINUTE``
   — humanize-zh's pre-P2.8 names; preserved for users who haven't
   migrated their deployment scripts.
2. ``HUMANIZE_CORE_WEB_TOKEN`` / ``HUMANIZE_CORE_WEB_RATE_LIMIT_PER_MINUTE``
   — humanize-core canonical names; recommended for new deployments
   so the same config works regardless of which plugin is installed.

A bad integer for either ``*_RATE_LIMIT_PER_MINUTE`` logs a warning and
disables the rate limiter (same behavior as humanize-core).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from humanize_core.web._security import (
    AbuseControlConfig as _CoreAbuseControlConfig,
)
from humanize_core.web._security import (
    AbuseControlMiddleware,  # noqa: F401  (legacy re-export)
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AbuseControlConfig(_CoreAbuseControlConfig):
    """Same shape as humanize-core's config, but reads legacy env vars too.

    Inherits all behavior (``auth_enabled`` / ``rate_limit_enabled`` /
    ``any_enabled`` properties, default constructor) from the
    framework dataclass; only :meth:`from_env` is overridden to look
    at the ``HUMANIZE_ZH_WEB_*`` aliases first.
    """

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AbuseControlConfig:
        """Build a config from env, preferring legacy ``HUMANIZE_ZH_WEB_*``.

        Why we prefer the legacy names: an existing user who sets
        ``HUMANIZE_ZH_WEB_TOKEN=...`` would be surprised if their
        deployment silently became unauthenticated after a humanize-zh
        upgrade. New users who only know the ``HUMANIZE_CORE_*`` names
        get them honored as the fallback.
        """
        src = env if env is not None else dict(os.environ)
        token = (
            src.get("HUMANIZE_ZH_WEB_TOKEN")
            or src.get("HUMANIZE_CORE_WEB_TOKEN")
            or None
        )
        raw_rate = (
            src.get("HUMANIZE_ZH_WEB_RATE_LIMIT_PER_MINUTE")
            or src.get("HUMANIZE_CORE_WEB_RATE_LIMIT_PER_MINUTE")
        )
        rate: int | None
        try:
            rate = int(raw_rate) if raw_rate else None
        except ValueError:
            logger.warning(
                "[humanize_zh.web] *_RATE_LIMIT_PER_MINUTE=%r is not an "
                "integer — rate limiting disabled",
                raw_rate,
            )
            rate = None
        return cls(token=token, rate_per_minute=rate)


__all__ = ["AbuseControlConfig", "AbuseControlMiddleware"]
