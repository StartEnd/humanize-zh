# humanize-zh

> 给自己写公众号 / 小红书 / 知乎用的中文去 AI 味工具

[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![mypy](https://img.shields.io/badge/mypy-clean-brightgreen)](pyproject.toml)
[![tests](https://img.shields.io/badge/tests-89%20passing-brightgreen)](tests/)

## 30 秒上手 (Web UI 推荐)

```bash
# 1. 进 repo, 装依赖
cd humanize-zh
uv pip install -e '.[openai,anthropic,ui]'

# 2. 在仓库根目录建 .env, 写一个或多个 LLM key (gitignored)
cat > .env <<'EOF'
DEEPSEEK_API_KEY=sk-...
# 或者 minimax 走 anthropic 兼容 (推荐双 LLM 防 judge collusion)
ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic
ANTHROPIC_API_KEY=sk-cp-...
ANTHROPIC_MODEL=MiniMax-M2.7
EOF

# 3. 启 Web UI
humanize-zh ui --port 8765
# 浏览器打开 http://127.0.0.1:8765
```

打开页面 → 默认就是 **🚀 一键去 AI** tab → 粘文章 → 点蓝色按钮 → 等 30-90s → 复制改写后文章 → 拿去
[朱雀检测](https://matrix.tencent.com/ai-detect/) 复测.

朱雀仍报高分? 点页面右上 **高级** → **🔁 闭环改写 (3 轮 LLM)** → 用第二个 LLM 当 judge 打分指
出 AI tells, 让第一个 LLM 针对 tells 重写, 最多 5 轮.

---

## 为什么需要这个

英文 AI 检测器对中文不准. 中文 AI 文有自己的统计特征 (`而是` 滥用 / 三段总结式 / 抽象比喻) 和不同
的"人味"标记. 这个工具组合了 4 层信号:

- **Rule detector** — 24+ 条中文 AI 写作模式
- **N-gram detector** — 基于 HC3-Chinese 的 char-level 困惑度
- **Combined score** — `max(rule, ngram)` 集成发布门控
- **Deterministic polish** — 不调 LLM 也能去掉常见 AI 词汇和数字反引号
- **LLM polish** — 多 provider 重写, best-of-N 选最低分候选
- **LLM judge** — 独立 LLM 审稿, 强制 writer ≠ judge 防共谋
- **Iterative loop** — writer ↔ judge ping-pong 多轮直到目标分

朱雀实测: 真实文章基线 10.56% AIGC → 完整 pipeline 后 ≤ 5% AIGC.

## Install (其它途径)

如果不想用 Web UI:

```bash
pip install humanize-zh                    # core: detect + ngram + deterministic cleanup
pip install "humanize-zh[openai]"          # + OpenAI provider
pip install "humanize-zh[anthropic]"       # + Anthropic / MiniMax via Anthropic-compat
pip install "humanize-zh[ui]"              # + Web UI (FastAPI + HTMX)
pip install "humanize-zh[all]"             # everything
```

## Quick start (SDK)

```python
from humanize_zh import score, ngram_score, combined_score, postprocess_humanize, judge, llm

text = open("article.md").read()

# 1. Pure-Python detection (no LLM)
s = score(text)
print(f"rule:     {s.total}/100  ({s.level})")
print(f"ngram:    {ngram_score(text).ai_probability:.1f}/100")
print(f"combined: {combined_score(text).combined_probability:.1f}/100")

# 2. Configure an LLM provider
llm.autodetect()                            # from env vars
# or: llm.use("openai", api_key="sk-...", model="gpt-4o")
# or: llm.use_openai_compat(name="deepseek", base_url="https://api.deepseek.com",
#                           api_key="sk-...", model="deepseek-chat")
# or: llm.use_callable(my_function, name="custom")

# 3. Polish (Chinese full pipeline)
polished, after, before = postprocess_humanize(text, scene="analysis")

# 4. Judge (independent LLM reviewer)
verdict = judge(text)
print(verdict["rewrite_brief"])

# 5. English LLM-only mode
polished_en, _, _ = postprocess_humanize(text_en, lang="en")
```

## CLI

```bash
humanize-zh detect article.md                    # rule + ngram + combined
humanize-zh detect article.md --json             # machine-readable output
humanize-zh polish article.md -o polished.md     # LLM rewrite (uses active provider)
humanize-zh polish article.md --lang en          # English LLM-only mode
humanize-zh judge  article.md --json             # JSON review
humanize-zh providers                            # list autodetectable LLMs
humanize-zh ui --port 8765                       # FastAPI + HTMX Web UI
humanize-zh --version
```

Exit codes: `0` ok • `1` runtime error • `2` usage / file error • `3` judge failed.

## Web UI

```bash
pip install "humanize-zh[ui]"
humanize-zh ui
# open http://127.0.0.1:8765/
```

Single-page UI with three tabs (`detect` / `polish` / `judge`), HTMX-driven
HTML fragments, Tailwind styling. JSON endpoints under `/api/*`.

## LLM providers

`humanize-zh` ships with four provider classes:

| Class | Use case |
|---|---|
| `OpenAIProvider` | api.openai.com (or Azure OpenAI via `base_url`) |
| `AnthropicProvider` | api.anthropic.com (Claude) |
| `OpenAICompatProvider` | DeepSeek, Groq, OpenRouter, Together, GLM, Moonshot, Qwen, Ollama, vLLM, LM Studio, … |
| `CallableProvider` | Any `(prompt: str) -> str` function (your gateway, mocks, custom retry layers) |

Auto-detection chain (env vars):

```
OPENAI_API_KEY → ANTHROPIC_API_KEY → DEEPSEEK_API_KEY → GROQ_API_KEY →
OPENROUTER_API_KEY → MOONSHOT_API_KEY → GLM_API_KEY → DASHSCOPE_API_KEY →
OLLAMA_BASE_URL
```

## Status

| Phase | Feature | Status |
|---|---|---|
| 1 | Independent repo, pyproject, package boundaries | ✅ |
| 2 | LLM provider abstraction (OpenAI / Anthropic / OpenAI-Compat / Callable / autodetect) | ✅ |
| 3 | `postprocess_humanize` + `judge` rewritten on the new provider layer + `lang="zh"`/`"en"` | ✅ |
| 4 | CLI (`humanize-zh detect / polish / judge / providers`) with argparse subcommands | ✅ |
| 5 | FastAPI + Jinja2 + HTMX + Tailwind Web UI (`humanize-zh ui`) | ✅ |
| 6 | Type hints, ruff/mypy clean, pytest with 72 tests (incl. 13 web), GitHub Actions CI | ✅ |
| 7 | Regression vs site-digester (3 sites × 2 versions × 6 checks = 36 ✓ on real articles) | ✅ |
| M1.5 | Full English detector (lexicon + ngram + rules) | 📋 |

## Repository layout

```
humanize_zh/
├── __init__.py              # Public API surface
├── detect.py                # Rule-based AI detection
├── ngram_check.py           # Character-level n-gram statistics
├── combined.py              # max(rule, ngram) ensemble
├── prompt.py                # Prompt builders for ZH + EN
├── postprocess.py           # LLM polish pipeline
├── judge.py                 # LLM judge with collusion detection
├── llm/                     # Provider abstraction
│   ├── base.py              # LLMProvider ABC + exception tree
│   ├── openai_provider.py
│   ├── anthropic_provider.py
│   ├── openai_compat.py
│   ├── callable_provider.py
│   └── registry.py          # Active provider + autodetect
├── cli/                     # argparse-based CLI
│   ├── main.py
│   └── __main__.py          # `python -m humanize_zh.cli`
├── web/                     # FastAPI + Jinja2 + HTMX UI
│   ├── app.py               # API + HTMX routes
│   ├── templates/           # base.html / index.html / _detect_result.html / ...
│   └── __main__.py          # `python -m humanize_zh.web`
└── data/                    # Embedded n-gram models, regression coefficients

tests/                       # pytest, with subprocess regression vs site-digester
docs/                        # SDK / CLI / providers / migration guides
```

## License

MIT © 2026 song
