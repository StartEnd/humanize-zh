"""Dedicated unit tests for :mod:`humanize_zh.ngram_check`.

The ngram layer ships with the vendored ``data/_ngram_engine.py`` scoring
engine. Tests here focus on the wrapper module (not the engine internals):

- Empty / short input handled without crashing
- Engine load isolation: ``sys.path`` is not mutated (regression test for the
  pre-Pass A hack that did ``sys.path.insert(0, str(DATA_DIR))``)
- ``available=False`` path triggers ``UNKNOWN`` level and zero probability
- ``level`` field always agrees with the shared :func:`level_label` helper
"""
from __future__ import annotations

import sys

from humanize_zh._format import level_label
from humanize_zh.ngram_check import (
    NgramScore,
    _load_engine,
    ngram_score,
)

# ─── Smoke ──────────────────────────────────────────────────────────────────


def test_ngram_score_returns_dataclass() -> None:
    s = ngram_score("北京今天下了一整天雨。我躲在咖啡馆里读完了一本书, 然后慢慢走回家。")
    assert isinstance(s, NgramScore)
    assert isinstance(s.ai_probability, float)
    assert 0 <= s.ai_probability <= 100


def test_ngram_score_level_matches_shared_helper_when_available() -> None:
    """When the engine is loaded, the label must come from level_label."""
    text = "综上所述, 这个产品赋能了所有用户。" * 12
    s = ngram_score(text)
    if s.available and s.char_count >= 30:
        assert s.level == level_label(s.ai_probability)


# ─── Empty / short input ───────────────────────────────────────────────────


def test_empty_text_short_circuits() -> None:
    s = ngram_score("")
    assert s.ai_probability == 0.0
    assert s.available is True
    assert s.char_count == 0


def test_whitespace_only_short_circuits() -> None:
    s = ngram_score("   \n\n   ")
    assert s.ai_probability == 0.0


def test_too_short_text_returns_low_band() -> None:
    """< 30 Chinese chars: not enough signal, label says so."""
    s = ngram_score("北京下雨。")
    # either short-circuit branch or the < 30 char ppl branch
    assert s.ai_probability == 0.0
    assert "LOW" in s.level or "UNKNOWN" in s.level


# ─── Engine loader ────────────────────────────────────────────────────────


def test_engine_loads_under_private_module_name() -> None:
    """Engine is imported under ``humanize_zh._ngram_engine`` (sys.modules)."""
    engine = _load_engine()
    assert engine is not None
    assert "humanize_zh._ngram_engine" in sys.modules


def test_engine_load_does_not_pollute_sys_path() -> None:
    """Regression: pre-Pass A code inserted ``data/`` into sys.path globally."""
    snapshot = list(sys.path)
    _load_engine()  # may be a no-op if cached, that's the point
    assert list(sys.path) == snapshot


def test_engine_handle_is_cached() -> None:
    """Second call returns the same module object — no re-loading."""
    first = _load_engine()
    second = _load_engine()
    assert first is second


# ─── available=False path ─────────────────────────────────────────────────


def test_unavailable_engine_returns_unknown_level(monkeypatch) -> None:
    """If ``_load_engine`` returns None, score must surface available=False.

    NOTE: After the Phase-1 multi-language refactor, the implementation lives
    in ``humanize_zh._lang.zh.ngram``; ``humanize_zh.ngram_check`` is a
    compat shim. We monkeypatch the canonical module so ``ngram_score``'s
    own globals see the override.
    """
    from humanize_zh._lang.zh import ngram as ngram_impl

    monkeypatch.setattr(ngram_impl, "_load_engine", lambda: None)
    monkeypatch.setattr(ngram_impl, "_ENGINE_LOAD_ERROR", "test-fake-missing", raising=False)
    s = ngram_impl.ngram_score("北京今天下了一整天雨。咖啡馆里很安静。" * 5)
    assert s.available is False
    assert s.level == "UNKNOWN"
    assert s.ai_probability == 0.0


def test_str_render_is_multiline() -> None:
    s = ngram_score("北京下雨。" * 30)
    rendered = str(s)
    assert "ngram AI 概率" in rendered
    assert "\n" in rendered
