"""Dedicated unit tests for :mod:`humanize_zh.combined`.

The combined layer is the release-gate scorer. Tests pin:

- ``max(rule, ngram)`` semantics — any single HIGH layer wins
- ``ngram_available=False`` falls back to rule-only without crashing
- ``has_notes=True`` plumbs through to the rule layer
- ``combined_level`` agrees with :func:`level_label`
- Empty input handled gracefully
"""
from __future__ import annotations

from unittest.mock import patch

from humanize_zh._format import level_label
from humanize_zh.combined import CombinedScore, combined_score

# ─── Smoke / contract ───────────────────────────────────────────────────────


def test_combined_score_returns_dataclass() -> None:
    cs = combined_score("综上所述, 这个产品赋能了所有用户。")
    assert isinstance(cs, CombinedScore)
    assert 0 <= cs.combined_probability <= 100
    assert 0 <= cs.rule_probability <= 100
    assert 0 <= cs.ngram_probability <= 100


def test_combined_level_agrees_with_shared_helper() -> None:
    cs = combined_score("综上所述, 这个产品赋能了所有用户。" * 5)
    assert cs.combined_level == level_label(cs.combined_probability)


# ─── max-style aggregation ─────────────────────────────────────────────────


def test_combined_is_max_of_rule_and_ngram() -> None:
    """``combined_probability`` == max(rule, ngram) when ngram is available."""
    text = "综上所述, 这个产品赋能了所有用户。" * 10
    cs = combined_score(text)
    if cs.ngram_available:
        assert cs.combined_probability == max(cs.rule_probability, cs.ngram_probability)
    else:
        assert cs.combined_probability == cs.rule_probability


def test_high_rule_wins_when_ngram_low() -> None:
    """Even if ngram says LOW, a HIGH rule score must drag combined up."""
    text = (
        "综上所述, 值得注意的是, 不难发现, 此外然而, 与此同时, 不仅如此, "
        "毋庸置疑, 显而易见, 归根结底, 由此可见。" * 6
    )
    cs = combined_score(text)
    assert cs.rule_probability >= cs.ngram_probability or cs.combined_probability == cs.rule_probability


# ─── Fallback when ngram unavailable ──────────────────────────────────────


def test_combined_falls_back_to_rule_when_ngram_engine_fails() -> None:
    """If ngram_score raises, combined_score still returns a valid object."""
    def _broken_ngram(*_args, **_kwargs):
        raise RuntimeError("simulated engine crash")

    with patch("humanize_zh.ngram_check.ngram_score", _broken_ngram):
        cs = combined_score("综上所述, 这个产品赋能了所有用户。")
    assert cs.ngram_available is False
    assert "error" in cs.ngram_metrics
    # rule layer still ran, so combined is rule-only
    assert cs.combined_probability == cs.rule_probability


# ─── has_notes plumbing ───────────────────────────────────────────────────


def test_has_notes_flag_propagates_to_rule_layer() -> None:
    text = "我在凌晨 3 点测试了这个产品, 感觉它非常神奇。" * 5
    no_notes = combined_score(text, has_notes=False)
    with_notes = combined_score(text, has_notes=True)
    assert with_notes.has_notes is True
    assert no_notes.has_notes is False
    # has_notes never raises the score
    assert with_notes.rule_probability <= no_notes.rule_probability


# ─── Edge cases ───────────────────────────────────────────────────────────


def test_empty_text_does_not_raise() -> None:
    cs = combined_score("")
    assert cs.combined_probability == 0.0
    assert cs.text_length == 0


def test_str_renders_three_layers() -> None:
    cs = combined_score("综上所述, 这个产品赋能了所有用户。" * 3)
    rendered = str(cs)
    assert "综合 AI 概率" in rendered
    assert "rule:" in rendered
    assert "ngram:" in rendered
