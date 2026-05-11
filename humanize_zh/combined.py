"""humanize.combined — 三层 AI 检测综合 (rule + ngram + LLM judge)

设计哲学:
    - Layer 1 (rule):  规则检测, 抓"AI 词汇 + 模板段 + 句式模式" — 语义维度
    - Layer 2 (ngram): 统计检测, 抓"字符级 perplexity + burstiness + entropy" — 统计维度
    - Layer 3 (LLM):   终审层, 抓"具体哪段像 AI + 哪些判断没证据" — 语义+解释

三个维度抓不同的东西, 一个能过 rule 不一定能过 ngram, 反之亦然。

综合 AI 概率使用 max-style 组合:
    combined = max(rule, ngram)

任意一层判定 HIGH 就触发警告。这比平均更保守, 适合发布门控。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._format import level_label
from .detect import Score as RuleScore
from .detect import score as rule_score


@dataclass
class CombinedScore:
    """综合三层检测的结果"""
    combined_probability: float          # 0-100 综合 AI 概率(max 组合)
    combined_level: str                   # LOW / MEDIUM / HIGH / VERY HIGH

    rule_probability: float               # Layer 1: 规则检测 0-100
    rule_level: str

    ngram_probability: float              # Layer 2: ngram 统计检测 0-100
    ngram_level: str
    ngram_available: bool                 # ngram 资源是否加载成功

    rule_violations: list = field(default_factory=list)
    ngram_metrics: dict[str, Any] = field(default_factory=dict)

    text_length: int = 0
    char_count: int = 0
    has_notes: bool = False

    def __str__(self):
        return (
            f"综合 AI 概率: {self.combined_probability:.1f}/100  ({self.combined_level})\n"
            f"  rule:  {self.rule_probability:.1f}/100  ({self.rule_level})\n"
            f"  ngram: {self.ngram_probability:.1f}/100  ({self.ngram_level})"
            + ("  [资源未加载]" if not self.ngram_available else "")
        )


def combined_score(text: str, has_notes: bool = False) -> CombinedScore:
    """对文本同时跑规则检测 + ngram 统计检测, 综合两者输出。

    设计为发布门控: 任意一层判定 HIGH 即触发警告。

    Args:
        text:      待检测文本
        has_notes: 是否有真实操作记录(影响规则层的 fake_human 检测)

    Returns:
        CombinedScore: 包含三层各自的分数和综合分数
    """
    # Layer 1: 规则检测
    rs: RuleScore = rule_score(text, has_notes=has_notes)

    # Layer 2: ngram 检测
    ngram_metrics: dict[str, Any]
    try:
        from .ngram_check import NgramScore, ngram_score
        ns: NgramScore = ngram_score(text)
        ngram_prob = ns.ai_probability
        ngram_lvl = ns.level
        ngram_avail = ns.available
        ngram_metrics = ns.metrics
        char_count = ns.char_count
    except Exception as e:
        ngram_prob = 0.0
        ngram_lvl = "UNAVAILABLE"
        ngram_avail = False
        ngram_metrics = {"error": str(e)}
        char_count = 0

    # 综合: max-style(任一层 HIGH 就报警)
    combined_prob = max(rs.total, ngram_prob) if ngram_avail else rs.total

    return CombinedScore(
        combined_probability=round(combined_prob, 1),
        combined_level=level_label(combined_prob),
        rule_probability=round(rs.total, 1),
        rule_level=rs.level,
        ngram_probability=round(ngram_prob, 1),
        ngram_level=ngram_lvl,
        ngram_available=ngram_avail,
        rule_violations=rs.violations,
        ngram_metrics=ngram_metrics,
        text_length=len(text),
        char_count=char_count,
        has_notes=has_notes,
    )
