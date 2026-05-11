"""humanize_zh.iterative — 迭代闭环改写 (writer + judge 多轮 ping-pong)

为什么需要这个?
================

单轮 LLM polish 对第三方检测器 (朱雀/Originality) 效果有限, 因为:

1. 我们的 rule + ngram 评分跟 transformer 困惑度不在同一信号源 — 我们说"21 分像
   人写的", 朱雀仍报 73% AI.
2. LLM 一次重写的"力度"由 prompt 决定, 但 LLM 倾向保守, 一次改不彻底.

迭代闭环的思路:

    Round N: writer 重写 → judge 给 0-100 AI 分 + 具体 tells
    Round N+1: 拿 N 轮 tells 当 violations, 让 writer 再改

每一轮 judge 不只是分数, 还输出"具体哪些段落像 AI / 缺什么人味" — 下一轮 polish
有针对性, 而不是盲改.

防 collusion:

writer 和 judge 默认必须不同 provider (例: writer=deepseek, judge=hunyuan/qwen).
若用户只配了一个 provider, 强制要求 ``allow_self_judge=True`` 才放行 (会在
返回 history 里 mark warning).
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .detect import Violation, score
from .judge import _call_llm as _judge_call_llm
from .judge import _parse_json
from .llm import (
    LLMError,
    LLMNotConfiguredError,
    LLMProvider,
    ProviderArg,
    provider_id,
    resolve_provider,
)
from .postprocess import _call_llm as _writer_call_llm
from .postprocess import postprocess_humanize
from .prompt import build_humanize_postprocess_prompt

logger = logging.getLogger(__name__)


# ── Loop-specific judge prompt (vs full judge.JUDGE_PROMPT) ─────────────
#
# We don't need the full 7-field审稿 JSON inside a polish loop; we only need:
#  - ai_score (0-100, like transformer-based detectors estimate)
#  - tells   : concrete句式/词语/段落 issues to feed next-round polish

_LOOP_JUDGE_PROMPT_ZH = """你是 AI 文本检测员. 评估下面这段中文文章看起来多大概率是 AI(LLM) 生成.

评估维度 (与朱雀 / GPTZero 同源, transformer 困惑度视角):
- 句式整齐度 (越像模板越像 AI)
- 段落开头多样性 (越统一越像 AI)
- 套话密度 (综上所述/赋能/不容忽视/在...背景下/为...提供)
- 抽象 vs 具体 (越抽象越像 AI)
- 人味标记 (主观判断/不确定承认/自嘲/口语 — 越缺越像 AI)

输入:
---
{ARTICLE}
---

严格输出 JSON, 不要 markdown 包裹:

{{
  "ai_score": <int 0-100, 0=完全人写, 100=完全 AI>,
  "tells": [
    "<具体哪一句/哪一段像 AI, 用不超过 30 字描述>"
  ],
  "verdict": "<HUMAN_LIKE | BORDERLINE | AI_LIKE>"
}}

tells 数组至少给 3 条, 最多 8 条. 不要泛泛而谈, 必须是文章里能 grep 到的具体片段.
"""


_LOOP_JUDGE_PROMPT_EN = """You are an AI-text detector. Estimate how likely the
text below is AI-generated (LLM-written).

Evaluation axes (same family as GPTZero / Originality — transformer perplexity):
- Sentence uniformity (template-like = AI)
- Paragraph opener diversity (uniform = AI)
- Filler density ("It's worth noting", "In conclusion", "needless to say")
- Abstract vs concrete (more abstract = more AI)
- Human markers (subjective claim, uncertainty, self-correction, voice)

Input:
---
{ARTICLE}
---

Output strict JSON, no markdown:

{{
  "ai_score": <int 0-100, 0=human-like, 100=clearly AI>,
  "tells": [
    "<concrete sentence/paragraph that looks AI, ≤30 words>"
  ],
  "verdict": "<HUMAN_LIKE | BORDERLINE | AI_LIKE>"
}}

