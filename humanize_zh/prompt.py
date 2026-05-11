"""humanize_zh.prompt — compat shim.

The implementation moved as part of the multi-language refactor (see
``docs/plan-multilang.md``):

- ZH-specific section constants, ``SCENES``, ``build_humanize_prompt``,
  and the ZH postprocess templates live in
  :mod:`humanize_zh._lang.zh.prompts`.
- The cross-language dispatcher
  :func:`build_humanize_postprocess_prompt` and the placeholder
  ``POSTPROCESS_PROMPT_EN`` template live in
  :mod:`humanize_zh._core.prompt`.

This shim re-exports both surfaces so existing imports keep working:

    from humanize_zh.prompt import build_humanize_prompt              # ZH builder
    from humanize_zh.prompt import build_humanize_postprocess_prompt  # dispatcher
    from humanize_zh.prompt import SCENES, POSTPROCESS_PROMPT_EN      # constants

New code should import directly from the canonical modules.
"""
from __future__ import annotations

from ._core.prompt import (
    POSTPROCESS_PROMPT_EN,
    build_humanize_postprocess_prompt,
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

__all__ = [
    "ASSERTION_TEMPLATE",
    "CORE_RULES",
    "HARD_LIMITS",
    "HARD_NEVER",
    "OPENING_DIVERSITY",
    "POSTPROCESS_PROMPT",
    "POSTPROCESS_PROMPT_AGGRESSIVE",
    "POSTPROCESS_PROMPT_EN",
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
