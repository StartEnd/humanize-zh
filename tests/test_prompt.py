"""Dedicated unit tests for :mod:`humanize_zh.prompt`.

Pins the prompt-builder contracts that downstream LLM callers depend on:

- ``build_humanize_prompt`` renders for all 4 scenes
- Unknown scenes fall back to ``analysis`` (no crash)
- ``build_humanize_postprocess_prompt`` interpolates article + violations
- ``lang="en"`` returns the self-contained English template
- ``aggressive=True`` switches to the rewrite-heavy prompt
- All 5 ironclad rules appear in the rendered output
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from humanize_zh.prompt import (
    POSTPROCESS_PROMPT_AGGRESSIVE,
    POSTPROCESS_PROMPT_EN,
    SCENES,
    build_humanize_postprocess_prompt,
    build_humanize_prompt,
)


@dataclass
class _StubViolation:
    """Lightweight stand-in for :class:`humanize_zh.detect.Violation`.

    ``build_humanize_postprocess_prompt`` reads ``.category``, ``.rule``,
    ``.count``, ``.sample`` only — a real Violation would also work but we
    avoid the extra dependency by stubbing.
    """
    category: str
    rule: str
    count: int
    sample: str


# ─── build_humanize_prompt ─────────────────────────────────────────────────


@pytest.mark.parametrize("scene", ["analysis", "essay", "academic", "blog"])
def test_prompt_renders_for_all_scenes(scene: str) -> None:
    text = build_humanize_prompt(scene=scene)
    assert text.startswith("# 去 AI 味写作纪律")
    # 5 ironclad rules — the headline section always present
    assert "5 大铁律" in text
    assert "删除填充短语" in text


def test_unknown_scene_falls_back_to_analysis() -> None:
    """Defensive: caller typos should not crash, they get the default."""
    fallback = build_humanize_prompt(scene="not-a-real-scene")
    analysis = build_humanize_prompt(scene="analysis")
    assert fallback == analysis


def test_scenes_dict_lists_all_supported_scenes() -> None:
    assert set(SCENES) == {"analysis", "essay", "academic", "blog"}


def test_compact_flag_does_not_crash() -> None:
    """compact= is accepted; current impl returns the same body."""
    a = build_humanize_prompt(scene="analysis", compact=True)
    b = build_humanize_prompt(scene="analysis", compact=False)
    assert isinstance(a, str) and isinstance(b, str)
    assert a == b  # current behavior — pin it so a future change is intentional


# ─── build_humanize_postprocess_prompt (zh) ────────────────────────────────


def test_postprocess_prompt_zh_interpolates_article_and_violations() -> None:
    article = "## 测试文章\n\n综上所述, 这个产品赋能了所有用户。"
    violations = [
        _StubViolation(
            category="blacklist_words", rule="ai_high_freq",
            count=2, sample="综上所述, 这个产品赋能了",
        ),
    ]
    prompt = build_humanize_postprocess_prompt(article, violations, scene="analysis")
    assert article in prompt
    assert "ai_high_freq" in prompt
    assert "命中 2 次" in prompt
    # ironclad rules section embedded
    assert "5 大铁律" in prompt


def test_postprocess_prompt_zh_handles_empty_violations() -> None:
    """No violations: prompt still emits a placeholder, doesn't crash."""
    prompt = build_humanize_postprocess_prompt(
        "## 文章\n\n短句子。", violations=[], scene="analysis",
    )
    assert "规则扫描器未命中" in prompt


def test_postprocess_prompt_zh_clips_long_sample() -> None:
    """Sample lines truncate at 40 chars in the violation listing."""
    long_sample = "x" * 200
    v = _StubViolation(category="blacklist_words", rule="r", count=1, sample=long_sample)
    prompt = build_humanize_postprocess_prompt("文章", [v], scene="analysis")
    assert "x" * 40 in prompt
    assert "x" * 41 not in prompt


# ─── build_humanize_postprocess_prompt (en + aggressive) ──────────────────


def test_postprocess_prompt_en_uses_english_template() -> None:
    article = "## Test\n\nIt's worth noting that..."
    prompt = build_humanize_postprocess_prompt(article, violations=[], lang="en")
    assert prompt.startswith(POSTPROCESS_PROMPT_EN.split("\n")[0])
    assert article in prompt
    # ZH-only rule section must not bleed into the EN template
    assert "5 大铁律" not in prompt


def test_postprocess_prompt_aggressive_switches_template() -> None:
    """aggressive=True selects the rewrite-heavy template, not the polite polish one."""
    article = "## 文章\n\n综上所述..."
    aggressive = build_humanize_postprocess_prompt(
        article, violations=[], scene="analysis", aggressive=True,
    )
    polish = build_humanize_postprocess_prompt(
        article, violations=[], scene="analysis", aggressive=False,
    )
    assert aggressive != polish
    assert aggressive.startswith(POSTPROCESS_PROMPT_AGGRESSIVE.split("\n")[0])
    assert "改写句式而非删事实" in aggressive
