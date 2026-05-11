# Changelog

All notable changes to **humanize-zh** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Multi-language plugin scaffold (Phase 1)** — internal architecture
  refactor preparing the ground for a `humanize-en` sibling package.
  Zero observable change for v0.1 callers: every public import,
  function signature, CLI flag, and Web UI route is byte-identical;
  the existing 215 tests pass unchanged.
  - New `humanize_zh._core/` (framework): `protocols.py` declares the
    `Detector` / `NgramEngine` / `ReplacementsTable` / `PromptPack` /
    `LanguageProfile` runtime-checkable protocols, and
    `language_registry.py` provides thread-safe
    `register_language` / `get_language` / `list_languages` plus
    entry-point discovery under `humanize_core.languages`.
  - New `humanize_zh._lang/zh/` (built-in plugin): the ZH detector,
    n-gram engine, replacements table, prompts, and assembled
    `zh_profile` live here. `humanize_zh.detect` / `humanize_zh.ngram_check`
    are kept as thin compat shims that re-export from the canonical
    locations.
  - `humanize_zh/__init__.py` auto-registers `zh_profile` on import
    and exposes the registry surface
    (`get_language`, `register_language`, `LanguageProfile`, …).
  - `humanize_zh.judge()` and `humanize_zh.iterative_polish()` accept an
    optional `profile: LanguageProfile`; `humanize_zh.postprocess_humanize`
    accepts an optional `replacements: ReplacementsTable`. Defaults
    preserve v0.1.0a1 behavior bit-for-bit.
  - +71 net tests: `tests/test_protocols.py` covers the protocol /
    registry contracts; `tests/test_en_dry_run.py` plugs a stub English
    profile end-to-end through `judge` / `iterative_polish` /
    `postprocess` via the registry, proving the protocol surface is
    sufficient for a real Phase-3 EN plugin without framework changes.
  - Design recorded in `docs/plan-multilang.md`.
- `humanize_zh.web._security.AbuseControlMiddleware` — opt-in
  Bearer-token auth and per-IP rolling-window rate limiting. Activate
  via `HUMANIZE_ZH_WEB_TOKEN` and/or
  `HUMANIZE_ZH_WEB_RATE_LIMIT_PER_MINUTE`. Default: both off (no
  behavior change for existing deployments). Auth runs before rate-limit
  so unauthenticated bursts cannot drain the budget for real users.
  `/health` always passes through. See `SECURITY.md`.
- XSS regression tests for `/htmx/detect` and `/htmx/polish` — pin the
  Jinja2 autoescape contract so a stray `| safe` filter is caught at CI.
- `humanize_zh._format.level_label()` — single source of truth for the
  `LOW / MEDIUM / HIGH / VERY HIGH` Chinese label mapping used across
  `detect`, `ngram_check`, and `combined`.
- `humanize_zh.llm.provider_id()` — shared provider identity helper
  (`<name>::<model>` format). Replaces local copies in `judge.py` and
  `iterative.py`.
- `humanize_zh.llm.list_providers()` and `required_env_keys_hint()` —
  catalogue of supported providers + env-var keys, consumed by both the CLI
  `providers` subcommand and the Web UI provider panel.
- `humanize_zh.llm.resolve_provider()` — unified `LLMProvider | str | None`
  normalization, with optional `autodetect_on_none=` for zero-config callers.
- Dedicated test files: `test_detect.py`, `test_ngram_check.py`,
  `test_combined.py`, `test_prompt.py`, `test_helpers.py`, `test_providers.py`.
- Concurrency test: `set_active` under a 50-thread barrier (Pass C.2).
- `Makefile` with `make test / lint / fmt / typecheck / cov / dev / build / clean`.
- `.pre-commit-config.yaml` mirroring CI gates (ruff + mypy).
- `patterns.json::replacements` gained `site_digester` and `hedge_to_assertive`
  buckets plus an explicit `_order` array; previously hardcoded list in
  `postprocess._deterministic_cleanup` is now data-driven (75 pairs total).

### Changed

- Bumped `__version__` in `humanize_zh/__init__.py` to `0.1.0a1` to match
  `pyproject.toml` (they had drifted).
- Vendored `data/_ngram_engine.py` is now loaded via
  `importlib.util.spec_from_file_location` under the
  `humanize_zh._ngram_engine` private module name. No more
  `sys.path.insert(0, DATA_DIR)` global pollution.
- `ngram_check._safe_call` switched from `print(..., file=sys.stderr)` to
  the package `logger.warning` so errors honor the host's logging config.
- `registry._ACTIVE` access is now wrapped in a `threading.RLock` — safe for
  the FastAPI threadpool that runs sync routes.
- Provider id separator standardized on `::` (was inconsistent: `judge.py`
  used `::`, `iterative.py` used `:`). The single-colon variant collided
  with Ollama model names like `qwen2.5:7b`.

### Fixed

- `iterative_polish(writer_provider="deepseek")` (and other OpenAI-compat
  names) used to raise `ValueError` because `iterative._resolve` routed
  string args through `llm.use()` which only accepts `"openai"` / `"anthropic"`.
  Now routes through `resolve_provider` which understands the full
  autodetect catalogue.

## [0.1.0a1] — Initial scaffold

- Three-layer detection: rule (`detect.py`), ngram statistical
  (`ngram_check.py`), combined max-aggregation (`combined.py`).
- LLM polish layer (`postprocess.py`) with deterministic cleanup +
  protected-span regex + best-of-N candidate selection.
- LLM judge layer (`judge.py`) with collusion protection (writer ≠ judge
  by default).
- Iterative writer ↔ judge loop (`iterative.py`).
- LLM provider abstraction (`llm/`) for OpenAI, Anthropic,
  OpenAI-compatible (DeepSeek / Groq / OpenRouter / Moonshot / GLM /
  Qwen / Ollama), and Callable.
- CLI (`humanize-zh` entry point) with `detect / polish / judge /
  providers / ui` subcommands.
- FastAPI + HTMX web UI (`humanize_zh.web`).
- 89 tests, ~64% line coverage at scaffold time.
