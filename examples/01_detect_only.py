"""Example 1: detect-only — three-layer scoring with no LLM dependency.

Run:
    uv run python examples/01_detect_only.py

The detect (rule) and ngram (statistical) layers are pure Python and run in
milliseconds. The combined score takes the max of the two — any layer
flagging HIGH triggers the release gate.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from humanize_zh import combined_score, ngram_score, score  # noqa: E402

ARTICLE = """
综上所述, 这个产品赋能了所有用户。

值得注意的是, 它构建了完整的闭环。首先, 它解决了用户痛点。其次, 它提供了
系统性的解决方案。最后, 它实现了价值的沉淀。

不难发现, 这种产品形态正在重塑整个行业。
"""


def main() -> None:
    rule = score(ARTICLE)
    print(f"Layer 1 (rule):  {rule.total:.1f}/100  ({rule.level})")
    print(f"  fired {len(rule.violations)} violations")

    ng = ngram_score(ARTICLE)
    if ng.available:
        print(f"Layer 2 (ngram): {ng.ai_probability:.1f}/100  ({ng.level})")
    else:
        print("Layer 2 (ngram): unavailable")

    cs = combined_score(ARTICLE)
    print(f"\nCombined: {cs.combined_probability:.1f}/100  ({cs.combined_level})")
    print("  decision:", "BLOCK" if cs.combined_probability >= 50 else "OK")


if __name__ == "__main__":
    main()
