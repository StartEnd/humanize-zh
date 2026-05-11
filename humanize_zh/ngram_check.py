"""humanize_zh.ngram_check — compat shim.

The actual implementation moved to :mod:`humanize_zh._lang.zh.ngram` as
part of the multi-language refactor (see ``docs/plan-multilang.md``).
This module re-exports the public + test-imported surface so existing
imports keep working without modification:

    from humanize_zh.ngram_check import ngram_score, NgramScore
    from humanize_zh.ngram_check import _load_engine          # used by tests
    from humanize_zh.ngram_check import _ENGINE_LOAD_ERROR    # used by tests

New code should prefer ``humanize_zh._lang.zh.ngram`` directly, or the
protocol-typed handle ``humanize_zh._lang.zh.ngram.zh_ngram``.
"""
from __future__ import annotations

from ._lang.zh.ngram import (
    _ENGINE,
    _ENGINE_LOAD_ERROR,
    _ENGINE_PATH,
    DATA_DIR,
    NgramScore,
    ZhNgramEngine,
    _load_engine,
    _safe_call,
    main,
    ngram_score,
    zh_ngram,
)

__all__ = [
    "DATA_DIR",
    "NgramScore",
    "ZhNgramEngine",
    "_ENGINE",
    "_ENGINE_LOAD_ERROR",
    "_ENGINE_PATH",
    "_load_engine",
    "_safe_call",
    "main",
    "ngram_score",
    "zh_ngram",
]


if __name__ == "__main__":
    # Preserve ``python -m humanize_zh.ngram_check <file>`` historical CLI.
    main()
