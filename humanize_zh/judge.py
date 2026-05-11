#!/usr/bin/env python3
"""humanize_zh.judge — LLM 终审层

规则检测器 (detect.py) 便宜、快, 适合 CI; LLM 判官慢、贵, 适合终审。
两者 **不要混在一个总分里**, 各自输出, 由人或 pipeline 决定后续动作。

判官输出严格的 JSON, 包含 7 个字段 (codex 在 .agent-chat/dialogue.md Turn 003 设计):

    {
      "publishable": false,
      "worst_ai_sections": [
        {"para": "第三段...", "reason": "三段式套路 + 模糊归因"}
      ],
      "unsupported_claims": [
        {"claim": "运营者是单兵", "missing_evidence": "没引用 sitemap 工整度"}
      ],
      "template_smell": ["整篇按 5W2H 分节, 每节长度近似一致, 像填空"],
      "fake_human_details": ["第七段「凌晨三点」是 AI 编造的, 数据里没有这个时间点"],
      "best_theses": ["Direct 52% 实际是付费引荐二次回访 — 这个判断有 3 条证据支撑"],
      "rewrite_brief": "重点改第三段和第七段, 删去伪场景, 把「专家认为」改为具体出处"
    }

防 LLM 共谋: 默认强制 judge_provider != writer_provider (按 name+model 比较).

用法:
    from humanize_zh import llm
    from humanize_zh.judge import judge

    llm.use_openai_compat(name="deepseek", ...)  # writer
    writer = llm.get_active()

    # 换个 provider 做 judge, 防共谋
    llm.use("anthropic", api_key="sk-ant-...")
    judge_provider = llm.get_active()

    result = judge(article_text, writer_provider=writer, judge_provider=judge_provider)
    if not result["publishable"]:
        print(result["rewrite_brief"])

CLI:
    python -m humanize_zh.judge <file> [--lang zh|en] [--allow-self-judge]
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from . import llm as _llm_module
from .llm import (
    LLMError,
    LLMNotConfiguredError,
    LLMProvider,
    ProviderArg,
    provider_id,
    resolve_provider,
)

logger = logging.getLogger(__name__)


JUDGE_PROMPT = """# 任务: 给一篇网站分析文章做终审编辑审稿

你是一位独立编辑, 专门审稿"网站流量深度分析"类的中文长文。
你不写文章, 不点评作者, 只输出**结构化的审稿意见 JSON**。

## 评判标准

文章发表标准是: **读者愿意相信、愿意转发、读完能记住 1-2 个判断**。

具体标准:
1. **有可反驳的判断** — 不是常识句(「用户体验很重要」), 是能被一句反例推翻的具体断言
2. **判断背后有证据链** — 每个核心断言后跟 ≥ 2 条具体数据或事实
3. **结构由问题驱动** — 不是模板填空(总分总 / 11 节大纲 / 5W2H 套壳)
4. **没有伪人味** — 没有编造的具体场景(凌晨三点 / 周三晚上)、没有虚构的第一人称经历(去年我接触过)、没有编造的对话(他在 Discord 里告诉我)
5. **能记住 1-2 个判断** — 读完后读者应该能复述至少一个反直觉的具体结论

## 你必须输出的 JSON

严格按以下 schema, 不要加 markdown 代码块包裹:

```
{{
  "publishable": <bool>,
  "worst_ai_sections": [
    {{"para": "<原文段落第一句的前 30 字>", "reason": "<具体的 AI 体特征>"}}
  ],
  "unsupported_claims": [
    {{"claim": "<原文里的判断>", "missing_evidence": "<缺失的证据类型>"}}
  ],
  "template_smell": [
    "<具体的模板感描述, 不是空话>"
  ],
  "fake_human_details": [
    "<编造的具体场景或经历, 写出原文片段>"
  ],
  "best_theses": [
    "<文章里最强的判断, 写出原文片段, 说明为什么强>"
  ],
  "rewrite_brief": "<3-5 句话告诉作者重点改哪里, 不超过 200 字>"
}}
```

## 字段说明

