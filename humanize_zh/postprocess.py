#!/usr/bin/env python3
"""humanize_zh.postprocess — 对已生成文章做"去 AI 味润色 pass"

用法:
    from humanize_zh import postprocess_humanize, llm

    # 1) 先配置 provider(任选其一)
    llm.autodetect()
    # 或 llm.use("openai", api_key="sk-...")
    # 或 llm.use_openai_compat(name="deepseek", base_url=..., api_key=..., model="deepseek-chat")
    # 或 llm.use_callable(my_func)

    # 2) 调用润色
    polished, after, before = postprocess_humanize(article_text, scene="analysis")

    # 英文 LLM-only 模式 (跳过中文 detect / ngram, 只跑 LLM polish + 通用反引号清理)
    polished, after, _ = postprocess_humanize(article_text, lang="en")

设计要点:
    - 中文模式 (lang="zh"): rule + ngram 检测 → LLM polish → 候选比较选最优
    - 英文模式 (lang="en"): 跳过中文检测, 直接 LLM polish (内嵌 5 原则)
    - LLM 改写非单调变好: 可能降低 rule 分却拉高 ngram 分, 所以比较多个候选
    - 引语 / 书名号 / 行内代码受保护区间, 不会被机械替换动到原话或技术词
"""

from __future__ import annotations

import json
import logging
import re
import sys
from functools import lru_cache
from pathlib import Path

from . import llm as _llm_module
from .detect import Score, Violation, score
from .llm import (
    LLMError,
    LLMNotConfiguredError,
    ProviderArg,
    resolve_provider,
)
from .prompt import build_humanize_postprocess_prompt

logger = logging.getLogger(__name__)

_PATTERNS_PATH = Path(__file__).parent / "patterns.json"


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


