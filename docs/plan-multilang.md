# Multi-language refactor plan — `humanize-zh` → `humanize-core` + plugins

**Status**: approved 2026-05-11. Branch: `multilang-spike` (Phase 1).

## 0. Goal & Done

End state (3-4 weeks):

- `pip install humanize-zh` — current capability, zero break for v0.1.0a1 users.
- `pip install humanize-en` — independent package, full English support
  (detect / polish / judge / iterative / Web UI).
- `pip install humanize-zh humanize-en` — single Web UI with language
  switcher; CLI accepts `--lang en|zh`.

Architecture: `humanize-core` is the runtime engine. `humanize-zh` and
`humanize-en` are language plugins discovered via PyPI entry-points.

Compat promise for v0.1.0a1 users:

- All `from humanize_zh import score, postprocess_humanize, ...` keep working.
- `humanize-zh` CLI entry kept as alias.
- Env var names unchanged.

## 1. Target architecture

```
humanize-core (PyPI)
  protocols: Detector, NgramEngine, ReplacementsTable, LanguageProfile
  pipeline: postprocess (lang-agnostic), iterative, judge (lang-aware)
  llm/: provider abstraction (8 services)
  web/: FastAPI + HTMX shell, ?lang= routing
  cli/: humanize entrypoint, --lang flag
  registry: register_language / get_language / list_languages
            (entry-point auto-discovery)

  ▲                                ▲
  │ depends on                     │ depends on

humanize-zh (PyPI)               humanize-en (PyPI, new repo)
  _profile.py: zh impl             _profile.py: en impl
  detect_zh.py                     detect_en.py
  ngram_zh/ + HC3-Chinese          ngram_en/ + RAID-en
  patterns_zh.json                 patterns_en.json
  prompts_zh.py                    prompts_en.py
  templates/*_zh.html              templates/*_en.html
  labels_zh.json                   labels_en.json
  entry_point: zh = ...            entry_point: en = ...
  v0.1 compat shim
```

## 2. Protocol design

```python
# humanize_core/protocols.py
from typing import Protocol, runtime_checkable
from dataclasses import dataclass

@dataclass(frozen=True)
class RuleScoreResult:
    probability: float          # [0, 100]
    violations: list[Violation]
    has_notes: bool
    chars: int
    detector_name: str
    detector_version: str

@runtime_checkable
class Detector(Protocol):
    code: str          # "zh", "en"
    version: str       # rule-set semver
    def score(self, text: str) -> RuleScoreResult: ...

@runtime_checkable
class NgramEngine(Protocol):
    code: str
    available: bool
    corpus_id: str
    def score(self, text: str) -> NgramScoreResult: ...
    def reason_unavailable(self) -> str | None: ...

@runtime_checkable
class ReplacementsTable(Protocol):
    code: str
    def ordered_pairs(self) -> list[tuple[str, str]]: ...

@dataclass(frozen=True)
class PromptPack:
    code: str
    writer_system: str
    writer_user_template: str   # uses {text}, {scene}, {violations}
    judge_system: str
    judge_user_template: str
    rules_section: str

@dataclass(frozen=True)
class LanguageProfile:
    code: str
    display_name: str
    detector: Detector
    ngram_engine: NgramEngine | None
    replacements: ReplacementsTable
    prompt_pack: PromptPack
    level_labels: dict[str, str]  # {"LOW": "...", "MEDIUM": "...", ...}
    metadata: dict[str, str]
```

Discovery: PyPI entry-point group `humanize_core.languages`. Each plugin
registers `code = "humanize_zh:profile"`. Core scans on import via
`importlib.metadata.entry_points(group=...)`.

## 3. File boundary table

| Existing path | Goes to | Notes |
|---|---|---|
| `humanize_zh/llm/` | core | reused as-is |
| `humanize_zh/iterative.py` | core | accepts LanguageProfile |
| `humanize_zh/judge.py` | core | adds `lang: str` param |
| `humanize_zh/postprocess.py` (pipeline) | core | `_deterministic_cleanup` takes injected ReplacementsTable |
| `humanize_zh/combined.py` | core | language-agnostic aggregator |
| `humanize_zh/_format.py` | core | accepts injected `level_labels` |
| `humanize_zh/web/` (minus templates) | core | adds `?lang=` routing |
| `humanize_zh/cli/` | core | `humanize` entry, `--lang` flag |
| `humanize_zh/llm/registry.py` | core | unchanged |
| `humanize_zh/llm/_resolve.py` | core | unchanged |
| `humanize_zh/detect.py` | zh plugin | renamed `detector.py` |
| `humanize_zh/ngram_check.py` + `data/` | zh plugin | data + engine in zh package |
| `humanize_zh/patterns.json` | zh plugin | rules + replacements both there |
| `humanize_zh/prompt.py` | split | framework → core, zh templates → zh plugin |
| `humanize_zh/web/templates/*.html` | zh plugin | exposed via entry-point template dir |

