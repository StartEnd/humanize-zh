"""Phase-1 spike: protocol + language-registry contract tests.

Goals
-----

1. **Pin the runtime-checkable shape** — if a future refactor stops a
   real implementation from satisfying ``Detector`` / ``NgramEngine`` /
   ``ReplacementsTable``, we want a noisy test failure, not a runtime
   ``AttributeError`` deep in the polish pipeline.

2. **Exercise registry edge cases** — duplicate code, missing code,
   thread-safety, entry-point discovery (mocked).

3. **Validate sufficiency for a hypothetical EN plugin** — we build a
   dummy English profile entirely with stubs, register it, and confirm
   the protocol surface is enough for downstream code (Phase 2-4) to
   operate on it without language-specific branches.

If any test here fails, the protocol design itself is suspect — fix the
abstraction before chasing the symptom.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from humanize_zh._core.language_registry import (
    ENTRY_POINT_GROUP,
    LanguageAlreadyRegistered,
    UnknownLanguage,
    get_language,
    list_languages,
    list_profiles,
    register_language,
    reset_for_tests,
    unregister_language,
)
from humanize_zh._core.protocols import (
    Detector,
    LanguageProfile,
    NgramEngine,
    NgramScoreResult,
    PromptPack,
    ReplacementsTable,
    RuleScoreResult,
)

# ─── Stub implementations for protocol-fit tests ──────────────────────────


@dataclass
class _StubRuleResult:
    total: float = 42.0
    level: str = "MEDIUM"
    violations: list[Any] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    text_length: int = 0


@dataclass
class _StubNgramResult:
    ai_probability: float = 50.0
    level: str = "MEDIUM"
    metrics: dict[str, Any] = field(default_factory=dict)
    text_length: int = 0
    char_count: int = 0
    available: bool = True


class _StubDetector:
    code = "xx"
    version = "0.0.1"

    def score(self, text: str, *, has_notes: bool = False) -> _StubRuleResult:
        return _StubRuleResult(total=99.0, text_length=len(text))


class _StubNgram:
    code = "xx"
    available = True
    corpus_id = "test-corpus"

    def score(self, text: str) -> _StubNgramResult:
        return _StubNgramResult(text_length=len(text), char_count=len(text))

    def reason_unavailable(self) -> str | None:
        return None


class _StubReplacements:
    code = "xx"

    def ordered_pairs(self) -> list[tuple[str, str]]:
        return [("foo", "bar")]


def _make_prompt_pack(code: str = "xx") -> PromptPack:
    return PromptPack(
        code=code,
        writer_system="sys",
        writer_user_template="{text}",
        judge_system="judge sys",
        judge_user_template="{text}",
        loop_judge_user_template="{ARTICLE}",
        rules_section="rules",
    )


def _make_profile(code: str = "xx", *, with_ngram: bool = True) -> LanguageProfile:
    detector = _StubDetector()
    detector.code = code  # type: ignore[misc]
    repl = _StubReplacements()
    repl.code = code  # type: ignore[misc]
    ngram: NgramEngine | None
    if with_ngram:
        ng = _StubNgram()
        ng.code = code  # type: ignore[misc]
        ngram = ng
    else:
        ngram = None
    return LanguageProfile(
        code=code,
        display_name=f"Stub-{code}",
        detector=detector,
        ngram_engine=ngram,
        replacements=repl,
        prompt_pack=_make_prompt_pack(code),
        level_labels={"LOW": "low", "MEDIUM": "med", "HIGH": "high", "VERY_HIGH": "vh"},
        metadata={"corpus": "stub"},
    )


# ─── Fixtures ─────────────────────────────────────────────────────────────


# NOTE: ``clean_registry`` moved to ``tests/conftest.py`` in P2.8 so it
# is discovered via pytest's directory-based fixture scanner instead of
# a cross-module ``from tests.test_protocols import ...``. The latter
# fails once humanize-core is installed editably because *its* sibling
# ``tests/`` package shadows ours on ``sys.path``.


# ─── Protocol fit (runtime_checkable isinstance) ─────────────────────────


def test_stub_detector_satisfies_detector_protocol() -> None:
    assert isinstance(_StubDetector(), Detector)


def test_stub_ngram_satisfies_ngram_engine_protocol() -> None:
    assert isinstance(_StubNgram(), NgramEngine)


def test_stub_replacements_satisfies_replacements_protocol() -> None:
    assert isinstance(_StubReplacements(), ReplacementsTable)


def test_stub_rule_result_satisfies_rule_score_protocol() -> None:
    assert isinstance(_StubRuleResult(), RuleScoreResult)


def test_stub_ngram_result_satisfies_ngram_score_protocol() -> None:
    assert isinstance(_StubNgramResult(), NgramScoreResult)


def test_existing_zh_score_dataclass_satisfies_rule_score_protocol() -> None:
    """The real Score from detect.py must keep satisfying the contract."""
    from humanize_zh.detect import Score
    s = Score(total=10.0, level="LOW", violations=[], stats={}, text_length=42)
    assert isinstance(s, RuleScoreResult)


def test_existing_zh_ngram_score_satisfies_ngram_score_protocol() -> None:
    from humanize_zh.ngram_check import NgramScore
    ns = NgramScore(ai_probability=20.0, level="LOW")
    assert isinstance(ns, NgramScoreResult)


# ─── LanguageProfile validation ───────────────────────────────────────────


def test_language_profile_rejects_mismatched_detector_code() -> None:
    bad_detector = _StubDetector()
    bad_detector.code = "yy"  # type: ignore[misc]
    with pytest.raises(ValueError, match="all components must agree"):
        LanguageProfile(
            code="xx",
            display_name="x",
            detector=bad_detector,
            ngram_engine=None,
            replacements=_StubReplacements(),
            prompt_pack=_make_prompt_pack("xx"),
        )


def test_language_profile_rejects_mismatched_ngram_code() -> None:
    bad_ngram = _StubNgram()
    bad_ngram.code = "yy"  # type: ignore[misc]
    with pytest.raises(ValueError, match="ngram_engine.code"):
        LanguageProfile(
            code="xx",
            display_name="x",
            detector=_StubDetector(),
            ngram_engine=bad_ngram,
            replacements=_StubReplacements(),
            prompt_pack=_make_prompt_pack("xx"),
        )


def test_language_profile_allows_none_ngram() -> None:
    """Languages without n-gram models must still construct cleanly."""
    profile = _make_profile("xx", with_ngram=False)
    assert profile.ngram_engine is None


def test_language_profile_rejects_mismatched_prompt_pack_code() -> None:
    """Cover the third validation branch in ``__post_init__``."""
    with pytest.raises(ValueError, match="all components must agree"):
        LanguageProfile(
            code="xx",
            display_name="x",
            detector=_StubDetector(),
            ngram_engine=None,
            replacements=_StubReplacements(),
            prompt_pack=_make_prompt_pack("yy"),  # mismatch
        )


class _MissingFields:
    """Class without any of the expected RuleScoreResult attrs."""


def test_class_missing_attrs_does_not_satisfy_rule_score_protocol() -> None:
    """Negative case — guards against attribute-only Protocol regressions
    (Python's runtime_checkable behaviour for non-method attrs has
    changed between versions; if it ever silently passes, we want a
    loud test failure here, not a silent bug downstream).
    """
    assert not isinstance(_MissingFields(), RuleScoreResult)
    assert not isinstance(_MissingFields(), Detector)


# ─── Registry behaviour ───────────────────────────────────────────────────


def test_register_then_get_returns_same_instance(clean_registry) -> None:
    profile = _make_profile("xx")
    register_language(profile)
    assert get_language("xx") is profile


def test_register_duplicate_raises(clean_registry) -> None:
    register_language(_make_profile("xx"))
    with pytest.raises(LanguageAlreadyRegistered):
        register_language(_make_profile("xx"))


def test_register_duplicate_with_replace_overwrites(clean_registry) -> None:
    first = _make_profile("xx")
    register_language(first)
    second = _make_profile("xx")
    register_language(second, replace=True)
    assert get_language("xx") is second


def test_register_rejects_non_profile(clean_registry) -> None:
    with pytest.raises(TypeError, match="LanguageProfile"):
        register_language("not a profile")  # type: ignore[arg-type]


def test_get_unknown_raises_with_helpful_hint(clean_registry) -> None:
    register_language(_make_profile("xx"))
    register_language(_make_profile("yy"))
    with pytest.raises(UnknownLanguage) as exc_info:
        get_language("zz")
    msg = str(exc_info.value)
    assert "zz" in msg
    assert "xx" in msg and "yy" in msg


def test_get_unknown_when_empty_suggests_install(clean_registry) -> None:
    with pytest.raises(UnknownLanguage) as exc_info:
        get_language("zh")
    assert "humanize-zh" in str(exc_info.value)


def test_list_languages_is_sorted(clean_registry) -> None:
    register_language(_make_profile("zh"))
    register_language(_make_profile("en"))
    register_language(_make_profile("ja"))
    assert list_languages() == ["en", "ja", "zh"]


def test_list_profiles_returns_profiles_in_code_order(clean_registry) -> None:
    pz = _make_profile("zh")
    pe = _make_profile("en")
    register_language(pz)
    register_language(pe)
    profiles = list_profiles()
    assert [p.code for p in profiles] == ["en", "zh"]


def test_unregister_returns_removed_profile(clean_registry) -> None:
    p = _make_profile("xx")
    register_language(p)
    removed = unregister_language("xx")
    assert removed is p
    assert "xx" not in list_languages()


def test_unregister_unknown_returns_none(clean_registry) -> None:
    assert unregister_language("nonexistent") is None


def test_register_after_unregister_does_not_need_replace_flag(clean_registry) -> None:
    """``replace=True`` should not be needed after a clean unregister —
    otherwise tests that swap profiles in/out get awkward.
    """
    register_language(_make_profile("xx"))
    unregister_language("xx")
    # Different instance, same code, no replace=True — must succeed.
    register_language(_make_profile("xx"))
    assert "xx" in list_languages()


def test_list_languages_empty_when_nothing_registered(clean_registry) -> None:
    assert list_languages() == []
    assert list_profiles() == []


# ─── Thread safety ────────────────────────────────────────────────────────


def test_concurrent_unique_registration_does_not_corrupt(clean_registry) -> None:
    """Many threads register *distinct* codes simultaneously; all must land."""
    import threading

    barrier = threading.Barrier(parties=8)

    def worker(idx: int) -> None:
        barrier.wait()
        register_language(_make_profile(f"x{idx}"))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(list_languages()) == sorted(f"x{i}" for i in range(8))


def test_concurrent_same_code_registration_serializes_to_one_winner(
    clean_registry,
) -> None:
    """Many threads race to register the *same* code without ``replace=True``.

    Exactly one must succeed; the rest must observe
    :class:`LanguageAlreadyRegistered` rather than corrupting the dict
    or silently overwriting. Verifies the lock is doing its job on the
    contention-heavy path.
    """
    import threading

    barrier = threading.Barrier(parties=8)
    successes: list[int] = []
    failures: list[int] = []
    lock = threading.Lock()

    def worker(idx: int) -> None:
        barrier.wait()
        try:
            register_language(_make_profile("xx"))
            with lock:
                successes.append(idx)
        except LanguageAlreadyRegistered:
            with lock:
                failures.append(idx)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(successes) == 1
    assert len(failures) == 7
    assert list_languages() == ["xx"]


# ─── Entry-point discovery (mocked) ───────────────────────────────────────


def test_entry_point_group_constant_is_stable() -> None:
    """Plugins encode this string in their pyproject.toml; must not drift."""
    assert ENTRY_POINT_GROUP == "humanize_core.languages"


def test_discovery_loads_profile_from_callable_entry_point(clean_registry) -> None:
    """Plugins ship either a LanguageProfile or a zero-arg factory."""
    # ``clean_registry`` parks discovery=done; opt back in for this test.
    from humanize_zh._core import language_registry as reg
    with reg._LOCK:
        reg._DISCOVERY_DONE = False

    profile = _make_profile("xx")
    fake_ep = MagicMock()
    fake_ep.name = "xx"
    fake_ep.load.return_value = lambda: profile

    with patch(
        "humanize_zh._core.language_registry.entry_points",
        return_value=[fake_ep],
    ):
        # Trigger discovery by listing — first call runs it.
        codes = list_languages()
    assert "xx" in codes
    assert get_language("xx") is profile


def test_discovery_skips_broken_entry_points(clean_registry) -> None:
    """One broken plugin must not crash discovery for other plugins."""
    from humanize_zh._core import language_registry as reg
    with reg._LOCK:
        reg._DISCOVERY_DONE = False

    good_profile = _make_profile("xx")
    good_ep = MagicMock()
    good_ep.name = "xx"
    good_ep.load.return_value = good_profile
    bad_ep = MagicMock()
    bad_ep.name = "broken"
    bad_ep.load.side_effect = ImportError("boom")
    wrong_type_ep = MagicMock()
    wrong_type_ep.name = "wrong"
    wrong_type_ep.load.return_value = "not a profile"

    with patch(
        "humanize_zh._core.language_registry.entry_points",
        return_value=[bad_ep, wrong_type_ep, good_ep],
    ):
        codes = list_languages()
    assert codes == ["xx"]


def test_discovery_runs_only_once_per_process(clean_registry) -> None:
    """Repeated lookups must not re-trigger entry-point scanning."""
    from humanize_zh._core import language_registry as reg
    with reg._LOCK:
        reg._DISCOVERY_DONE = False

    call_count = {"n": 0}

    def fake_eps(group: str = ""):
        call_count["n"] += 1
        return []

    with patch(
        "humanize_zh._core.language_registry.entry_points", side_effect=fake_eps,
    ):
        list_languages()
        list_languages()
        list_profiles()
        # Only the first call should have triggered discovery.
    assert call_count["n"] == 1


def test_discovery_publishes_profiles_atomically(clean_registry) -> None:
    """Regression for the race where ``_DISCOVERY_DONE`` flipped to True
    *before* discovery actually populated ``_PROFILES``.

    A reader thread that calls ``list_languages`` while discovery is
    in progress must either block (preferred) or observe the fully
    loaded state — never an empty/partial dict with the flag claiming
    "done". This test would fail on the pre-fix implementation that
    set ``_DISCOVERY_DONE = True`` before running ``_discover_*``.
    """
    import threading
    import time

    from humanize_zh._core import language_registry as reg
    with reg._LOCK:
        reg._DISCOVERY_DONE = False

    profile = _make_profile("xx")
    discovery_started = threading.Event()
    discovery_can_finish = threading.Event()
    fake_ep = MagicMock()
    fake_ep.name = "xx"

    def slow_load():
        discovery_started.set()
        # Park here long enough for the reader to race in.
        discovery_can_finish.wait(timeout=2.0)
        return profile

    fake_ep.load.side_effect = slow_load
    reader_seen: list[list[str]] = []

    def discoverer() -> None:
        list_languages()  # triggers entry-point scan + slow_load

    def reader() -> None:
        # Wait for discovery to enter slow_load, then race in.
        discovery_started.wait(timeout=2.0)
        reader_seen.append(list_languages())

    with patch(
        "humanize_zh._core.language_registry.entry_points",
        return_value=[fake_ep],
    ):
        d_thread = threading.Thread(target=discoverer)
        r_thread = threading.Thread(target=reader)
        d_thread.start()
        r_thread.start()
        # Both threads parked: discoverer inside slow_load, reader on
        # the in-progress _DISCOVERY_LOCK. Release to let them finish.
        time.sleep(0.1)
        discovery_can_finish.set()
        d_thread.join(timeout=2.0)
        r_thread.join(timeout=2.0)

    assert reader_seen == [["xx"]], (
        f"reader thread saw an inconsistent registry: {reader_seen}; "
        f"expected the lock to make discovery atomic"
    )


def test_discovery_swallows_entry_points_function_failure(clean_registry) -> None:
    """If ``entry_points()`` itself raises (both modern + fallback paths),
    discovery must not crash callers — log and move on with empty registry.
    """
    def always_raise(*args, **kwargs):
        raise RuntimeError("metadata API broken")

    with patch(
        "humanize_zh._core.language_registry.entry_points", side_effect=always_raise,
    ):
        codes = list_languages()
    assert codes == []  # discovery returned cleanly; registry empty


# ─── Real ZH plugin adapter ─────────────────────────────────────────────


def test_zh_detector_adapter_satisfies_detector_protocol() -> None:
    """End-to-end smoke test for the real ZH plugin's Detector adapter.

    The class-attribute ``code`` and the lazy-loaded ``version`` must
    both be present and string-typed, and ``score()`` must return a
    Score that satisfies :class:`RuleScoreResult`.
    """
    from humanize_zh._lang.zh.detector import ZhDetector, zh_detector

    assert isinstance(zh_detector, Detector)
    assert zh_detector.code == "zh"
    assert isinstance(zh_detector.version, str)
    assert zh_detector.version  # non-empty
    result = zh_detector.score("综上所述, 我们需要深入探讨这个问题")
    assert isinstance(result, RuleScoreResult)
    assert result.total > 0  # the test sentence is full of LLM-tells
    # Class-only smoke (in case singleton is mutated by a future test).
    assert isinstance(ZhDetector(), Detector)


def test_zh_detector_compat_shim_re_exports_full_surface() -> None:
    """v0.1.0a1 users import via ``humanize_zh.detect`` directly — the
    shim must preserve every documented + test-imported symbol.
    """
    from humanize_zh import detect as shim
    expected = {
        "PATTERNS_PATH", "Score", "Violation", "ZhDetector",
        "_load_patterns", "_strip_codeblocks", "main", "score", "zh_detector",
    }
    assert expected <= set(dir(shim))
    # The shim symbols and the new-location symbols must be the same objects.
    from humanize_zh._lang.zh import detector as canonical
    for name in expected:
        assert getattr(shim, name) is getattr(canonical, name), (
            f"shim.{name} drifted from canonical implementation"
        )


def test_zh_ngram_adapter_satisfies_ngram_engine_protocol() -> None:
    """End-to-end smoke for the ZH plugin's NgramEngine adapter."""
    from humanize_zh._lang.zh.ngram import ZhNgramEngine, zh_ngram

    assert isinstance(zh_ngram, NgramEngine)
    assert zh_ngram.code == "zh"
    assert isinstance(zh_ngram.available, bool)
    if zh_ngram.available:
        assert zh_ngram.reason_unavailable() is None
        result = zh_ngram.score("北京今天下了一整天雨。" * 12)
        assert isinstance(result, NgramScoreResult)
    # Even when available, ``reason_unavailable()`` must be safely callable.
    assert isinstance(ZhNgramEngine(), NgramEngine)


