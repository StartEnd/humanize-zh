"""humanize_zh._core.language_registry — discovery and lookup for language plugins.

Two ways a :class:`~humanize_zh._core.protocols.LanguageProfile` ends up
in this registry:

1. **Manual registration** — a plugin's ``__init__.py`` calls
   :func:`register_language` at import time. This is what the in-repo
   spike (Phase 1) uses, and it remains the recommended path during
   tests because it doesn't depend on the install layout.

2. **Entry-point auto-discovery** — once plugins ship as separate PyPI
   packages (Phase 2+), each declares
   ``[project.entry-points."humanize_core.languages"]`` and we use
   :func:`importlib.metadata.entry_points` to load them lazily on first
   :func:`get_language` / :func:`list_languages` call.

The registry is **process-global, mutable, and thread-safe** (guarded by
``threading.RLock``). FastAPI runs sync routes on a threadpool, so two
concurrent requests calling :func:`get_language("zh")` must not race.

Failure modes:

- Duplicate ``code`` registration without ``replace=True`` →
  :class:`LanguageAlreadyRegistered`. Prevents two plugins both
  claiming ``"zh"``.
- :func:`get_language` on an unknown code → :class:`UnknownLanguage`
  with a hint listing what *is* registered + how to install.
- Entry-point load that raises during import → logged and skipped, not
  fatal. One bad plugin should not nuke the whole app.
"""
from __future__ import annotations

import logging
import threading
from importlib.metadata import EntryPoint, entry_points

from .protocols import LanguageProfile

logger = logging.getLogger("humanize_zh._core.language_registry")

ENTRY_POINT_GROUP = "humanize_core.languages"

# ─── Module state ──────────────────────────────────────────────────────────
#
# Two locks, on purpose:
#
# - ``_LOCK`` (RLock) guards every read/write of ``_PROFILES``. Reentrant
#   so plugins whose import path re-enters the registry don't deadlock.
# - ``_DISCOVERY_LOCK`` (plain Lock) serialises the *first* entry-point
#   scan, which is allowed to call ``register_language`` (which takes
#   ``_LOCK`` itself). A reentrant lock here would let a buggy plugin
#   recursively trigger another discovery; a plain Lock makes that an
#   immediate deadlock instead — easier to debug than a hang.

_LOCK = threading.RLock()
_DISCOVERY_LOCK = threading.Lock()
_PROFILES: dict[str, LanguageProfile] = {}
_DISCOVERY_DONE = False


# ─── Exceptions ────────────────────────────────────────────────────────────


class LanguageAlreadyRegistered(ValueError):
    """Two ``LanguageProfile`` instances registered with the same code."""


class UnknownLanguage(KeyError):
    """:func:`get_language` called with a code that is not registered."""

    def __init__(self, code: str, registered: list[str]) -> None:
        if registered:
            hint = f"Registered: {sorted(registered)}."
        else:
            hint = (
                "No language plugins registered. Install one of "
                "humanize-zh, humanize-en, ..."
            )
        super().__init__(f"unknown language code {code!r}. {hint}")
        self.code = code
        self.registered = registered


# ─── Public API ────────────────────────────────────────────────────────────


def register_language(
    profile: LanguageProfile,
    *,
    replace: bool = False,
) -> None:
    """Register a language plugin.

    Args:
        profile: The :class:`LanguageProfile` to add.
        replace: When ``True``, silently overwrite any existing entry
            with the same ``profile.code``. Default ``False`` raises
            :class:`LanguageAlreadyRegistered` so misconfigurations are
            loud. Use ``replace=True`` only in tests.

    Raises:
        TypeError: ``profile`` is not a :class:`LanguageProfile`.
        LanguageAlreadyRegistered: ``profile.code`` already taken and
            ``replace=False``.
    """
    if not isinstance(profile, LanguageProfile):
        raise TypeError(
            f"register_language expected LanguageProfile, got "
            f"{type(profile).__name__}"
        )
    with _LOCK:
        existing = _PROFILES.get(profile.code)
        if existing is not None and not replace:
            raise LanguageAlreadyRegistered(
                f"language code {profile.code!r} is already registered "
                f"(display_name={existing.display_name!r}). "
                f"Pass replace=True if this is intentional."
            )
        _PROFILES[profile.code] = profile
        logger.debug(
            "[humanize_zh._core] registered language %r (display_name=%r)",
            profile.code, profile.display_name,
        )


