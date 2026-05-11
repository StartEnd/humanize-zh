"""Phase 8: Iterative closed-loop polish tests."""
from __future__ import annotations

import json

import pytest

from humanize_zh import iterative_polish, llm
from humanize_zh.iterative import RoundResult, _judge_one_round


def _make_loop_judge_fn(scores: list[int], tells: list[str] | None = None):
    """Return a callable that returns judge JSON per call from `scores`.

    Each invocation pops the next score (so we can simulate decreasing AI score
    across rounds, e.g. [80, 50, 20]).
    """
    state = {"i": 0}
    tells_list = tells or ["套话太多", "段落开头千篇一律", "缺少主观判断"]

    def _fn(prompt: str) -> str:
        # We're a unified callable doing both polish-LLM and judge-LLM duty.
        if "AI 文本检测员" in prompt or "AI-text detector" in prompt:
            i = state["i"]
            state["i"] = min(i + 1, len(scores) - 1)
            sv = scores[i]
            verdict = (
                "HUMAN_LIKE" if sv < 30
                else "AI_LIKE" if sv > 70
                else "BORDERLINE"
            )
            return json.dumps(
                {"ai_score": sv, "tells": tells_list, "verdict": verdict},
                ensure_ascii=False,
            )
        # Otherwise act as polish writer: return a deterministic rewrite.
        return (
            "# 站点分析\n\n这个站点提供了具体的解决方案。\n\n"
            "解决用户痛点, 提供完整闭环, 沉淀价值。\n\n"
            "重塑行业。\n\n值得深入研究。\n"
        )

    return _fn


def test_self_judge_blocked_without_flag(ai_article_zh: str) -> None:
    """writer == judge (same provider) must require allow_self_judge=True."""
    fn = _make_loop_judge_fn([60, 30])
    llm.use_callable(fn, name="fakeprov", model="v1")
    with pytest.raises(ValueError, match="(?i)collusion|both"):
        iterative_polish(ai_article_zh, rounds=2)


def test_self_judge_allowed_with_flag(ai_article_zh: str) -> None:
    fn = _make_loop_judge_fn([60, 25])
    llm.use_callable(fn, name="fakeprov", model="v1")
    result = iterative_polish(ai_article_zh, rounds=2, allow_self_judge=True)
    assert result.self_judge is True
    assert len(result.rounds) >= 1
    assert result.writer_provider == result.judge_provider == "fakeprov::v1"


def test_loop_stops_when_target_reached(ai_article_zh: str) -> None:
    """If judge returns score <= target, loop should short-circuit."""
    fn = _make_loop_judge_fn([20])  # already below default target 30
    llm.use_callable(fn, name="fakeprov", model="v1")
    result = iterative_polish(
        ai_article_zh, rounds=3, target_ai_score=30, allow_self_judge=True,
    )
    assert result.stopped_reason == "target_reached"
    assert len(result.rounds) == 1
    assert result.rounds[0].ai_score == 20
    assert result.rounds[0].verdict == "HUMAN_LIKE"


def test_loop_runs_all_rounds_when_target_not_reached(ai_article_zh: str) -> None:
    fn = _make_loop_judge_fn([85, 70, 55])  # never below 30
    llm.use_callable(fn, name="fakeprov", model="v1")
    result = iterative_polish(
        ai_article_zh, rounds=3, target_ai_score=30, allow_self_judge=True,
    )
    assert result.stopped_reason == "rounds_exhausted"
    assert len(result.rounds) == 3
    assert [r.ai_score for r in result.rounds] == [85, 70, 55]


def test_loop_picks_lowest_ai_score_round(ai_article_zh: str) -> None:
    """final_text should come from the round with the smallest ai_score."""
    fn = _make_loop_judge_fn([60, 25, 80])  # round 2 wins
    llm.use_callable(fn, name="fakeprov", model="v1")
    result = iterative_polish(
        ai_article_zh, rounds=3, target_ai_score=10,  # never reached -> exhaust
        allow_self_judge=True,
    )
    # Loop stops at round 2 because 25 <= target? No, target=10. So all 3 rounds run.
    # Round 2 ai_score = 25 is lowest, so final_text comes from round 2.
    assert len(result.rounds) == 3
    assert result.final_text == result.rounds[1].polished


def test_loop_preserves_history_on_judge_failure(ai_article_zh: str) -> None:
    """If judge returns malformed JSON, loop stops with judge_failed and keeps history."""
    def _fn(prompt: str) -> str:
        if "AI 文本检测员" in prompt:
            return "<not json at all>"
        return "# 改写后\n\n这是改写后的文章。\n"
    llm.use_callable(_fn, name="fakeprov", model="v1")
    result = iterative_polish(ai_article_zh, rounds=3, allow_self_judge=True)
    assert result.stopped_reason == "judge_failed"
    assert len(result.rounds) == 1
    assert result.rounds[0].ai_score is None
    assert result.rounds[0].verdict == "UNKNOWN"


def test_invalid_rounds_raises() -> None:
    with pytest.raises(ValueError, match="rounds must be"):
        iterative_polish("text", rounds=0, allow_self_judge=True)


def test_invalid_target_score_raises() -> None:
    with pytest.raises(ValueError, match="target_ai_score must be"):
        iterative_polish("text", rounds=1, target_ai_score=200, allow_self_judge=True)


def test_to_dict_serializes_rounds(ai_article_zh: str) -> None:
    fn = _make_loop_judge_fn([20])
    llm.use_callable(fn, name="fakeprov", model="v1")
    result = iterative_polish(
        ai_article_zh, rounds=1, target_ai_score=30, allow_self_judge=True,
    )
    d = result.to_dict()
    assert d["stopped_reason"] == "target_reached"
    assert d["self_judge"] is True
    assert isinstance(d["rounds"], list)
    assert d["rounds"][0]["ai_score"] == 20
    assert d["rounds"][0]["verdict"] == "HUMAN_LIKE"
    assert "polished" in d["rounds"][0]


def test_round_result_dataclass_fields() -> None:
    r = RoundResult(
        round=1, polished="abc", polished_len=3,
        rule_score=12.5, ai_score=40, verdict="BORDERLINE", tells=["x"],
    )
    assert r.round == 1
    assert r.error is None
    assert r.tells == ["x"]


def test_judge_one_round_parses_valid_json() -> None:
    fn = _make_loop_judge_fn([45], tells=["a", "b", "c"])
    llm.use_callable(fn, name="fakeprov", model="v1")
    provider = llm.get_active()
    score, tells, verdict = _judge_one_round("dummy", judge_provider=provider)
    assert score == 45
    assert tells == ["a", "b", "c"]
    assert verdict == "BORDERLINE"


def test_judge_one_round_handles_score_out_of_range() -> None:
    """ai_score outside 0-100 should be clamped."""
    def _fn(prompt: str) -> str:
        return json.dumps({"ai_score": 150, "tells": [], "verdict": "AI_LIKE"})
    llm.use_callable(_fn, name="fakeprov", model="v1")
    provider = llm.get_active()
    score, _, _ = _judge_one_round("dummy", judge_provider=provider)
    assert score == 100  # clamped


def test_loop_lang_en_skips_rule_score(ai_article_en: str) -> None:
    fn = _make_loop_judge_fn([20])
    llm.use_callable(fn, name="fakeprov", model="v1")
    result = iterative_polish(
        ai_article_en, rounds=1, lang="en", allow_self_judge=True,
    )
    assert result.rounds[0].rule_score is None
