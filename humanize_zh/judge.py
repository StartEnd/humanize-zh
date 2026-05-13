#!/usr/bin/env python3
"""humanize_zh.judge — ZH-defaulted thin shim over :mod:`humanize_core.judge`.

P2.8c collapses the LLM final-review pass onto humanize-core. This
module:

- delegates :func:`judge` to humanize-core with ``lang="zh"`` defaulted,
- keeps a *ZH-localized* :func:`format_report` (the framework version
  emits English), so callers / web templates / CLI summaries that
  expect 「## 终审结果: ✅ 可发表」-style output keep working byte-for-byte,
- preserves the legacy ``main()`` CLI for ``python -m humanize_zh.judge``.

Backward-compat re-exports (``JUDGE_PROMPT``, ``JUDGE_PROMPT_EN``,
``_call_llm``, ``_parse_json``) point at the canonical homes
(``humanize_zh._lang.zh.prompts`` for the ZH template,
``humanize_core.prompt`` / ``humanize_core.judge`` for the rest).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from humanize_core.judge import _call_llm, _parse_json, _resolve_profile  # noqa: F401
from humanize_core.judge import judge as _core_judge

from . import llm as _llm_module
from ._core.protocols import LanguageProfile
from ._lang.zh.prompts import JUDGE_PROMPT  # noqa: F401  (legacy re-export)
from .llm import (  # noqa: F401  (legacy re-exports)
    LLMError,
    LLMNotConfiguredError,
    LLMProvider,
    ProviderArg,
    provider_id,
    resolve_provider,
)
from .prompt import JUDGE_PROMPT_EN  # noqa: F401  (legacy re-export)

logger = logging.getLogger(__name__)


def judge(
    article: str,
    *,
    lang: str = "zh",
    profile: LanguageProfile | None = None,
    writer_provider: ProviderArg = None,
    judge_provider: ProviderArg = None,
    allow_self_judge: bool = False,
) -> dict[str, Any]:
    """Run the LLM final-review pass on ``article``.

    Thin wrapper over :func:`humanize_core.judge.judge`. The only
    behavioral difference is the default ``lang="zh"`` so calls from
    pre-P2.8c code paths keep working without an explicit ``lang=``.

    All other args are forwarded verbatim. See the canonical
    docstring on the framework function for collusion-detection
    semantics, ``_meta`` / ``_error`` envelopes, and provider
    resolution rules.
    """
    return _core_judge(
        article,
        profile=profile,
        lang=lang,
        writer_provider=writer_provider,
        judge_provider=judge_provider,
        allow_self_judge=allow_self_judge,
    )


def format_report(result: dict[str, Any]) -> str:
    """Render :func:`judge`'s JSON output as a ZH-localized Markdown report.

    P2.8c keeps this localized rather than delegating to
    :func:`humanize_core.judge.format_report` because:

    1. The CLI / Web UI / saved ``*.judge.md`` files all carry
       Chinese section headers (``## 终审结果``, ``### 最强的判断``,
       ``⚠️ 高风险``); switching to English would be a user-visible
       regression.
    2. ``format_report`` is *output formatting* — that is exactly the
       piece of the pipeline that should be plugin-localized rather
       than centralized in the framework.
    3. The framework version still exists for plugins that prefer
       English output; humanize-zh just doesn't use it.
    """
    if "_error" in result:
        return f"[judge] 错误: {result['_error']}"
    if "_parse_error" in result:
        return f"[judge] JSON 解析失败: {result['_parse_error']}\n\n原始:\n{result.get('_raw', '')}"

    lines: list[str] = []
    publishable = bool(result.get("publishable", False))
    lines.append(f"## 终审结果: {'✅ 可发表' if publishable else '❌ 需修改'}")
    lines.append("")

    if best := result.get("best_theses"):
        lines.append(f"### 最强的判断 ({len(best)} 条)")
        for t in best:
            lines.append(f"- {t}")
        lines.append("")

    if worst := result.get("worst_ai_sections"):
        lines.append(f"### 最像 AI 写的段落 ({len(worst)} 处)")
        for w in worst:
            if isinstance(w, dict):
                lines.append(f"- 「{w.get('para', '?')}...」 — {w.get('reason', '?')}")
            else:
                lines.append(f"- {w}")
        lines.append("")

    if claims := result.get("unsupported_claims"):
        lines.append(f"### 无证据支撑的判断 ({len(claims)} 条)")
        for c in claims:
            if isinstance(c, dict):
                lines.append(f"- 「{c.get('claim', '?')}」 缺失: {c.get('missing_evidence', '?')}")
            else:
                lines.append(f"- {c}")
        lines.append("")

    if smell := result.get("template_smell"):
        lines.append(f"### 模板感问题 ({len(smell)} 处)")
        for s in smell:
            lines.append(f"- {s}")
        lines.append("")

    if fake := result.get("fake_human_details"):
        lines.append(f"### 编造的人味细节 ({len(fake)} 处) ⚠️ 高风险")
        for f in fake:
            lines.append(f"- {f}")
        lines.append("")

    if brief := result.get("rewrite_brief"):
        lines.append("### 改稿建议")
        lines.append(brief)

    if meta := result.get("_meta"):
        lines.append("")
        lines.append(
            f"---\n*judge: {meta.get('judge_provider')} | "
            f"writer: {meta.get('writer_provider')} | "
            f"article: {meta.get('article_length'):,} 字符*"
        )
    return "\n".join(lines)


def main() -> None:
    # 轻量 CLI, 完整 CLI 在 humanize_zh.cli.
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) < 2:
        print(
            "usage: python -m humanize_zh.judge <file> [--lang zh|en] "
            "[--writer <provider>] [--judge <provider>] [--json] [--allow-self-judge]"
        )
        print()
        print(
            "Provider names: openai | anthropic | deepseek | groq | openrouter | "
            "moonshot | glm | qwen | ollama"
        )
        print(
            "Omit both --writer and --judge to use the active / "
            "autodetected provider for judging."
        )
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"error: file not found: {path}")
        sys.exit(1)

    lang = "zh"
    writer = None
    judge_p = None
    allow_self = "--allow-self-judge" in sys.argv
    out_json = "--json" in sys.argv
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--lang" and i + 1 < len(args):
            lang = args[i + 1]
            i += 2
        elif a == "--writer" and i + 1 < len(args):
            writer = args[i + 1]
            i += 2
        elif a == "--judge" and i + 1 < len(args):
            judge_p = args[i + 1]
            i += 2
        else:
            i += 1

    if (
        judge_p is None
        and not _llm_module.has_active()
        and _llm_module.autodetect() is None
    ):
        print(
            "error: no LLM provider configured. Set one of "
            "OPENAI_API_KEY / ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / ..."
        )
        sys.exit(2)

    article = path.read_text(encoding="utf-8")
    result = judge(
        article,
        lang=lang,
        writer_provider=writer,
        judge_provider=judge_p,
        allow_self_judge=allow_self,
    )

    if out_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))

    if not out_json:
        report_path = path.with_suffix(".judge.md")
        report_path.write_text(format_report(result), encoding="utf-8")
        print(f"\nreport saved: {report_path}")


if __name__ == "__main__":
    main()


__all__ = ["judge", "format_report", "main", "JUDGE_PROMPT", "JUDGE_PROMPT_EN"]