def unregister_language(code: str) -> LanguageProfile | None:
    """Remove a language. Returns the removed profile or ``None``.

    Primarily intended for test isolation.
    """
    with _LOCK:
        return _PROFILES.pop(code, None)


def get_language(code: str) -> LanguageProfile:
    """Look up a registered language by code.

    Triggers entry-point discovery on first call if it has not run yet.

    Raises:
        UnknownLanguage: ``code`` is not registered.
    """
    _ensure_discovered()
    with _LOCK:
        try:
            return _PROFILES[code]
        except KeyError:
            raise UnknownLanguage(code, list(_PROFILES.keys())) from None


def list_languages() -> list[str]:
    """Return registered language codes, sorted for determinism."""
    _ensure_discovered()
    with _LOCK:
        return sorted(_PROFILES.keys())


def list_profiles() -> list[LanguageProfile]:
    """Return registered profiles, sorted by code."""
    _ensure_discovered()
    with _LOCK:
        return [_PROFILES[c] for c in sorted(_PROFILES.keys())]


def reset_for_tests() -> None:
    """Drop all state. Tests should call this in fixture teardown to
    avoid leaking registrations across test cases.
    """
    global _DISCOVERY_DONE
    with _LOCK:
        _PROFILES.clear()
        _DISCOVERY_DONE = False


# ─── Entry-point discovery ─────────────────────────────────────────────────


def _ensure_discovered() -> None:
    """Run entry-point discovery once per process. Idempotent.

    Double-checked locking pattern:

    1. Fast path read of ``_DISCOVERY_DONE`` without locks (Python's GIL
       makes single-attribute reads atomic).
    2. If not done, take ``_DISCOVERY_LOCK`` and re-check — another
       thread may have completed discovery while we waited.
    3. Run discovery; flip the flag *after* it finishes (or fails) so
       concurrent ``get_language`` callers always observe a consistent
       ``_PROFILES`` state — never a half-loaded one.
    """
    global _DISCOVERY_DONE
    if _DISCOVERY_DONE:
        return
    with _DISCOVERY_LOCK:
        if _DISCOVERY_DONE:
            return
        try:
            _discover_via_entrypoints()
        finally:
            # Set even on exception so we don't loop on persistent errors.
            _DISCOVERY_DONE = True


def _discover_via_entrypoints() -> None:
    """Load every plugin declared under :data:`ENTRY_POINT_GROUP`.

    Each entry-point should resolve to a :class:`LanguageProfile`
    instance (the plugin module exports it as a top-level ``profile``).
    Failures during a single load are logged and skipped — one broken
    plugin must not prevent others from loading.
    """
    try:
        eps = entry_points(group=ENTRY_POINT_GROUP)
    except Exception:
        # Older importlib.metadata (3.9) returns a SelectableGroups dict.
        # We unconditionally fall back to dict-style lookup.
        try:
            eps = entry_points().get(ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined,arg-type]
        except Exception as e:  # pragma: no cover
            logger.warning(
                "[humanize_zh._core] entry-points discovery failed: %s", e,
            )
            return

    for ep in eps:
        _load_entry_point(ep)


def _load_entry_point(ep: EntryPoint) -> None:
    """Load one entry-point and register its profile. Failures swallowed."""
    try:
        loaded = ep.load()
    except Exception as e:
        logger.warning(
            "[humanize_zh._core] entry-point %r failed to load: %s",
            ep.name, e,
        )
        return

    # Accept either a LanguageProfile or a zero-arg callable returning one
    # (lets plugins defer expensive initialization until first lookup).
    profile = loaded() if callable(loaded) and not isinstance(loaded, LanguageProfile) else loaded

    if not isinstance(profile, LanguageProfile):
        logger.warning(
            "[humanize_zh._core] entry-point %r resolved to %r, expected "
            "LanguageProfile — skipping",
            ep.name, type(profile).__name__,
        )
        return

    try:
        # replace=True so two installs of the same plugin (editable +
        # site-packages) don't blow up; last writer wins.
        register_language(profile, replace=True)
    except Exception as e:  # pragma: no cover
        logger.warning(
            "[humanize_zh._core] failed to register %r from entry-point: %s",
            profile.code, e,
        )


__all__ = [
    "ENTRY_POINT_GROUP",
    "LanguageAlreadyRegistered",
    "UnknownLanguage",
    "get_language",
    "list_languages",
    "list_profiles",
    "register_language",
    "reset_for_tests",
    "unregister_language",
]
