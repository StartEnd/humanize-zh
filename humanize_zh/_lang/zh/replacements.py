"""humanize_zh._lang.zh.replacements — ZH replacement table.

Loads deterministic word/phrase replacement pairs from the ZH plugin's
``data/replacements.json`` and exposes them via the
:class:`~humanize_zh._core.protocols.ReplacementsTable` protocol.

This module is the single source of truth for replacement-pair loading.
``humanize_zh.postprocess`` imports :func:`_load_replacements` from here
rather than reading the JSON itself, so the lru-cached parse and the
ordering guarantees live in exactly one place.

Ordering rules (preserved from the pre-refactor implementation):

1. Buckets apply in the order declared by ``replacements._order``,
   falling back to insertion order if absent.
2. Within each bucket, pairs sort by ``len(old)`` descending so longer
   phrases match before shorter substrings they contain (e.g.
   ``可能已经`` wins over a hypothetical ``可能`` rule in the same bucket).

Failure mode: on JSON parse / IO failure, log and return an empty tuple
so the polish pipeline degrades to a no-op rather than crashing.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Phase 1.6 split patterns.json into rules.json + replacements.json.
# This file owns only the replacement pairs; rules live in rules.json
# and are loaded by ``humanize_zh._lang.zh.detector``.
REPLACEMENTS_PATH = Path(__file__).parent / "data" / "replacements.json"


@lru_cache(maxsize=1)
def _load_replacements() -> tuple[tuple[str, str], ...]:
    """Load deterministic replacement pairs from ``replacements.json``.

    See module docstring for ordering rules. Returns a flat tuple so
    callers can iterate without re-parsing JSON.
    """
    try:
        data = json.loads(REPLACEMENTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.error("[humanize_zh] cannot load %s: %s", REPLACEMENTS_PATH, e)
        return ()
    section = data.get("replacements") or {}
    order = section.get("_order") or [
        k for k in section if not k.startswith("_") and isinstance(section[k], list)
    ]
    pairs: list[tuple[str, str]] = []
    for bucket in order:
        items = section.get(bucket)
        if not isinstance(items, list):
            continue
        bucket_pairs: list[tuple[str, str]] = []
        for entry in items:
            if (
                isinstance(entry, list)
                and len(entry) == 2
                and isinstance(entry[0], str)
                and isinstance(entry[1], str)
            ):
                bucket_pairs.append((entry[0], entry[1]))
        bucket_pairs.sort(key=lambda p: -len(p[0]))
        pairs.extend(bucket_pairs)
    return tuple(pairs)


# ─── Protocol adapter ─────────────────────────────────────────────────────


class ZhReplacementsTable:
    """Thin :class:`~humanize_zh._core.protocols.ReplacementsTable` adapter
    around :func:`_load_replacements`.

    The underlying loader is ``lru_cache``-d, so repeated calls to
    :meth:`ordered_pairs` cost only a function dispatch.
    """

    code = "zh"

    def ordered_pairs(self) -> tuple[tuple[str, str], ...]:
        return _load_replacements()


# Singleton — imported by ``humanize_zh._lang.zh.profile`` and downstream.
zh_replacements = ZhReplacementsTable()