## 4. Migration phases

### Phase 1 — In-repo spike (1.5 days)

Goal: validate the protocol design, smallest blast radius.

1. Add `humanize_zh/_core/` (temporary location)
   - `_core/protocols.py` — protocol definitions
   - `_core/language_registry.py` — register / get / list
2. Add `humanize_zh/_lang/zh/` subpackage
   - Move `detect.py` → `_lang/zh/detector.py`, adapt to protocol
   - Move `ngram_check.py` → `_lang/zh/ngram.py`
   - Split `patterns.json` into `rules.json` + `replacements.json` in `_lang/zh/data/`
   - Add `_lang/zh/profile.py` to assemble `LanguageProfile`
3. Refactor `postprocess.py` / `judge.py` / `iterative.py` / `combined.py`
   to accept `LanguageProfile`
4. Compat shim at top-level `humanize_zh/__init__.py`:
   ```python
   from ._lang.zh.profile import profile as _zh_profile
   from ._core.language_registry import register_language
   register_language(_zh_profile)
   from ._lang.zh.detector import score
   from .postprocess import postprocess_humanize  # default lang="zh"
   # ... full v0.1 surface re-exported
   ```
5. **Hard gate**: 215 tests pass with at most ~5 import-path tweaks.

Exit criterion: `pytest` 215 passed (+ ~15 new protocol tests), ruff +
mypy clean.

### Phase 2 — Package extraction (1 day)

1. New repo `humanize-core/`. Move `_core/` + core-bound files there.
2. `humanize-zh` switches to `from humanize_core import ...`, depends on
   `humanize-core>=0.1.0a1`, registers entry-point.
3. Publish `humanize-core 0.1.0a1` (TestPyPI first).
4. Publish `humanize-zh 0.2.0a1`. Public API unchanged.

Exit criterion: fresh venv, `pip install humanize-zh`, all examples + Web
UI byte-identical to v0.1.0a1.

### Phase 3 — humanize-en new repo (1.5 weeks)

1. New repo, copy `_lang/zh/` structure as scaffold.
2. **Detector rules**: passive voice, hedge phrases, "delve"-class
   LLM-tell words, Oxford comma usage, paragraph uniformity, em-dash
   abuse. References: DetectGPT, GPTZero public rules, Originality.ai
   patterns.
3. **N-gram engine**: train on RAID-en (CC-BY-4.0). Reuse engine algorithm.
4. **Replacements**: e.g. `leverage` → `use`, `utilize` → `use`,
   `in conclusion` → drop. Strunk & White / Plain English Campaign
   inspiration.
5. **Prompts**: writer/judge English templates, inject EN rule list.
6. **i18n labels**: `{"LOW": "looks human-written", ...}`.
7. **Web templates**: `index_en.html`, `_detect_result_en.html`, ...
8. **Tests**: 80+ unit tests; ROC-AUC on RAID-en 200 samples ≥ 0.75.

Exit criterion: fresh venv, `pip install humanize-en`, full pipeline
on EN articles. ROC-AUC gate met.

### Phase 4 — Bilingual Web UI (3 days)

1. Core web module adds `?lang=` routing.
2. Top-bar language switcher (zh / en, only shows installed plugins).
3. CLI `humanize detect --lang en file.txt`, defaults from `LANG` env.
4. Bump `humanize-core` 0.2, `humanize-zh` 0.3, `humanize-en` 0.2.

## 5. API compatibility

| User code | v0.1.0a1 | Post-refactor |
|---|---|---|
| `from humanize_zh import score` | works | works (re-export) |
| `from humanize_zh import postprocess_humanize` | works | works, default `lang="zh"` |
| `from humanize_zh import combined_score` | works | works |
| `from humanize_zh.detect import score` | works | works (re-export) |
| `from humanize_zh.llm import set_active` | works | works (re-export from core) |
| `humanize-zh detect file.txt` | works | works (alias) |
| `humanize-zh ui` | works | works |
| `humanize_zh.__version__` | `"0.1.0a1"` | `"0.2.0a1"` |