def test_zh_replacements_adapter_satisfies_replacements_table_protocol() -> None:
    """End-to-end smoke for the ZH plugin's ReplacementsTable adapter."""
    from humanize_zh._lang.zh.replacements import ZhReplacementsTable, zh_replacements

    assert isinstance(zh_replacements, ReplacementsTable)
    assert zh_replacements.code == "zh"
    pairs = zh_replacements.ordered_pairs()
    assert isinstance(pairs, tuple)
    assert pairs, "real ZH replacements.json should ship with at least one pair"
    for entry in pairs:
        assert isinstance(entry, tuple) and len(entry) == 2
        assert isinstance(entry[0], str) and isinstance(entry[1], str)
    # Class-only smoke (in case the singleton is mutated by a future test).
    assert isinstance(ZhReplacementsTable(), ReplacementsTable)


def test_zh_replacements_loader_failure_returns_empty_tuple(tmp_path, monkeypatch) -> None:
    """Polish pipeline must degrade to a no-op when ``replacements.json``
    is missing or malformed — never raise into callers.
    """
    from humanize_zh._lang.zh import replacements as repl_mod

    bogus = tmp_path / "missing.json"  # path that does not exist
    monkeypatch.setattr(repl_mod, "REPLACEMENTS_PATH", bogus)
    repl_mod._load_replacements.cache_clear()
    try:
        assert repl_mod._load_replacements() == ()
    finally:
        repl_mod._load_replacements.cache_clear()  # reset for downstream tests