- `publishable`: true 仅当所有问题都是小问题, 且 best_theses 至少 1 条
- `worst_ai_sections`: 最像 AI 写的 2-5 段(不是全部, 只挑最差的)
- `unsupported_claims`: 没有数据支撑的判断, 最多 5 条
- `template_smell`: 文章是否按模板填空, 给具体例子(不是"有点模板感"这种空话)
- `fake_human_details`: 凌晨三点 / 去年我 / 朋友买过 / 他在 Discord 告诉我 等编造场景
- `best_theses`: 最强的 1-3 个判断 — 这些可以保留
- `rewrite_brief`: 给作者的 3-5 句话改稿建议, 不要废话

## 严禁

- 不要在 JSON 外加任何文字、解释、markdown
- 不要在每个字段值里加 emoji
- 不要给出"很好"、"还需努力"类空话
- 不要重复检测器规则能抓的事(禁词、句式), 只看语义层面

---

## 待审稿文章

{ARTICLE}
"""


# ── 英文 judge prompt (用于 lang="en" 英文文章终审) ─────────────────
JUDGE_PROMPT_EN = """# Task: Final editorial review of a long-form English article

You are an independent editor reviewing deep-analysis long-form articles.
You do not rewrite the piece. You output a **structured JSON review only**.

## Bar for publication

Publishable = a reader will believe it, share it, and remember 1-2 concrete
takeaways after closing the tab.

Concrete criteria:
1. **Falsifiable claims** — not universal truisms, but specific assertions
   that a counter-example could refute.
2. **Each claim has evidence chain** — every core assertion backed by ≥2
   specific numbers or facts.
3. **Structure driven by questions** — not template filling (intro / body /
   conclusion / 5W2H shell).
4. **No fabricated human flavor** — no invented scenes ("at 3am last Tuesday"),
   no fake first-person experience ("a founder told me"), no made-up quotes.
5. **Memorable takeaways** — reader can restate ≥1 counter-intuitive concrete
   conclusion from memory.

## Required JSON output (no markdown wrapper)

```
{{
  "publishable": <bool>,
  "worst_ai_sections": [
    {{"para": "<first 30 chars of paragraph>", "reason": "<specific AI tell>"}}
  ],
  "unsupported_claims": [
    {{"claim": "<claim from article>", "missing_evidence": "<what's missing>"}}
  ],
  "template_smell": ["<concrete templated structure, not vague>"],
  "fake_human_details": ["<fabricated scene / experience quoted from article>"],
  "best_theses": ["<strongest claim, quoted, why it works>"],
  "rewrite_brief": "<3-5 sentences telling the author what to change, <200 chars>"
}}
```

## Field notes

- `publishable`: true only if all issues are minor AND ≥1 best_thesis.
- `worst_ai_sections`: pick the worst 2-5 (not all paragraphs).
- `unsupported_claims`: up to 5.
- `template_smell`: give concrete examples, not vague "feels a bit template".
- `fake_human_details`: quote exact fabricated passages.
- `best_theses`: 1-3 strongest claims with reasoning.
- `rewrite_brief`: 3-5 sentences, no fluff.

## Forbidden

- No text outside the JSON (no markdown fences, no explanation).
- No emoji inside field values.
- No platitudes ("good start", "needs work").
- Do not duplicate things a regex detector already catches (bad phrases,
  cliche sentences); focus on semantic issues.

---

## Article under review

