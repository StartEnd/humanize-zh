"""humanize_zh._core.protocols — language plugin contracts.

These protocols define what a *language* must provide so that the core
pipeline (``postprocess`` / ``iterative`` / ``judge`` / ``combined`` /
``web`` / ``cli``) can operate without knowing whether it is processing
Chinese, English, or some future language.

There are three *component* protocols — :class:`Detector`,
:class:`NgramEngine`, :class:`ReplacementsTable` — plus two *value
objects* (:class:`PromptPack`, :class:`LanguageProfile`) that bundle
them with metadata.

Design notes
------------

**Why ``Protocol`` and not ``abc.ABC``** — plugins ship as independent
PyPI packages (``humanize-zh``, ``humanize-en``, future ``humanize-ja``).
Forcing them to inherit from an ABC would require a hard import on
``humanize-core`` at class-definition time, complicating circular layering
during the in-repo spike. ``typing.Protocol`` enables *structural* typing:
plugins satisfy the contract by shape, no inheritance needed. The
``@runtime_checkable`` decorator lets us still do ``isinstance(profile,
Detector)`` smoke checks in tests.

**Why reuse existing dataclasses (``Score`` / ``NgramScore`` /
``Violation``) instead of introducing new ones** — backward compatibility.
v0.1.0a1 users import these names; renaming them in the spike would force
their code (and our 215 tests) to change. Protocols here describe the
*shape* of return values; concrete dataclasses live next to the impls.

**Stability commitment** — these contracts are versioned with
``humanize-core``. Breaking changes bump the major version; plugins
declare ``humanize-core>=X.Y,<X+1`` in ``pyproject.toml``.

**Forbidden in protocol return types** — anything language-specific
(Chinese characters in error messages, Markdown formatting choices, ...).
Keep the contract neutral; let plugins format strings inside their own
``__str__`` methods.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# ─── Component protocols ────────────────────────────────────────────────────


@runtime_checkable
class RuleScoreResult(Protocol):
    """Shape returned by :meth:`Detector.score`.

    Matches the existing ``humanize_zh.detect.Score`` dataclass so the zh
    plugin's ``Score`` instances satisfy this protocol without any
    adaptation. Future plugins may either reuse ``Score`` directly or
    define their own dataclass with these attributes.
    """

    total: float
    """AI probability in ``[0, 100]``. Higher means more AI-like."""

    level: str
    """Localized label, e.g. ``"HIGH (大概率 AI 生成)"`` or
    ``"HIGH (likely AI-generated)"``. Use :class:`LanguageProfile.level_labels`
    to localize."""

    violations: list[Any]
    """Triggered rules. Each item should expose ``category``, ``rule``,
    ``score``, ``count``, ``sample``, ``threshold`` for the Web UI to
    render. The zh plugin uses ``humanize_zh.detect.Violation``."""

    stats: dict[str, Any]
    """Diagnostic metrics (rhythm, fake-human ratios, ...). Free-form;
    only consumed by the CLI pretty-printer and Web UI."""

    text_length: int
    """Length of the input text used for length-normalization."""


@runtime_checkable
class Detector(Protocol):
    """Rule-based AI detector — pure local, no LLM, no network.

    Each language plugin contributes one ``Detector``. Implementations
    are expected to be **thread-safe and reentrant** because the FastAPI
    Web UI runs sync routes in a threadpool and may invoke ``score()``
    concurrently from multiple threads.
    """

    code: str
    """ISO 639-1 code of the language, e.g. ``"zh"``, ``"en"``."""

    version: str
    """Semver of the rule-set itself (independent of plugin package
    version). Bump when rules change so calibration drift is auditable."""

    def score(self, text: str, *, has_notes: bool = False) -> RuleScoreResult:
        """Score ``text`` against the rule library.

        Args:
            text: Input text in the plugin's target language. Behavior
                on mixed-language input is implementation-defined.
            has_notes: Caller-provided hint that this text accompanies
                real human operation logs. Plugins may use it to
                suppress ``fake_human`` style false positives.

        Returns:
            An object satisfying :class:`RuleScoreResult`.
        """
        ...


@runtime_checkable
class NgramScoreResult(Protocol):
    """Shape returned by :meth:`NgramEngine.score`.

    Matches ``humanize_zh.ngram_check.NgramScore``.
    """

    ai_probability: float
    """AI probability in ``[0, 100]`` derived from n-gram statistics."""

    level: str
    """Localized label."""

    metrics: dict[str, Any]
    """Per-feature breakdown (``perplexity``, ``burstiness``,
    ``entropy``, ...). Plugin-defined."""

    text_length: int
    char_count: int
    """``char_count`` is "tokens of interest" — for zh it's CJK chars,
    for en it's words. Use whichever lets the calibration generalize."""

    available: bool
    """``False`` when the n-gram data files are missing or failed to
    load. The combined-score code falls back to rule-only in that case."""


