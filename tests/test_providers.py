"""Provider unit tests for OpenAIProvider / OpenAICompatProvider / AnthropicProvider.

Strategy
--------
Real SDK calls would require network + credentials, so we monkey-patch the SDK
client class at module level. Each test injects a ``MagicMock`` client whose
``chat.completions.create`` / ``messages.create`` either returns a stub
response or raises a real SDK exception. We verify both:

1. **Constructor** — keyword-arg forwarding (``base_url`` for local relays,
   ``timeout``, ``organization``) and error paths (missing api_key).
2. **complete()** — success path produces a populated ``LLMResponse``; each
   SDK-specific exception lands in the right ``LLMError`` subclass.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from humanize_zh.llm import (
    LLMAuthError,
    LLMConfigError,
    LLMContextLimitError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
)

# ─── Helpers ────────────────────────────────────────────────────────────────


def _httpx_request() -> httpx.Request:
    return httpx.Request("POST", "https://example.test/v1/chat/completions")


def _httpx_response(status: int = 400) -> httpx.Response:
    return httpx.Response(status_code=status, request=_httpx_request())


def _stub_openai_completion(text: str = "polished output", total_tokens: int = 42) -> Any:
    """Mock the openai chat.completions.create return shape."""
    choice = MagicMock()
    choice.message.content = text
    choice.finish_reason = "stop"
    usage = MagicMock()
    usage.total_tokens = total_tokens
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _stub_anthropic_message(text: str = "claude output", in_tok: int = 10, out_tok: int = 32) -> Any:
    """Mock anthropic messages.create return shape (content blocks)."""
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "end_turn"
    resp.usage.input_tokens = in_tok
    resp.usage.output_tokens = out_tok
    return resp


@pytest.fixture
def patched_openai_client(monkeypatch: pytest.MonkeyPatch):
    """Replace ``openai.OpenAI`` with a factory returning a configurable mock client.

    Returns a (mock_client, captured_kwargs) tuple. Tests adjust
    ``mock_client.chat.completions.create.side_effect`` / ``return_value`` to
    shape the call behavior, and inspect ``captured_kwargs`` to verify
    constructor wiring (e.g. ``base_url`` for local relays).
    """
    import openai

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _stub_openai_completion()
    captured: dict[str, Any] = {}

    def _factory(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return mock_client

    monkeypatch.setattr(openai, "OpenAI", _factory)
    return mock_client, captured


@pytest.fixture
def patched_anthropic_client(monkeypatch: pytest.MonkeyPatch):
    """Replace ``anthropic.Anthropic`` with a factory returning a mock client."""
    import anthropic

    mock_client = MagicMock()
    mock_client.messages.create.return_value = _stub_anthropic_message()
    captured: dict[str, Any] = {}

    def _factory(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return mock_client

    monkeypatch.setattr(anthropic, "Anthropic", _factory)
    return mock_client, captured


# ─── OpenAIProvider ─────────────────────────────────────────────────────────


class TestOpenAIProvider:
    def test_missing_api_key_raises_config_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from humanize_zh.llm.openai_provider import OpenAIProvider

        with pytest.raises(LLMConfigError, match="api_key"):
            OpenAIProvider()

    def test_constructor_forwards_base_url_for_local_relay(
        self, patched_openai_client: tuple[Any, dict[str, Any]],
    ) -> None:
        """base_url must reach the SDK so users can route through local proxies."""
        from humanize_zh.llm.openai_provider import OpenAIProvider

        _, captured = patched_openai_client
        OpenAIProvider(
            api_key="sk-local",
            base_url="http://127.0.0.1:8080/v1",
            model="gpt-4o-mini",
            timeout=15.0,
            organization="org-xyz",
        )
        assert captured["api_key"] == "sk-local"
        assert captured["base_url"] == "http://127.0.0.1:8080/v1"
        assert captured["organization"] == "org-xyz"
        assert captured["timeout"] == 15.0

    def test_complete_success_returns_llm_response(
        self, patched_openai_client: tuple[Any, dict[str, Any]],
    ) -> None:
        from humanize_zh.llm.openai_provider import OpenAIProvider

        mock_client, _ = patched_openai_client
        provider = OpenAIProvider(api_key="sk-x", model="gpt-4o-mini")

        resp = provider.complete("hello", max_tokens=128, temperature=0.2)

        assert isinstance(resp, LLMResponse)
        assert resp.text == "polished output"
        assert resp.provider == "openai"
        assert resp.model == "gpt-4o-mini"
        assert resp.tokens_used == 42
        assert resp.finish_reason == "stop"
        assert resp.latency_ms is not None and resp.latency_ms >= 0
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 128
        assert call_kwargs["temperature"] == 0.2
        assert call_kwargs["messages"] == [{"role": "user", "content": "hello"}]

    def test_auth_error_maps_to_llm_auth_error(
        self, patched_openai_client: tuple[Any, dict[str, Any]],
    ) -> None:
        import openai

        from humanize_zh.llm.openai_provider import OpenAIProvider

        mock_client, _ = patched_openai_client
        mock_client.chat.completions.create.side_effect = openai.AuthenticationError(
            "bad key", response=_httpx_response(401), body=None,
        )
        provider = OpenAIProvider(api_key="sk-bad")
        with pytest.raises(LLMAuthError, match="auth failed"):
            provider.complete("x")

    def test_rate_limit_error_maps_and_extracts_retry_after(
        self, patched_openai_client: tuple[Any, dict[str, Any]],
    ) -> None:
        import openai

        from humanize_zh.llm.openai_provider import OpenAIProvider

        mock_client, _ = patched_openai_client
        response = _httpx_response(429)
        response.headers["retry-after"] = "7.5"
        mock_client.chat.completions.create.side_effect = openai.RateLimitError(
            "rate limit hit", response=response, body=None,
        )
        provider = OpenAIProvider(api_key="sk-x")
        with pytest.raises(LLMRateLimitError) as exc_info:
            provider.complete("x")
        assert exc_info.value.retry_after_seconds == pytest.approx(7.5)

    def test_timeout_error_maps_to_llm_timeout_error(
        self, patched_openai_client: tuple[Any, dict[str, Any]],
    ) -> None:
        import openai

        from humanize_zh.llm.openai_provider import OpenAIProvider

        mock_client, _ = patched_openai_client
        mock_client.chat.completions.create.side_effect = openai.APITimeoutError(
            request=_httpx_request(),
        )
        provider = OpenAIProvider(api_key="sk-x")
        with pytest.raises(LLMTimeoutError):
            provider.complete("x")

    def test_context_limit_error_detected_in_bad_request_message(
        self, patched_openai_client: tuple[Any, dict[str, Any]],
    ) -> None:
        import openai

        from humanize_zh.llm.openai_provider import OpenAIProvider

        mock_client, _ = patched_openai_client
        mock_client.chat.completions.create.side_effect = openai.BadRequestError(
            "maximum context length is 8192 tokens",
            response=_httpx_response(400),
            body=None,
        )
        provider = OpenAIProvider(api_key="sk-x")
        with pytest.raises(LLMContextLimitError):
            provider.complete("x")

    def test_non_context_bad_request_maps_to_provider_error(
        self, patched_openai_client: tuple[Any, dict[str, Any]],
    ) -> None:
        import openai

        from humanize_zh.llm.openai_provider import OpenAIProvider

        mock_client, _ = patched_openai_client
        mock_client.chat.completions.create.side_effect = openai.BadRequestError(
            "invalid model id", response=_httpx_response(400), body=None,
        )
        provider = OpenAIProvider(api_key="sk-x")
        with pytest.raises(LLMProviderError, match="bad request"):
            provider.complete("x")

    def test_api_connection_error_maps_to_provider_error(
        self, patched_openai_client: tuple[Any, dict[str, Any]],
    ) -> None:
        import openai

        from humanize_zh.llm.openai_provider import OpenAIProvider

        mock_client, _ = patched_openai_client
        mock_client.chat.completions.create.side_effect = openai.APIConnectionError(
            request=_httpx_request(),
        )
        provider = OpenAIProvider(api_key="sk-x")
        with pytest.raises(LLMProviderError):
            provider.complete("x")


# ─── OpenAICompatProvider ──────────────────────────────────────────────────


class TestOpenAICompatProvider:
    def test_missing_fields_raise_config_error(
        self, patched_openai_client: tuple[Any, dict[str, Any]],
    ) -> None:
        from humanize_zh.llm.openai_compat import OpenAICompatProvider

        with pytest.raises(LLMConfigError, match="name"):
            OpenAICompatProvider(name="", base_url="https://x", api_key="k", model="m")
        with pytest.raises(LLMConfigError, match="api_key"):
            OpenAICompatProvider(name="x", base_url="https://x", api_key="", model="m")
        with pytest.raises(LLMConfigError, match="base_url"):
            OpenAICompatProvider(name="x", base_url="", api_key="k", model="m")
        with pytest.raises(LLMConfigError, match="model"):
            OpenAICompatProvider(name="x", base_url="https://x", api_key="k", model="")

    def test_constructor_forwards_local_relay_settings(
        self, patched_openai_client: tuple[Any, dict[str, Any]],
    ) -> None:
        """Local proxy users typically wire compat → http://localhost/v1 + relay key."""
        from humanize_zh.llm.openai_compat import OpenAICompatProvider

        _, captured = patched_openai_client
        provider = OpenAICompatProvider(
            name="local-relay",
            base_url="http://127.0.0.1:11434/v1",
            api_key="ollama",
            model="qwen2.5:7b",
            timeout=30.0,
        )
        assert captured["base_url"] == "http://127.0.0.1:11434/v1"
        assert captured["api_key"] == "ollama"
        assert captured["timeout"] == 30.0
        assert provider.name == "local-relay"
        assert provider.model == "qwen2.5:7b"

    def test_complete_returns_response_with_custom_name(
        self, patched_openai_client: tuple[Any, dict[str, Any]],
    ) -> None:
        from humanize_zh.llm.openai_compat import OpenAICompatProvider

        provider = OpenAICompatProvider(
            name="deepseek", base_url="https://api.deepseek.com",
            api_key="sk-deep", model="deepseek-chat",
        )
        resp = provider.complete("ping")
        assert resp.text == "polished output"
        assert resp.provider == "deepseek"
        assert resp.model == "deepseek-chat"

    def test_auth_error_surfaces_provider_name(
        self, patched_openai_client: tuple[Any, dict[str, Any]],
    ) -> None:
        import openai

        from humanize_zh.llm.openai_compat import OpenAICompatProvider

        mock_client, _ = patched_openai_client
        mock_client.chat.completions.create.side_effect = openai.AuthenticationError(
            "bad", response=_httpx_response(401), body=None,
        )
        provider = OpenAICompatProvider(
            name="groq", base_url="https://api.groq.com/openai/v1",
            api_key="bad", model="llama-3.3-70b",
        )
        with pytest.raises(LLMAuthError, match="groq auth failed"):
            provider.complete("x")

    def test_context_limit_in_bad_request(
        self, patched_openai_client: tuple[Any, dict[str, Any]],
    ) -> None:
        import openai

        from humanize_zh.llm.openai_compat import OpenAICompatProvider

        mock_client, _ = patched_openai_client
        mock_client.chat.completions.create.side_effect = openai.BadRequestError(
            "prompt is too long for the model",
            response=_httpx_response(400), body=None,
        )
        provider = OpenAICompatProvider(
            name="deepseek", base_url="https://api.deepseek.com",
            api_key="k", model="deepseek-chat",
        )
        with pytest.raises(LLMContextLimitError, match="deepseek context limit"):
            provider.complete("x")

    def test_repr_includes_base_url(self, patched_openai_client) -> None:
        from humanize_zh.llm.openai_compat import OpenAICompatProvider

        provider = OpenAICompatProvider(
            name="lm-studio", base_url="http://localhost:1234/v1",
            api_key="lm", model="qwen2.5-7b-instruct",
        )
        rep = repr(provider)
        assert "lm-studio" in rep
        assert "http://localhost:1234/v1" in rep


