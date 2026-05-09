# humanize-zh

> Chinese AI text humanization library — 中文去 AI 味工具包

[![PyPI](https://img.shields.io/badge/pypi-0.1.0a1-blue)](https://pypi.org/project/humanize-zh/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A production-grade Python library for detecting and removing AI-generated patterns in Chinese text. Combines rule-based detection, character-level n-gram models, deterministic post-processing, and LLM-driven rewrites.

## Why

Existing AI text detectors target English. Chinese AI text has different statistical signatures and stylistic tells (e.g., overuse of `而是`, three-part summaries, rhetorical metaphors). `humanize-zh` provides:

- **Rule detector** — 24+ Chinese AI writing patterns from research (op7418/Humanizer-zh, OUBIGFA/De-AI-Prompt)
- **N-gram detector** — Character-level perplexity / burstiness / entropy on HC3-Chinese
- **Combined score** — `max(rule, ngram)` for max-style ensemble
- **Deterministic polish** — Strip number backticks, replace AI vocabulary, no LLM call
- **LLM polish** — Multi-provider rewriter that picks the best of (original / cleaned / LLM-polished / LLM-cleaned)
- **LLM judge** — Independent reviewer to catch semantic AI tells the rule layer misses

Tested against 腾讯朱雀 AI detector — bringing baseline 10.56% → **0% AIGC** on real analysis articles.

## Install

```bash
pip install humanize-zh

# With LLM provider support
pip install "humanize-zh[openai]"          # OpenAI
pip install "humanize-zh[anthropic]"       # Anthropic
pip install "humanize-zh[ui]"              # Web UI
pip install "humanize-zh[all]"             # Everything
```

## Quick start

```python
from humanize_zh import score, polish

text = open("article.md").read()

# 1. Just detect (no LLM)
s = score(text)
print(f"AI probability: {s.total}/100 ({s.level})")

# 2. Polish (needs LLM)
from humanize_zh import llm
llm.use("openai", model="gpt-4o", api_key="sk-...")
polished, after_score, before_score = polish(text)
```

## CLI

```bash
humanize detect article.md             # Rule + ngram detection
humanize polish article.md             # LLM-driven rewrite
humanize judge article.md              # LLM independent reviewer
humanize ui                            # Launch web UI on localhost:7860
```

## LLM Providers

```python
from humanize_zh import llm

# Auto-detect from environment
llm.autodetect()

# Official OpenAI
llm.use("openai", api_key="sk-...", model="gpt-4o")

# Anthropic
llm.use("anthropic", api_key="sk-ant-...", model="claude-3-5-sonnet")

# OpenAI-compatible (DeepSeek / Groq / OpenRouter / Ollama / etc.)
llm.use_openai_compat(
    name="deepseek",
    base_url="https://api.deepseek.com",
    api_key="sk-...",
    model="deepseek-chat",
)

# Custom callable (any function that takes a prompt and returns text)
llm.use_callable(lambda prompt: my_llm_api(prompt), name="custom")
```

## Status

| Feature | Status |
|---|---|
| Chinese rule detector | ✅ |
| Chinese n-gram detector | ✅ |
| Deterministic polish | ✅ |
| LLM polish (multi-provider) | 🚧 (Phase 2) |
| LLM judge | 🚧 |
| English mode (LLM-only) | 🚧 |
| English full detector | 📋 (M1.5) |
| FastAPI Web UI | 📋 (Phase 5) |
| pip-installable | ✅ |

## License

MIT © 2026 song
