"""humanize_zh.llm.openai_provider — Official OpenAI provider"""
from __future__ import annotations

import os
import time

from .base import (
    LLMAuthError,
    LLMConfigError,
    LLMContextLimitError,
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
)


class OpenAIProvider(LLMProvider):
    """Official OpenAI API provider.

    Args:
        api_key: OpenAI api key. Reads OPENAI_API_KEY env var if not given.
        model: Default model (gpt-4o, gpt-4o-mini, gpt-4-turbo, ...).
        base_url: Custom OpenAI base url. Defaults to api.openai.com. For non-OpenAI
                  endpoints prefer OpenAICompatProvider.
        timeout: Default call timeout in seconds.
        organization: Optional OpenAI org ID.

    Raises:
        LLMConfigError: api_key missing or openai package not installed.
    """

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
        timeout: float = 120.0,
        organization: str | None = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise LLMConfigError(
                "openai package not installed. Run: pip install 'humanize-zh[openai]'"
            ) from e

        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise LLMConfigError(
                "OpenAI api_key not provided. Pass api_key= or set OPENAI_API_KEY env var."
            )

        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            organization=organization,
            timeout=timeout,
        )
        self.model = model
        self.default_timeout = timeout

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> LLMResponse:
        from openai import (
            APIConnectionError,
            APIError,
            APITimeoutError,
            AuthenticationError,
            BadRequestError,
            RateLimitError,
        )

        start = time.time()
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout or self.default_timeout,
            )
        except AuthenticationError as e:
            raise LLMAuthError(f"OpenAI auth failed: {e}") from e
        except RateLimitError as e:
            retry_after = None
            response = getattr(e, "response", None)
            if response is not None and hasattr(response, "headers"):
                hdr = response.headers.get("retry-after")
                try:
                    retry_after = float(hdr) if hdr else None
                except (TypeError, ValueError):
                    retry_after = None
            raise LLMRateLimitError(f"OpenAI rate limit: {e}", retry_after_seconds=retry_after) from e
        except APITimeoutError as e:
            raise LLMTimeoutError(f"OpenAI timeout: {e}") from e
        except BadRequestError as e:
            err_msg = str(e).lower()
            if "context" in err_msg or "tokens" in err_msg:
                raise LLMContextLimitError(f"OpenAI context limit: {e}") from e
            raise LLMProviderError(f"OpenAI bad request: {e}") from e
        except (APIConnectionError, APIError) as e:
            raise LLMProviderError(f"OpenAI API error: {e}") from e

        latency_ms = int((time.time() - start) * 1000)
        text = resp.choices[0].message.content or ""
        finish_reason = resp.choices[0].finish_reason

        return LLMResponse(
            text=text,
            provider=self.name,
            model=self.model,
            tokens_used=resp.usage.total_tokens if resp.usage else None,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
        )
