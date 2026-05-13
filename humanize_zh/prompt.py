"""humanize_zh.prompt — ZH plugin prompt assembly.

P2.8b note: the EN placeholder templates
(``POSTPROCESS_PROMPT_EN`` / ``JUDGE_PROMPT_EN`` / ``LOOP_JUDGE_PROMPT_EN``)
live in :mod:`humanize_core.prompt` because they are framework-level
fallbacks shared by every plugin. The ZH-specific section constants
and the rule-list builder still live in :mod:`humanize_zh._lang.zh.prompts`.
This module:

- re-exports the framework EN placeholders for backward compat,
- re-exports the ZH section constants + ``build_humanize_prompt``,
- owns :func:`build_humanize_postprocess_prompt` — the ZH postprocess
  prompt dispatcher with rule-list injection. The function used to
  live in ``humanize_zh._core.prompt``; P2.8b moved it here because
  rule-list injection is plugin-internal (the EN path is just LLM-only
  and does not consult any rule list).

The legacy import path
``from humanize_zh._core.prompt import build_humanize_postprocess_prompt``
is preserved by the back-compat shim in ``humanize_zh._core/prompt.py``.
"""
from __future__ import annotations

from humanize_core.prompt import (
    JUDGE_PROMPT_EN,
    LOOP_JUDGE_PROMPT_EN,
    POSTPROCESS_PROMPT_EN,
)

from ._lang.zh.prompts import (
    ASSERTION_TEMPLATE,
    CORE_RULES,
    HARD_LIMITS,
    HARD_NEVER,
    OPENING_DIVERSITY,
    POSTPROCESS_PROMPT,
    POSTPROCESS_PROMPT_AGGRESSIVE,
    SCENES,
    SELF_CHECK,
    SOUL_INJECTION,
    WORDS_BLACKLIST,
    build_humanize_prompt,
)


def build_humanize_postprocess_prompt(
    article: str,
    violations: list,
    scene: str = "analysis",
    *,
    lang: str = "zh",
    aggressive: bool = False,
) -> str:
    """Assemble the postprocess (de-AI polishing) prompt.

    The function picks one of three template paths:

    1. ``lang="en"`` → :data:`POSTPROCESS_PROMPT_EN` (LLM-only, no
       rule-list injection — the 5 principles are inlined in the
       template itself).
    2. ``lang="zh"`` + ``aggressive=True`` → ZH aggressive rewrite
       template (used when a third-party AI detector still reports
       high score after the standard pass — rewrites sentence
       structure rather than just word choice).
    3. ``lang="zh"`` + default → ZH standard template with the rule
       list and the violation summary injected.

    Args:
        article:    The article to polish.
        violations: Output from :func:`humanize_zh.detect.score`.
                    Ignored when ``lang="en"``.
        scene:      ZH-mode rule-list scene (analysis / essay /
                    academic / blog).
        lang:       ``"zh"`` (default) or ``"en"``.
        aggressive: ZH-only flag for the strong-rewrite template.

    Returns:
        The fully-assembled prompt string.
    """
    if lang == "en":
        return POSTPROCESS_PROMPT_EN.format(ARTICLE=article)

    if violations:
        viol_text = "\n".join(
            f"- {v.category}.{v.rule}: 命中 {v.count} 次 | 例: 「{v.sample[:40]}」"
            for v in violations[:30]
        )
    else:
        viol_text = "(规则扫描器未命中, 但第三方检测器仍报高分 - 问题在句式结构)"

    if aggressive:
        return POSTPROCESS_PROMPT_AGGRESSIVE.format(
            ARTICLE=article,
            VIOLATIONS=viol_text,
        )

    rules = build_humanize_prompt(scene=scene, compact=True)
    return POSTPROCESS_PROMPT.format(
        ARTICLE=article,
        VIOLATIONS=viol_text,
        HUMANIZE_RULES=rules,
    )


__all__ = [
    "ASSERTION_TEMPLATE",
    "CORE_RULES",
    "HARD_LIMITS",
    "HARD_NEVER",
    "OPENING_DIVERSITY",
    "POSTPROCESS_PROMPT",
    "POSTPROCESS_PROMPT_AGGRESSIVE",
    "POSTPROCESS_PROMPT_EN",
    "JUDGE_PROMPT_EN",
    "LOOP_JUDGE_PROMPT_EN",
    "SCENES",
    "SELF_CHECK",
    "SOUL_INJECTION",
    "WORDS_BLACKLIST",
    "build_humanize_postprocess_prompt",
    "build_humanize_prompt",
]


if __name__ == "__main__":
    # Preserve historical CLI: ``python -m humanize_zh.prompt`` prints the
    # default analysis-scene rules section to stdout.
    print(build_humanize_prompt("analysis"))
