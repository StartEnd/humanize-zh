"""Shared pytest fixtures for humanize-zh tests."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from humanize_zh import llm

# ─── Sample articles ─────────────────────────────────────────────────────────

AI_ARTICLE_ZH = """# 某站分析

值得注意的是, 这个站点不仅仅是一个简单的工具, 而是一个系统性的解决方案。

首先, 它解决了用户的痛点。其次, 它提供了完整的闭环。最后, 它实现了价值的沉淀。

不难发现, 这种产品形态正在重塑整个行业。综上所述, 未来可期。
"""

AI_ARTICLE_EN = """# Analysis

It's worth noting that this platform is not just a tool but a comprehensive solution.

First, it solves user pain points. Second, it provides a complete loop. Third, it delivers
sustained value.

At its core, it reshapes the industry. In other words, it empowers users at every layer.

In conclusion, this is a case study worth exploring. The future looks bright.
"""


@pytest.fixture
def ai_article_zh() -> str:
    """A short Chinese article seeded with AI tells for detection testing."""
    return AI_ARTICLE_ZH


@pytest.fixture
def ai_article_en() -> str:
    """A short English article seeded with AI tells."""
    return AI_ARTICLE_EN


# ─── LLM provider fixtures ───────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_llm_between_tests():
    """Ensure each test starts with no active provider so tests can't leak."""
    llm.clear()
    yield
    llm.clear()


@pytest.fixture
def fake_polish_fn() -> Callable[[str], str]:
    """A deterministic callable that simulates polishing by removing AI tells."""
    def _fn(prompt: str) -> str:
        if "Task: De-AI polishing pass" in prompt:
            return (
                "# Analysis\n\n"
                "This platform is a comprehensive solution.\n\n"
                "It solves user pain points, provides a complete loop, "
                "and delivers sustained value.\n\n"
                "It reshapes the industry by empowering users.\n\n"
                "A case study worth exploring.\n"
            )
        return (
            "# 某站分析\n\n"
            "这个站点是一个系统性的解决方案。\n\n"
            "它解决了用户的痛点, 提供了完整的闭环, 实现了价值的积累。\n\n"
            "这种产品形态正在重塑整个行业。它的核心逻辑是帮助用户。\n\n"
            "这是一个值得深入研究的案例。\n"
        )
    return _fn


@pytest.fixture
def fake_judge_fn() -> Callable[[str], str]:
    """A deterministic callable that returns a valid judge JSON response."""
    def _fn(prompt: str) -> str:
        if "long-form English article" in prompt:
            return json.dumps(
                {
                    "publishable": False,
                    "worst_ai_sections": [
                        {"para": "It's worth noting", "reason": "filler opener + template"}
                    ],
                    "unsupported_claims": [],
                    "template_smell": ["First/Second/Third enumeration"],
                    "fake_human_details": [],
                    "best_theses": [],
                    "rewrite_brief": "Remove filler openers; replace enumeration with prose.",
                }
            )
        return json.dumps(
            {
                "publishable": False,
                "worst_ai_sections": [
                    {"para": "值得注意的是", "reason": "填充开场白 + 三段式"}
                ],
                "unsupported_claims": [],
                "template_smell": ["首先/其次/最后 三段式"],
                "fake_human_details": [],
                "best_theses": [],
                "rewrite_brief": "删除填充开场白; 把三段式改成自然过渡.",
            },
            ensure_ascii=False,
        )
    return _fn


# ─── Repository paths ────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DIGESTER_ROOT = REPO_ROOT.parent / "site-digester"


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def site_digester_root() -> Path:
    return SITE_DIGESTER_ROOT