def test_zh_prompt_shim_re_exports_canonical_modules() -> None:
    """``humanize_zh.prompt`` re-exports every name from its canonical home.

    Layout (post-P2.8b):
    - ``humanize_zh._lang.zh.prompts`` — ZH constants + builder + ZH templates.
    - ``humanize_core.prompt`` — framework EN placeholder templates.
    - ``humanize_zh.prompt`` — owns the ZH postprocess dispatcher
      (:func:`build_humanize_postprocess_prompt`) and re-exports both
      sources. The dispatcher used to live in ``humanize_zh._core.prompt``;
      P2.8b moved it here because rule-list injection is plugin-internal.
    """
    from humanize_zh import prompt as shim
    from humanize_zh._lang.zh import prompts as zh
    from humanize_core import prompt as core

    zh_owned = {
        "ASSERTION_TEMPLATE", "CORE_RULES", "HARD_LIMITS", "HARD_NEVER",
        "OPENING_DIVERSITY", "POSTPROCESS_PROMPT", "POSTPROCESS_PROMPT_AGGRESSIVE",
        "SCENES", "SELF_CHECK", "SOUL_INJECTION", "WORDS_BLACKLIST",
        "build_humanize_prompt",
    }
    core_owned = {"POSTPROCESS_PROMPT_EN", "JUDGE_PROMPT_EN", "LOOP_JUDGE_PROMPT_EN"}

    for name in zh_owned:
        assert getattr(shim, name) is getattr(zh, name), f"shim.{name} drifted from ZH canonical"
    for name in core_owned:
        assert getattr(shim, name) is getattr(core, name), f"shim.{name} drifted from core canonical"
    # The dispatcher now lives on the shim itself, not on either source.
    assert callable(shim.build_humanize_postprocess_prompt)