@runtime_checkable
class NgramEngine(Protocol):
    """Statistical AI detector trained on a labelled corpus.

    Optional — a language plugin may omit n-gram support and set
    :attr:`LanguageProfile.ngram_engine` to ``None``. The combined
    score then degrades gracefully to rule-only.
    """

    code: str
    corpus_id: str
    """Human-readable identifier of the training corpus, e.g.
    ``"HC3-Chinese-300+300"`` or ``"RAID-en-2024"``. Surfaced in
    ``--version``-style output for reproducibility."""

    @property
    def available(self) -> bool:
        """``True`` if the engine successfully loaded its data files at
        construction time. Read-only — declared as a property here so
        plugins can implement it as either a plain attribute or a
        ``@property``; both satisfy the structural type check."""
        ...

    def score(self, text: str) -> NgramScoreResult:
        """Score ``text`` against the n-gram model. If
        :attr:`available` is ``False``, must still return a valid
        ``NgramScoreResult`` (with ``available=False``); never raise."""
        ...

    def reason_unavailable(self) -> str | None:
        """Human-readable explanation when :attr:`available` is ``False``
        (e.g. ``"data file not found at /path/...""``). Returns ``None``
        when the engine is healthy."""
        ...


@runtime_checkable
class ReplacementsTable(Protocol):
    """Ordered deterministic-cleanup pairs for the polish pipeline.

    The polish stage applies these pairs *before* and *after* the LLM
    rewrite to enforce simple word-substitution preferences (e.g.
    ``"综上所述" → "总之"``, ``"leverage" → "use"``). Order matters —
    longer phrases must come before their substrings to avoid partial
    rewrites.
    """

    code: str

    def ordered_pairs(self) -> Sequence[tuple[str, str]]:
        """Return ``(pattern, replacement)`` tuples in apply order.

        Returning ``Sequence`` (rather than ``list``) lets plugins ship
        an immutable ``tuple[tuple[str, str], ...]`` to advertise that
        the table is read-only at runtime. Callers must treat the
        result as covariantly read-only and never mutate it.

        ``pattern`` may be a literal string or a regex (the polish
        pipeline uses ``re.sub`` with no flags by default; the plugin
        is responsible for escaping if the entries are meant literal).
        Implementations should be cheap to call repeatedly — wrap
        with ``functools.lru_cache`` if the underlying source (JSON
        file, DB) is expensive.
        """
        ...


# ─── Value objects ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PromptPack:
    """Localized writer/judge prompts for a single language.

    Templates use ``str.format``-style placeholders so plugins can ship
    them as plain strings without pulling in Jinja2 just for prompts.
    The polish/judge code substitutes a fixed set of keys:

    - ``writer_user_template`` placeholders: ``{text}``, ``{scene}``,
      ``{violations}``, ``{aggressive_block}``.
    - ``judge_user_template`` placeholders: ``{text}``,
      ``{rules_summary}``.
    """

    code: str
    writer_system: str
    writer_user_template: str
    judge_system: str
    judge_user_template: str
    rules_section: str
    """Standalone rules block that callers can inject into a custom
    writing prompt (see ``examples/04_inject_rules_into_prompt.py``)."""


@dataclass(frozen=True)
class LanguageProfile:
    """Bundle of all language-specific components plus metadata.

    A plugin's ``profile.py`` constructs exactly one instance of this
    and registers it with :func:`humanize_zh._core.language_registry.register_language`.
    """

    code: str
    """ISO 639-1 code; must equal each component's ``code``."""

    display_name: str
    """Human-readable name, e.g. ``"中文 (简体)"``, ``"English"``.
    Used in the Web UI lang switcher."""

    detector: Detector
    ngram_engine: NgramEngine | None
    """``None`` allowed — combined-score falls back to rule-only."""

    replacements: ReplacementsTable
    prompt_pack: PromptPack

    level_labels: dict[str, str] = field(default_factory=dict)
    """Localized labels keyed by ``LOW`` / ``MEDIUM`` / ``HIGH`` /
    ``VERY_HIGH``. Empty dict means "use raw level codes" (testing /
    headless contexts). The shared formatter
    :func:`humanize_zh._format.level_label` reads from here."""

    metadata: dict[str, str] = field(default_factory=dict)
    """Free-form ID strings: ``corpus``, ``calibration_version``,
    ``maintainer_email``, etc. Surfaced by ``humanize providers``."""

    def __post_init__(self) -> None:
        # Cheap consistency check — catches mismatched plugins early
        # (e.g. someone wires a zh detector into an en profile).
        for component_name, component_code in [
            ("detector", self.detector.code),
            ("replacements", self.replacements.code),
            ("prompt_pack", self.prompt_pack.code),
        ]:
            if component_code != self.code:
                raise ValueError(
                    f"LanguageProfile(code={self.code!r}) has "
                    f"{component_name}.code={component_code!r} — "
                    f"all components must agree on the language code"
                )
        if self.ngram_engine is not None and self.ngram_engine.code != self.code:
            raise ValueError(
                f"LanguageProfile(code={self.code!r}) has "
                f"ngram_engine.code={self.ngram_engine.code!r}"
            )


__all__ = [
    "Detector",
    "LanguageProfile",
    "NgramEngine",
    "NgramScoreResult",
    "PromptPack",
    "ReplacementsTable",
    "RuleScoreResult",
]
