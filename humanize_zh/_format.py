"""humanize_zh._format — shared formatting helpers for score reporting.

Three modules (``detect`` / ``ngram_check`` / ``combined``) used to carry
identical copies of the ``_level()`` Chinese label mapping. Any drift between
them — e.g. a tweaked threshold — would surface as inconsistent ``LOW`` /
``HIGH`` labels for the same numeric probability. This module is the single
source of truth.

Calibration source: HC3-Chinese 300+300 human/AI samples (see ``_meta`` in
``patterns.json``).
"""
from __future__ import annotations


def level_label(prob: float) -> str:
    """Map a 0-100 AI-probability score to a human-readable Chinese label.

    Thresholds (inclusive of lower bound):
        - ``[0, 25)``  → ``LOW (基本像人写的)``
        - ``[25, 50)`` → ``MEDIUM (有些 AI 痕迹)``
        - ``[50, 75)`` → ``HIGH (大概率 AI 生成)``
        - ``[75, 100]`` → ``VERY HIGH (几乎确定是 AI)``

    Args:
        prob: AI probability in the range ``[0, 100]``. Values outside the
            range are clamped to the nearest band (no exception).

    Returns:
        Localized Chinese label string ready for CLI / Web rendering.
    """
    if prob < 25:
        return "LOW (基本像人写的)"
    if prob < 50:
        return "MEDIUM (有些 AI 痕迹)"
    if prob < 75:
        return "HIGH (大概率 AI 生成)"
    return "VERY HIGH (几乎确定是 AI)"


__all__ = ["level_label"]
