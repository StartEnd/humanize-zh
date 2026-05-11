"""humanize_zh.llm._resolve — shared provider-argument resolver

Three call-sites (``postprocess`` / ``judge`` / ``iterative``) used to carry
their own near-identical copy of the ``provider: LLMProvider | str | None``
normalization. Subtle drift built up:

- ``iterative._resolve`` routed string names through ``llm.use(name)`` which
  only knows ``"openai"`` and ``"anthropic"`` — so ``iterative_polish(
  writer_provider="deepseek")`` crashed with ``ValueError`` even when
  ``DEEPSEEK_API_KEY`` was set in env.
- ``postprocess`` auto-ran ``autodetect()`` when no provider was active;
  ``judge`` did not, which means CLI workflows that only configured a
  ``judge_provider=`` argument needed extra ceremony.

This module centralizes the logic so all three layers share a single,
tested implementation.
"""
from __future__ import annotations

import os

from .base import LLMProvider

ProviderArg = LLMProvider | str | None


def resolve_provider(
    provider: ProviderArg,
    *,
    autodetect_on_none: bool = False,
) -> LLMProvider:
    """Normalize a ``provider`` argument into an :class:`LLMProvider` instance.

    Args:
        provider: One of:
            - ``LLMProvider`` instance — returned as-is.
            - ``str`` — interpreted as a provider name. ``"openai"`` and
              ``"anthropic"`` are built from their env vars directly; any
              other name (``"deepseek"``, ``"groq"``, ``"qwen"``, …) is
              looked up via :func:`registry.autodetect` with ``prefer=[name]``.
            - ``None`` — return the currently active provider.
        autodetect_on_none: When ``provider`` is ``None`` and no provider is
            active yet, run :func:`autodetect` once before reading the
            active slot. Matches the ``postprocess`` zero-config behaviour.

    Raises:
        LLMNotConfiguredError: ``provider`` is ``None`` and no provider is or
            can be configured.
        ValueError: ``provider`` is a string that cannot be built from the
            current environment.
        TypeError: ``provider`` is of an unsupported type.
    """
    from . import registry  # local import: avoid a cycle at module load.

    if isinstance(provider, LLMProvider):
        return provider

    if provider is None:
        if autodetect_on_none and not registry.has_active():
            registry.autodetect()
        return registry.get_active()

    if isinstance(provider, str):
        if provider == "openai" and os.environ.get("OPENAI_API_KEY"):
            from .openai_provider import OpenAIProvider

            return OpenAIProvider(model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))

        if provider == "anthropic" and (
            os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        ):
            from .anthropic_provider import AnthropicProvider

            return AnthropicProvider(
                model=os.environ.get(
                    "ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"
                ),
                base_url=os.environ.get("ANTHROPIC_BASE_URL"),
            )

        detected = registry.autodetect(prefer=[provider])
        if detected is not None:
            return detected
        raise ValueError(
            f"provider={provider!r} cannot be resolved from env vars. "
            f"Use llm.use_openai_compat(...) or pass an LLMProvider instance."
        )

    raise TypeError(
        f"provider must be None | str | LLMProvider, got {type(provider).__name__}"
    )


def provider_id(provider: LLMProvider | None) -> str | None:
    """Return a stable identity string for a provider, or ``None`` if absent.

    Format: ``"<name>::<model>"``. The double-colon separator is intentional —
    Ollama model identifiers contain a single colon (``qwen2.5:7b``), so a
    single-colon separator would make the id ambiguous to split. The
    collusion-detection code in :mod:`humanize_zh.judge` and
    :mod:`humanize_zh.iterative` compares this string verbatim, so both layers
    must agree on the format — that is the whole point of centralizing it here.

    Args:
        provider: Provider instance or ``None``.

    Returns:
        ``"openai::gpt-4o-mini"`` / ``"ollama::qwen2.5:7b"`` / ``None``.
    """
    if provider is None:
        return None
    return f"{provider.name}::{getattr(provider, 'model', '?')}"


__all__ = ["resolve_provider", "provider_id", "ProviderArg"]