# ─── AnthropicProvider ─────────────────────────────────────────────────────


class TestAnthropicProvider:
    def test_missing_credentials_raise_config_error(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        from humanize_zh.llm.anthropic_provider import AnthropicProvider

        with pytest.raises(LLMConfigError, match="credentials"):
            AnthropicProvider()

    def test_api_key_only_passes_api_key_to_sdk(
        self, patched_anthropic_client: tuple[Any, dict[str, Any]],
    ) -> None:
        from humanize_zh.llm.anthropic_provider import AnthropicProvider

        _, captured = patched_anthropic_client
        AnthropicProvider(api_key="sk-anthropic", model="claude-3-5-sonnet-20241022")
        assert captured["api_key"] == "sk-anthropic"
        assert "auth_token" not in captured
        assert "base_url" not in captured

    def test_auth_token_wins_over_api_key_for_minimax_gateway(
        self, patched_anthropic_client: tuple[Any, dict[str, Any]],
    ) -> None:
        """MiniMax / proxies use Bearer auth — auth_token must replace api_key."""
        from humanize_zh.llm.anthropic_provider import AnthropicProvider

        _, captured = patched_anthropic_client
        AnthropicProvider(
            api_key="sk-anthropic",
            auth_token="bearer-token",
            base_url="https://api.minimaxi.com/anthropic",
            model="MiniMax-M1",
        )
        assert captured["auth_token"] == "bearer-token"
        assert "api_key" not in captured, "auth_token must replace api_key, not co-exist"
        assert captured["base_url"] == "https://api.minimaxi.com/anthropic"

    def test_base_url_reads_from_env(
        self,
        patched_anthropic_client: tuple[Any, dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from humanize_zh.llm.anthropic_provider import AnthropicProvider

        _, captured = patched_anthropic_client
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://relay.local/anthropic")
        AnthropicProvider(api_key="sk-x", model="claude-3-5-sonnet-20241022")
        assert captured["base_url"] == "https://relay.local/anthropic"

    def test_complete_success_aggregates_content_blocks(
        self, patched_anthropic_client: tuple[Any, dict[str, Any]],
    ) -> None:
        from humanize_zh.llm.anthropic_provider import AnthropicProvider

        mock_client, _ = patched_anthropic_client
        # Multi-block response: provider must concatenate .text from all blocks.
        block_a = MagicMock()
        block_a.text = "hello "
        block_b = MagicMock()
        block_b.text = "world"
        resp_obj = MagicMock()
        resp_obj.content = [block_a, block_b]
        resp_obj.stop_reason = "end_turn"
        resp_obj.usage.input_tokens = 5
        resp_obj.usage.output_tokens = 9
        mock_client.messages.create.return_value = resp_obj

        provider = AnthropicProvider(api_key="sk-x", model="claude-3-haiku-20240307")
        resp = provider.complete("ping")
        assert resp.text == "hello world"
        assert resp.provider == "anthropic"
        assert resp.model == "claude-3-haiku-20240307"
        assert resp.tokens_used == 14
        assert resp.finish_reason == "end_turn"

    def test_auth_error_maps(
        self, patched_anthropic_client: tuple[Any, dict[str, Any]],
    ) -> None:
        import anthropic

        from humanize_zh.llm.anthropic_provider import AnthropicProvider

        mock_client, _ = patched_anthropic_client
        mock_client.messages.create.side_effect = anthropic.AuthenticationError(
            "bad token", response=_httpx_response(401), body=None,
        )
        provider = AnthropicProvider(api_key="sk-x")
        with pytest.raises(LLMAuthError, match="Anthropic auth failed"):
            provider.complete("x")

    def test_rate_limit_error_maps(
        self, patched_anthropic_client: tuple[Any, dict[str, Any]],
    ) -> None:
        import anthropic

        from humanize_zh.llm.anthropic_provider import AnthropicProvider

        mock_client, _ = patched_anthropic_client
        mock_client.messages.create.side_effect = anthropic.RateLimitError(
            "rate limited", response=_httpx_response(429), body=None,
        )
        provider = AnthropicProvider(api_key="sk-x")
        with pytest.raises(LLMRateLimitError):
            provider.complete("x")

    def test_timeout_error_maps(
        self, patched_anthropic_client: tuple[Any, dict[str, Any]],
    ) -> None:
        import anthropic

        from humanize_zh.llm.anthropic_provider import AnthropicProvider

        mock_client, _ = patched_anthropic_client
        mock_client.messages.create.side_effect = anthropic.APITimeoutError(
            request=_httpx_request(),
        )
        provider = AnthropicProvider(api_key="sk-x")
        with pytest.raises(LLMTimeoutError):
            provider.complete("x")

    def test_context_limit_inferred_from_bad_request(
        self, patched_anthropic_client: tuple[Any, dict[str, Any]],
    ) -> None:
        import anthropic

        from humanize_zh.llm.anthropic_provider import AnthropicProvider

        mock_client, _ = patched_anthropic_client
        mock_client.messages.create.side_effect = anthropic.BadRequestError(
            "prompt is too long, exceeds 200k tokens",
            response=_httpx_response(400), body=None,
        )
        provider = AnthropicProvider(api_key="sk-x")
        with pytest.raises(LLMContextLimitError):
            provider.complete("x")

    def test_non_context_bad_request_maps_to_provider_error(
        self, patched_anthropic_client: tuple[Any, dict[str, Any]],
    ) -> None:
        import anthropic

        from humanize_zh.llm.anthropic_provider import AnthropicProvider

        mock_client, _ = patched_anthropic_client
        mock_client.messages.create.side_effect = anthropic.BadRequestError(
            "invalid model id", response=_httpx_response(400), body=None,
        )
        provider = AnthropicProvider(api_key="sk-x")
        with pytest.raises(LLMProviderError, match="bad request"):
            provider.complete("x")


# ─── resolve_provider integration ──────────────────────────────────────────


class TestResolveProvider:
    """Ensures the shared resolver actually picks up env-derived providers."""

    def test_str_openai_routes_to_openai_provider(
        self,
        patched_openai_client: tuple[Any, dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from humanize_zh.llm import resolve_provider
        from humanize_zh.llm.openai_provider import OpenAIProvider

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
        p = resolve_provider("openai")
        assert isinstance(p, OpenAIProvider)
        assert p.model == "gpt-4o-mini"

    def test_str_anthropic_auth_token_routes_through(
        self,
        patched_anthropic_client: tuple[Any, dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from humanize_zh.llm import resolve_provider
        from humanize_zh.llm.anthropic_provider import AnthropicProvider

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "bearer-x")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic")
        monkeypatch.setenv("ANTHROPIC_MODEL", "MiniMax-M1")
        p = resolve_provider("anthropic")
        assert isinstance(p, AnthropicProvider)
        assert p.model == "MiniMax-M1"
        assert p.base_url == "https://api.minimaxi.com/anthropic"

    def test_str_deepseek_routes_to_compat(
        self,
        patched_openai_client: tuple[Any, dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Previously broken in iterative.py — non-builtin str now resolves via autodetect."""
        from humanize_zh.llm import resolve_provider
        from humanize_zh.llm.openai_compat import OpenAICompatProvider

        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deep")
        p = resolve_provider("deepseek")
        assert isinstance(p, OpenAICompatProvider)
        assert p.name == "deepseek"
