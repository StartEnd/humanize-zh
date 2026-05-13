"""humanize_zh.postprocess — ZH-defaulted thin shim over :mod:`humanize_core.postprocess`.

P2.8c collapses the postprocess pipeline onto ``humanize_core``. The
public ZH API surface (``postprocess_humanize`` keyword shape,
``_deterministic_cleanup`` test contract, ``Score`` /
``Violation`` re-exports) is preserved by translating the legacy
``replacements=`` kwarg into a per-call profile clone:

    profile = dataclasses.replace(zh_profile, replacements=table)

so the framework dispatcher's profile-based plumbing stays clean.
Callers that omit ``replacements=`` get the canonical ZH profile
straight from the registry.

Usage::

    from humanize_zh import postprocess_humanize, llm

    llm.autodetect()
    polished, after, before = postprocess_humanize(article, scene="analysis")

    # English LLM-only mode (no ZH detector)
    polished, after, _ = postprocess_humanize(article, lang="en")
"""

from __future__ import annotations

import dataclasses

from humanize_core.postprocess import (
    _BACKTICK_NUMBER_PATTERNS,
    _PROTECTED_SPAN_RE,
    _best_candidate,
    _build_writer_prompt,
    _call_llm,
    _protect_spans,
    _release_distance,
    _resolve_profile,
    _restore_spans,
    _strip_number_backticks,
)
from humanize_core.postprocess import (
    _deterministic_cleanup as _core_deterministic_cleanup,
)
from humanize_core.postprocess import (
    postprocess_humanize as _core_postprocess_humanize,
)

from . import llm as _llm_module  # noqa: F401  (legacy import path)
from ._core.protocols import ReplacementsTable
from ._lang.zh.profile import zh_profile
from ._lang.zh.replacements import _load_replacements
from .detect import Score, Violation, score  # noqa: F401  (legacy import path)
from .llm import (  # noqa: F401  (legacy import path)
    LLMError,
    LLMNotConfiguredError,
    ProviderArg,
    resolve_provider,
)
from .prompt import build_humanize_postprocess_prompt  # noqa: F401  (legacy)


class _ZhCodeReplacementsAdapter:
    """Re-stamp a user-supplied :class:`ReplacementsTable` as ``code="zh"``.

    :class:`LanguageProfile.__post_init__` enforces that every
    component's ``code`` equals the profile code, otherwise it raises
    ``ValueError`` (catches mismatched plugins early). Tests inject
    stub tables with ``code="stub"`` purely as a sentinel — they're
    *meant* as ZH overrides. This adapter wraps the stub so the
    profile clone validates while the substitution pairs and any
    other public attributes flow through unchanged.
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: ReplacementsTable) -> None:
        self._inner = inner

    @property
    def code(self) -> str:  # noqa: D401 — stub
        return "zh"

    def ordered_pairs(self) -> list[tuple[str, str]]:
        return self._inner.ordered_pairs()

    def __getattr__(self, name: str):  # forward any plugin-defined extras
        return getattr(self._inner, name)


def _profile_with_optional_replacements(
    replacements: ReplacementsTable | None,
):
    """Return ``zh_profile`` or a clone with ``replacements`` swapped.

    ``LanguageProfile`` is a frozen dataclass so we use
    :func:`dataclasses.replace` to build the override copy. Returning
    the singleton when no override is requested lets the framework
    dispatcher hit its profile-identity-cached fast path. The
    override path goes through :class:`_ZhCodeReplacementsAdapter` to
    pass the profile-component code-match check.
    """
    if replacements is None:
        return zh_profile
    if replacements.code != "zh":
        replacements = _ZhCodeReplacementsAdapter(replacements)
    return dataclasses.replace(zh_profile, replacements=replacements)


def _deterministic_cleanup(
    text: str,
    *,
    replacements: ReplacementsTable | None = None,
) -> str:
    """Mechanically scrub the highest-confidence ZH AI tells.

    Thin wrapper over :func:`humanize_core.postprocess._deterministic_cleanup`
    with the profile defaulted to ``zh_profile``. The legacy
    ``replacements=`` kwarg builds a profile clone with the table
    swapped — this preserves the v0.1.0a1 injection point used by the
    Phase-1.10 cross-language tests.
    """
    profile = _profile_with_optional_replacements(replacements)
    return _core_deterministic_cleanup(text, profile=profile)


def postprocess_humanize(
    article: str,
    *,
    scene: str = "analysis",
    lang: str = "zh",
    violations: list[Violation] | None = None,
    provider: ProviderArg = None,
    detect_first: bool = True,
    force_llm: bool = False,
    replacements: ReplacementsTable | None = None,
) -> tuple[str, Score | None, Score | None]:
    """One-pass de-AI polish, ZH-defaulted.

    Args:
        article: Source text.
        scene: ZH rule-list scene (``analysis`` / ``essay`` / ``academic`` /
            ``blog``); ignored on the EN path.
        lang: ``"zh"`` (default) for the full ZH pipeline (detect + ngram +
            LLM polish) or ``"en"`` for LLM-only English mode (skips ZH
            detection, runs the framework's EN placeholder template plus
            the language-agnostic backtick-cleanup pass).
        violations: Pre-computed violation list. ZH mode auto-detects when
            ``None``; EN ignores.
        provider: Same conventions as :mod:`humanize_zh.llm`.
        detect_first: ZH-only flag; when ``True`` (default) computes the
            ``before`` rule score so callers can show a delta.
        force_llm: Skip the "already publishable" early-return so the
            UI's "polish anyway" button always reaches the LLM.
        replacements: Optional :class:`ReplacementsTable` override. When
            present, runs the polish against a profile clone with
            ``replacements`` swapped — used by the EN-plugin dry-run
            harness and by tests asserting the injection plumbing.

    Returns:
        ``(polished_text, after_score, before_score)``. ``after_score``
        and ``before_score`` are ``None`` on the EN path (no detector).
    """
    profile = _profile_with_optional_replacements(replacements) if lang == "zh" else None
    return _core_postprocess_humanize(
        article,
        profile=profile,
        lang=lang if profile is None else None,
        scene=scene,
        violations=violations,
        provider=provider,
        detect_first=detect_first,
        force_llm=force_llm,
    )


__all__ = [
    "Score",
    "Violation",
    "score",
    "postprocess_humanize",
    "_deterministic_cleanup",
    "_load_replacements",
    "build_humanize_postprocess_prompt",
]
