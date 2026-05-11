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


# ─── Phase 1.9: ReplacementsTable injection ──────────────────────────────


def test_deterministic_cleanup_default_matches_zh_replacements_singleton() -> None:
    """``_deterministic_cleanup(text)`` (default) and
    ``_deterministic_cleanup(text, replacements=zh_replacements)`` must
    return identical strings — proves the injection plumbing does not
    silently change the ZH path's behavior.
    """
    from humanize_zh._lang.zh.replacements import zh_replacements
    from humanize_zh.postprocess import _deterministic_cleanup

    sample = (
        "综上所述, 这个产品赋能了所有用户。\n"
        "首先, 它解决了痛点。其次, 它提供闭环。最后, 它实现了价值。\n"
        "「这段引语里的『综上所述』不应被替换」\n"
    )
    assert _deterministic_cleanup(sample) == _deterministic_cleanup(
        sample, replacements=zh_replacements
    )


def test_deterministic_cleanup_uses_injected_table() -> None:
    """A custom ``ReplacementsTable`` must drive substitutions, not the
    ZH default loader.
    """
    from humanize_zh.postprocess import _deterministic_cleanup

    class _StubTable:
        code = "stub"

        def ordered_pairs(self) -> list[tuple[str, str]]:
            return [("foo", "BAR")]

    out = _deterministic_cleanup("hello foo world", replacements=_StubTable())
    # ZH defaults would not touch "foo", so the stub must be the one
    # producing the substitution.
    assert out == "hello BAR world"


def test_deterministic_cleanup_empty_table_is_passthrough_modulo_backticks() -> None:
    """Phase 3 EN plugin will likely ship an empty initial table; the
    cleanup must still strip number-backticks (a language-agnostic op)
    and leave the remaining text alone.
    """
    from humanize_zh.postprocess import _deterministic_cleanup

    class _EmptyTable:
        code = "stub"

        def ordered_pairs(self) -> list[tuple[str, str]]:
            return []

    text = "result was `42` percent."
    out = _deterministic_cleanup(text, replacements=_EmptyTable())
    assert out == "result was 42 percent."


def test_postprocess_humanize_threads_replacements_into_fallback(ai_article_zh) -> None:
    """When the LLM is unavailable, the fallback path uses
    ``_deterministic_cleanup`` and must honour the injected table.
    """
    from humanize_zh import postprocess_humanize

    class _StubTable:
        code = "stub"

        def ordered_pairs(self) -> list[tuple[str, str]]:
            return [("综上所述", "ZZZSENTINEL")]

    polished, _, _ = postprocess_humanize(
        ai_article_zh,
        scene="analysis",
        lang="zh",
        replacements=_StubTable(),
    )
    # ZH defaults would delete "综上所述" entirely (replace → ""); the
    # stub instead substitutes "ZZZSENTINEL", proving the injected
    # table won and not the singleton's pairs.
    assert "ZZZSENTINEL" in polished
    assert "综上所述" not in polished