@lru_cache(maxsize=1)
def _load_replacements() -> tuple[tuple[str, str], ...]:
    """Load deterministic replacement pairs from ``patterns.json::replacements``.

    Buckets are applied in the order declared by the ``_order`` array
    (insertion order if omitted). Within each bucket, pairs are sorted by
    ``len(old)`` descending so that longer phrases win over shorter prefixes
    they contain (e.g. ``可能已经`` matches before any hypothetical ``可能`` rule).
    Returns a flat tuple so callers can iterate without re-parsing JSON.

    On parse failure logs and returns an empty tuple — cleanup degrades to
    a no-op rather than crashing the polish pipeline.
    """
    try:
        data = json.loads(_PATTERNS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.error("[humanize_zh] cannot load %s: %s", _PATTERNS_PATH, e)
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


def _deterministic_cleanup(text: str) -> str:
    """机械清理一批高置信 AI 痕迹。

    这不是完整改写器, 只处理检测器已经明确标红、且替换后不改变事实的词和句式。
    引号 / 书名号 / 行内代码内的内容会被保护, 不参与替换 — 防止改原话和技术词。
    替换表来自 ``patterns.json::replacements`` (见 :func:`_load_replacements`).
    """
    # 先去掉数字反引号 (在 _protect_spans 之前, 因为反引号内会被保护)
    text = _strip_number_backticks(text)

    protected, spans = _protect_spans(text)
    for old, new in _load_replacements():
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


def _call_llm(prompt: str, *, provider: ProviderArg = None) -> str | None:
    """调 LLM 润色. 返回 None 表示调用失败(被日志记录), 让调用方走 fallback."""
    try:
        p = resolve_provider(provider, autodetect_on_none=True)
    except LLMNotConfiguredError as e:
        logger.error("[humanize_zh] no LLM provider configured: %s", e)
        return None
    except (ValueError, TypeError) as e:
        logger.error("[humanize_zh] bad provider arg: %s", e)
        return None

    try:
        resp = p.complete(prompt)
    except LLMError as e:
        logger.error("[humanize_zh] LLM call failed (%s): %s", p.name, e)
        return None
    except Exception as e:  # 防第三方 SDK 抛未被 base.py 覆盖的异常
        logger.exception("[humanize_zh] unexpected LLM error (%s): %s", p.name, e)
        return None

    return resp.text or None


def postprocess_humanize(
    article: str,
    *,
    scene: str = "analysis",
    lang: str = "zh",
    violations: list[Violation] | None = None,
    provider: ProviderArg = None,
    detect_first: bool = True,
    force_llm: bool = False,
) -> tuple[str, Score | None, Score | None]:
    """对一篇文章做"去 AI 味润色 pass"。

    Args:
        article: 原文
        scene: 中文 scene (analysis / essay / academic / blog); 英文模式忽略
        lang: "zh" 中文完整 pipeline (detect + ngram + LLM polish)
              "en" 英文 LLM-only 模式 (跳过中文 detect/ngram, 只做 LLM polish + 通用反引号清理)
        violations: 已知违规清单(可选, 中文模式不给会自动 detect; 英文忽略)
        provider: LLM provider. 支持:
                  - None (默认):   从 llm.get_active() 取, 没配则抛 LLMNotConfiguredError
                  - LLMProvider:  直接使用该 provider 实例
                  - str:          builtin 名称 ("openai"/"anthropic"/"deepseek"/...)
                                 会尝试从 env 建; 建不起来抛 ValueError
        detect_first: 中文模式是否先跑 detect 给出 before-score
        force_llm: True 强制调 LLM (跳过"已达发布线"早期返回); 用于 UI 强制改写按钮

    Returns:
        (polished_text, score_after_or_None, score_before_or_None)
        英文模式下 score_after / score_before 均为 None (没有中文检测可用)
    """
    if lang not in ("zh", "en"):
        raise ValueError(f"lang must be 'zh' or 'en', got {lang!r}")

    # ─── 英文 LLM-only 模式 ─────────────────────────────────────────
    if lang == "en":
        prompt = build_humanize_postprocess_prompt(article, [], scene=scene, lang="en")
        logger.info("[humanize_zh] EN LLM polish (prompt %d chars)", len(prompt))
        polished = _call_llm(prompt, provider=provider)
        if not polished:
            logger.warning("[humanize_zh] EN LLM failed, returning deterministic cleanup only")
            fallback = _strip_number_backticks(article)
            return fallback, None, None
        # 英文模式也对输出做一次数字反引号清理(通用规则)
        polished_clean = _strip_number_backticks(polished)
        return polished_clean, None, None

    # ─── 中文完整 pipeline ─────────────────────────────────────────
    score_before: Score | None = None
    if detect_first:
        score_before = score(article)
        logger.info(
            "[humanize_zh] 润色前 AI 分: %.1f (%s)",
            score_before.total, score_before.level,
        )

    if violations is None and score_before is not None:
        violations = score_before.violations

    if score_before is None:
        return article, score(article), None

    combined_before = _combined_value(article)
    if not force_llm and (not violations or score_before.total < 25) and combined_before < 30:
        logger.info(
            "[humanize_zh] 已达发布线 (rule %.1f, combined %.1f), 跳过 LLM 润色",
            score_before.total, combined_before,
        )
        return article, score_before, None

    prompt = build_humanize_postprocess_prompt(
        article, violations or [], scene=scene, lang="zh", aggressive=force_llm,
    )
    logger.info(
        "[humanize_zh] LLM polish pass (prompt %d chars, aggressive=%s)",
        len(prompt), force_llm,
    )

    polished = _call_llm(prompt, provider=provider)
    if not polished:
        fallback = _deterministic_cleanup(article)
        score_after = score(fallback)
        logger.warning(
            "[humanize_zh] LLM 失败, 使用确定性清理 fallback: %.1f (%s)",
            score_after.total, score_after.level,
        )
        return fallback, score_after, score_before

    if force_llm:
        # User explicitly asked for LLM rewrite; trust it even if combined-score is higher.
        # combined-score is a rule-based metric and may not align with transformer-based
        # third-party detectors (Zhuque / Originality / GPTZero).
        best = _best_candidate([polished, _deterministic_cleanup(polished)])
        logger.info("[humanize_zh] force_llm=True, 跳过原文回退, 选 LLM 候选中较优者")
    else:
        best = _best_candidate(
            [article, _deterministic_cleanup(article), polished, _deterministic_cleanup(polished)]
        )
        if best != polished:
            logger.info("[humanize_zh] LLM 未必最优, 按 combined 分选择更低分候选")

    score_after = score(best)
    logger.info(
        "[humanize_zh] 润色后 AI 分: %.1f (%s)",
        score_after.total, score_after.level,
    )
    if score_before:
        delta = score_before.total - score_after.total
        logger.info("[humanize_zh] 降幅: %+.1f", delta)

    return best, score_after, score_before


if __name__ == "__main__":
    # 轻量 CLI, 完整 CLI 在 humanize_zh.cli (Phase 4).
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) < 2:
        print(
            "usage: python -m humanize_zh.postprocess <article.md> "
            "[--scene analysis] [--lang zh|en] [--out polished.md]"
        )
        sys.exit(1)
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"error: file not found: {src}")
        sys.exit(1)

    scene = "analysis"
    lang = "zh"
    out_path = src.with_suffix(".polished.md")
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--scene" and i + 1 < len(args):
            scene = args[i + 1]
            i += 2
        elif a == "--lang" and i + 1 < len(args):
            lang = args[i + 1]
            i += 2
        elif a == "--out" and i + 1 < len(args):
            out_path = Path(args[i + 1])
            i += 2
        else:
            i += 1

    # autodetect provider if not already set
    if not _llm_module.has_active() and _llm_module.autodetect() is None:
        print(
            "error: no LLM provider configured. Set one of OPENAI_API_KEY / "
            "ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / GROQ_API_KEY / ..."
        )
        sys.exit(2)

    text = src.read_text(encoding="utf-8")
    polished, after, before = postprocess_humanize(text, scene=scene, lang=lang)
    out_path.write_text(polished, encoding="utf-8")
    print(f"\n✓ output: {out_path}")
    if before is not None and after is not None:
        print(f"  AI score: {before.total:.1f} → {after.total:.1f} (Δ {before.total - after.total:+.1f})")
    elif lang == "en":
        print("  (lang=en: rule/ngram scoring skipped)")
