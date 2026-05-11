"""humanize_zh.llm.registry — global active provider + autodetect

Holds the process-wide active :class:`LLMProvider`. Polish/judge layers call
:func:`get_active` to obtain the provider; user code calls :func:`set_active`,
:func:`use`, :func:`use_openai_compat`, :func:`use_callable`, or
:func:`autodetect` to configure it.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from .base import LLMNotConfiguredError, LLMProvider

logger = logging.getLogger(__name__)


# The active provider is process-wide mutable state. FastAPI sync routes run
# in a threadpool, so concurrent first-request handlers can race on
# autodetect(). The lock is **re-entrant** because :func:`autodetect` calls
# :func:`set_active` while already holding it.
_ACTIVE: LLMProvider | None = None
_ACTIVE_LOCK = threading.RLock()


def set_active(provider: LLMProvider) -> LLMProvider:
    """Set the process-wide active provider (thread-safe)."""
    global _ACTIVE
    with _ACTIVE_LOCK:
        _ACTIVE = provider
        logger.info("[humanize_zh.llm] active provider: %r", provider)
        return provider


def get_active() -> LLMProvider:
    """Return the active provider. Raises LLMNotConfiguredError if none.

    Read is locked for visibility — a concurrent writer in another thread
    could otherwise return a stale ``None`` snapshot to a reader that just
    saw ``has_active() == True``.
    """
    with _ACTIVE_LOCK:
        if _ACTIVE is None:
            raise LLMNotConfiguredError()
        return _ACTIVE


def has_active() -> bool:
    """Return True if a provider is configured (non-throwing variant of ``get_active``)."""
    with _ACTIVE_LOCK:
        return _ACTIVE is not None


def clear() -> None:
    """Clear the active provider (mainly for tests)."""
    global _ACTIVE
    with _ACTIVE_LOCK:
        _ACTIVE = None


# ─── Autodetect ────────────────────────────────────────────────────────────
#
# Detection priority by env var (default chain):
#
#   OPENAI_API_KEY     -> OpenAIProvider
#   ANTHROPIC_API_KEY  -> AnthropicProvider
#   DEEPSEEK_API_KEY   -> OpenAICompatProvider(name="deepseek")
#   GROQ_API_KEY       -> OpenAICompatProvider(name="groq")
#   OPENROUTER_API_KEY -> OpenAICompatProvider(name="openrouter")
#   MOONSHOT_API_KEY   -> OpenAICompatProvider(name="moonshot")
#   GLM_API_KEY        -> OpenAICompatProvider(name="glm")
#   DASHSCOPE_API_KEY  -> OpenAICompatProvider(name="qwen")
#   OLLAMA_BASE_URL    -> OpenAICompatProvider(name="ollama")  (no key)


_OPENAI_COMPAT_TABLE: dict[str, dict] = {
    "deepseek": {
        "env_key": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "model_env": "DEEPSEEK_MODEL",
    },
    "groq": {
        "env_key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "model_env": "GROQ_MODEL",
    },
    "openrouter": {
        "env_key": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "anthropic/claude-3.5-sonnet",
        "model_env": "OPENROUTER_MODEL",
    },
    "moonshot": {
        "env_key": "MOONSHOT_API_KEY",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-32k",
        "model_env": "MOONSHOT_MODEL",
    },
    "glm": {
        "env_key": "GLM_API_KEY",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-plus",
        "model_env": "GLM_MODEL",
    },
    "qwen": {
        "env_key": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-max",
        "model_env": "QWEN_MODEL",
    },
    "ollama": {
        "env_key": None,  # Ollama needs no key
        "base_url": None,  # read from OLLAMA_BASE_URL
        "default_model": "qwen2.5:7b",
        "model_env": "OLLAMA_MODEL",
    },
}


_DEFAULT_DETECT_ORDER = [
    "openai",
    "anthropic",
    "deepseek",
    "groq",
    "openrouter",
    "moonshot",
    "glm",
    "qwen",
    "ollama",
]


# ─── Public provider catalogue (consumed by CLI / Web layers) ───────────────
#
# Returns the canonical list of provider names + env-var keys + availability.
# CLI and Web layers consume this so they don't drift from the registry.
# Adding a new provider only requires touching ``_OPENAI_COMPAT_TABLE`` above.

_BUILTIN_ENV_KEYS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def list_providers() -> list[dict[str, Any]]:
    """Return the catalogue of supported providers with availability flags.

    Each entry has:

        - ``name`` (str): provider id, e.g. ``"deepseek"``.
        - ``env`` (str): primary env-var key, e.g. ``"DEEPSEEK_API_KEY"``;
          ``"OLLAMA_BASE_URL"`` for the keyless Ollama case.
        - ``available`` (bool): whether the env var is set in the current
          process. For ``"anthropic"`` either ``ANTHROPIC_API_KEY`` or
          ``ANTHROPIC_AUTH_TOKEN`` counts as available (Anthropic SDK +
          MiniMax-style Bearer gateways).

    The ordering matches :data:`_DEFAULT_DETECT_ORDER` (the autodetect chain).
    """
    rows: list[dict[str, Any]] = []
    for name in _DEFAULT_DETECT_ORDER:
        env_key = _env_key_for(name)
        if name == "anthropic":
            available = bool(
                os.environ.get(env_key) or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            )
        else:
            available = bool(os.environ.get(env_key))
        rows.append({"name": name, "env": env_key, "available": available})
    return rows


def _env_key_for(name: str) -> str:
    """Return the primary env-var key for a provider name."""
    if name in _BUILTIN_ENV_KEYS:
        return _BUILTIN_ENV_KEYS[name]
    if name == "ollama":
        return "OLLAMA_BASE_URL"
    spec = _OPENAI_COMPAT_TABLE.get(name)
    if spec is None:
        raise KeyError(f"unknown provider name: {name!r}")
    env_key = spec["env_key"]
    if not isinstance(env_key, str):  # defensive — spec rows always carry a str env_key
        raise TypeError(f"{name!r} env_key spec is not a string: {env_key!r}")
    return env_key


def required_env_keys_hint() -> str:
    """Comma-separated list of env keys, useful for error messages."""
    return " / ".join(_env_key_for(n) for n in _DEFAULT_DETECT_ORDER)


def autodetect(*, prefer: list[str] | None = None) -> LLMProvider | None:
    """Auto-detect a provider from environment variables.

    Args:
        prefer: Custom detection order (provider name list). Falls back to the
                default chain if not given.

    Returns:
        Active provider, or ``None`` if no env vars are set.

    Thread safety: the detect-then-set chain runs under :data:`_ACTIVE_LOCK`
    (re-entrant) so concurrent first-request handlers in a FastAPI threadpool
    cannot interleave provider construction with state mutation.
    """
    chain = prefer or _DEFAULT_DETECT_ORDER
    with _ACTIVE_LOCK:
        for name in chain:
            try:
                provider = _try_provider_from_env(name)
                if provider is not None:
                    return set_active(provider)
            except Exception as e:
                logger.warning("[humanize_zh.llm] autodetect %s failed: %s", name, e)
                continue
        return None


def _try_provider_from_env(name: str) -> LLMProvider | None:
    """Build a provider from env vars if applicable. Returns None to skip."""
    if name == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            return None
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        )

    if name == "anthropic":
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            return None
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),  # MiniMax / proxy support
        )

    spec = _OPENAI_COMPAT_TABLE.get(name)
    if spec is None:
        return None

    if name == "ollama":
        base_url = os.environ.get("OLLAMA_BASE_URL")
        if not base_url:
            return None
        from .openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            name="ollama",
            base_url=base_url.rstrip("/") + ("/v1" if not base_url.endswith("/v1") else ""),
            api_key="ollama",
            model=os.environ.get(spec["model_env"], spec["default_model"]),
        )

    api_key = os.environ.get(spec["env_key"])
    if not api_key:
        return None

    from .openai_compat import OpenAICompatProvider

    return OpenAICompatProvider(
        name=name,
        base_url=spec["base_url"],
        api_key=api_key,
        model=os.environ.get(spec["model_env"], spec["default_model"]),
    )