tells: 3-8 entries, must be specific phrases visible in the input.
"""


@dataclass
class RoundResult:
    """Outcome of a single polish + judge round."""

    round: int  # 1-indexed
    polished: str
    polished_len: int
    rule_score: float | None  # our local rule probability (zh only)
    ai_score: int | None  # judge's 0-100 AI probability
    verdict: Literal["HUMAN_LIKE", "BORDERLINE", "AI_LIKE", "UNKNOWN"]
    tells: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class IterativeResult:
    """Bundled outcome of an iterative_polish() invocation."""

    final_text: str
    rounds: list[RoundResult]
    writer_provider: str | None
    judge_provider: str | None
    target_ai_score: int
    stopped_reason: Literal["target_reached", "rounds_exhausted", "judge_failed"]
    self_judge: bool  # True if writer == judge (collusion warning)

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_text": self.final_text,
            "rounds": [asdict(r) for r in self.rounds],
            "writer_provider": self.writer_provider,
            "judge_provider": self.judge_provider,
            "target_ai_score": self.target_ai_score,
            "stopped_reason": self.stopped_reason,
            "self_judge": self.self_judge,
        }


Verdict = Literal["HUMAN_LIKE", "BORDERLINE", "AI_LIKE", "UNKNOWN"]


def _judge_one_round(
    text: str,
    *,
    judge_provider: LLMProvider,
    lang: str = "zh",
) -> tuple[int | None, list[str], Verdict]:
    """Call the lightweight loop-judge prompt and parse.

    Returns:
        (ai_score, tells, verdict). All None / empty on failure.
    """
    template = _LOOP_JUDGE_PROMPT_EN if lang == "en" else _LOOP_JUDGE_PROMPT_ZH
    prompt = template.format(ARTICLE=text)
    raw = _judge_call_llm(prompt, provider=judge_provider)
    if not raw:
        return None, [], "UNKNOWN"

    parsed = _parse_json(raw)
    if "_parse_error" in parsed:
        logger.warning("[iterative] judge json parse failed: %s", parsed["_parse_error"])
        return None, [], "UNKNOWN"

    raw_score = parsed.get("ai_score")
    score_v: int | None = (
        max(0, min(100, int(raw_score))) if isinstance(raw_score, (int, float)) else None
    )

    tells_raw = parsed.get("tells") or []
    tells: list[str] = (
        [str(t)[:200] for t in tells_raw if t] if isinstance(tells_raw, list) else []
    )

    raw_verdict = parsed.get("verdict")
    verdict: Verdict = (
        raw_verdict if raw_verdict in ("HUMAN_LIKE", "BORDERLINE", "AI_LIKE") else "UNKNOWN"
    )

    return score_v, tells, verdict


def iterative_polish(
    article: str,
    *,
    rounds: int = 3,
    target_ai_score: int = 30,
    scene: str = "analysis",
    lang: str = "zh",
    writer_provider: ProviderArg = None,
    judge_provider: ProviderArg = None,
    allow_self_judge: bool = False,
) -> IterativeResult:
    """Run a closed-loop polish: each round writer rewrites, judge scores.

    The loop stops early when ``judge ai_score <= target_ai_score`` or when
    ``rounds`` is exhausted. Each round's rewrite is informed by the previous
    round's tells, so polishing becomes increasingly targeted.

    Args:
        article: source text.
        rounds: max rounds (recommended 2-4; each round = 2 LLM calls).
        target_ai_score: stop when judge gives ≤ this score.
        scene/lang: passed to writer (postprocess_humanize).
        writer_provider: who rewrites. None = active.
        judge_provider:  who scores. None = active. Should differ from writer.
        allow_self_judge: bypass collusion check (warning logged).

    Returns:
        IterativeResult with rounds list, final text, stop reason, etc.
    """
    if rounds < 1:
        raise ValueError(f"rounds must be ≥ 1, got {rounds}")
    if not 0 <= target_ai_score <= 100:
        raise ValueError(f"target_ai_score must be 0-100, got {target_ai_score}")

    writer_resolved = resolve_provider(writer_provider)
    judge_resolved = resolve_provider(judge_provider)
    writer_id = provider_id(writer_resolved)
    judge_id = provider_id(judge_resolved)
    self_judge = writer_id == judge_id and writer_id is not None
    if self_judge and not allow_self_judge:
        raise ValueError(
            f"writer and judge are both {writer_id}. Collusion risk is high. "
            "Pass a different judge_provider or set allow_self_judge=True."
        )
    if self_judge:
        logger.warning(
            "[iterative] self-judge enabled (writer == judge == %s); "
            "judge scores are unreliable", writer_id,
        )

    history: list[RoundResult] = []
    current = article
    prior_tells: list[str] = []
    stopped: Literal["target_reached", "rounds_exhausted", "judge_failed"] = "rounds_exhausted"

    for r in range(1, rounds + 1):
        # Round 1: standard aggressive polish on `current`.
        # Round ≥2: same polish, then a targeted refine using prior_tells.
        try:
            polished, _after, _before = postprocess_humanize(
                current,
                scene=scene,
                lang=lang,
                provider=writer_resolved,
                force_llm=True,  # always rewrite in a loop, ignore "已达发布线" gate
            )
        except (LLMError, LLMNotConfiguredError, ValueError) as e:
            history.append(RoundResult(
                round=r, polished=current, polished_len=len(current),
                rule_score=None, ai_score=None, verdict="UNKNOWN",
                tells=[], error=f"writer error: {e}",
            ))
            break

        if prior_tells and r >= 2:
            synthetic = [
                Violation(category="judge_tell", rule=f"round{r-1}",
                          weight=10, count=1, sample=t[:200])
                for t in prior_tells[:8]
            ]
            targeted_prompt = build_humanize_postprocess_prompt(
                polished, synthetic, scene=scene, lang=lang, aggressive=True,
            )
            refined = _writer_call_llm(targeted_prompt, provider=writer_resolved)
            if refined:
                polished = refined

        # Local rule score (zh only) — sanity check, not decisive.
        rule_v: float | None = None
        if lang == "zh":
            rule_v = score(polished).total

        # Judge
        ai_score_v, tells, verdict = _judge_one_round(
            polished, judge_provider=judge_resolved, lang=lang,
        )
        history.append(RoundResult(
            round=r, polished=polished, polished_len=len(polished),
            rule_score=rule_v, ai_score=ai_score_v, verdict=verdict, tells=tells,
        ))

        current = polished
        prior_tells = tells

        if ai_score_v is None:
            stopped = "judge_failed"
            break
        if ai_score_v <= target_ai_score:
            stopped = "target_reached"
            break

    # Pick best round (lowest ai_score; ties broken by highest round number).
    rated = [h for h in history if h.ai_score is not None and not h.error]
    if rated:
        best = min(rated, key=lambda h: (h.ai_score or 999, -h.round))
        final_text = best.polished
    elif history:
        final_text = history[-1].polished
    else:
        final_text = article

    return IterativeResult(
        final_text=final_text,
        rounds=history,
        writer_provider=writer_id,
        judge_provider=judge_id,
        target_ai_score=target_ai_score,
        stopped_reason=stopped,
        self_judge=self_judge,
    )
