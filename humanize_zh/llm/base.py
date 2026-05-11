"""humanize_zh.llm.base — LLM provider 抽象基类与异常体系

This is the unified internal interface for all LLM calls in humanize-zh.
Every provider (OpenAI / Anthropic / OpenAI-Compat / Custom) implements LLMProvider.

Core design:
    - Synchronous complete() returns LLMResponse (text + metadata)
    - Exception tree covers common LLM call failures (auth/rate/timeout/context)
    - Optional streaming interface (V0.2)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """LLM completion response with metadata.

    Attributes:
        text: The completion text.
        provider: Provider identifier (e.g. "openai", "deepseek").
        model: Model used (e.g. "gpt-4o", "claude-3-5-sonnet").
        tokens_used: Total tokens (prompt + completion). None if unknown.
        latency_ms: Request latency in milliseconds.
        finish_reason: Provider-specific finish reason (stop/length/content_filter/...).
    """
    text: str
    provider: str
    model: str
    tokens_used: int | None = None
    latency_ms: int | None = None
    finish_reason: str | None = None

    def __bool__(self) -> bool:
        return bool(self.text and self.text.strip())


# ─── Exception tree ────────────────────────────────────────────────────────

class LLMError(Exception):
    """Base class for all LLM-related errors."""


class LLMConfigError(LLMError):
    """Provider configuration error (missing api_key, invalid model, ...)."""


class LLMAuthError(LLMError):
    """Provider authentication failed (invalid api_key)."""


class LLMRateLimitError(LLMError):
    """Provider rate limit hit."""

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class LLMTimeoutError(LLMError):
    """Provider call timed out."""


class LLMContextLimitError(LLMError):
    """Prompt exceeded provider's context window."""


class LLMProviderError(LLMError):
    """Provider internal error (5xx, network drop, ...)."""


class LLMNotConfiguredError(LLMError):
    """No active LLM provider, but code attempted an LLM call."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or (
                "No LLM provider configured. Use one of:\n"
                "  llm.use('openai', api_key='sk-...')\n"
                "  llm.use_openai_compat(name='deepseek', base_url='...', api_key='...', model='deepseek-chat')\n"
                "  llm.use_callable(my_func)\n"
                "  llm.autodetect()  # auto-detect from env vars"
            )
        )


# ─── LLMProvider ABC ───────────────────────────────────────────────────────

class LLMProvider(ABC):
    """Abstract base for all providers.

    Subclasses must set ``name`` (provider identifier) and implement ``complete``.
    """

    name: str

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> LLMResponse:
        """Synchronously call LLM. Failure raises an LLMError subclass."""
        ...

    def complete_stream(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> Iterator[str]:
        """Streaming call. Default implementation falls back to complete()."""
        resp = self.complete(prompt, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
        yield resp.text

    def is_available(self) -> bool:
        """Whether the provider is reachable and configured. Override in subclasses."""
        return True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
