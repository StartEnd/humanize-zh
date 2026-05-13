"""humanize_zh._lang.zh.profile — assembled ZH language plugin.

This is the single integration point for the Chinese plugin. It wires
the four component singletons (:data:`detector.zh_detector`,
:data:`ngram.zh_ngram`, :data:`replacements.zh_replacements`, plus a
freshly-built :class:`PromptPack`) into one frozen
:class:`~humanize_zh._core.protocols.LanguageProfile` named
:data:`zh_profile`.

The profile is **constructed but not auto-registered** here — Phase
1.11 will hook ``humanize_zh/__init__.py`` to call
:func:`register_language(zh_profile, replace=True)` exactly once on
package import. Tests that need an isolated registry can construct a
fresh profile by calling :func:`make_zh_profile` directly.

Level-label migration
---------------------

The protocol's :attr:`LanguageProfile.level_labels` field exists so
that future work can drop the hard-coded Chinese strings out of
:func:`humanize_zh._format.level_label` and look them up per-language
instead. Phase 1.8 declares the labels here in canonical form; the
free function in ``_format`` continues to return the same strings,
keeping backward compatibility while preparing for the lookup-based
implementation in Phase 2/3.
"""

from __future__ import annotations

from ..._core.protocols import LanguageProfile, PromptPack
from .detector import zh_detector
from .ngram import zh_ngram
from .prompts import (
    JUDGE_PROMPT,
    LOOP_JUDGE_PROMPT,
    POSTPROCESS_PROMPT,
    build_humanize_prompt,
)
from .replacements import zh_replacements

# ─── Level labels ──────────────────────────────────────────────────────────


# Mirrors the band cut-offs in ``humanize_zh._format.level_label``:
#   [0, 25)  → LOW
#   [25, 50) → MEDIUM
#   [50, 75) → HIGH
#   [75, 100] → VERY_HIGH
#
# Keeping the strings in lockstep with that helper is verified by a
# regression test in ``tests/test_protocols.py``.
ZH_LEVEL_LABELS: dict[str, str] = {
    "LOW": "LOW (基本像人写的)",
    "MEDIUM": "MEDIUM (有些 AI 痕迹)",
    "HIGH": "HIGH (大概率 AI 生成)",
    "VERY_HIGH": "VERY HIGH (几乎确定是 AI)",
}


# ─── Prompt pack assembly ──────────────────────────────────────────────────


def _build_zh_prompt_pack() -> PromptPack:
    """Build the ZH ``PromptPack``.

    Implementation notes:

    - ``writer_user_template`` carries the existing ``POSTPROCESS_PROMPT``
      verbatim so byte-identical prompts continue to flow into the LLM.
      The protocol docstring documents canonical placeholder names
      (``{text}``, ``{violations}``, ...) but renaming the existing
      ``{ARTICLE}`` / ``{VIOLATIONS}`` / ``{HUMANIZE_RULES}`` placeholders
      would be a breaking change for anyone using the ``humanize_zh.prompt``
      surface directly. Phase 2 will introduce the canonical names as
      additional aliases without removing the legacy ones.

    - ``writer_system`` / ``judge_system`` are intentionally empty for
      this plugin: the existing ZH templates are self-contained user
      prompts and we never sent a separate system message in v0.1.0a1.
      Future plugins are free to use this slot.

    - ``rules_section`` defaults to the ``analysis`` scene because that
      is what every example and CLI flow uses today. Callers needing a
      different scene can build it on the fly via :func:`build_humanize_prompt`.
    """
    # Why ``writer_prompt_builder`` is wired up:
    #
    # The ZH writer template carries three placeholders (``{ARTICLE}``,
    # ``{VIOLATIONS}``, ``{HUMANIZE_RULES}``) plus an aggressive-mode
    # alternate template. ``humanize_core.postprocess`` (P2.5+) only
    # knows how to do naive ``str.format(ARTICLE=...)``, so without an
    # explicit builder it raises ``KeyError: 'VIOLATIONS'``. The
    # builder hook lets plugins own full assembly. We delegate to the
    # ZH-internal :func:`build_humanize_postprocess_prompt` that lives
    # in ``humanize_zh.prompt`` (it dispatches between standard /
    # aggressive templates and injects the scene-specific rules block).
    #
    # Imported lazily inside this factory function to avoid
    # ``humanize_zh.prompt`` → ``humanize_zh._lang.zh.profile`` at
    # import time (``humanize_zh.prompt`` re-exports names from this
    # module's ZH templates).
    from ...prompt import build_humanize_postprocess_prompt

    def _zh_writer_prompt_builder(
        *,
        article: str,
        violations: list,
        scene: str,
        aggressive: bool,
    ) -> str:
        return build_humanize_postprocess_prompt(
            article,
            violations,
            scene=scene,
            lang="zh",
            aggressive=aggressive,
        )

    return PromptPack(
        code="zh",
        writer_system="",
        writer_user_template=POSTPROCESS_PROMPT,
        judge_system="",
        judge_user_template=JUDGE_PROMPT,
        loop_judge_user_template=LOOP_JUDGE_PROMPT,
        rules_section=build_humanize_prompt(scene="analysis"),
        writer_prompt_builder=_zh_writer_prompt_builder,
    )


# ─── Profile factory ───────────────────────────────────────────────────────


def make_zh_profile() -> LanguageProfile:
    """Build a fresh ``LanguageProfile`` for ``zh``.

    Tests should prefer calling this over importing :data:`zh_profile`
    when they need a profile that does not share state with the
    process-global singleton. Production callers (Web UI, CLI) use the
    singleton via :func:`humanize_zh._core.language_registry.get_language`.
    """
    return LanguageProfile(
        code="zh",
        display_name="中文 (简体)",
        detector=zh_detector,
        ngram_engine=zh_ngram,
        replacements=zh_replacements,
        prompt_pack=_build_zh_prompt_pack(),
        level_labels=dict(ZH_LEVEL_LABELS),  # defensive copy, frozen profile keeps its own dict
        metadata={
            "corpus": "HC3-Chinese",
            "rule_set_version": zh_detector.version,
            "ngram_corpus_id": zh_ngram.corpus_id,
        },
    )


# Singleton consumed by Phase 1.11's auto-registration hook in
# ``humanize_zh/__init__.py``. Built exactly once at import time so the
# four component singletons (which themselves cache JSON loads) are not
# re-parsed for every web request.
zh_profile: LanguageProfile = make_zh_profile()


__all__ = [
    "ZH_LEVEL_LABELS",
    "make_zh_profile",
    "zh_profile",
]