No deprecation warnings emitted. Docs note "new code should prefer
`from humanize_core import ...` for multi-language support."

## 6. Test strategy

Phase 1:
- 215 existing tests pass with ≤ 5 import-path tweaks.
- ~15 new protocol tests: detector/ngram/replacements contract checks;
  registry duplicate-detection / entry-point discovery / get_language
  error paths.

Phase 2:
- `tox` in clean env, install `humanize-zh==0.2.0a1`, all examples + 215
  tests green.
- Smoke test: `humanize-zh detect`, `humanize-zh ui`.

Phase 3 (humanize-en):
- 80+ unit tests across rules / ngram / replacements / prompts / web / cli.
- ROC-AUC on RAID-en 200 samples ≥ 0.75.
- Coexistence test: both plugins registered without conflict.

Phase 4:
- Playwright E2E: install both plugins → start Web UI → switch lang →
  submit text in each language → expected rules fire.

## 7. Risk register

| Risk | P | I | Mitigation |
|---|---|---|---|
| Protocol abstraction insufficient for EN at Phase 3 | M | M | Phase 1 exit: write EN pseudo-impl against protocols, validate sufficiency |
| `_ngram_engine.py` importlib hack complicates relocation | M | L | Engine algorithm → core, data files → each plugin, plugin passes path via NgramEngine protocol |
| Cross-package Jinja template loading | L | L | core uses `ChoiceLoader` over plugin template dirs |
| Entry-points stale in `pip install -e` mode | M | L | document `pip install -e .` may need cache clear |
| Data file path drift breaks existing patterns.json | L | M | Add path-resolution test coverage |
| `humanize-core` installed without any plugin → confusing error | M | L | Core start-up: log warning + helpful pip hint if no language registered |
| Version constraint hell across 3 packages | M | M | `humanize-core>=0.1.0a1,<0.3` soft constraint + CI matrix |
| Existing 215 tests import internal paths directly | H | L | Re-export shims; test changes < 10 lines |
| Cross-module conventions like `provider_id` `::` separator scatter | L | M | Collect in `humanize_core.contracts/` during extraction |
| EN false-positive rate high | H | M | Phase 3 ROC-AUC ≥ 0.75 gate; alpha downgrade if missed |
| User mixes old humanize-zh + new humanize-core versions | L | L | Strict SemVer; 0.x allowed to break, ≥ 1.0 locked |
| Bilingual docs maintenance | M | L | EN README only for humanize-en, ZH only for humanize-zh, core README architecture-only |

## 8. Out of scope

- ja / ko / es language plugins — community contribution post-Phase 4.
- Mobile app / browser extension.
- Self-hosted model fine-tuning — n-gram training scripts may live in
  separate repo.
- Commercial SaaS / auth / billing — Web UI remains a dev tool.
- Multi-tenant — current process-global `_ACTIVE` provider precludes.

## 9. Decisions locked in

| # | Decision |
|---|---|
| 1 | Core PyPI name: `humanize-core` |
| 2 | `humanize-en` lives in separate GitHub repo, same org |
| 3 | Primary CLI: `humanize`; `humanize-zh` kept as alias |
| 4 | Release waves: Week 2 (core + zh), Week 4 (en) |
| 5 | EN n-gram training data: RAID-en (CC-BY-4.0) |
| 6 | EN rules: maintainer-designed, refs to public papers |
| 7 | Web UI: same page + lang switcher, shows only installed plugins |

Pending (need user input at Phase 2):
- GitHub username / org for `humanize-en` and `humanize-core` repos
- TestPyPI vs PyPI for first publish (recommended: TestPyPI first)

## 10. Effort estimate

| Phase | Description | Time |
|---|---|---|
| 0 | Plan into repo + review | 30 min |
| 1 | In-repo spike: protocols + zh plugin + 215 tests green | 1.5 days |
| 2 | Extract `humanize-core`, publish, `humanize-zh` 0.2 | 1 day |
| 3 | `humanize-en` repo: rules + ngram + replacements + prompts + web + 80 tests | 1.5 weeks |
| 4 | Bilingual Web UI + CLI lang switching + synchronized release | 3 days |
| **Total** | | **~3 weeks** |
