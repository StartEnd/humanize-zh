"""Example 3: iterative — writer ↔ judge closed loop, multi-round to target.

Run (needs two distinct providers — writer ≠ judge by default):
    DEEPSEEK_API_KEY=... ANTHROPIC_API_KEY=... uv run python examples/03_iterative_loop.py

For a single-provider sanity check, set ``allow_self_judge=True`` (collusion
risk is real but useful for local debugging).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from humanize_zh import iterative_polish  # noqa: E402

ARTICLE = """
综上所述, 这个产品赋能了所有用户。

值得注意的是, 它构建了完整的闭环。首先, 它解决了用户痛点。其次, 它提供了
系统性的解决方案。最后, 它实现了价值的沉淀。

不难发现, 这种产品形态正在重塑整个行业。
"""


def main() -> None:
    result = iterative_polish(
        ARTICLE,
        rounds=3,
        target_ai_score=30,
        scene="analysis",
        writer_provider="deepseek",     # autodetected from DEEPSEEK_API_KEY
        judge_provider="anthropic",     # different model = no collusion
        allow_self_judge=False,
    )
    print(f"stopped: {result.stopped_reason}")
    print(f"writer: {result.writer_provider}, judge: {result.judge_provider}")
    print(f"rounds: {len(result.rounds)}")
    for r in result.rounds:
        print(
            f"  round {r.round}: ai_score={r.ai_score} verdict={r.verdict} "
            f"polished_len={r.polished_len}"
        )
    print()
    print("--- final ---")
    print(result.final_text)


if __name__ == "__main__":
    main()