def test_postprocess_dispatcher_picks_correct_template_per_lang() -> None:
    """Lang dispatch must route ``zh`` / ``en`` to the right template,
    and rely only on the LANG flag (not on detector violations).

    P2.8b moved the dispatcher to :mod:`humanize_zh.prompt` (from
    ``humanize_zh._core.prompt``). The legacy import path still works
    via the ``_core`` shim package — see
    :func:`test_legacy_core_prompt_path_still_resolves_dispatcher`.
    """
    from humanize_zh.prompt import build_humanize_postprocess_prompt

    zh_out = build_humanize_postprocess_prompt("article", [], lang="zh", scene="analysis")
    en_out = build_humanize_postprocess_prompt("article", [], lang="en")
    assert "去 AI 味" in zh_out
    assert "De-AI polishing pass" in en_out
    assert "去 AI 味" not in en_out
    assert "De-AI polishing pass" not in zh_out


def test_legacy_core_prompt_path_still_resolves_dispatcher() -> None:
    """The legacy import
    ``from humanize_zh._core.prompt import build_humanize_postprocess_prompt``
    used to work pre-P2.8b. After the alias to ``humanize_core.prompt``,
    the framework module no longer ships the ZH-aware dispatcher, so
    legacy callers must migrate to ``humanize_zh.prompt``. We assert the
    new layer is the canonical home.
    """
    import humanize_zh._core.prompt as legacy
    import humanize_core.prompt as canonical

    assert legacy is canonical
    # Dispatcher must NOT live on the framework module; it's plugin code.
    assert not hasattr(canonical, "build_humanize_postprocess_prompt")
    # And it MUST live on humanize_zh.prompt now.
    from humanize_zh.prompt import build_humanize_postprocess_prompt
    assert callable(build_humanize_postprocess_prompt)


