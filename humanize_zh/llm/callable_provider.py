"""humanize_zh.llm.callable_provider — Custom callable provider

Lets the caller plug in any ``(prompt: str) -> str`` function. Useful for:

    - Projects with their own LLM gateway (e.g. site-digester's generate_article)
    - Tests using mock callables
    - Routing through a custom retry/cache layer
    - Bridging to non-OpenAI/Anthropic SDKs (Bedrock, Vertex, etc.)
"""
from __future__ import annotations

import time
from collections.abc import Callable

from .base import LLMProvider, LLMProviderError, LLMResponse


class CallableProvider(LLMProvider):
    """Wrap a Python callable as an LLMProvider.

    Args:
        fn: Callable taking a prompt string and returning the response text
            (or None on failure). Note: max_tokens / temperature / timeout are
            forwarded only as informational; the callable is responsible for
            honoring (or ignoring) them.
        name: Provider identifier.
        model: Model identifier (informational, default ``"callable"``).

    Example:
        >>> def my_llm(prompt: str) -> str:
        ...     return company_internal_api(prompt)
        >>> provider = CallableProvider(my_llm, name="company-llm")
    """

    def __init__(
        self,
        fn: Callable[[str], str | None],
        *,
        name: str = "custom",
        model: str = "callable",
    ) -> None:
        if not callable(fn):
            raise TypeError("fn must be callable")
        self._fn = fn
        self.name = name
        self.model = model

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> LLMResponse:
        del max_tokens, temperature, timeout  # callable decides on its own
        start = time.time()
        try:
            text = self._fn(prompt) or ""
        except Exception as e:
            raise LLMProviderError(f"{self.name} callable raised: {e}") from e
        latency_ms = int((time.time() - start) * 1000)

        return LLMResponse(
            text=text,
            provider=self.name,
            model=self.model,
            latency_ms=latency_ms,
        )
