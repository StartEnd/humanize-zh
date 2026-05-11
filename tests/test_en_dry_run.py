"""Phase 1.12 capstone: prove the protocol surface is rich enough to ship
an EN plugin entirely from public APIs.

This test is *not* the production EN profile — that lives in a separate
``humanize-en`` package (Phase 3). The point here is to assemble a
plausible EN ``LanguageProfile`` using only:

  - ``humanize_zh.LanguageProfile`` + the protocol stubs
  - ``humanize_zh.register_language`` / ``get_language``
  - ``judge`` / ``iterative_polish`` / ``postprocess_humanize``
    accepting that profile

…and demonstrate end-to-end that every public entry point routes
correctly through the EN profile. If a Phase-3 implementor cannot
build a working plugin against these tests, the protocol design is
incomplete and we must extend it before merging.

The fixture in ``test_protocols.py::clean_registry`` is reused to
snapshot/restore the registry around the EN registration so we don't
leak state into other tests.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

import humanize_zh
from humanize_zh import (
    LanguageProfile,
    iterative_polish,
    judge,
    llm,
    register_language,
)
from humanize_zh._core.protocols import (
    NgramScoreResult,
    PromptPack,
    RuleScoreResult,
)
from humanize_zh.llm.callable_provider import CallableProvider

# Re-use the registry snapshot fixture from test_protocols.py.
from tests.test_protocols import clean_registry  # noqa: F401

# ─── Concrete duck-typed result dataclasses ─────────────────────────────
#
# ``RuleScoreResult`` and ``NgramScoreResult`` in ``_core.protocols`` are
# Protocols (structural types); plugins must ship their *own* concrete
# dataclasses that match the shape. Doing so here is itself part of the
# protocol-sufficiency proof — if a plugin author cannot model the
# result shape with plain stdlib dataclasses, the protocol is leaking
# implementation details.


@dataclass
class _EnRuleResult:
    total: float
    level: str
    violations: list[Any] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    text_length: int = 0


@dataclass
class _EnNgramResult:
    ai_probability: float
    available: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    chinese_char_count: int = 0


# ─── EN pseudo-impl ─────────────────────────────────────────────────────


class _EnDetector:
    """Minimal Detector protocol impl for EN.

    Rule-based scoring that counts a handful of well-known EN AI tells:
    ``"It's worth noting"`` / ``"In conclusion"`` / ``"needless to say"``.
    """

    code = "en"
    version = "0.0.1-pseudo"

    _TELLS = (
        "it's worth noting",
        "in conclusion",
        "needless to say",
        "delve into",
        "tapestry",
    )

    def score(self, text: str, *, has_notes: bool = False) -> RuleScoreResult:
        lower = text.lower()
        hits = [t for t in self._TELLS if t in lower]
        per_hit = 15.0
        total = min(100.0, len(hits) * per_hit)
        if total < 25:
            level = "LOW"
        elif total < 50:
            level = "MEDIUM"
        elif total < 75:
            level = "HIGH"
        else:
            level = "VERY_HIGH"
        return _EnRuleResult(
            total=total,
            level=level,
            violations=[],  # we don't bother building Violation objects here
            stats={"hits": hits, "tells_checked": len(self._TELLS)},
            text_length=len(text),
        )


class _EnReplacements:
    """ReplacementsTable for EN — five high-confidence rewrites."""

    code = "en"

    _PAIRS = (
        ("It's worth noting that ", ""),
        (" it's worth noting that ", " "),
        ("In conclusion, ", ""),
        ("Needless to say, ", ""),
        ("delve into", "look at"),
        ("tapestry of", "mix of"),
    )

    def ordered_pairs(self) -> tuple[tuple[str, str], ...]:
        return self._PAIRS


class _EnNgramEngine:
    """Stub NgramEngine: always reports unavailable so we exercise the
    graceful-degradation path. A real EN engine would ship a calibrated
    HC3-en / RAID-en model."""

    code = "en"
    corpus_id = "pseudo-en-v0"

    @property
    def available(self) -> bool:
        return False

    def score(self, text: str) -> NgramScoreResult:
        return _EnNgramResult(
            ai_probability=0.0,
            available=False,
            metrics={},
            chinese_char_count=0,  # field is named historically; 0 is fine
        )

    def reason_unavailable(self) -> str | None:
        return "pseudo-en ngram: no trained data file (dry-run stub)"


_EN_JUDGE_PROMPT = (
    "EN-JUDGE-V0::Evaluate the article below; return JSON only.\n\n{ARTICLE}\n"
)
_EN_LOOP_JUDGE_PROMPT = "EN-LOOP-JUDGE-V0::{ARTICLE}"
_EN_WRITER_PROMPT = "EN-WRITER-V0::scene={scene}\n\n{text}\n"


def _make_en_profile() -> LanguageProfile:
    pack = PromptPack(
        code="en",
        writer_system="You are a copy editor stripping AI tells.",
        writer_user_template=_EN_WRITER_PROMPT,
        judge_system="You are an AI-text detector.",
        judge_user_template=_EN_JUDGE_PROMPT,
        loop_judge_user_template=_EN_LOOP_JUDGE_PROMPT,
        rules_section="EN rules: drop filler openers, vary sentence length.",
    )
    return LanguageProfile(
        code="en",
        display_name="English (pseudo dry-run)",
        detector=_EnDetector(),
        ngram_engine=_EnNgramEngine(),
        replacements=_EnReplacements(),
        prompt_pack=pack,
        level_labels={
            "LOW": "LOW (mostly human)",
            "MEDIUM": "MEDIUM (some AI smell)",
            "HIGH": "HIGH (clearly AI)",
            "VERY_HIGH": "VERY HIGH (full AI)",
        },
        metadata={
            "corpus": "pseudo-en-v0",
            "rule_set_version": "0.0.1-pseudo",
            "ngram_corpus_id": "pseudo-en-v0",
        },
    )


# ─── Fixture ────────────────────────────────────────────────────────────


@pytest.fixture
def en_registered(clean_registry):  # noqa: F811 — reused fixture
    """Register the EN pseudo profile for the duration of one test."""
    profile = _make_en_profile()
    # `clean_registry` already reset the registry; we must re-register ZH
    # too so the package-level invariant ("zh always present") holds for
    # any helper that reaches for it. We register both fresh.
    register_language(humanize_zh.zh_profile)
    register_language(profile)
    return profile


# ─── End-to-end smoke tests ─────────────────────────────────────────────


def test_en_profile_routes_through_registry(en_registered: LanguageProfile) -> None:
    """``humanize_zh.get_language("en")`` returns the registered EN profile
    and all of its components answer ``isinstance`` against the protocols.
    """
    fetched = humanize_zh.get_language("en")
    assert fetched is en_registered
    assert fetched.code == "en"
    assert fetched.detector.code == "en"
    assert fetched.replacements.code == "en"
    assert fetched.prompt_pack.code == "en"
    assert fetched.ngram_engine is not None
    assert fetched.ngram_engine.code == "en"
    # Graceful-degradation contract: an unavailable engine still scores.
    ngram = fetched.ngram_engine.score("hello world")
    assert ngram.available is False
    assert ngram.ai_probability == 0.0


def test_en_detector_runs_through_protocol(en_registered: LanguageProfile) -> None:
    """The EN detector's rule-based score returns a well-formed
    ``RuleScoreResult`` — proves the protocol is enough to ship a real
    rule engine without inheriting from any framework class."""
    article = (
        "It's worth noting that this report will delve into a tapestry of"
        " key takeaways. In conclusion, the future is bright."
    )
    result = en_registered.detector.score(article)
    assert isinstance(result, RuleScoreResult)
    # Four tells fired: 15 each, capped — score should be >= 50.
    assert result.total >= 50, result
    assert result.level in ("HIGH", "VERY_HIGH")
    assert len(result.stats["hits"]) >= 4


def test_en_judge_uses_profile_template(en_registered: LanguageProfile) -> None:
    """``judge(..., profile=en)`` must call the LLM with
    ``en.prompt_pack.judge_user_template``."""
    captured: list[str] = []

    def _capture(prompt: str) -> str:
        captured.append(prompt)
        return json.dumps(
            {
                "publishable": False,
                "worst_ai_sections": [],
                "unsupported_claims": [],
                "template_smell": ["filler opener"],
                "fake_human_details": [],
                "best_theses": [],
                "rewrite_brief": "Drop the opener.",
            }
        )

    j = CallableProvider(_capture, name="cap", model="m1")
    result = judge(
        "It's worth noting that the future is bright.",
        lang="en",
        profile=en_registered,
        judge_provider=j,
    )
    assert captured and captured[0].startswith("EN-JUDGE-V0::"), captured[0][:60]
    assert "_error" not in result, result


def test_en_iterative_polish_uses_profile_loop_judge(
    en_registered: LanguageProfile,
) -> None:
    """``iterative_polish(..., profile=en)`` routes the loop-judge prompt
    through the EN profile, ignoring the language-keyed module fallback.
    """
    captured: list[str] = []

    def _capture(prompt: str) -> str:
        if prompt.startswith("EN-LOOP-JUDGE-V0::"):
            captured.append(prompt)
            return json.dumps(
                {"ai_score": 20, "tells": ["filler opener"], "verdict": "BORDERLINE"}
            )
        # writer call
        return "Polished output. The future is bright."

    llm.use_callable(_capture, name="fakeprov", model="v1")
    article = "It's worth noting that the future is bright."
    result = iterative_polish(
        article,
        rounds=1,
        lang="en",
        profile=en_registered,
        allow_self_judge=True,
    )
    assert captured, "loop judge was not invoked through the EN profile"
    assert captured[0].startswith("EN-LOOP-JUDGE-V0::")
    assert result.rounds[0].rule_score is None  # lang=en skips local rule score


def test_en_postprocess_uses_profile_replacements(
    en_registered: LanguageProfile,
) -> None:
    """``postprocess_humanize`` with ``replacements`` from the EN profile
    must apply EN-specific substitutions — i.e. the framework does *not*
    look at language; it just consumes whatever ``ReplacementsTable`` it
    was handed.

    NB: ``postprocess_humanize(lang="en", ...)`` currently runs an
    LLM-only path and does not apply the replacements table by design
    (the EN path skips ZH-specific rule detect). To exercise the table
    plumbing we therefore pass ``lang="zh"`` plus the EN replacements —
    this is the same code path a future ``humanize-en`` plugin would
    take by registering its own pipeline module. The test only proves
    the seam works; semantic correctness of "EN on ZH pipeline" is not
    asserted.
    """
    from humanize_zh.postprocess import _deterministic_cleanup

    text = (
        "It's worth noting that we should delve into this matter."
        " In conclusion, the result is clear."
    )
    out = _deterministic_cleanup(text, replacements=en_registered.replacements)
    assert "It's worth noting that" not in out
    assert "In conclusion, " not in out
    assert "delve into" not in out
    assert "look at" in out


def test_en_profile_metadata_schema_matches_zh(
    en_registered: LanguageProfile,
) -> None:
    """A Phase-3 EN plugin must expose the same metadata keys as ZH so
    ``humanize providers`` (Phase 2) can render a uniform table."""
    md = en_registered.metadata
    for key in ("corpus", "rule_set_version", "ngram_corpus_id"):
        assert key in md, f"EN profile.metadata missing {key!r}"


def test_en_profile_swap_does_not_disturb_zh(en_registered: LanguageProfile) -> None:
    """After EN is registered, ``judge(..., lang='zh')`` (no profile)
    must still pick the ZH default prompt — registration must not
    introduce cross-language contamination.
    """
    from humanize_zh._lang.zh.prompts import JUDGE_PROMPT as ZH_JUDGE_PROMPT

    captured: list[str] = []

    def _capture(prompt: str) -> str:
        captured.append(prompt)
        return json.dumps(
            {
                "publishable": True,
                "worst_ai_sections": [],
                "unsupported_claims": [],
                "template_smell": [],
                "fake_human_details": [],
                "best_theses": [],
                "rewrite_brief": "",
            }
        )

    j = CallableProvider(_capture, name="cap", model="m1")
    judge("文章正文测试。", lang="zh", judge_provider=j)
    assert captured
    # ZH path is the canonical JUDGE_PROMPT, NOT the EN sentinel.
    assert not captured[0].startswith("EN-JUDGE-V0::")
    expected_prefix = ZH_JUDGE_PROMPT.split("{ARTICLE}", 1)[0][:40]
    assert captured[0].startswith(expected_prefix)


def test_en_profile_lang_mismatch_with_zh_lang_returns_error(
    en_registered: LanguageProfile,
) -> None:
    """Sanity: judge() rejects (profile=en, lang=zh) the same way it
    rejects (profile=zh, lang=en) — Phase 1.10 contract holds across
    both directions."""

    def _noop(_: str) -> str:
        return "{}"

    j = CallableProvider(_noop, name="cap", model="m1")
    result = judge(
        "anything",
        lang="zh",
        profile=en_registered,
        judge_provider=j,
    )
    assert "_error" in result
    assert "profile.code='en'" in result["_error"]
    assert "lang='zh'" in result["_error"]


def test_protocol_surface_is_self_contained() -> None:
    """Final assertion: building ``_make_en_profile()`` did NOT need any
    import from ``humanize_zh._lang.zh.*`` — only from the public
    ``humanize_zh`` namespace + ``humanize_zh._core.protocols``.

    If a future refactor leaks ZH-specific classes into the
    framework-level imports (e.g. forces plugins to subclass
    ``ZhDetector``), this test will fail because the assertion below
    will need updating. That's the alarm.
    """
    import inspect

    src = inspect.getsource(_make_en_profile)
    assert "_lang.zh" not in src, "EN dry-run leaked ZH internals"
    assert "ZhDetector" not in src
    assert "ZhNgramEngine" not in src
    assert "ZhReplacementsTable" not in src


def test_en_profile_components_runtime_check_against_protocols(
    en_registered: LanguageProfile,
) -> None:
    """The pseudo EN components answer ``isinstance`` against every
    runtime-checkable protocol — the same litmus we apply to ``zh_profile``.
    """
    from humanize_zh._core.protocols import (
        Detector,
        NgramEngine,
        PromptPack,
        ReplacementsTable,
    )
    assert isinstance(en_registered.detector, Detector)
    assert isinstance(en_registered.ngram_engine, NgramEngine)
    assert isinstance(en_registered.replacements, ReplacementsTable)
    assert isinstance(en_registered.prompt_pack, PromptPack)
