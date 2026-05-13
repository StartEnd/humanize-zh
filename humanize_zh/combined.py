"""humanize_zh.combined — backward-compat ZH wrapper.

P2.8b collapses the three-layer aggregator onto
:func:`humanize_core.combined.combined_score`, which now takes an
explicit ``lang=`` (or pre-resolved ``profile=``) and drives the
detect / ngram layers through :class:`LanguageProfile`. Old callers of
``humanize_zh.combined.combined_score(text, has_notes=...)`` keep
working — we default ``lang="zh"`` here.

The public dataclass :class:`CombinedScore` is re-exported from
``humanize_core`` *unchanged*. Compared to the v0.1.0a1 ZH-only class,
the new one adds a ``lang`` field at the end (default ``""``), so old
positional / keyword construction continues to type-check.

Internals diverge from the legacy ZH-only path in one place that
shows up in tests: the ngram layer now goes through
``profile.ngram_engine.score(text)`` instead of
``humanize_zh.ngram_check.ngram_score``. Tests that simulated engine
failure by patching the latter must patch the former (or the
``ZhNgramEngine.score`` method) — see
``tests/test_combined.py::test_combined_falls_back_to_rule_when_ngram_engine_fails``.
"""

from __future__ import annotations

from humanize_core.combined import CombinedScore
from humanize_core.combined import combined_score as _core_combined_score


def combined_score(text: str, has_notes: bool = False) -> CombinedScore:
    """ZH-defaulted wrapper over :func:`humanize_core.combined.combined_score`.

    See the canonical implementation for full semantics. This shim
    only locks ``lang="zh"`` so existing two-arg callers keep working.

    Args:
        text:      Text to score.
        has_notes: Whether the document has real operation notes
                   attached (affects the rule layer's fake-human heuristics).

    Returns:
        :class:`CombinedScore` aggregating rule + ngram layers.
    """
    return _core_combined_score(text, has_notes=has_notes, lang="zh")


__all__ = ["CombinedScore", "combined_score"]