{ARTICLE}
"""


def _call_llm(prompt: str, *, provider: LLMProvider) -> str | None:
    """Call the LLM with the judge prompt. Returns None on failure."""
    try:
        resp = provider.complete(prompt)
    except LLMError as e:
        logger.error("[humanize_zh.judge] LLM call failed (%s): %s", provider.name, e)
        return None
    except Exception as e:
        logger.exception("[humanize_zh.judge] unexpected LLM error (%s): %s", provider.name, e)
        return None
    return resp.text or None


def _parse_json(raw: str) -> dict[str, object]:
    """从 LLM 输出里抽 JSON 对象, 容错"""
    if not raw:
        return {}
    # 去 markdown 包裹
    s = raw.strip()
    if s.startswith("```"):
        # 找第一个 { 和最后一个 }
        i = s.find("{")
        j = s.rfind("}")
        if i >= 0 and j > i:
            s = s[i:j + 1]
    elif s.startswith("{") and s.endswith("}"):
        pass
    else:
        i = s.find("{")
        j = s.rfind("}")
        if i >= 0 and j > i:
            s = s[i:j + 1]
        else:
            return {"_parse_error": "no json found", "_raw": raw[:500]}

    try:
        parsed = json.loads(s)
    except json.JSONDecodeError as e:
        return {"_parse_error": str(e), "_raw": raw[:500]}
    if not isinstance(parsed, dict):
        return {"_parse_error": "expected JSON object", "_raw": raw[:500]}
    return parsed


def judge(
    article: str,
    *,
    lang: str = "zh",
    writer_provider: ProviderArg = None,
    judge_provider: ProviderArg = None,
    allow_self_judge: bool = False,
) -> dict:
    """对一篇文章调 LLM 做终审.

    Args:
        article: 待审文章 (原始 markdown)
        lang: "zh" (默认, 中文 judge prompt) 或 "en" (英文 judge prompt)
        writer_provider: 写作用的 provider (用于防共谋, 仅作标识; 不实际调用).
                         支持: LLMProvider 实例 | str | None
        judge_provider:  评审 provider. 支持: LLMProvider 实例 | str | None
                         None 时使用全局 active (并警告若与 writer_provider 同).
        allow_self_judge: 允许同 provider+model 自审(不推荐, 共谋风险高).

    Returns:
        7 字段结构化 JSON dict, 失败时返回 {"_error": ...}
    """
    if lang not in ("zh", "en"):
        return {"_error": f"lang must be 'zh' or 'en', got {lang!r}"}

    # resolve writer (可选, 仅作标识)
    writer_resolved: LLMProvider | None = None
    if writer_provider is not None:
        try:
            writer_resolved = resolve_provider(writer_provider)
        except (LLMNotConfiguredError, ValueError, TypeError) as e:
            return {"_error": f"cannot resolve writer_provider: {e}"}

    # resolve judge (必需)
    try:
        judge_resolved = resolve_provider(judge_provider)
    except LLMNotConfiguredError as e:
        return {
            "_error": (
                "no judge provider configured; pass judge_provider= or call "
                f"llm.autodetect() / llm.use(...) first ({e})"
            )
        }
    except (ValueError, TypeError) as e:
        return {"_error": f"cannot resolve judge_provider: {e}"}

    # collusion check: same (name, model) = same model talking to itself
    writer_id = provider_id(writer_resolved)
    judge_id = provider_id(judge_resolved)
    if writer_id is not None and writer_id == judge_id and not allow_self_judge:
        return {
            "_error": (
                f"writer and judge are both {judge_id}. Collusion risk is high. "
                f"Pass a different judge_provider or set allow_self_judge=True to force."
            )
        }

    template = JUDGE_PROMPT_EN if lang == "en" else JUDGE_PROMPT
    prompt = template.format(ARTICLE=article)
    logger.info(
        "[humanize_zh.judge] calling %s (lang=%s, prompt %d chars)",
        judge_resolved.name, lang, len(prompt),
    )

    raw = _call_llm(prompt, provider=judge_resolved)
    if not raw:
        return {"_error": f"LLM ({judge_resolved.name}) call failed"}

    result = _parse_json(raw)
    if "_parse_error" in result:
        logger.warning("[humanize_zh.judge] JSON parse failed: %s", result["_parse_error"])
        return result

    result["_meta"] = {
        "judge_provider": judge_id,
        "writer_provider": writer_id,
        "lang": lang,
        "article_length": len(article),
    }
    return result


def format_report(result: dict) -> str:
    """把 judge() 的 JSON 输出格式化成可读报告"""
    if "_error" in result:
        return f"[judge] 错误: {result['_error']}"
    if "_parse_error" in result:
        return f"[judge] JSON 解析失败: {result['_parse_error']}\n\n原始:\n{result.get('_raw', '')}"

    lines = []
    publishable = result.get("publishable", False)
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
        lines.append(f"---\n*judge: {meta.get('judge_provider')} | writer: {meta.get('writer_provider')} | article: {meta.get('article_length'):,} 字符*")

    return "\n".join(lines)


def main() -> None:
    # 轻量 CLI, 完整 CLI 在 humanize_zh.cli (Phase 4).
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) < 2:
        print(
            "usage: python -m humanize_zh.judge <file> [--lang zh|en] "
            "[--writer <provider>] [--judge <provider>] [--json] [--allow-self-judge]"
        )
        print()
        print("Provider names: openai | anthropic | deepseek | groq | openrouter | moonshot | glm | qwen | ollama")
        print("Omit both --writer and --judge to use the active / autodetected provider for judging.")
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

    # autodetect if nothing is configured and user didn't pass one
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
