"""Phase 3: postprocess_humanize — zh full pipeline + en LLM-only mode."""
from __future__ import annotations

import pytest

from humanize_zh import llm, postprocess_humanize


def test_zh_unconfigured_falls_back_to_cleanup(ai_article_zh: str) -> None:
    """Without a provider, ZH mode should return a deterministically cleaned version."""
    polished, after, before = postprocess_humanize(
        ai_article_zh, scene="analysis", lang="zh"
    )
    assert polished is not None
    assert before is not None, "ZH mode should compute before score"
    assert after is not None, "ZH fallback still scores the cleaned output"
    # cleanup alone should still reduce AI probability
    assert after.total <= before.total


def test_zh_with_callable_provider_polishes(ai_article_zh, fake_polish_fn) -> None:
    llm.use_callable(fake_polish_fn, name="fake-polish", model="v1")
    polished, after, before = postprocess_humanize(
        ai_article_zh, scene="analysis", lang="zh"
    )
    assert before is not None
    assert after is not None
    # 显著降分 (from 82 down to ~33 in practice)
    assert after.total < before.total - 20, (
        f"expected ≥20 point reduction, got before={before.total} after={after.total}"
    )
    assert polished != ai_article_zh


def test_en_llm_only_polishes(ai_article_en, fake_polish_fn) -> None:
    llm.use_callable(fake_polish_fn, name="fake-en", model="v1")
    polished, after, before = postprocess_humanize(ai_article_en, lang="en")
    # EN mode skips Chinese detection
    assert before is None
    assert after is None
    assert "worth noting" not in polished
    assert "First, " not in polished


def test_en_unconfigured_falls_back(ai_article_en) -> None:
    polished, after, before = postprocess_humanize(ai_article_en, lang="en")
    assert polished  # non-empty
    assert before is None
    assert after is None


def test_invalid_lang_raises(ai_article_zh) -> None:
    with pytest.raises(ValueError, match="lang"):
        postprocess_humanize(ai_article_zh, lang="fr")


def test_zh_detect_first_false_skips_pre_score(ai_article_zh, fake_polish_fn) -> None:
    llm.use_callable(fake_polish_fn, name="fake", model="v1")
    polished, after, before = postprocess_humanize(
        ai_article_zh, detect_first=False
    )
    # detect_first=False: before score skipped, function falls through to before-less branch
    assert before is None
    assert after is not None


def test_provider_as_llmprovider_instance(ai_article_zh, fake_polish_fn) -> None:
    """Passing an LLMProvider instance directly should work without touching the registry."""
    from humanize_zh.llm.callable_provider import CallableProvider

    llm.clear()  # no active provider
    provider = CallableProvider(fake_polish_fn, name="direct", model="v1")
    polished, after, before = postprocess_humanize(
        ai_article_zh, provider=provider
    )
    assert after is not None and after.total < before.total
