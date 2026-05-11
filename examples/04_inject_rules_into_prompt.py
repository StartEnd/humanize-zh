"""Example 4: inject the humanize rules section into your own writing prompt.

Run:
    uv run python examples/04_inject_rules_into_prompt.py

This is the cheapest integration mode: pull the rules block at template
build time, splice it into your prompt, and let the LLM avoid the AI tells
*during generation* rather than fixing them afterward.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from humanize_zh import build_humanize_prompt  # noqa: E402

MY_TEMPLATE = """\
你是一位资深中文专栏作者. 写一篇关于 {topic} 的深度分析,
800-1200 字, 必须遵守下面的写作纪律:

{HUMANIZE_RULES}

正式开始写作:
"""


def main() -> None:
    rules = build_humanize_prompt(scene="analysis")  # 或 essay / academic / blog
    full_prompt = MY_TEMPLATE.format(
        topic="独立开发者的 SaaS 增长路径",
        HUMANIZE_RULES=rules,
    )
    print(f"final prompt length: {len(full_prompt):,} chars")
    print()
    print(full_prompt[:600] + "\n... (truncated for display) ...")


if __name__ == "__main__":
    main()
