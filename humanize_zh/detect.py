"""humanize_zh.detect — compat shim.

The actual implementation moved to :mod:`humanize_zh._lang.zh.detector`
as part of the multi-language refactor (see ``docs/plan-multilang.md``).
This module re-exports the public + test-imported surface so existing
imports keep working without modification:

    from humanize_zh.detect import score, Score, Violation
    from humanize_zh.detect import PATTERNS_PATH        # used by tests
    from humanize_zh.detect import _load_patterns       # used by tests
    from humanize_zh.detect import _strip_codeblocks    # used by tests

New code should prefer ``humanize_zh._lang.zh.detector`` directly, or
the protocol-typed handle ``humanize_zh._lang.zh.detector.zh_detector``.
"""
from __future__ import annotations

from ._lang.zh.detector import (
    PATTERNS_PATH,
    Score,
    Violation,
    ZhDetector,
    _load_patterns,
    _strip_codeblocks,
    main,
    score,
    zh_detector,
)

__all__ = [
    "PATTERNS_PATH",
    "Score",
    "Violation",
    "ZhDetector",
    "_load_patterns",
    "_strip_codeblocks",
    "main",
    "score",
    "zh_detector",
]


if __name__ == "__main__":
    # Preserve ``python -m humanize_zh.detect <file>`` historical CLI.
    main()