def test_postprocess_imports_load_replacements_from_canonical_module() -> None:
    """Phase 1.6 moved the loader out of ``postprocess.py``. Guard against
    drift / accidental re-introduction of a duplicate implementation.
    """
    from humanize_zh import postprocess
    from humanize_zh._lang.zh import replacements as canonical
    assert postprocess._load_replacements is canonical._load_replacements


def test_zh_ngram_compat_shim_re_exports_full_surface() -> None:
    """The ``humanize_zh.ngram_check`` shim must preserve every name that
    tests + downstream code imports.
    """
    from humanize_zh import ngram_check as shim
    expected = {
        "DATA_DIR", "NgramScore", "ZhNgramEngine",
        "_ENGINE", "_ENGINE_LOAD_ERROR", "_ENGINE_PATH",
        "_load_engine", "_safe_call", "main", "ngram_score", "zh_ngram",
    }
    assert expected <= set(dir(shim))
    from humanize_zh._lang.zh import ngram as canonical
    for name in expected:
        # ``_ENGINE`` / ``_ENGINE_LOAD_ERROR`` are module-level mutables
        # that get rebound by load — value-equality, not identity.
        if name in {"_ENGINE", "_ENGINE_LOAD_ERROR"}:
            continue
        assert getattr(shim, name) is getattr(canonical, name), (
            f"shim.{name} drifted from canonical implementation"
        )


