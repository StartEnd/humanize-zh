# Migration: `humanize` → `humanize-zh`

If you were using the bundled `humanize` module from
[site-digester](https://github.com/song/site-digester), you can switch to the
standalone `humanize-zh` package without changing any detection scores.

## What stays identical

Phase 7 regression validates that, for every real article on
templeluck.com / rpedia.me / youraislopbores.me, both versions agree on:

- `score(text).total` and `score(text).level` (rule-based detection)
- `ngram_score(text).ai_probability` (n-gram statistics)
- `combined_score(text).combined_probability` (max-style ensemble)
- The exact list of `Violation` objects (category / rule / count)
- `_deterministic_cleanup(text)` byte-for-byte output (sha256 match)
- `_strip_number_backticks(text)` byte-for-byte output

3 sites × 2 article versions × 6 checks = **36 ✓ in the regression suite**.

## What changes

| Old (`site-digester/humanize/`) | New (`humanize-zh`) |
|---|---|
| `from humanize import score` | `from humanize_zh import score` |
| `from humanize import postprocess_humanize` | `from humanize_zh import postprocess_humanize` |
| `provider="deepseek"` (string only) | `provider=LLMProvider \| str \| None` |
| Implicit `from generate import generate_article` | Explicit `llm.use(...)` / `llm.autodetect()` |
| No CLI entry point | `humanize-zh detect / polish / judge` |
| Chinese only | `lang="zh"` (default) or `lang="en"` (LLM-only) |

## Step-by-step migration

### 1. Replace imports

```diff
- from humanize import score, postprocess_humanize, judge, build_humanize_prompt
+ from humanize_zh import score, postprocess_humanize, judge, build_humanize_prompt
```

The public API names are identical.

### 2. Configure the LLM provider explicitly

The old module reached into `scripts/generate.py` of site-digester for
LLM access. `humanize-zh` decouples that:

```python
from humanize_zh import llm

# Option A: keep the old behavior with env-var autodetection
llm.autodetect()

# Option B: bridge to the existing generate_article gateway
from scripts.generate import generate_article
llm.use_callable(
    lambda prompt: generate_article(prompt) or "",
    name="site-digester-gateway",
)
```

Once configured, every call to `postprocess_humanize`/`judge` will use it.

### 3. Use the CLI in place of the script

site-digester's `scripts/humanize.py` ran detection / polish / judge as
subcommands. The new CLI is a drop-in replacement:

| site-digester command | humanize-zh command |
|---|---|
| `python scripts/humanize.py detect article.md` | `humanize-zh detect article.md` |
| `python scripts/humanize.py polish article.md --provider deepseek` | `humanize-zh polish article.md --provider deepseek` |
| `python scripts/humanize.py judge article.md --writer deepseek --judge anthropic` | `humanize-zh judge article.md --writer deepseek --judge anthropic` |

Exit codes and output formats are unchanged for `detect`. `polish` writes to
`<file>.polished.md` by default; pass `-o OUT` to override.

### 4. Optional: switch to the typed provider classes

If you want richer error handling than the legacy string-based provider:

```python
from humanize_zh import postprocess_humanize, llm
from humanize_zh.llm import LLMRateLimitError
from humanize_zh.llm.openai_compat import OpenAICompatProvider

deepseek = OpenAICompatProvider(
    name="deepseek",
    base_url="https://api.deepseek.com",
    api_key=os.environ["DEEPSEEK_API_KEY"],
    model="deepseek-chat",
)

try:
    polished, after, before = postprocess_humanize(article, provider=deepseek)
except LLMRateLimitError as e:
    time.sleep(e.retry_after_seconds or 30)
    # retry...
```

### 5. Keep using site-digester's templates

`humanize-zh` does **not** carry the article-shape templates
(`narrative-plan.md`, `draft-*.md`). Those stay in site-digester's
`templates/`. The boundary is:

- **site-digester** owns: data collection, evidence mapping, narrative
  planning, draft generation, full pipeline orchestration.
- **humanize-zh** owns: detection (rule + ngram + combined), polish (LLM),
  judge (LLM), prompt-injectable rule blocks (`build_humanize_prompt`).

You can call `build_humanize_prompt(scene="analysis")` from your draft
template to inject the same "去 AI 味" rule block that the polish layer
applies as feedback.

## Verifying the migration

After switching, run site-digester's regression command:

```bash
# In humanize-zh repo:
.venv/bin/python -m pytest tests/test_regression_templeluck.py -v
```

It runs both packages in subprocess-isolated workers and compares all six
metrics on the real articles. If any check fails, the test names tell you
exactly which (site, version, metric) triple diverged.
