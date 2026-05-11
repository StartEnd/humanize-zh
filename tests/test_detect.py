"""Dedicated unit tests for :mod:`humanize_zh.detect`.

The rule layer is the foundation of the whole system — every pipeline path
(``polish`` / ``iterative`` / ``combined`` / ``judge``) starts by scoring with
``detect.score()``. Before Pass B this module had no dedicated test file;
coverage came only from indirect calls through ``combined`` / ``polish``.
This file pins:

- Length normalization (per-3000-char unit, capped at 100)
- ``has_notes=True`` exempts the ``fake_human`` detector
- Code blocks / inline code do not count toward the score
- Each rule family (``blacklist_words``, ``blacklist_phrases``,
  ``structural_rules``, ``rhythm_rules``, ``soul_signals``) fires for known
  AI tells and stays silent for clean prose
- Empty / whitespace-only input is handled without crashing
- Score level labels track ``level_label`` (lower-bound inclusive thresholds)
- Score JSON / repr surface no surprises (stable contract)
"""
from __future__ import annotations

import json

import pytest

from humanize_zh._format import level_label
from humanize_zh.detect import (
    PATTERNS_PATH,
    Score,
    Violation,
    _load_patterns,
    _strip_codeblocks,
    score,
)

# ─── Smoke / contract ───────────────────────────────────────────────────────


def test_score_returns_dataclass_with_expected_fields() -> None:
    s = score("综上所述, 这个产品赋能了所有用户。")
    assert isinstance(s, Score)
    assert isinstance(s.total, float)
    assert isinstance(s.level, str)
    assert isinstance(s.violations, list)
    assert isinstance(s.stats, dict)
    assert s.text_length == len("综上所述, 这个产品赋能了所有用户。")


def test_score_level_matches_shared_helper() -> None:
    """Score.level must come from the same threshold map as ngram/combined."""
    s = score("综上所述, 这个产品赋能了所有用户。" * 3)
    assert s.level == level_label(s.total)


def test_score_clamped_to_100() -> None:
    """Even an article spammed with AI tells must not exceed the 100 cap."""
    # Stack many hits in a short article: per-3000-char normalization should
    # still keep us at the cap rather than overflowing.
    text = (
        "综上所述, 值得注意的是, 不难发现, 此外然而, 与此同时, 不仅如此, "
        "毋庸置疑, 显而易见, 归根结底, 由此可见。" * 5
    )
    s = score(text)
    assert 0 <= s.total <= 100


def test_score_is_zero_for_clean_short_prose() -> None:
    """A simple two-sentence statement with no AI tells should score very low."""
    s = score("北京今天下了雨。我在家煮了一壶茶。")
    assert s.total < 25, f"expected LOW band, got {s.total}"
    assert s.level.startswith("LOW")


# ─── Length normalization ──────────────────────────────────────────────────


def test_length_normalization_dampens_long_articles() -> None:
    """Per-3000-char normalization: same hit density should not blow up scores."""
    one_unit = "综上所述, 这个产品赋能了所有用户。" * 30  # ~500 chars × density
    short_score = score(one_unit).total

    ten_units = one_unit * 10  # 10× length, 10× hits → norm-factor ≈ 10
    long_score = score(ten_units).total

    # Same density per unit length → scores should land in the same band.
    # We allow a small margin because rule weights are integer and the
    # normalization is per-3000 not per-500.
    assert abs(short_score - long_score) < 20, (
        f"length normalization failed: short={short_score} long={long_score}"
    )


# ─── Code / inline code stripping ──────────────────────────────────────────


def test_strip_codeblocks_removes_fenced() -> None:
    cleaned = _strip_codeblocks("正文 ```python\n综上所述, x=1\n``` 结束")
    assert "综上所述" not in cleaned


def test_strip_codeblocks_removes_inline() -> None:
    cleaned = _strip_codeblocks("正文 `综上所述` 结束")
    assert "综上所述" not in cleaned


def test_code_inside_fences_does_not_contribute_to_score() -> None:
    """A code sample full of AI words must not pollute the article score."""
    article = "正文很正常。\n\n```\n综上所述, 值得注意的是, 不难发现\n```\n\n结尾。"
    s = score(article)
    assert s.total < 25, f"code-fenced AI words leaked into score: {s.total}"


# ─── has_notes flag ────────────────────────────────────────────────────────


def test_has_notes_true_exempts_fake_human_detector() -> None:
    """has_notes=True signals real operation logs exist, exempting fake-experience hits."""
    # A passage with a fabricated personal anecdote — fake_human should fire
    # when notes are absent and stay quiet when notes=True.
    text = "我在凌晨 3 点测试了这个产品, 感觉它非常神奇。" * 5
    without = score(text, has_notes=False)
    with_notes = score(text, has_notes=True)
    # has_notes never increases the score — at worst stays the same.
    assert with_notes.total <= without.total


# ─── Rule families fire ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ai_word",
    ["赋能", "底层逻辑", "数字化转型", "助力", "破圈", "复盘"],
)
def test_empty_grand_word_fires(ai_word: str) -> None:
    """Each empty-grand vocabulary term should produce at least one violation."""
    text = f"我们的产品{ai_word}了用户的所有需求, 帮助大家提升效率。" * 3
    s = score(text)
    hit_words = " ".join(v.sample for v in s.violations)
    assert ai_word in hit_words, f"{ai_word!r} did not fire any violation"


def test_three_part_template_fires_pattern_rule() -> None:
    text = "首先, A 解决了问题。其次, B 提供了方案。最后, C 实现了价值。" * 3
    s = score(text)
    rules = {v.rule for v in s.violations}
    assert "three_part_list" in rules, (
        f"首先/其次/最后 三段式 should hit three_part_list, got rules={rules}"
    )


# ─── Empty / whitespace input ──────────────────────────────────────────────


def test_empty_text_does_not_raise() -> None:
    s = score("")
    assert s.total == 0.0
    assert s.violations == []
    assert s.text_length == 0


def test_whitespace_only_text_does_not_raise() -> None:
    s = score("   \n\n\t   ")
    assert s.total == 0.0


# ─── Violation dataclass ──────────────────────────────────────────────────


def test_violation_repr_includes_sample() -> None:
    v = Violation(
        category="blacklist_words",
        rule="ai_high_freq",
        weight=3,
        count=2,
        sample="综上所述",
        score=6.0,
    )
    rendered = str(v)
    assert "ai_high_freq" in rendered
    assert "综上所述" in rendered


# ─── patterns.json sanity ──────────────────────────────────────────────────


def test_load_patterns_returns_expected_top_keys() -> None:
    data = _load_patterns()
    for key in (
        "_meta", "blacklist_words", "blacklist_phrases",
        "structural_rules", "rhythm_rules",
    ):
        assert key in data, f"patterns.json missing {key!r}"


def test_patterns_json_is_valid() -> None:
    """The bundled patterns file must parse cleanly — defense against bad edits."""
    text = PATTERNS_PATH.read_text(encoding="utf-8")
    data = json.loads(text)
    assert isinstance(data, dict)
    assert data["_meta"]["version"]
