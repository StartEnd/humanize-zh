# Changelog

All notable changes to **humanize-zh** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0a1] — Phase 2: package extraction (humanize-core split)

### Changed (high-level)

This release completes the multi-language refactor's **Phase 2**:
the framework code (protocols, registry, postprocess/judge/iterative
dispatchers, LLM provider abstractions, web middleware) moved to a
new sibling package, **`humanize-core`**. `humanize-zh` is now a
thin language plugin layered on top of it via the
`humanize_core.languages` entry-point.

The user-visible API is **byte-identical to v0.1.0a1**: every public
import (`from humanize_zh import score, postprocess_humanize, judge,
iterative_polish, ...`) still works, every CLI flag and Web UI route
behaves the same, and all 288 tests pass unchanged. The change is
purely structural — installing `humanize-zh` now also installs
`humanize-core>=0.1.0a1` as a dependency, and the registry
auto-discovers the ZH profile on first use.

### Added

- New runtime dependency: **`humanize-core>=0.1.0a1`** (declared in
  `pyproject.toml`). `humanize-zh[openai|anthropic|ui]` extras forward
  to the matching `humanize-core[*]` extras so users still get a
  one-line install.
- Entry-point auto-registration: `humanize-zh` advertises
  `zh = humanize_zh._lang.zh.profile:zh_profile` under the
  `humanize_core.languages` group. Importing `humanize_zh` is no
  longer required for `humanize_core.get_language("zh")` to work —
  the framework discovers the plugin lazily.
- `humanize_zh.web._security.AbuseControlConfig.from_env` accepts both
  the legacy `HUMANIZE_ZH_WEB_TOKEN` /
  `HUMANIZE_ZH_WEB_RATE_LIMIT_PER_MINUTE` env vars **and** the
  canonical `HUMANIZE_CORE_WEB_*` names. Legacy names take
  precedence so existing deployments keep working.
- ZH `PromptPack.writer_prompt_builder` is now wired to
  `build_humanize_postprocess_prompt`, so the framework's polish
  dispatcher routes through ZH's rule-list / aggressive-mode
  assembler instead of naive `str.format(ARTICLE=...)`.

### Changed (per-module)

The following modules became **thin shims** over `humanize_core`.
Public API unchanged; line counts are post-shrink.

| Module | Pre-shrink | Post-shrink | Notes |
|---|---|---|---|
| `humanize_zh._core/` | full package | sys.modules alias to `humanize_core` | preserves `humanize_zh._core.{language_registry,protocols,prompt}` import paths |
| `humanize_zh._format` | local impl | re-export from `humanize_core._format` | |
| `humanize_zh.llm.*` | full impl | re-export from `humanize_core.llm` | |
| `humanize_zh.detect` | full impl | shim | delegates to `humanize_core.detect` + `zh_profile` |
| `humanize_zh.combined` | full impl | shim | |
| `humanize_zh.ngram_check` | full impl | shim | |
| `humanize_zh.prompt` | full impl | shim + ZH `build_humanize_postprocess_prompt` dispatcher | |
| `humanize_zh.postprocess` | 375 LOC | 185 LOC | wraps `humanize_core.postprocess.postprocess_humanize` with `lang="zh"` default; preserves `replacements=` injection via `_ZhCodeReplacementsAdapter` |
| `humanize_zh.judge` | 290 LOC | 232 LOC | delegates `judge()` to humanize-core; keeps a ZH-localized `format_report` so output stays Chinese |
| `humanize_zh.iterative` | 230 LOC | 123 LOC | re-exports `IterativeResult` / `RoundResult` / `Verdict` from core; wraps `_judge_one_round` with `profile=zh_profile` default |
| `humanize_zh.web._security` | 174 LOC | 84 LOC | inherits `AbuseControlConfig` from core; only overrides `from_env` for env-var aliasing |

### Notably **not** collapsed (and why)

- `humanize_zh.cli/` and `humanize_zh.web/app.py` stay ZH-specialized.
  The substantive operations (detect/postprocess/judge) flow through
  the shims into `humanize_core`, so there's no remaining duplicate
  *logic* — only the presentation layer (Chinese strings, ZH-only
  routes, ZH templates) lives here, which is exactly where
  plugin-localized UX belongs.

### Fixed

- `humanize_core.postprocess._build_writer_prompt` now substitutes
  `{ARTICLE}` / `{text}` / `{scene}` / `{violations}` /
  `{aggressive_block}` only where present in the template, instead
  of failing with `KeyError` when a `PromptPack` uses a strict subset
  of placeholders. Matches the contract documented on
  `humanize_core.PromptPack`.

### Migration notes for v0.1.0a1 users

- **No code changes required.** Every import path used by the
  v0.1.0a1 README and examples still resolves. Even legacy private
  imports (`humanize_zh._core.language_registry`,
  `humanize_zh.judge._call_llm`, etc.) are kept as re-exports for
  out-of-tree readers.
- **`pip install humanize-zh==0.2.0a1`** will pull `humanize-core` as a
  transitive dependency. Users who don't want the framework dep
  shouldn't upgrade.
- **Web env vars**: both `HUMANIZE_ZH_WEB_TOKEN` and
  `HUMANIZE_CORE_WEB_TOKEN` are honored. New deployments should
  prefer the `HUMANIZE_CORE_*` names because they work regardless
  of which language plugin is installed.

### Background — Phase 1 (also shipped in this release)

The internal-only Phase-1 scaffold (the protocol layer, ZH plugin
extraction, registry-aware tests) was completed but never tagged on
its own; it ships as part of `0.2.0a1` together with Phase 2. The
Phase-1 highlights below are reproduced for completeness; the
substantive listing (`### Changed`, `### Fixed`) above already
covers everything new in `0.2.0a1`.

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
