"""humanize_zh.llm.anthropic_provider — Official Anthropic provider

Anthropic API does NOT follow OpenAI's chat-completions schema, so it has its
own provider class. For OpenAI-compatible services use OpenAICompatProvider.
"""
from __future__ import annotations

import os
import time
from typing import Any

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


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider.

    Args:
        api_key: ANTHROPIC_API_KEY env var or explicit.
        model: claude-3-5-sonnet-20241022 / claude-3-opus-20240229 / claude-3-haiku-20240307 / ...
        timeout: Default call timeout in seconds.

    Raises:
        LLMConfigError: api_key missing or anthropic package not installed.
    """

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        auth_token: str | None = None,
        model: str = "claude-3-5-sonnet-20241022",
        base_url: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        """
        Args:
            api_key: standard Anthropic ``x-api-key`` (Anthropic SDK default).
                Falls back to ``ANTHROPIC_API_KEY`` env var.
            auth_token: ``Authorization: Bearer ...`` token (used by some
                Anthropic-compatible gateways like MiniMax). Falls back to
                ``ANTHROPIC_AUTH_TOKEN`` env var. Either one is required;
                if both are set, ``auth_token`` wins.
            base_url: optional Anthropic-compatible endpoint. Falls back to
                ``ANTHROPIC_BASE_URL`` env. Set to ``https://api.minimaxi.com/anthropic``
                for MiniMax (China) or ``https://api.minimax.io/anthropic`` (intl).
        """
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise LLMConfigError(
                "anthropic package not installed. Run: pip install 'humanize-zh[anthropic]'"
            ) from e

        auth_token = auth_token or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not auth_token and not api_key:
            raise LLMConfigError(
                "Anthropic credentials missing. Set ANTHROPIC_API_KEY (Anthropic) or "
                "ANTHROPIC_AUTH_TOKEN (MiniMax / proxies). Pass api_key=/auth_token= explicitly."
            )

        base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")
        client_kwargs: dict[str, Any] = {"timeout": timeout}
        if auth_token:
            client_kwargs["auth_token"] = auth_token
        else:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = Anthropic(**client_kwargs)
        self.model = model
        self.base_url = base_url  # for provider_id / debugging
        self.default_timeout = timeout

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> LLMResponse:
        from anthropic import (
            APIConnectionError,
            APIError,
            APITimeoutError,
            AuthenticationError,
            BadRequestError,
            RateLimitError,
        )

        start = time.time()
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
                timeout=timeout or self.default_timeout,
            )
        except AuthenticationError as e:
            raise LLMAuthError(f"Anthropic auth failed: {e}") from e
        except RateLimitError as e:
            raise LLMRateLimitError(f"Anthropic rate limit: {e}") from e
        except APITimeoutError as e:
            raise LLMTimeoutError(f"Anthropic timeout: {e}") from e
        except BadRequestError as e:
            err_msg = str(e).lower()
            if "context" in err_msg or "tokens" in err_msg or "too long" in err_msg:
                raise LLMContextLimitError(f"Anthropic context limit: {e}") from e
            raise LLMProviderError(f"Anthropic bad request: {e}") from e
        except (APIConnectionError, APIError) as e:
            raise LLMProviderError(f"Anthropic API error: {e}") from e

        latency_ms = int((time.time() - start) * 1000)
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        finish_reason = resp.stop_reason

        tokens = None
        if resp.usage:
            tokens = resp.usage.input_tokens + resp.usage.output_tokens

        return LLMResponse(
            text=text,
            provider=self.name,
            model=self.model,
            tokens_used=tokens,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
        )
