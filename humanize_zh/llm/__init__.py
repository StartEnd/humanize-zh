"""humanize_zh.llm — pluggable LLM provider layer

Public API (typical usage)::

    from humanize_zh import llm

    # 1. Auto-detect from env vars
    llm.autodetect()

    # 2. Explicit OpenAI
    llm.use("openai", api_key="sk-...", model="gpt-4o")

    # 3. OpenAI-compatible (DeepSeek / Groq / OpenRouter / Ollama / ...)
    llm.use_openai_compat(
        name="deepseek",
        base_url="https://api.deepseek.com",
        api_key="sk-...",
        model="deepseek-chat",
    )

    # 4. Custom callable (any function: (prompt: str) -> str)
    llm.use_callable(my_function, name="custom")

After configuration, downstream layers (``polish``, ``judge``) call
``llm.get_active().complete(prompt)`` internally.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ._resolve import ProviderArg, provider_id, resolve_provider
from .base import (
    LLMAuthError,
    LLMConfigError,
    LLMContextLimitError,
    LLMError,
    LLMNotConfiguredError,
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
)
from .registry import (
    autodetect,
    clear,
    get_active,
    has_active,
    list_providers,
    required_env_keys_hint,
    set_active,
)


def use(provider_name: str, **kwargs: Any) -> LLMProvider:
    """Activate a builtin provider by name.

    Args:
        provider_name: ``"openai"`` or ``"anthropic"``.
        **kwargs: Forwarded to the provider constructor (api_key, model, ...).

    Returns:
        The newly active provider.

    Raises:
        ValueError: provider_name is not a builtin.
    """
    if provider_name == "openai":
        from .openai_provider import OpenAIProvider

        return set_active(OpenAIProvider(**kwargs))
    if provider_name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return set_active(AnthropicProvider(**kwargs))
    raise ValueError(
        f"Unknown builtin provider: {provider_name!r}. "
        f"Available: 'openai' | 'anthropic'. "
        f"For other services use llm.use_openai_compat() or llm.use_callable()."
    )


def use_openai_compat(
    *,
    name: str,
    base_url: str,
    api_key: str,
    model: str,
    timeout: float = 120.0,
) -> LLMProvider:
    """Activate an OpenAI-compatible provider.

    Suitable for: DeepSeek / Groq / OpenRouter / Together / 智谱 GLM / Moonshot /
    Qwen / Ollama / vLLM / LM Studio / Azure OpenAI / etc.

    Args:
        name: Identifier you choose (used in logs / errors).
        base_url: API base URL.
        api_key: API key (use ``"ollama"`` placeholder for Ollama).
        model: Model name.
        timeout: Default request timeout in seconds.
    """
    from .openai_compat import OpenAICompatProvider

    return set_active(
        OpenAICompatProvider(
            name=name,
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
        )
    )


def use_callable(
    fn: Callable[[str], str | None],
    *,
    name: str = "custom",
    model: str = "callable",
) -> LLMProvider:
    """Activate a Python callable as the provider.

    Args:
        fn: ``(prompt: str) -> Optional[str]`` function. ``None`` means failure.
        name: Provider identifier.
        model: Informational model name.
    """
    from .callable_provider import CallableProvider

    return set_active(CallableProvider(fn, name=name, model=model))


__all__ = [
    # Public API functions
    "use",
    "use_openai_compat",
    "use_callable",
    "autodetect",
    "set_active",
    "get_active",
    "has_active",
    "clear",
    "list_providers",
    "required_env_keys_hint",
    "resolve_provider",
    "provider_id",
    # Types
    "LLMProvider",
    "LLMResponse",
    "ProviderArg",
    # Exceptions
    "LLMError",
    "LLMConfigError",
    "LLMAuthError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "LLMContextLimitError",
    "LLMProviderError",
    "LLMNotConfiguredError",
]
