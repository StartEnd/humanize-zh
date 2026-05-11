"""Phase 2: LLM provider abstraction tests."""
from __future__ import annotations

import os

import pytest

from humanize_zh import llm
from humanize_zh.llm.base import (
    LLMAuthError,
    LLMConfigError,
    LLMContextLimitError,
    LLMError,
    LLMNotConfiguredError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)


def test_get_active_raises_when_unconfigured() -> None:
    with pytest.raises(LLMNotConfiguredError):
        llm.get_active()


def test_use_callable_returns_provider() -> None:
    p = llm.use_callable(lambda prompt: f"[fake: {len(prompt)} chars]", name="test")
    assert p.name == "test"


def test_callable_complete_returns_llm_response() -> None:
    p = llm.use_callable(lambda prompt: f"[fake: {len(prompt)} chars]", name="test")
    resp = p.complete("hello world")
    assert resp.text == "[fake: 11 chars]"
    assert resp.provider == "test"
    assert resp.latency_ms is not None
    assert resp.latency_ms >= 0


def test_get_active_returns_configured_provider() -> None:
    p = llm.use_callable(lambda x: "x", name="t")
    assert llm.get_active() is p


def test_clear_resets_state() -> None:
    llm.use_callable(lambda x: "x", name="t")
    assert llm.has_active()
    llm.clear()
    assert not llm.has_active()
    with pytest.raises(LLMNotConfiguredError):
        llm.get_active()


def test_autodetect_without_env_returns_none() -> None:
    saved = {
        k: os.environ.pop(k)
        for k in [
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY",
            "OPENROUTER_API_KEY", "MOONSHOT_API_KEY", "GLM_API_KEY", "DASHSCOPE_API_KEY",
            "OLLAMA_BASE_URL",
        ]
        if k in os.environ
    }
    try:
        assert llm.autodetect() is None
    finally:
        os.environ.update(saved)


@pytest.mark.parametrize("exc_cls", [
    LLMConfigError, LLMAuthError, LLMRateLimitError, LLMTimeoutError,
    LLMContextLimitError, LLMProviderError, LLMNotConfiguredError,
])
def test_exception_subclass_of_llm_error(exc_cls: type) -> None:
    assert issubclass(exc_cls, LLMError)


def test_rate_limit_error_retains_retry_after() -> None:
    err = LLMRateLimitError("rate limited", retry_after_seconds=12.0)
    assert err.retry_after_seconds == 12.0


def test_use_unknown_provider_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown builtin provider"):
        llm.use("foobar", api_key="x")


def test_use_callable_propagates_name_and_model() -> None:
    p = llm.use_callable(lambda x: "ok", name="myllm", model="v1")
    assert p.name == "myllm"
    assert p.model == "v1"


def test_callable_exception_wrapped_as_provider_error() -> None:
    def bad(prompt: str) -> str:
        raise RuntimeError("boom")
    p = llm.use_callable(bad, name="bad")
    with pytest.raises(LLMProviderError, match="boom"):
        p.complete("x")


def test_llm_response_fields_propagate() -> None:
    p = llm.use_callable(lambda x: "hi", name="m", model="m1")
    resp = p.complete("prompt")
    assert resp.text == "hi"
    assert resp.provider == "m"
    assert resp.model == "m1"


def test_empty_llm_response_is_falsy() -> None:
    p = llm.use_callable(lambda x: "", name="empty")
    resp = p.complete("x")
    assert not resp  # __bool__ returns False for empty text


def test_set_active_is_thread_safe() -> None:
    """Pass C.2: 50 threads writing different providers must end on one of them.

    Without the lock, ``set_active`` would interleave the assignment with the
    ``logger.info`` read of ``provider`` in another thread, but the bigger risk
    is in :func:`autodetect`: the build-then-set sequence used to be two
    separate operations. This test exercises ``set_active`` directly under
    concurrent pressure; a thread-unsafe implementation would not deterministically
    leave ``get_active()`` returning one of the inputs.
    """
    import threading

    providers = [
        llm.use_callable(lambda _x, n=i: f"r{n}", name=f"p{i}", model="m")
        for i in range(50)
    ]
    # use_callable activates the *last* provider; clear and re-set under threads.
    llm.clear()
    barrier = threading.Barrier(len(providers))

    def _worker(p):
        barrier.wait()
        from humanize_zh.llm import set_active
        set_active(p)

    threads = [threading.Thread(target=_worker, args=(p,)) for p in providers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    active = llm.get_active()
    assert active in providers
