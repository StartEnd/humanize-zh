#!/usr/bin/env python3
"""humanize.ngram_check — 基于 ngram 频率表的 AI 文本统计检测

完全本地, 0 网络依赖, 毫秒级。引擎来自 voidborne-d/humanize-chinese 项目,
经过 HC3-Chinese 300+300 样本 Cohen's d 校准。

提供 8 个统计维度:
- perplexity        字符级困惑度(AI 文本通常 < 30, 人类 > 50)
- burstiness        困惑度突变性(人类 CV > 0.3, AI < 0.2)
- entropy_uniformity 段落熵均匀度(AI 段落熵几乎相同)
- transition_density 转折词密度(AI 13.7/千字 vs 人类 6.98/千字, d=0.617)
- sentence_cv       句长变异系数(AI 普遍均匀)
- short_frac        短句占比(< 10 字)
- char_mattr        字级 Moving Average TTR(词汇丰富度)
- comma_density     逗号密度(HC3 上人类 4.82/100chars vs AI 3.82, d=-0.47)

用法:
    from humanize.ngram_check import ngram_score, NgramScore

    s = ngram_score(open("article.md").read())
    print(s.ai_probability)   # 0-100, 综合多维度的 AI 概率估计
    print(s.metrics)          # 各维度的原始数值

设计原则: 这是 detect.py 的**补充**, 不替代规则检测。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 让内部 _ngram_engine.py 可以 import
DATA_DIR = Path(__file__).parent / "data"
sys.path.insert(0, str(DATA_DIR))


@dataclass
class NgramScore:
    """ngram 检测的综合结果"""
    ai_probability: float                       # 0-100, 估计的 AI 概率
    level: str                                  # LOW / MEDIUM / HIGH / VERY HIGH
    metrics: dict[str, float] = field(default_factory=dict)
    text_length: int = 0
    char_count: int = 0                         # 中文字符数
    available: bool = True                      # 资源是否加载成功

    def __str__(self):
        lines = [
            f"ngram AI 概率: {self.ai_probability:.1f}/100  ({self.level})",
            f"中文字符数: {self.char_count}",
            "",
            "各维度指标:",
        ]
        for k, v in self.metrics.items():
            lines.append(f"  {k:25s}: {v}")
        return "\n".join(lines)


def _level(prob: float) -> str:
    if prob < 25:
        return "LOW (基本像人写的)"
    elif prob < 50:
        return "MEDIUM (有些 AI 痕迹)"
    elif prob < 75:
        return "HIGH (大概率 AI 生成)"
    return "VERY HIGH (几乎确定是 AI)"


def _safe_call(fn, *args, default=None, **kwargs):
    """安全调用 _ngram_engine 的函数, 失败返回默认值"""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        print(f"  [ngram] {fn.__name__} 失败: {e}", file=sys.stderr)
        return default


def ngram_score(text: str) -> NgramScore:
    """对文本做 ngram 统计检测, 返回综合 AI 概率分数。

    完全本地, 不调 LLM, 不需要网络。基于 humanize-chinese 项目的 HC3 校准。
    """
    if not text or not text.strip():
        return NgramScore(
            ai_probability=0.0, level="LOW (空文本)",
            text_length=0, char_count=0, available=True,
        )

    try:
        import _ngram_engine as eng  # type: ignore
    except ImportError as e:
        print(f"  [ngram] _ngram_engine.py 未找到: {e}", file=sys.stderr)
        return NgramScore(
            ai_probability=0.0, level="UNKNOWN", available=False,
            text_length=len(text),
        )

    # 检查 ngram_freq_cn.json 是否在
    if not (DATA_DIR / "ngram_freq_cn.json").exists():
        print(f"  [ngram] 缺失 {DATA_DIR}/ngram_freq_cn.json", file=sys.stderr)
        return NgramScore(
            ai_probability=0.0, level="UNKNOWN", available=False,
            text_length=len(text),
        )

    metrics: dict[str, Any] = {}

    # 1. 困惑度
    ppl_result = _safe_call(eng.compute_perplexity, text, default={})
    if ppl_result and ppl_result.get("char_count", 0) >= 30:
        metrics["perplexity"] = round(ppl_result.get("perplexity", 0.0), 2)
        metrics["avg_log_prob"] = round(ppl_result.get("avg_log_prob", 0.0), 3)
        char_count = ppl_result.get("char_count", 0)
    else:
        char_count = ppl_result.get("char_count", 0) if ppl_result else 0
        if char_count < 30:
            return NgramScore(
                ai_probability=0.0, level="LOW (文本太短无法统计)",
                text_length=len(text), char_count=char_count, available=True,
            )

    # 2. burstiness (perplexity CV)
    burst = _safe_call(eng.compute_burstiness, text, default={})
    if burst:
        metrics["burstiness"] = round(burst.get("burstiness", 0.0), 3)

    # 3. 段落熵均匀度
    entropy = _safe_call(eng.compute_entropy_uniformity, text, default={})
    if entropy:
        metrics["entropy_cv"] = round(entropy.get("entropy_cv", 0.0), 3)
        metrics["mean_entropy"] = round(entropy.get("mean_entropy", 0.0), 2)

    # 4. 转折词密度
    trans = _safe_call(eng.compute_transition_density, text, default={})
    if trans:
        metrics["transition_density"] = round(trans.get("density", 0.0), 2)
        metrics["transition_count"] = trans.get("count", 0)

    # 5. 句长统计
    sent = _safe_call(eng.compute_sentence_length_features, text, default={})
    if sent:
        metrics["sentence_cv"] = round(sent.get("cv", 0.0), 3)
        metrics["short_frac"] = round(sent.get("short_frac", 0.0), 3)
        metrics["equal_mid_frac"] = round(sent.get("equal_mid_frac", 0.0), 3)

    # 6. 字级 MATTR
    mattr = _safe_call(eng.compute_char_mattr, text, default=0.0)
    metrics["char_mattr"] = round(mattr, 3)

    # 7. 标点密度
    punct = _safe_call(eng.compute_punctuation_density, text, default={})
    if punct:
        metrics["comma_density"] = round(punct.get("comma_density", 0.0), 2)
        metrics["punct_density"] = round(punct.get("punct_density", 0.0), 2)

    # 综合 AI 概率(基于 HC3-Chinese Cohen's d 加权)
    # 这是简化的启发式, 不是训好的 LR (避免依赖 lr_coef 文件格式)
    ai_signals = 0.0
    n_signals = 0

    # perplexity: < 30 = AI, 30-60 = 不确定, > 60 = 人类
    if "perplexity" in metrics:
        p = metrics["perplexity"]
        if p < 30:
            ai_signals += min(100, (30 - p) * 3)
        elif p > 60:
            ai_signals += max(0, 30 - (p - 60) * 0.5)
        else:
            ai_signals += 50 - (p - 30) * 1.0
        n_signals += 1

    # burstiness: < 0.2 = AI, > 0.3 = 人类
    if "burstiness" in metrics:
        b = metrics["burstiness"]
        if b < 0.2:
            ai_signals += min(100, (0.2 - b) * 400)
        elif b > 0.3:
            ai_signals += max(0, 50 - (b - 0.3) * 200)
        else:
            ai_signals += 50
        n_signals += 1

    # transition_density: > 13 = AI, < 7 = 人类(HC3 校准)
    if "transition_density" in metrics:
        t = metrics["transition_density"]
        if t > 13:
            ai_signals += min(100, 50 + (t - 13) * 5)
        elif t < 7:
            ai_signals += max(0, 50 - (7 - t) * 5)
        else:
            ai_signals += 50
        n_signals += 1

    # sentence_cv: < 0.4 = AI(均匀), > 0.6 = 人类
    if "sentence_cv" in metrics:
        s = metrics["sentence_cv"]
        if s < 0.4:
            ai_signals += min(100, (0.4 - s) * 200)
        elif s > 0.6:
            ai_signals += max(0, 50 - (s - 0.6) * 100)
        else:
            ai_signals += 50
        n_signals += 1

    # comma_density: < 4 = AI, > 5 = 人类(HC3)
    if "comma_density" in metrics:
        c = metrics["comma_density"]
        if c < 4:
            ai_signals += min(100, 50 + (4 - c) * 12)
        elif c > 5:
            ai_signals += max(0, 50 - (c - 5) * 12)
        else:
            ai_signals += 50
        n_signals += 1

    # char_mattr: < 0.62 = AI(词汇贫乏), > 0.7 = 人类
    if "char_mattr" in metrics and metrics["char_mattr"] > 0:
        m = metrics["char_mattr"]
        if m < 0.62:
            ai_signals += min(100, (0.62 - m) * 500)
        elif m > 0.7:
            ai_signals += max(0, 50 - (m - 0.7) * 200)
        else:
            ai_signals += 50
        n_signals += 1

    ai_prob = ai_signals / n_signals if n_signals > 0 else 0.0
    ai_prob = min(100.0, max(0.0, ai_prob))

    return NgramScore(
        ai_probability=round(ai_prob, 1),
        level=_level(ai_prob),
        metrics=metrics,
        text_length=len(text),
        char_count=char_count,
        available=True,
    )


def main():
    if len(sys.argv) < 2:
        print("用法: python -m humanize.ngram_check <file> [--json]")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"错误: 文件不存在 {path}")
        sys.exit(1)

    text = path.read_text(encoding="utf-8")
    s = ngram_score(text)

    if "--json" in sys.argv:
        import json
        print(json.dumps({
            "ai_probability": s.ai_probability,
            "level": s.level,
            "char_count": s.char_count,
            "available": s.available,
            "metrics": s.metrics,
        }, ensure_ascii=False, indent=2))
    else:
        print(s)


if __name__ == "__main__":
    main()
