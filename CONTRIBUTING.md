# Contributing to humanize-zh

Thanks for considering a contribution! This document covers the basics. The
project is small and opinionated — please read the README first to see the
design philosophy (three-layer detection + two-layer polish + provider
abstraction).

## Setup

```bash
git clone <repo>
cd humanize-zh
make install               # uv sync + dev/ui/openai/anthropic extras
make test                  # 200+ tests should pass in < 3s
```

Python 3.10+ required. We use `uv` as the package manager.

## Daily loop

```bash
make test-fast             # pytest -q, no coverage instrumentation
make lint                  # ruff check
make fmt                   # ruff --fix + format
make typecheck             # mypy
make web                   # uvicorn reload on :8080
```

Pre-commit hooks mirror the CI gates:

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

## Code style

- **Ruff** for both linting and formatting (config in `pyproject.toml`).
- **mypy** strict mode for `llm.*`, `postprocess`, `judge`, `cli.*`,
  `web.*`. Other modules use progressive typing — same applies to new code
  you add.
- Imports go at the top of the file, sorted by ruff's I001.
- Public functions and classes deserve docstrings; private helpers
  (`_underscore`) only need them when behavior is non-obvious.
- Avoid emojis in code/docs unless explicitly requested.

## Tests

Every behavior change needs a test. Layout:

| File                            | What it covers                          |
|---------------------------------|-----------------------------------------|
| `tests/test_detect.py`          | rule scoring, length norm, edge cases   |
| `tests/test_ngram_check.py`     | ngram wrapper + engine loader           |
| `tests/test_combined.py`        | max-aggregation, fallback semantics     |
| `tests/test_prompt.py`          | prompt-builder contracts                |
| `tests/test_postprocess.py`     | polish pipeline (zh + en)               |
| `tests/test_judge.py`           | judge call + JSON parsing + report      |
| `tests/test_iterative.py`       | writer ↔ judge loop                     |
| `tests/test_llm.py`             | provider registry + concurrency         |
| `tests/test_providers.py`       | OpenAI / Anthropic / Compat SDK mocking |
| `tests/test_helpers.py`         | shared `_format` / `_resolve` helpers   |
| `tests/test_cli.py`             | CLI subcommands (subprocess + in-proc)  |
| `tests/test_web.py`             | FastAPI routes + HTMX fragments         |

LLM-using tests use the **CallableProvider** fixture pattern from
`tests/conftest.py` — never make real API calls in unit tests.

## Pull requests

1. Branch from `main`.
2. Run `make fmt lint typecheck test` locally — all green.
3. Update `CHANGELOG.md` under `## [Unreleased]`.
4. If your change touches `patterns.json` rules, document the calibration
   source (HC3-Chinese sample range, Cohen's d, etc.) in the entry's
   `_desc`.
5. Open a PR with a description of the **before / after** behavior, not
   just the diff.

## Adding a new LLM provider

If it's OpenAI-API-compatible, append a row to
`humanize_zh/llm/registry.py::_OPENAI_COMPAT_TABLE` — CLI and Web UI pick
it up automatically. Anything else needs a new file under `humanize_zh/llm/`
that subclasses `LLMProvider` and implements `complete()`. See
`tests/test_providers.py` for the SDK-mock pattern.

## Reporting bugs

Please include:

- `humanize-zh providers` output
- Python version (`python --version`)
- Minimal reproducer (text snippet + the call that misbehaved)
- Whether you're using a local relay or a hosted endpoint