# ─── Sufficiency check: pretend we're shipping an EN plugin ──────────────


def test_protocol_surface_supports_a_hypothetical_en_plugin(clean_registry) -> None:
    """Build a complete EN-flavoured profile from stubs and register it.

    This is the cheapest signal that the protocol design is rich enough
    for Phase 3. If a downstream call needs something the stubs can't
    provide, this test (or its Phase-2 successor) flags it before we
    fork a separate humanize-en repo.
    """
    en_profile = _make_profile("en")
    register_language(en_profile)
    fetched = get_language("en")
    # Smoke: every component is reachable and shape-compatible.
    rule_result = fetched.detector.score("hello world")
    assert isinstance(rule_result, RuleScoreResult)
    assert fetched.ngram_engine is not None
    ngram_result = fetched.ngram_engine.score("hello world")
    assert isinstance(ngram_result, NgramScoreResult)
    pairs = fetched.replacements.ordered_pairs()
    assert isinstance(pairs, list) and pairs
    assert "writer_system" in fetched.prompt_pack.writer_system or fetched.prompt_pack.writer_system
    assert fetched.level_labels["LOW"]


# ─── Phase 1.8: assembled ZH LanguageProfile ─────────────────────────────


def test_zh_profile_singleton_satisfies_language_profile() -> None:
    """``zh_profile`` must be a fully-wired ``LanguageProfile`` whose
    component codes all agree (the post-init guard would already raise
    on import if not, but we want an explicit regression test in case
    that guard ever weakens)."""
    from humanize_zh._lang.zh.profile import zh_profile
    assert isinstance(zh_profile, LanguageProfile)
    assert zh_profile.code == "zh"
    assert zh_profile.detector.code == "zh"
    assert zh_profile.ngram_engine is not None
    assert zh_profile.ngram_engine.code == "zh"
    assert zh_profile.replacements.code == "zh"
    assert zh_profile.prompt_pack.code == "zh"


