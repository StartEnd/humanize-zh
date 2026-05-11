"""Unit tests for the small shared helpers extracted in Pass A.

Each test pins behavior that previously lived in multiple per-module copies.
Drift between copies caused real bugs (notably the ``::`` vs ``:``
provider-id mismatch between ``judge.py`` and ``iterative.py``), so these are
the regression tests for that drift class.
"""
from __future__ import annotations

import pytest

from humanize_zh import llm
from humanize_zh._format import level_label
from humanize_zh.llm import list_providers, provider_id, required_env_keys_hint

# ─── level_label ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "prob,expected_prefix",
    [
        (0.0, "LOW"),
        (24.9, "LOW"),
        (25.0, "MEDIUM"),
        (49.9, "MEDIUM"),
        (50.0, "HIGH"),
        (74.9, "HIGH"),
        (75.0, "VERY HIGH"),
        (100.0, "VERY HIGH"),
    ],
)
def test_level_label_thresholds(prob: float, expected_prefix: str) -> None:
    """Each band boundary maps to the right label, lower-bound inclusive."""
    assert level_label(prob).startswith(expected_prefix)


def test_level_label_returns_chinese_localized() -> None:
    """The label carries the Chinese context — keep at least one CJK char."""
    label = level_label(50.0)
    assert any("\u4e00" <= ch <= "\u9fff" for ch in label)


def test_level_label_used_consistently_across_modules() -> None:
    """detect / ngram_check / combined must all surface identical labels.

    Before Pass A each module carried its own ``_level()`` copy. A future
    drift would re-introduce the divergence; this test catches that.
    """
    from humanize_zh.combined import CombinedScore
    from humanize_zh.detect import score as rule_score
    from humanize_zh.ngram_check import ngram_score

    text = (
        "综上所述, 这个产品赋能了所有用户。值得注意的是, 它构建了完整的闭环。"
        "首先, 它解决了用户痛点。其次, 它提供了系统性的解决方案。最后, 它实现了价值沉淀。"
        "不难发现, 这种产品形态正在重塑整个行业。"
    ) * 4

    rule = rule_score(text)
    ng = ngram_score(text)
    # Both labels must come from the shared helper — same probability → same band.
    assert rule.level == level_label(rule.total)
    if ng.available:
        assert ng.level == level_label(ng.ai_probability)

    cs_label = CombinedScore(
        combined_probability=42.0, combined_level=level_label(42.0),
        rule_probability=42.0, rule_level=level_label(42.0),
        ngram_probability=42.0, ngram_level=level_label(42.0),
        ngram_available=True,
    ).combined_level
    assert cs_label == level_label(42.0)


# ─── provider_id ─────────────────────────────────────────────────────────


def test_provider_id_none_returns_none() -> None:
    assert provider_id(None) is None


def test_provider_id_uses_double_colon_separator() -> None:
    """Single-colon separator would collide with Ollama model names (qwen2.5:7b)."""
    p = llm.use_callable(lambda x: "ok", name="openai", model="gpt-4o-mini")
    assert provider_id(p) == "openai::gpt-4o-mini"


def test_provider_id_handles_colon_in_model_name() -> None:
    """Ollama-style model id with embedded colon must round-trip unambiguously."""
    p = llm.use_callable(lambda x: "ok", name="ollama", model="qwen2.5:7b")
    pid = provider_id(p)
    assert pid == "ollama::qwen2.5:7b"
    # split on `::` recovers exactly (name, model)
    assert pid is not None
    name, model = pid.split("::", 1)
    assert (name, model) == ("ollama", "qwen2.5:7b")


def test_provider_id_default_model_when_missing() -> None:
    """Providers that forgot to set .model fall back to '?', not crash."""

    class _BareProvider:
        name = "bare"

        def complete(self, prompt: str, **_: object) -> object:
            raise NotImplementedError

    assert provider_id(_BareProvider()) == "bare::?"  # type: ignore[arg-type]


def test_provider_id_is_shared_between_judge_and_iterative_modules() -> None:
    """Lock the historical drift: both modules must import the same callable.

    Note: ``humanize_zh/__init__.py`` exports ``judge`` as a function (via
    ``from .judge import judge``), which shadows the submodule attribute in
    the package namespace. We pull the module out of ``sys.modules`` to
    bypass that shadowing.
    """
    import importlib
    iter_mod = importlib.import_module("humanize_zh.iterative")
    judge_mod = importlib.import_module("humanize_zh.judge")

    assert iter_mod.provider_id is provider_id
    assert judge_mod.provider_id is provider_id


# ─── list_providers / required_env_keys_hint ─────────────────────────────


def test_list_providers_returns_all_nine_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    for env in [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
        "DEEPSEEK_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
        "MOONSHOT_API_KEY", "GLM_API_KEY", "DASHSCOPE_API_KEY",
        "OLLAMA_BASE_URL",
    ]:
        monkeypatch.delenv(env, raising=False)

    rows = list_providers()
    names = [r["name"] for r in rows]
    assert names == [
        "openai", "anthropic", "deepseek", "groq", "openrouter",
        "moonshot", "glm", "qwen", "ollama",
    ]
    assert all(r["available"] is False for r in rows)


def test_list_providers_marks_anthropic_available_with_either_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anthropic SDK accepts api_key OR auth_token (MiniMax-style Bearer)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "bearer-x")
    rows = {r["name"]: r for r in list_providers()}
    assert rows["anthropic"]["available"] is True


def test_list_providers_marks_deepseek_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-d")
    rows = {r["name"]: r for r in list_providers()}
    assert rows["deepseek"]["available"] is True
    assert rows["deepseek"]["env"] == "DEEPSEEK_API_KEY"


def test_required_env_keys_hint_covers_all_providers() -> None:
    hint = required_env_keys_hint()
    for key in (
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
        "GROQ_API_KEY", "OPENROUTER_API_KEY", "MOONSHOT_API_KEY",
        "GLM_API_KEY", "DASHSCOPE_API_KEY", "OLLAMA_BASE_URL",
    ):
        assert key in hint
