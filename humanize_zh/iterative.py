"""humanize_zh.iterative — ZH-defaulted thin shim over :mod:`humanize_core.iterative`.

P2.8c collapses the writer/judge ping-pong loop onto humanize-core.
The public API preserves the v0.1.0a1 calling convention:

    from humanize_zh import iterative_polish
    result = iterative_polish(article, rounds=3, target_ai_score=30)

so callers keep working without change. The only behavioral difference
is that ``lang="zh"`` is now the default — pass ``lang="en"`` (or an
EN ``profile=``) to exercise the framework's EN path.

Dataclasses (:class:`RoundResult`, :class:`IterativeResult`) are
re-exported from humanize-core unchanged; tests that introspect their
fields keep working.
"""

from __future__ import annotations

from humanize_core.iterative import (
    IterativeResult,
    RoundResult,
    Verdict,
    _build_round_violations,  # noqa: F401  (legacy re-export for tests)
)
from humanize_core.iterative import _judge_one_round as _core_judge_one_round
from humanize_core.iterative import iterative_polish as _core_iterative_polish

from ._core.protocols import LanguageProfile
from ._lang.zh.profile import zh_profile
from ._lang.zh.prompts import LOOP_JUDGE_PROMPT  # noqa: F401  (legacy re-export)
from .llm import LLMProvider, ProviderArg, provider_id  # noqa: F401  (legacy re-export)
from .prompt import LOOP_JUDGE_PROMPT_EN  # noqa: F401  (legacy re-export)


def _judge_one_round(
    text: str,
    *,
    judge_provider: LLMProvider,
    profile: LanguageProfile | None = None,
) -> tuple[int | None, list[str], Verdict]:
    """Run one judge round; defaults ``profile=zh_profile``.

    Thin wrapper over :func:`humanize_core.iterative._judge_one_round`.
    The framework function requires ``profile=`` as an explicit
    keyword argument (it cannot assume a default language). Legacy ZH
    callers that invoked ``_judge_one_round("text", judge_provider=p)``
    pre-P2.8c did not know about the ``profile=`` parameter at all,
    so this shim defaults it to :data:`zh_profile` — preserving the
    exact call site shape that ZH unit tests exercise.
    """
    return _core_judge_one_round(
        text,
        judge_provider=judge_provider,
        profile=zh_profile if profile is None else profile,
    )


def iterative_polish(
    article: str,
    *,
    rounds: int = 3,
    target_ai_score: int = 30,
    scene: str = "analysis",
    lang: str = "zh",
    profile: LanguageProfile | None = None,
    writer_provider: ProviderArg = None,
    judge_provider: ProviderArg = None,
    allow_self_judge: bool = False,
) -> IterativeResult:
    """Closed-loop polish — each round writer rewrites, judge scores.

    Thin wrapper over :func:`humanize_core.iterative.iterative_polish`
    with ``lang="zh"`` as the backward-compat default. All other
    arguments forward verbatim.

    Loop termination (inherited from the framework):

    - ``judge.ai_score <= target_ai_score`` — reached the bar.
    - ``rounds`` exhausted.
    - Judge call fails (the failure is captured as ``stopped_reason``
      and surfaced on the ``RoundResult.error`` field).

    Args:
        article: Source markdown.
        rounds: Maximum number of writer/judge passes.
        target_ai_score: Early-exit threshold on the judge's 0-100 AI
            probability. ``<=`` wins.
        scene: ZH rule-list scene forwarded to the writer prompt.
        lang: ``"zh"`` (default) or ``"en"``. Ignored when ``profile``
            is given.
        profile: Pre-resolved :class:`LanguageProfile`. Takes priority
            over ``lang=``.
        writer_provider: LLM provider for the polish call.
        judge_provider: LLM provider for the judge call. Must differ
            from ``writer_provider`` unless ``allow_self_judge=True``.
        allow_self_judge: Override the collusion check.

    Returns:
        :class:`IterativeResult` with all rounds' polished texts,
        scores, verdicts, and a ``stopped_reason`` tag.
    """
    return _core_iterative_polish(
        article,
        profile=profile,
        lang=lang,
        rounds=rounds,
        target_ai_score=target_ai_score,
        scene=scene,
        writer_provider=writer_provider,
        judge_provider=judge_provider,
        allow_self_judge=allow_self_judge,
    )


__all__ = [
    "IterativeResult",
    "RoundResult",
    "Verdict",
    "iterative_polish",
    "LOOP_JUDGE_PROMPT",
    "LOOP_JUDGE_PROMPT_EN",
]
