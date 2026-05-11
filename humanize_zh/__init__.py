"""humanize_zh — 商业级中文去 AI 味 SDK + CLI

主要 API::

    from humanize_zh import (
        score,                    # 规则检测 (0-100)
        ngram_score,              # ngram 统计检测
        combined_score,           # 组合检测 (发布门控)
        postprocess_humanize,     # LLM 润色去 AI 味 (支持 lang="zh"/"en")
        judge,                    # LLM 终审
        build_humanize_prompt,    # 可注入的规则段
        llm,                      # LLM provider 层
    )

    # 配置 LLM (任选其一)
    llm.autodetect()                              # 从 env 自动检测
    llm.use("openai", api_key="sk-...")
    llm.use_openai_compat(                        # DeepSeek/Groq/OpenRouter/...
        name="deepseek", base_url="...", api_key="...", model="deepseek-chat",
    )
    llm.use_callable(my_fn)                       # 自定义函数

参考的开源项目:
    - op7418/Humanizer-zh           (24 条 AI 写作模式 + 1-50 评分)
    - hylarucoder/ai-flavor-remover (LangGPT 角色扮演 prompt)
    - OUBIGFA/De-AI-Prompt          (18 条硬量化约束 + 段落节奏)
    - nezhazheng/quaiwei-skill      (引号 + 中英空格清理)
    - shyuan/writing-humanizer      (双轮改写 + 红旗自检)
    - voidborne-d/humanize-chinese  (HC3 校准 + ML 评分)
"""

from . import llm
from .combined import CombinedScore, combined_score
from .detect import Score, Violation, score
from .iterative import IterativeResult, RoundResult, iterative_polish
from .judge import format_report as format_judge_report
from .judge import judge
from .ngram_check import NgramScore, ngram_score
from .postprocess import postprocess_humanize
from .prompt import build_humanize_postprocess_prompt, build_humanize_prompt

__version__ = "0.1.0a1"

__all__ = [
    "__version__",
    "llm",
    # detection
    "score",
    "Score",
    "Violation",
    "ngram_score",
    "NgramScore",
    "combined_score",
    "CombinedScore",
    # polish / judge
    "postprocess_humanize",
    "judge",
    "format_judge_report",
    "iterative_polish",
    "IterativeResult",
    "RoundResult",
    # prompts
    "build_humanize_prompt",
    "build_humanize_postprocess_prompt",
]
