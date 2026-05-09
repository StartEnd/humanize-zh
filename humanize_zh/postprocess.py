#!/usr/bin/env python3
"""humanize.postprocess — 对已生成文章做"去 AI 味润色 pass"

这是 site-digester 工作流的可选第三步:
    Step 1: thinking (研究员脑图)
    Step 2: article  (原始文章)
    Step 3: humanize (本步, 去 AI 味润色, 可选)
    Step 4: verify   (数字溯源校验)

用法:
    from humanize import postprocess_humanize
    polished = postprocess_humanize(article_text, scene="analysis")

    # 或带具体的违规清单(更精准的修复):
    from humanize import score
    s = score(article_text)
    polished = postprocess_humanize(article_text, violations=s.violations)

实现要点:
    - LLM 改写不是单调变好, 可能降低 rule 分但拉高 ngram 分
    - 因此会比较原文 / deterministic cleanup / LLM 输出 / LLM 输出再 cleanup
    - 最终用 combined_score 选最低分候选
    - 引语、书名号和行内代码会被保护, 防止机械替换改动原话或技术词
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .detect import score, Score, Violation
from .prompt import build_humanize_postprocess_prompt


# 保护这些区间内的文本免被替换 — 引语 / 书名号 / 行内代码里的词改了会扭曲原意。
# 中文引号「」『』、智能双引号 “”、英文双引号 ""、书名号《》、行内代码 `...`。
_PROTECTED_SPAN_RE = re.compile(
    r'(「[^」]*」|『[^』]*』|“[^”]*”|"[^"]*"|《[^》]*》|`[^`\n]+`)'
)


def _protect_spans(text: str) -> tuple[str, list[str]]:
    """暂存引号/书名号/行内代码内的内容为占位符, 后续替换不会动它们。"""
    spans: list[str] = []

    def _replace(m: re.Match) -> str:
        spans.append(m.group(0))
        return f"\x00QSPAN{len(spans) - 1}\x00"

    return _PROTECTED_SPAN_RE.sub(_replace, text), spans


def _restore_spans(text: str, spans: list[str]) -> str:
    for i, s in enumerate(spans):
        text = text.replace(f"\x00QSPAN{i}\x00", s)
    return text


_BACKTICK_NUMBER_PATTERNS = [
    # `670` `1.87` `78%` `43.5%` — 纯数字, 可带小数点 / 百分号
    re.compile(r"`(\d+(?:\.\d+)?%?)`"),
    # `47,594` `984,282` — 千位分隔
    re.compile(r"`(\d{1,3}(?:,\d{3})+(?:\.\d+)?%?)`"),
    # `670 万` `1.5 亿` — 数字 + 中文单位
    re.compile(r"`(\d+(?:\.\d+)?\s*[万亿千百]+)`"),
    # `2026-03` `2026-04-08` — ISO 日期
    re.compile(r"`(\d{4}-\d{1,2}(?:-\d{1,2})?)`"),
    # `2026 年 3 月 2 日` `3 月 5 日` `4 月` — 中文日期
    re.compile(r"`((?:\d{4}\s*年\s*)?\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?)`"),
    # `104.3s` `30s` `2.5min` — 时长(数字+s/min/h)
    re.compile(r"`(\d+(?:\.\d+)?(?:s|ms|min|h)\b)`"),
    # `65.6K` `1.5M` `0.6 KB` `2.3 GB` — 数字 + 英文单位
    re.compile(r"`(\d+(?:\.\d+)?\s*(?:K|M|G|T|KB|MB|GB|TB|Hz|ms)\b)`"),
    # `~670` `>78%` `<5%` — 带前缀符号的数字
    re.compile(r"`([~><=±]?\d+(?:\.\d+)?%?)`"),
    # `0/5` `3/10` — 比例
    re.compile(r"`(\d+/\d+)`"),
]


def _strip_number_backticks(text: str) -> str:
    """去掉自然叙述里给数字 / 百分比 / 日期加的反引号。

    LLM 默认从技术文档语料学到给具体数字加反引号 (inline code) 的习惯。
    但分析文章 / 专栏文 / 公众号深度文不会这么写, 反引号包数字是显著的 AI 痕迹。
    保留代码 / 路径 / HTML 标签 / 文件名的反引号 (如 `robots.txt`, `<meta>`)。
    """
    out = text
    for pat in _BACKTICK_NUMBER_PATTERNS:
        out = pat.sub(r"\1", out)
    return out


def _deterministic_cleanup(text: str) -> str:
    """机械清理一批高置信 AI 痕迹。

    这不是完整改写器, 只处理检测器已经明确标红、且替换后不改变事实的词和句式。
    引号 / 书名号 / 行内代码内的内容会被保护, 不参与替换 — 防止改原话和技术词。
    """
    # 先去掉数字反引号 (在 _protect_spans 之前, 因为反引号内会被保护)
    text = _strip_number_backticks(text)

    # TODO(when 50+ rules or scene-conditional): migrate to patterns.json::replacements.
    replacements = [
        ("，而是", "，是"),
        ("而是", "是"),
        ("站点使基于 Next.js 搭建", "站点基于 Next.js 搭建"),
        ("使用基于 Next.js 搭建", "基于 Next.js 搭建"),
        ("站点使用 Next.js 构建", "站点基于 Next.js 搭建"),
        ("站点用 Next.js 构建", "站点基于 Next.js 搭建"),
        ("使用 Next.js 构建", "基于 Next.js 搭建"),
        ("有可能仅够", "大致只够"),
        ("可能仅够", "大致只够"),
        ("证明", "说明"),
        ("构建", "搭建"),
        ("打造", "做出"),
        ("拆解", "分析"),
        ("梳理", "整理"),
        ("剖析", "分析"),
        ("洞察", "观察"),
        ("沉淀", "积累"),
        ("底层逻辑", "核心逻辑"),
        ("必然", ""),
        ("显然", ""),
        ("毋庸置疑", ""),
        ("误差可能达", "误差可达"),
        ("更可能对应", "更接近"),
        ("可能已经", "已经"),
        ("可能无意间", "容易"),
        ("就可能", "会"),
        ("或许", ""),
        ("也许", ""),
        ("大概", ""),
        ("似乎", ""),
        ("仿佛", ""),
        ("隐约", ""),
        ("暗示", "指向"),
        ("看起来像", "接近"),
        ("看上去", "显得"),
        ("表面上", "从表面看"),
        ("推断", "判断"),
        ("推测", "估算"),
    ]
    protected, spans = _protect_spans(text)
    for old, new in replacements:
        protected = protected.replace(old, new)
    cleaned = _restore_spans(protected, spans)

    return cleaned


def _combined_value(text: str) -> float:
    try:
        from .combined import combined_score

        return combined_score(text).combined_probability
    except Exception:
        return score(text).total


def _best_candidate(candidates: list[str]) -> str:
    uniq: list[str] = []
    seen = set()
    for item in candidates:
        if not item or item in seen:
            continue
        seen.add(item)
        uniq.append(item)
    def _release_distance(text: str) -> tuple[float, float, float]:
        try:
            from .combined import combined_score

            s = combined_score(text)
            combined = s.combined_probability
            rule = s.rule_probability
            ngram = s.ngram_probability if s.ngram_available else 0.0
        except Exception:
            rule = score(text).total
            combined = rule
            ngram = 0.0

        # 先看离发布门槛最远的那一项, 再看 combined, 最后看 rule。
        distance = max(combined - 30, rule - 25, ngram - 30, 0)
        return (distance, combined, rule)

    return min(uniq, key=_release_distance)


def _call_llm(prompt: str, *, provider: str | None = None) -> str | None:
    """调 LLM. 复用 site-digester 的 generate_article 函数(避免重复实现)。"""
    try:
        # 动态 import 防止 humanize/ 模块被外部项目引用时挂掉
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from generate import generate_article  # type: ignore
        return generate_article(prompt, provider=provider)
    except Exception as e:
        print(f"  [humanize] LLM 调用失败: {e}", file=sys.stderr)
        return None


def postprocess_humanize(
    article: str,
    *,
    scene: str = "analysis",
    violations: list[Violation] | None = None,
    provider: str | None = None,
    detect_first: bool = True,
) -> tuple[str, Score, Score | None]:
    """对一篇文章做"去 AI 味润色 pass"。

    Args:
        article: 原文
        scene: 场景 (analysis / essay / academic / blog)
        violations: 已知的违规清单(可选, 不给会自动 detect)
        provider: LLM 名称
        detect_first: 是否先 detect 给出 before-score

    Returns:
        (polished_text, score_after, score_before_or_None)
    """
    score_before = None
    if detect_first:
        score_before = score(article)
        print(f"  [humanize] 润色前 AI 分: {score_before.total} ({score_before.level})")

    if violations is None and score_before is not None:
        violations = score_before.violations

    if score_before is None:
        return article, score(article), None

    combined_before = _combined_value(article)
    if (not violations or score_before.total < 25) and combined_before < 30:
        # rule 和 combined 都已经够好, 不需要润色。
        print(
            f"  [humanize] 文章已经达到发布线 "
            f"(rule {score_before.total:.1f}, combined {combined_before:.1f}), 跳过润色"
        )
        return article, score_before, None

    prompt = build_humanize_postprocess_prompt(article, violations or [], scene=scene)
    print(f"  [humanize] 调 LLM 做润色 pass(prompt {len(prompt):,} 字符)...")

    polished = _call_llm(prompt, provider=provider)
    if not polished:
        fallback = _deterministic_cleanup(article)
        score_after = score(fallback)
        print(f"  [humanize] LLM 失败, 使用确定性清理 fallback: {score_after.total} ({score_after.level})")
        return fallback, score_after, score_before

    best = _best_candidate([article, _deterministic_cleanup(article), polished, _deterministic_cleanup(polished)])
    if best != polished:
        print(f"  [humanize] LLM 结果未必最优, 已按 combined 分选择更低分候选")

    score_after = score(best)
    print(f"  [humanize] 润色后 AI 分: {score_after.total} ({score_after.level})")
    if score_before:
        delta = score_before.total - score_after.total
        print(f"  [humanize] 降幅: {delta:+.1f}")

    return best, score_after, score_before


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python -m humanize.postprocess <article.md> [--scene analysis] [--out polished.md]")
        sys.exit(1)
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"错误: 文件不存在 {src}")
        sys.exit(1)

    scene = "analysis"
    out_path = src.with_suffix(".polished.md")
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--scene" and i + 1 < len(args):
            scene = args[i + 1]
            i += 2
        elif a == "--out" and i + 1 < len(args):
            out_path = Path(args[i + 1])
            i += 2
        else:
            i += 1

    text = src.read_text(encoding="utf-8")
    polished, after, before = postprocess_humanize(text, scene=scene)
    out_path.write_text(polished, encoding="utf-8")
    print(f"\n✓ 输出: {out_path}")
    if before:
        print(f"  AI 分: {before.total:.1f} → {after.total:.1f} (降 {before.total - after.total:+.1f})")
