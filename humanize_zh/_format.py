"""humanize_zh._format — backward-compat ZH label wrapper.

P2.8a moved the band-cutoff logic into :mod:`humanize_core._format`,
which exposes ``level_key`` (raw band id) and a labels-aware
``level_label(prob, labels)``. This module preserves the historical
zero-arg ``level_label(prob)`` API used internally by the ZH plugin
and by older tests by binding the labels argument to
:data:`humanize_zh._lang.zh.profile.ZH_LEVEL_LABELS`.

The labels themselves live on :attr:`LanguageProfile.level_labels` for
the ZH profile, so we go through the profile-owned dict (single source
of truth) instead of redefining the strings here.
"""
from __future__ import annotations

from humanize_core._format import LEVEL_KEYS, level_key
from humanize_core._format import level_label as _core_level_label

# We *re-declare* the ZH labels here rather than importing from
# ``humanize_zh._lang.zh.profile`` to avoid a circular import: the ZH
# detector imports ``level_label`` from this module, and the profile
# itself imports the detector. ``profile.py`` keeps its own copy as the
# authoritative source on ``LanguageProfile.level_labels``; both
# tables must stay in sync. There is a regression test in
# ``tests/test_protocols.py::test_zh_format_labels_match_profile`` that
# enforces equality so any future drift is caught immediately.
_ZH_LEVEL_LABELS = {
    "LOW": "LOW (基本像人写的)",
    "MEDIUM": "MEDIUM (有些 AI 痕迹)",
    "HIGH": "HIGH (大概率 AI 生成)",
    "VERY_HIGH": "VERY HIGH (几乎确定是 AI)",
}


def level_label(prob: float) -> str:
    """Map a 0-100 AI-probability score to the localized ZH label.

    Thin shim over :func:`humanize_core._format.level_label` with the
    label dict bound to the ZH labels above. The band cut-offs
    ([0,25), [25,50), [50,75), [75,100]) are owned by ``humanize_core``.
    """
    return _core_level_label(prob, _ZH_LEVEL_LABELS)


__all__ = ["level_label", "level_key", "LEVEL_KEYS"]
