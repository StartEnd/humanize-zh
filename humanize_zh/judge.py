#!/usr/bin/env python3
"""humanize.judge — LLM 终审层

规则检测器(detect.py)便宜、快, 适合 CI; LLM 判官慢、贵, 适合终审。
两者**不要混在一个总分里**, 各自输出, 由人或 pipeline 决定后续动作。

判官输出严格的 JSON, 包含 7 个字段(由 codex 在 .agent-chat/dialogue.md Turn 003 设计):

    {
      "publishable": false,
      "worst_ai_sections": [
        {"para": "第三段...", "reason": "三段式套路 + 模糊归因"}
      ],
      "unsupported_claims": [
        {"claim": "运营者是单兵", "missing_evidence": "没引用 sitemap 工整度"}
      ],
      "template_smell": [
        "整篇按 5W2H 分节, 每节长度近似一致, 像填空"
      ],
      "fake_human_details": [
        "第七段「凌晨三点」是 AI 编造的, 数据里没有这个时间点"
      ],
      "best_theses": [
        "Direct 52% 实际是付费引荐二次回访 - 这个判断有 3 条证据支撑"
      ],
      "rewrite_brief": "重点改第三段和第七段, 删去伪场景, 把「专家认为」改为具体出处"
    }

防 LLM 共谋: 默认强制 judge_provider != writer_provider。

用法:
    from humanize.judge import judge
    result = judge(article_text, writer_provider="deepseek")
    if not result["publishable"]:
        print(result["rewrite_brief"])

CLI:
    uv run python -m humanize.judge <file> [--writer deepseek] [--judge anthropic]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 让 humanize 内可以反向 import scripts/generate.py 的 LLM 调用
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


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


def _call_llm(prompt: str, *, provider: str | None = None) -> str | None:
    """调 LLM. 复用 scripts/generate.py 的 generate_article。"""
    try:
        from generate import generate_article  # type: ignore
        return generate_article(prompt, provider=provider)
    except Exception as e:
        print(f"  [judge] LLM 调用失败: {e}", file=sys.stderr)
        return None


def _parse_json(raw: str) -> dict:
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
        return json.loads(s)
    except json.JSONDecodeError as e:
        return {"_parse_error": str(e), "_raw": raw[:500]}


def judge(
    article: str,
    *,
    writer_provider: str | None = None,
    judge_provider: str | None = None,
    allow_self_judge: bool = False,
) -> dict:
    """对一篇文章调 LLM 做终审。

    Args:
        article: 待审文章(原始 markdown)
        writer_provider: 写文章用的 provider(用于防共谋)
        judge_provider: 评审 provider, 必须 != writer_provider 除非 allow_self_judge
        allow_self_judge: 允许同一模型自审(不推荐)

    Returns:
        7 字段结构化 JSON dict, 失败时返回 {"_error": ...}
    """
    if writer_provider and judge_provider and writer_provider == judge_provider:
        if not allow_self_judge:
            return {
                "_error": (
                    f"writer 和 judge 都是 {writer_provider}, LLM 共谋风险高。"
                    "传 judge_provider 指定不同模型, 或设 allow_self_judge=True 强制运行。"
                )
            }

    # 默认: writer 是 deepseek 时, judge 用 anthropic; 反之亦然
    if not judge_provider:
        if writer_provider in ("deepseek", "glm", "qwen"):
            judge_provider = "anthropic"
        else:
            judge_provider = "deepseek"
        print(f"  [judge] 自动选择 judge provider: {judge_provider} (writer={writer_provider})")

    prompt = JUDGE_PROMPT.format(ARTICLE=article)
    print(f"  [judge] 调 {judge_provider} 终审 (prompt {len(prompt):,} 字符)...")

    raw = _call_llm(prompt, provider=judge_provider)
    if not raw:
        return {"_error": f"LLM ({judge_provider}) 调用失败"}

    result = _parse_json(raw)
    if "_parse_error" in result:
        print(f"  [judge] JSON 解析失败: {result['_parse_error']}", file=sys.stderr)
        return result

    # 元信息
    result["_meta"] = {
        "judge_provider": judge_provider,
        "writer_provider": writer_provider,
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


def main():
    if len(sys.argv) < 2:
        print("用法: python -m humanize.judge <file> [--writer <provider>] [--judge <provider>] [--json] [--allow-self-judge]")
        print()
        print("默认: writer 是 deepseek 时 judge 用 anthropic, 反之亦然")
        print("强制同模型自审: 加 --allow-self-judge (不推荐, 共谋风险高)")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"错误: 文件不存在 {path}")
        sys.exit(1)

    writer = None
    judge_p = None
    allow_self = "--allow-self-judge" in sys.argv
    out_json = "--json" in sys.argv
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--writer" and i + 1 < len(args):
            writer = args[i + 1]; i += 2
        elif a == "--judge" and i + 1 < len(args):
            judge_p = args[i + 1]; i += 2
        else:
            i += 1

    article = path.read_text(encoding="utf-8")
    result = judge(article, writer_provider=writer, judge_provider=judge_p, allow_self_judge=allow_self)

    if out_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))

    # 写出报告文件
    if not out_json:
        report_path = path.with_suffix(".judge.md")
        report_path.write_text(format_report(result), encoding="utf-8")
        print(f"\n报告已保存: {report_path}")


if __name__ == "__main__":
    main()
