"""humanize_zh.llm.openai_compat — Generic OpenAI-compatible provider

Works with any service that implements the OpenAI Chat Completions API:

    - DeepSeek           (https://api.deepseek.com)
    - Groq               (https://api.groq.com/openai/v1)
    - OpenRouter         (https://openrouter.ai/api/v1)
    - Together AI        (https://api.together.xyz/v1)
    - 智谱 GLM           (https://open.bigmodel.cn/api/paas/v4)
    - Moonshot Kimi      (https://api.moonshot.cn/v1)
    - 阿里 Qwen          (https://dashscope.aliyuncs.com/compatible-mode/v1)
    - 火山引擎豆包       (https://ark.cn-beijing.volces.com/api/v3)
    - Ollama (local)     (http://localhost:11434/v1)
    - vLLM / SGLang / LM Studio self-hosted
    - Azure OpenAI       (https://YOUR.openai.azure.com/openai/deployments/...)

Use this when you have ``base_url + api_key + model``. For the official OpenAI
endpoint use :class:`OpenAIProvider`; for Anthropic use :class:`AnthropicProvider`
(they have different SDKs).
"""
from __future__ import annotations

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


class OpenAICompatProvider(LLMProvider):
    """OpenAI-compatible provider for any third-party endpoint.

    Args:
        name: Identifier you choose (e.g. "deepseek", "groq", "openrouter").
              Surfaces in logs and error messages.
        base_url: API base URL (required).
        api_key: API key (required).
        model: Model name (required).
        timeout: Default request timeout in seconds.

    Raises:
        LLMConfigError: missing required fields or openai package not installed.
    """

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 120.0,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise LLMConfigError(
                "openai package required for OpenAI-compatible providers. "
                "Run: pip install 'humanize-zh[openai]'"
            ) from e

        if not name:
            raise LLMConfigError("name is required")
        if not api_key:
            raise LLMConfigError(f"{name}: api_key is required")
        if not base_url:
            raise LLMConfigError(f"{name}: base_url is required")
        if not model:
            raise LLMConfigError(f"{name}: model is required")

        self.name = name
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self.model = model
        self.base_url = base_url
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
            raise LLMAuthError(f"{self.name} auth failed: {e}") from e
        except RateLimitError as e:
            raise LLMRateLimitError(f"{self.name} rate limit: {e}") from e
        except APITimeoutError as e:
            raise LLMTimeoutError(f"{self.name} timeout: {e}") from e
        except BadRequestError as e:
            err_msg = str(e).lower()
            if "context" in err_msg or "tokens" in err_msg or "too long" in err_msg:
                raise LLMContextLimitError(f"{self.name} context limit: {e}") from e
            raise LLMProviderError(f"{self.name} bad request: {e}") from e
        except (APIConnectionError, APIError) as e:
            raise LLMProviderError(f"{self.name} API error: {e}") from e

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

    def __repr__(self) -> str:
        return (
            f"<OpenAICompatProvider name={self.name!r} "
            f"base_url={self.base_url!r} model={self.model!r}>"
        )
