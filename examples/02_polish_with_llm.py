"""Example 2: polish — call an LLM to rewrite the AI tells out.

Run (after exporting one of: OPENAI_API_KEY / DEEPSEEK_API_KEY / ...):
    uv run python examples/02_polish_with_llm.py

If you use a local OpenAI relay, set OPENAI_API_KEY=<relay-key> and
``OPENAI_BASE_URL=http://127.0.0.1:8080/v1``; the SDK picks up base_url
automatically when ``OpenAIProvider`` is built without an explicit override.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from humanize_zh import postprocess_humanize  # noqa: E402

ARTICLE = """
综上所述, 这个产品赋能了所有用户。

值得注意的是, 它构建了完整的闭环。首先, 它解决了用户痛点。其次, 它提供了
系统性的解决方案。最后, 它实现了价值的沉淀。

不难发现, 这种产品形态正在重塑整个行业。
"""


def main() -> None:
    polished, after, before = postprocess_humanize(
        ARTICLE,
        scene="analysis",  # essay / academic / blog also supported
        # provider=None  # auto-detect from env (OPENAI_API_KEY / ...).
        # provider="deepseek"  # or pin a specific provider name.
    )
    if before is None:
        print("(zh detection skipped — likely lang=en path)")
    else:
        print(f"before: {before.total:.1f}/100  ({before.level})")
    if after is not None:
        print(f"after:  {after.total:.1f}/100  ({after.level})")
    print()
    print("--- polished article ---")
    print(polished)


if __name__ == "__main__":
    if not any(os.environ.get(k) for k in (
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
        "GROQ_API_KEY", "OPENROUTER_API_KEY", "MOONSHOT_API_KEY",
        "GLM_API_KEY", "DASHSCOPE_API_KEY", "OLLAMA_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
    )):
        print(
            "warning: no LLM provider env vars detected — postprocess_humanize "
            "will fall back to deterministic cleanup only."
        )
    main()