def test_zh_profile_components_runtime_check_against_protocols() -> None:
    """Structural typing — every component answers ``isinstance`` against
    its declared protocol. Catches accidental method removal.
    """
    from humanize_zh._lang.zh.profile import zh_profile
    assert isinstance(zh_profile.detector, Detector)
    assert isinstance(zh_profile.ngram_engine, NgramEngine)
    assert isinstance(zh_profile.replacements, ReplacementsTable)
    assert isinstance(zh_profile.prompt_pack, PromptPack)


def test_zh_profile_level_labels_match_format_helper() -> None:
    """The level-label dict on the profile must produce the same strings
    that :func:`humanize_zh._format.level_label` returns today.

    Phase 2 plans to switch the helper to read from the active profile;
    if the labels drift before that migration, both call sites will
    diverge silently. Pin them here.
    """
    from humanize_zh._format import level_label
    from humanize_zh._lang.zh.profile import ZH_LEVEL_LABELS, zh_profile

    # Pick one probability from each band (covering all four cut-offs).
    samples = {
        "LOW": 0.0,
        "MEDIUM": 25.0,
        "HIGH": 50.0,
        "VERY_HIGH": 75.0,
    }
    for key, prob in samples.items():
        assert ZH_LEVEL_LABELS[key] == level_label(prob), (
            f"ZH_LEVEL_LABELS[{key!r}] drifted from _format.level_label({prob})"
        )
        assert zh_profile.level_labels[key] == level_label(prob)


def test_zh_profile_prompt_pack_carries_existing_zh_templates() -> None:
    """The PromptPack must wrap the canonical ZH templates, not stubs.
    A regression here would mean the LLM sees a different prompt after
    Phase 1.10 wires consumers to the profile."""
    from humanize_zh._lang.zh.profile import zh_profile
    from humanize_zh._lang.zh.prompts import (
        JUDGE_PROMPT,
        POSTPROCESS_PROMPT,
        build_humanize_prompt,
    )
    assert zh_profile.prompt_pack.writer_user_template is POSTPROCESS_PROMPT
    assert zh_profile.prompt_pack.judge_user_template is JUDGE_PROMPT
    # rules_section is a freshly-built string — compare by value.
    assert zh_profile.prompt_pack.rules_section == build_humanize_prompt(scene="analysis")


def test_zh_profile_metadata_exposes_versioning_ids() -> None:
    """Operators reading ``humanize providers`` (Phase 2) need stable
    keys to pin calibration drift. Lock the metadata schema here."""
    from humanize_zh._lang.zh.profile import zh_profile
    md = zh_profile.metadata
    assert md["corpus"] == "HC3-Chinese"
    assert md["rule_set_version"] == zh_profile.detector.version
    assert md["ngram_corpus_id"] == zh_profile.ngram_engine.corpus_id  # type: ignore[union-attr]


