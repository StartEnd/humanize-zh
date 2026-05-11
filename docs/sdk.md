# SDK reference

`humanize-zh` is designed as both a Python library (this document) and a CLI
(see [`cli.md`](cli.md)). All public API lives in the top-level `humanize_zh`
namespace.

```python
from humanize_zh import (
    score,                      # rule detector
    Score,                      # rule score dataclass
    Violation,                  # individual rule hit
    ngram_score,                # ngram detector
    NgramScore,
    combined_score,             # max(rule, ngram) ensemble
    CombinedScore,
    postprocess_humanize,       # LLM polish pipeline
    judge,                      # LLM judge
    format_judge_report,
    build_humanize_prompt,      # injectable rules block
    build_humanize_postprocess_prompt,
    llm,                        # provider configuration submodule
    __version__,
)
```

## Detection

### `score(text, *, has_notes=False, skip_codeblocks=True) -> Score`

Rule-based AI detection. Pure-Python, no network call.

```python
from humanize_zh import score

s = score(open("article.md").read())
print(s.total)            # 0-100 probability
print(s.level)            # LOW / MEDIUM / HIGH / VERY HIGH
for v in s.violations:
    print(f"{v.category}.{v.rule} x{v.count}: {v.sample}")
```

`has_notes=True` relaxes fake-human detection when the article is grounded in
a real `notes.md` log.

### `ngram_score(text) -> NgramScore`

Character-level statistical detection (perplexity / burstiness / entropy).
Calibrated on HC3-Chinese.

```python
ns = ngram_score(text)
print(ns.ai_probability)  # 0-100
print(ns.metrics)         # raw per-feature numbers
print(ns.available)       # False if data files are missing (graceful degrade)
```

### `combined_score(text, has_notes=False) -> CombinedScore`

Ensemble of rule + ngram for release gating:
```
combined_probability = max(rule_probability, ngram_probability)
```
Any layer scoring HIGH triggers the combined HIGH. Useful as the final
gate before publish.

## Polish

### `postprocess_humanize(text, *, scene, lang, violations, provider, detect_first)`

```python
from humanize_zh import postprocess_humanize, llm

llm.autodetect()  # or any other provider configuration

polished, after, before = postprocess_humanize(
    text,
    scene="analysis",   # analysis | essay | academic | blog
    lang="zh",          # "zh" full pipeline | "en" LLM-only
)

print(f"AI score: {before.total} → {after.total}")
```

| `lang` | Behavior |
|---|---|
| `"zh"` | Detect → if rule<25 and combined<30 skip; otherwise LLM polish; pick the lowest-scoring of (orig / cleaned / LLM / LLM+cleaned) |
| `"en"` | Skip Chinese detection layers; LLM polish with English prompt + universal number-backtick stripping |

`provider` accepts:

- `None` — use `llm.get_active()` (raises `LLMNotConfiguredError` if unset)
- `LLMProvider` instance — used directly, doesn't touch the global registry
- `str` — provider name; resolved against env vars

If the LLM call fails, ZH mode falls back to the deterministic-cleanup
candidate; EN mode falls back to the input + number-backtick stripping.

## Judge

### `judge(text, *, lang, writer_provider, judge_provider, allow_self_judge)`

Independent LLM review. Returns the 7-field structured JSON designed for
release gating:

```json
{
  "publishable": false,
  "worst_ai_sections": [{"para": "...", "reason": "..."}],
  "unsupported_claims": [{"claim": "...", "missing_evidence": "..."}],
  "template_smell": ["..."],
  "fake_human_details": ["..."],
  "best_theses": ["..."],
  "rewrite_brief": "...",
  "_meta": {
      "judge_provider": "anthropic::claude-3-5-sonnet-20241022",
      "writer_provider": "deepseek::deepseek-chat",
      "lang": "zh",
      "article_length": 4870
  }
}
```

Collusion detection compares `(provider.name, provider.model)`. If both writer
and judge resolve to the same identity, returns `{"_error": "Collusion ..."}`
unless `allow_self_judge=True`.

### `format_judge_report(result) -> str`

Render the JSON into a human-readable Markdown report.

## Prompt building

### `build_humanize_prompt(scene="analysis", *, compact=False) -> str`

Build the full set of "去 AI 味" rules as a Markdown block, ready to inject
into your own writing prompt:

```python
from humanize_zh import build_humanize_prompt

rules = build_humanize_prompt(scene="analysis")
my_prompt = my_template.replace("{HUMANIZE_RULES}", rules)
```

Scenes: `analysis` | `essay` | `academic` | `blog`.

### `build_humanize_postprocess_prompt(article, violations, scene, *, lang)`

Used internally by `postprocess_humanize`. Exposed for advanced cases where
you want to manage the LLM call yourself.

## LLM providers

See [`providers.md`](providers.md) for the full guide.

```python
from humanize_zh import llm

# 1. Auto-detect
llm.autodetect()

# 2. OpenAI / Anthropic
llm.use("openai", api_key="sk-...", model="gpt-4o")
llm.use("anthropic", api_key="sk-ant-...", model="claude-3-5-sonnet-20241022")

# 3. Any OpenAI-compatible service
llm.use_openai_compat(
    name="deepseek",
    base_url="https://api.deepseek.com",
    api_key="sk-...",
    model="deepseek-chat",
)

# 4. Custom callable
llm.use_callable(my_func, name="custom", model="v1")

# Inspect / reset
llm.has_active()           # bool
llm.get_active()           # LLMProvider, raises LLMNotConfiguredError
llm.clear()                # reset
```

## Exception tree

All errors derive from `LLMError`:

```
LLMError
├── LLMConfigError              # missing api_key, invalid model, etc.
├── LLMAuthError                # invalid api_key
├── LLMRateLimitError           # 429, carries .retry_after_seconds
├── LLMTimeoutError             # request timeout
├── LLMContextLimitError        # prompt exceeds context window
├── LLMProviderError            # 5xx, network, generic provider failures
└── LLMNotConfiguredError       # get_active() called with no active provider
```

Catch `LLMError` for a generic safety net; catch the specific subclass for
targeted recovery (e.g. `LLMRateLimitError` → backoff retry).
