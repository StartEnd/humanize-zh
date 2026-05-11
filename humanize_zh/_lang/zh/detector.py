#!/usr/bin/env python3
"""humanize_zh._lang.zh.detector — Chinese rule-based AI-style detector.

This is the canonical home of the ZH detector. The historical import
path ``humanize_zh.detect`` still works via a compat shim
(``humanize_zh/detect.py``) that re-exports everything below.

Scoring (HC3-Chinese calibration):

- 0-24   LOW        looks human-written
- 25-49  MEDIUM     some AI traces
- 50-74  HIGH       likely AI-generated
- 75-100 VERY HIGH  almost certainly AI

Public surface (preserved verbatim for v0.1.0a1 users):

    from humanize_zh.detect import score, Score, Violation, PATTERNS_PATH

Protocol adapter:

    from humanize_zh._lang.zh.detector import zh_detector   # Detector instance

CLI:

    python -m humanize_zh.detect <file>
    python -m humanize_zh._lang.zh.detector <file>          # equivalent
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, pstdev

from ..._format import level_label

# Phase 1.6 split the monolithic ``patterns.json`` into ``rules.json``
# (detector) + ``replacements.json`` (postprocess). The historical
# ``PATTERNS_PATH`` constant is kept for backwards compatibility — it
# points at the new ``rules.json`` since that's the file the detector
# actually consumes. Tests that read ``PATTERNS_PATH`` (looking for
# ``_meta.version``) keep working because both halves carry ``_meta``.
PATTERNS_PATH = Path(__file__).parent / "data" / "rules.json"


@dataclass
class Violation:
    category: str           # blacklist_words / blacklist_phrases / structural_rules / rhythm_rules / soul_signals
    rule: str               # rule key, e.g. "ai_high_freq"
    weight: int
    count: int
    sample: str             # 命中的一个示例片段, 便于人工审查
    threshold: int | None = None
    score: float = 0.0      # 这条规则贡献的分

    def __str__(self):
        thr = f" (阈值 {self.threshold})" if self.threshold is not None else ""
        return f"  [{self.score:+5.1f}] {self.category}.{self.rule}: 命中 {self.count} 次{thr} | 例: 「{self.sample[:30]}」"


@dataclass
class Score:
    total: float
    level: str
    violations: list[Violation] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    text_length: int = 0

    def __str__(self):
        lines = [
            f"AI 味评分: {self.total:.1f}/100  ({self.level})",
            f"文本长度: {self.text_length} 字符",
            "",
            "命中规则:",
        ]
        if not self.violations:
            lines.append("  (无)")
        else:
            for v in sorted(self.violations, key=lambda v: -v.score):
                lines.append(str(v))
        if self.stats:
            lines += ["", "节奏统计:"]
            for k, v in self.stats.items():
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)


def _load_patterns() -> dict:
    return json.loads(PATTERNS_PATH.read_text(encoding="utf-8"))


def _strip_codeblocks(text: str) -> str:
    """跳过代码块 — 代码里的关键词不算"""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`\n]+`", "", text)
    return text


def _check_word_list(text: str, rule: str, conf: dict) -> Violation | None:
    """检查纯字符串列表"""
    weight = conf.get("weight", 1)
    count = 0
    sample = ""
    for w in conf.get("patterns", []):
        n = text.count(w)
        if n > 0 and not sample:
            idx = text.find(w)
            sample = text[max(0, idx - 10):idx + len(w) + 10]
        count += n

    if count == 0:
        return None

    soft = conf.get("soft_threshold")
    hard = conf.get("hard_threshold")
    threshold = hard if hard is not None else soft

    if hard is not None and count > hard:
        # 硬约束: 超出部分每次扣 weight 分
        score = (count - hard) * weight
    elif soft is not None and count <= soft:
        # 软约束未超阈: 半权扣
        score = count * weight * 0.5
    else:
        score = count * weight

    return Violation(
        category="blacklist_words", rule=rule, weight=weight,
        count=count, sample=sample, threshold=threshold, score=score
    )


def _check_regex_list(text: str, rule: str, conf: dict, category: str = "blacklist_phrases") -> Violation | None:
    """检查 regex 列表"""
    weight = conf.get("weight", 1)
    count = 0
    sample = ""
    for pat in conf.get("patterns", []):
        try:
            matches = list(re.finditer(pat, text))
        except re.error:
            continue
        if matches and not sample:
            sample = matches[0].group(0)
        count += len(matches)
    if count == 0:
        return None

    soft = conf.get("soft_threshold")
    hard = conf.get("hard_threshold")
    threshold = hard if hard is not None else soft

    if hard is not None and count > hard:
        score = (count - hard) * weight
    elif soft is not None and count <= soft:
        score = count * weight * 0.5
    else:
        score = count * weight
    return Violation(
        category=category, rule=rule, weight=weight,
        count=count, sample=sample, threshold=threshold, score=score
    )


def _check_structural(text: str, rule: str, conf: dict) -> Violation | None:
    """structural_rules 段 — 单 pattern + 阈值"""
    pattern = conf.get("pattern", "")
    is_regex = conf.get("regex", False)
    weight = conf.get("weight", 1)
    if is_regex:
        try:
            count = len(list(re.finditer(pattern, text)))
        except re.error:
            return None
    else:
        count = text.count(pattern)
    if count == 0:
        return None

    soft = conf.get("soft_threshold")
    hard = conf.get("hard_threshold")
    threshold = hard if hard is not None else soft
    if hard is not None and count > hard:
        score = (count - hard) * weight
    elif soft is not None and count <= soft:
        score = count * weight * 0.5
    else:
        score = count * weight
    sample = ""
    if is_regex:
        m = re.search(pattern, text)
        if m:
            sample = m.group(0)
    else:
        idx = text.find(pattern)
        if idx >= 0:
            sample = text[max(0, idx - 5):idx + len(pattern) + 5]
    return Violation(
        category="structural_rules", rule=rule, weight=weight,
        count=count, sample=sample, threshold=threshold, score=score
    )


def _split_sentences(text: str) -> list[str]:
    """中文断句"""
    parts = re.split(r"[。！？!?\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]


def _rhythm_score(text: str, patterns: dict) -> tuple[list[Violation], dict]:
    """节奏维度评分"""
    out = []
    stats = {}
    rules = patterns.get("rhythm_rules", {})

    sents = _split_sentences(text)
    if len(sents) >= 5:
        lens = [len(s) for s in sents]
        cv = pstdev(lens) / mean(lens) if mean(lens) > 0 else 0
        stats["句长 CV"] = f"{cv:.2f}"
        thr = rules.get("sentence_length_cv", {}).get("thresholds", {})
        if cv < thr.get("ai", 0.5):
            out.append(Violation(
                category="rhythm_rules", rule="sentence_length_cv", weight=10,
                count=1, sample=f"CV={cv:.2f} < {thr.get('ai', 0.5)}",
                threshold=int(thr.get("ai", 0.5) * 100), score=10
            ))

        short = sum(1 for L in lens if L < 10)
        ratio = short / len(lens)
        stats["短句占比"] = f"{ratio:.1%}"
        thr = rules.get("short_sentence_ratio", {}).get("thresholds", {})
        if ratio < thr.get("ai", 0.05):
            out.append(Violation(
                category="rhythm_rules", rule="short_sentence_ratio", weight=5,
                count=1, sample=f"短句率 {ratio:.1%} < 5%",
                threshold=5, score=5
            ))

    paras = _split_paragraphs(text)
    if len(paras) >= 5:
        plens = [len(p) for p in paras]
        pcv = pstdev(plens) / mean(plens) if mean(plens) > 0 else 0
        stats["段长 CV"] = f"{pcv:.2f}"
        thr = rules.get("paragraph_uniformity", {}).get("thresholds", {})
        if pcv < thr.get("ai", 0.3):
            out.append(Violation(
                category="rhythm_rules", rule="paragraph_uniformity", weight=5,
                count=1, sample=f"段长 CV={pcv:.2f} < {thr.get('ai', 0.3)}",
                threshold=int(thr.get("ai", 0.3) * 100), score=5
            ))

    pat = rules.get("para_opening_diversity", {})
    if pat:
        para_starts = [p[:30] for p in paras]
        n_third = sum(1 for s in para_starts
                      if re.match(pat["pattern"], s))
        if n_third > pat.get("hard_threshold", 2):
            out.append(Violation(
                category="rhythm_rules", rule="para_opening_diversity", weight=5,
                count=n_third, sample=f"「第 N 个 X 是」开头 {n_third} 段",
                threshold=pat.get("hard_threshold", 2),
                score=(n_third - pat["hard_threshold"]) * 5
            ))
        stats["「第N个」开头段数"] = str(n_third)

    return out, stats


def _soul_bonus(text: str, patterns: dict) -> tuple[list[Violation], int]:
    """灵魂信号: 缺失则加 AI 分(扣灵魂分)"""
    out = []
    bonus = 0
    rules = patterns.get("soul_signals", {})
    for rule_name, conf in rules.items():
        if rule_name.startswith("_"):
            continue
        pat = conf.get("pattern", "")
        try:
            n = len(list(re.finditer(pat, text))) if conf.get("regex") else text.count(pat)
        except re.error:
            n = 0
        min_thr = conf.get("min_threshold", 0)
        if n < min_thr:
            penalty = (min_thr - n) * 5
            out.append(Violation(
                category="soul_signals", rule=rule_name, weight=5,
                count=n, sample=f"缺失「{conf['name']}」(需 ≥ {min_thr})",
                threshold=min_thr, score=penalty
            ))
            bonus += penalty
    return out, bonus


def score(text: str, *, skip_codeblocks: bool = True, has_notes: bool = False) -> Score:
    """对文本评分。

    Args:
        text: 要评分的文本
        skip_codeblocks: 是否跳过代码块
        has_notes: 项目是否有 notes.md 记录了真实体验。
            - False (默认): fake_human 检测器启用, 伪人味表达会被重处
            - True: 伪人味检测器变为警告, 允许具体场景和第一人称
    """
    if not text.strip():
        return Score(total=0.0, level="LOW (空文本)")
    plain = _strip_codeblocks(text) if skip_codeblocks else text
    patterns = _load_patterns()

    violations: list[Violation] = []

    # 1. 词黑名单
    for rule_name, conf in patterns.get("blacklist_words", {}).items():
        if rule_name.startswith("_"):
            continue
        v = _check_word_list(plain, rule_name, conf)
        if v:
            violations.append(v)

    # 2. 句式黑名单 (regex)
    for rule_name, conf in patterns.get("blacklist_phrases", {}).items():
        if rule_name.startswith("_"):
            continue
        v = _check_regex_list(plain, rule_name, conf)
        if v:
            violations.append(v)

    # 3. 结构性硬约束
    for rule_name, conf in patterns.get("structural_rules", {}).items():
        if rule_name.startswith("_"):
            continue
        v = _check_structural(plain, rule_name, conf)
        if v:
            violations.append(v)

    # 4. 节奏
    rhythm_violations, stats = _rhythm_score(plain, patterns)
    violations.extend(rhythm_violations)

    # 5. 反伪经验检测 - 只在没 notes.md 时启用
    if not has_notes:
        for rule_name, conf in patterns.get("fake_human", {}).items():
            if rule_name.startswith("_"):
                continue
            v = _check_regex_list(plain, rule_name, conf, category="fake_human")
            if v:
                violations.append(v)
    else:
        # 有 notes.md, 改为轻提醒(不扣分)
        stats["伪经验检测"] = "已豁免 (notes.md 存在)"

    # 6. 灵魂信号(论证质量, 不强迫第一人称)
    soul_violations, _ = _soul_bonus(plain, patterns)
    violations.extend(soul_violations)

    raw = sum(v.score for v in violations)
    # 长度归一: 每 3000 字一个标准单位, 超长不要被加倍
    norm_factor = max(1.0, len(plain) / 3000)
    total = min(100.0, raw / norm_factor)

    return Score(
        total=round(total, 1),
        level=level_label(total),
        violations=violations,
        stats=stats,
        text_length=len(plain),
    )


def main():
    if len(sys.argv) < 2:
        print("用法: python -m humanize.detect <file> [--json] [--notes]")
        print("  --notes  项目有 notes.md, 豁免伪经验检测器")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"错误: 文件不存在 {path}")
        sys.exit(1)
    text = path.read_text(encoding="utf-8")

    # 自动检测 notes.md (句柄同级目录或 site-digester output 目录)
    has_notes = "--notes" in sys.argv
    if not has_notes:
        # 同级目录查 notes.md
        notes_path = path.parent / "notes.md"
        if notes_path.exists() and notes_path.stat().st_size > 100:
            has_notes = True
            print(f"  自动检测到 {notes_path}, 豁免伪经验检测\n")

    s = score(text, has_notes=has_notes)

    if "--json" in sys.argv:
        out = {
            "total": s.total,
            "level": s.level,
            "text_length": s.text_length,
            "stats": s.stats,
            "violations": [
                {"category": v.category, "rule": v.rule,
                 "count": v.count, "score": v.score, "sample": v.sample}
                for v in s.violations
            ],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(s)


# ─── Protocol adapter ─────────────────────────────────────────────────────


class ZhDetector:
    """Thin :class:`~humanize_zh._core.protocols.Detector` adapter around
    the module-level :func:`score` function.

    Stateless; safe to share across threads (relies on the function's own
    re-entrancy, which only touches the on-disk ``patterns.json`` via
    ``_load_patterns``).
    """

    code = "zh"

    def __init__(self) -> None:
        # Lazy-read rule-set version from patterns.json so it tracks the
        # data file rather than getting baked into source.
        try:
            self.version: str = _load_patterns().get("_meta", {}).get("version", "0.0.0")
        except Exception:
            self.version = "0.0.0"

    def score(self, text: str, *, has_notes: bool = False) -> Score:
        """Delegate to the module-level :func:`score`.

        The function exposes an extra ``skip_codeblocks`` kwarg that the
        Detector protocol does not require; we keep its default (``True``)
        to match historical behaviour.
        """
        return score(text, has_notes=has_notes)


# Singleton instance — imported by ``humanize_zh._lang.zh.profile`` and by
# any caller that wants a Detector-protocol-typed handle without paying
# the rule-set version read twice.
zh_detector = ZhDetector()


if __name__ == "__main__":
    main()
