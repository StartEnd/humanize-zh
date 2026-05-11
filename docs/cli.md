# CLI reference

The `humanize-zh` shell command (installed via `pip install humanize-zh`) is
a thin wrapper around the Python SDK. Same logic, same outputs.

```
humanize-zh [-v|--verbose] [--version]
            { detect | polish | judge | providers }
            [subcommand options...]
```

You can also run it as a module: `python -m humanize_zh.cli ...`

## Global flags

| Flag | Purpose |
|---|---|
| `--version` | Print version and exit. |
| `-v / --verbose` | Enable INFO logging from `humanize_zh.*`. Off by default. |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Runtime error (LLM failure, unexpected exception) |
| `2` | Usage error (missing subcommand, bad args, file not found) |
| `3` | `judge` returned an error verdict (e.g. parse error, collusion) |
| `130` | `Ctrl+C` |

## `detect` — rule + ngram + combined score

```
humanize-zh detect FILE [--json] [--has-notes] [--lang zh|en]
```

| Flag | Default | Description |
|---|---|---|
| `--json` | off | Emit machine-readable JSON instead of text. |
| `--has-notes` | off | Article is grounded in a `notes.md`; relax fake-human checks. |
| `--lang` | `zh` | `en` early-exits with a notice — there's no Chinese rule/ngram model for English. |

Examples:

```bash
humanize-zh detect article.md
humanize-zh detect article.md --json | jq '.combined.probability'
```

## `polish` — LLM 去 AI 味润色

```
humanize-zh polish FILE [-o OUT]
                        [--scene analysis|essay|academic|blog]
                        [--lang zh|en]
                        [--provider NAME]
```

| Flag | Default | Description |
|---|---|---|
| `-o / --out` | `<file>.polished.md` | Output path. |
| `--scene` | `analysis` | Sets injected rules; only matters in ZH mode. |
| `--lang` | `zh` | `zh` runs the full pipeline; `en` runs LLM-only with English prompt. |
| `--provider` | autodetect | Force a specific provider name (overrides autodetect). |

Provider names: `openai`, `anthropic`, `deepseek`, `groq`, `openrouter`,
`moonshot`, `glm`, `qwen`, `ollama`. See [`providers.md`](providers.md).

If no provider is configured and no `--provider` is given, `polish` exits 1
with a clear error pointing to the env vars to set.

Examples:

```bash
# Use whatever provider is detected from env
humanize-zh polish article.md

# Force DeepSeek
DEEPSEEK_API_KEY=... humanize-zh polish article.md --provider deepseek

# English LLM-only
OPENAI_API_KEY=... humanize-zh polish article.md --lang en -o cleaned.md
```

## `judge` — LLM 终审

```
humanize-zh judge FILE [-o OUT]
                       [--lang zh|en]
                       [--writer NAME]
                       [--judge NAME]
                       [--json]
                       [--allow-self-judge]
```

| Flag | Default | Description |
|---|---|---|
| `-o / --out` | `<file>.judge.md` | Where to save the report (or JSON if `--json`). |
| `--lang` | `zh` | Switches between Chinese and English judge prompts. |
| `--writer` | none | Identity used to detect collusion (the "writer" of the article). |
| `--judge` | active provider | Provider that performs the review. |
| `--json` | off | Emit JSON instead of the formatted Markdown report. |
| `--allow-self-judge` | off | Bypass the writer-vs-judge collusion check (not recommended). |

Collusion is detected on `(name, model)`. If `--writer deepseek` and the
active judge resolves to the same identity, `judge` returns `_error` (exit 3).

Examples:

```bash
# Use the autodetected provider as the judge
humanize-zh judge article.md

# Two different providers (recommended): writer was DeepSeek, judge with Claude
humanize-zh judge article.md --writer deepseek --judge anthropic

# JSON output for automation
humanize-zh judge article.md --json | jq '.publishable'
```

## `providers` — list autodetectable LLMs

```
humanize-zh providers
```

Prints the chain of supported providers and which ones currently have their
API keys set in the environment:

```
provider     env var                status
------------------------------------------------
openai       OPENAI_API_KEY           (not set)
anthropic    ANTHROPIC_API_KEY        (not set)
deepseek     DEEPSEEK_API_KEY       ✓ available
groq         GROQ_API_KEY             (not set)
...

active provider will autodetect in order: deepseek
```