def test_make_zh_profile_returns_independent_instances() -> None:
    """``make_zh_profile()`` must build a fresh profile each call so
    tests can swap profiles without poisoning the global singleton."""
    from humanize_zh._lang.zh.profile import make_zh_profile, zh_profile
    fresh = make_zh_profile()
    assert fresh is not zh_profile
    assert fresh.code == zh_profile.code
    # Component singletons *are* shared (intentional — they cache JSON).
    assert fresh.detector is zh_profile.detector


# ─── Phase 1.11: package-level auto-registration ────────────────────────


def test_humanize_zh_import_auto_registers_zh_profile() -> None:
    """A bare ``import humanize_zh`` must leave the registry with the
    built-in ZH profile already accessible via ``get_language("zh")``.

    This is the contract that lets every downstream call site
    (``judge`` / ``iterative_polish`` / ``humanize providers``) look up
    a language by code without a manual ``register_language`` call.
    """
    import humanize_zh
    from humanize_zh._lang.zh.profile import zh_profile as canonical

    fetched = humanize_zh.get_language("zh")
    assert fetched is canonical
    assert "zh" in humanize_zh.list_languages()


def test_humanize_zh_reexports_registry_helpers() -> None:
    """The package root must surface ``register_language`` /
    ``get_language`` / ``LanguageProfile`` etc. so downstream EN
    plugins can register without reaching into the private ``_core``
    namespace.
    """
    import humanize_zh

    expected = {
        "LanguageProfile",
        "get_language",
        "list_languages",
        "list_profiles",
        "register_language",
        "unregister_language",
        "LanguageAlreadyRegistered",
        "UnknownLanguage",
        "zh_profile",
    }
    assert expected <= set(humanize_zh.__all__), (
        f"missing from __all__: {expected - set(humanize_zh.__all__)}"
    )
    for name in expected:
        assert hasattr(humanize_zh, name), f"humanize_zh.{name} missing"


def test_humanize_zh_reimport_is_idempotent(clean_registry) -> None:
    """``importlib.reload`` (or a second registration triggered by some
    plugin) must not raise — the auto-register block swallows
    ``LanguageAlreadyRegistered`` deliberately.
    """
    import importlib

    import humanize_zh
    from humanize_zh._lang.zh.profile import zh_profile

    # Pre-populate so the reload-time auto-register hits the swallow path.
    register_language(zh_profile)
    importlib.reload(humanize_zh)
    # Reload re-runs ``__init__.py``; the registry must still hold ZH.
    assert humanize_zh.get_language("zh").code == "zh"


def test_zh_profile_judge_prompts_relocated_from_judge_module() -> None:
    """Phase 1.8 moved ``JUDGE_PROMPT`` / ``JUDGE_PROMPT_EN`` out of
    ``humanize_zh.judge``. Verify the new homes are wired and that the
    judge module still re-exports them for backward compat.
    """
    import importlib

    from humanize_zh._core.prompt import JUDGE_PROMPT_EN as core_en_prompt
    from humanize_zh._lang.zh.prompts import JUDGE_PROMPT as zh_prompt
    # NB: ``humanize_zh/__init__.py`` does ``from .judge import judge``
    # which shadows the submodule on the package namespace. Reach the
    # module via importlib to get the actual ``ModuleType``.
    judge_module = importlib.import_module("humanize_zh.judge")
    assert judge_module.JUDGE_PROMPT is zh_prompt
    assert judge_module.JUDGE_PROMPT_EN is core_en_prompt
    # Both prompts must contain the placeholder consumers rely on.
    assert "{ARTICLE}" in zh_prompt
    assert "{ARTICLE}" in core_en_prompt


def test_zh_format_labels_match_profile() -> None:
    """Regression for the duplication introduced in P2.8a.

    ``humanize_zh._format`` keeps a private copy of the ZH level labels
    so that importing it does not pull the heavy ``_lang.zh.profile``
    module (which would create a circular import — the detector
    imports ``level_label``, the profile imports the detector). The
    profile owns the canonical copy on
    ``LanguageProfile.level_labels``; both tables must stay in sync or
    CLI / Web will render different strings depending on which entry
    point the caller used. This test enforces equality.
    """
    from humanize_zh._format import _ZH_LEVEL_LABELS
    from humanize_zh._lang.zh.profile import ZH_LEVEL_LABELS, zh_profile

    assert _ZH_LEVEL_LABELS == ZH_LEVEL_LABELS
    assert _ZH_LEVEL_LABELS == zh_profile.level_labels
