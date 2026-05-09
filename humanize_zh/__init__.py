"""humanize — 综合 6 个开源项目的去 AI 味工具

主要 API:
    from humanize import score, build_humanize_prompt, postprocess_humanize

参考的开源项目:
    - op7418/Humanizer-zh           (24 条 AI 写作模式 + 1-50 评分)
    - hylarucoder/ai-flavor-remover (LangGPT 角色扮演 prompt)
    - OUBIGFA/De-AI-Prompt          (18 条硬量化约束 + 段落节奏)
    - nezhazheng/quaiwei-skill      (引号 + 中英空格清理)
    - shyuan/writing-humanizer      (双轮改写 + 红旗自检)
    - voidborne-d/humanize-chinese  (HC3 校准 + ML 评分)
"""

from .detect import score, Score, Violation
from .prompt import build_humanize_prompt, build_humanize_postprocess_prompt
from .postprocess import postprocess_humanize
from .judge import judge, format_report as format_judge_report
from .ngram_check import ngram_score, NgramScore
from .combined import combined_score, CombinedScore

__all__ = [
    "score",
    "Score",
    "Violation",
    "build_humanize_prompt",
    "build_humanize_postprocess_prompt",
    "postprocess_humanize",
    "judge",
    "format_judge_report",
    "ngram_score",
    "NgramScore",
    "combined_score",
    "CombinedScore",
]
