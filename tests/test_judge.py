"""Phase 3: judge() — lang=zh/en, collusion detection, provider resolution.

Plus Pass B.3 additions: ``_parse_json`` edge cases and ``format_report``
field-rendering paths that previously dragged ``judge.py`` coverage to 51%.
"""
from __future__ import annotations

import json

from humanize_zh import llm
from humanize_zh.judge import _parse_json, format_report, judge
from humanize_zh.llm.callable_provider import CallableProvider


def test_zh_judge_with_callable(ai_article_zh, fake_judge_fn) -> None:
    llm.use_callable(fake_judge_fn, name="fake-judge", model="j1")
    result = judge(ai_article_zh, lang="zh")
    assert "_error" not in result, result
    assert result["publishable"] is False
    assert result["_meta"]["lang"] == "zh"
    assert result["_meta"]["judge_provider"] == "fake-judge::j1"


def test_en_judge_with_callable(ai_article_en, fake_judge_fn) -> None:
    llm.use_callable(fake_judge_fn, name="fake-en", model="j1")
    result = judge(ai_article_en, lang="en")
    assert "_error" not in result
    assert result["_meta"]["lang"] == "en"


def test_collusion_same_provider_and_model_rejected(ai_article_zh, fake_polish_fn, fake_judge_fn) -> None:
    writer = CallableProvider(fake_polish_fn, name="same", model="m1")
    judge_p = CallableProvider(fake_judge_fn, name="same", model="m1")
    result = judge(ai_article_zh, writer_provider=writer, judge_provider=judge_p)
    assert "_error" in result
    assert "Collusion" in result["_error"]


def test_allow_self_judge_bypasses_collusion(ai_article_zh, fake_polish_fn, fake_judge_fn) -> None:
    writer = CallableProvider(fake_polish_fn, name="same", model="m1")
    judge_p = CallableProvider(fake_judge_fn, name="same", model="m1")
    result = judge(
        ai_article_zh,
        writer_provider=writer,
        judge_provider=judge_p,
        allow_self_judge=True,
    )
    assert "_error" not in result


def test_unconfigured_returns_error(ai_article_zh) -> None:
    result = judge(ai_article_zh)
    assert "_error" in result
    assert "no judge provider" in result["_error"]


def test_different_writer_and_judge_ok(ai_article_zh, fake_polish_fn, fake_judge_fn) -> None:
    w = CallableProvider(fake_polish_fn, name="writer", model="w1")
    j = CallableProvider(fake_judge_fn, name="judger", model="j1")
    result = judge(ai_article_zh, writer_provider=w, judge_provider=j)
    assert "_error" not in result, result
    assert result["_meta"]["writer_provider"] == "writer::w1"
    assert result["_meta"]["judge_provider"] == "judger::j1"


def test_invalid_lang_returns_error(ai_article_zh, fake_judge_fn) -> None:
    j = CallableProvider(fake_judge_fn, name="j", model="j1")
    result = judge(ai_article_zh, lang="fr", judge_provider=j)
    assert "_error" in result
    assert "lang" in result["_error"]


def test_judge_result_has_required_fields(ai_article_zh, fake_judge_fn) -> None:
    llm.use_callable(fake_judge_fn, name="j", model="j1")
    result = judge(ai_article_zh)
    for field in ["publishable", "worst_ai_sections", "unsupported_claims",
                  "template_smell", "fake_human_details", "best_theses", "rewrite_brief"]:
        assert field in result, f"missing field: {field}"


def test_judge_format_report_renders(ai_article_zh, fake_judge_fn) -> None:
    llm.use_callable(fake_judge_fn, name="j", model="j1")
    result = judge(ai_article_zh)
    report = format_report(result)
    assert "终审结果" in report or "publishable" in report


# ─── _parse_json edge cases (Pass B.3) ──────────────────────────────────────


def test_parse_json_plain_object() -> None:
    assert _parse_json('{"publishable": true}') == {"publishable": True}


def test_parse_json_strips_markdown_fence() -> None:
    raw = '```json\n{"publishable": false, "best_theses": ["x"]}\n```'
    parsed = _parse_json(raw)
    assert parsed["publishable"] is False
    assert parsed["best_theses"] == ["x"]


def test_parse_json_handles_trailing_prose() -> None:
    """LLMs often add a sentence before/after the JSON block."""
    raw = '这是 JSON 输出:\n\n{"publishable": true}\n\n以上.'
    assert _parse_json(raw) == {"publishable": True}


def test_parse_json_returns_error_on_pure_prose() -> None:
    parsed = _parse_json("This is just commentary with no JSON at all.")
    assert "_parse_error" in parsed
    assert parsed["_parse_error"] == "no json found"
    assert "commentary" in parsed["_raw"]


def test_parse_json_returns_error_on_array_response() -> None:
    """Judge prompt requires an object — arrays are rejected with raw stashed."""
    parsed = _parse_json('[1, 2, 3]')
    assert "_parse_error" in parsed


def test_parse_json_returns_error_on_malformed_json() -> None:
    parsed = _parse_json('{"unterminated: "yes')
    assert "_parse_error" in parsed
    assert "_raw" in parsed


def test_parse_json_empty_returns_empty_dict() -> None:
    assert _parse_json("") == {}


def test_parse_json_clips_raw_in_error_payload() -> None:
    """Raw passthrough is capped at 500 chars to avoid log explosions."""
    blob = "x" * 5000
    parsed = _parse_json(blob)
    assert "_parse_error" in parsed
    assert len(parsed["_raw"]) <= 500


# ─── format_report rendering (Pass B.3) ─────────────────────────────────────


def test_format_report_error_path() -> None:
    rendered = format_report({"_error": "no judge provider"})
    assert "[judge] 错误" in rendered
    assert "no judge provider" in rendered


def test_format_report_parse_error_path() -> None:
    rendered = format_report({"_parse_error": "bad json", "_raw": "garbage"})
    assert "JSON 解析失败" in rendered
    assert "garbage" in rendered


def test_format_report_renders_publishable_yes() -> None:
    rendered = format_report({"publishable": True, "best_theses": ["论点 A", "论点 B"]})
    assert "可发表" in rendered
    assert "最强的判断" in rendered
    assert "论点 A" in rendered


def test_format_report_renders_publishable_no() -> None:
    rendered = format_report({"publishable": False})
    assert "需修改" in rendered


def test_format_report_renders_worst_sections_as_dicts() -> None:
    rendered = format_report({
        "publishable": False,
        "worst_ai_sections": [
            {"para": "首先, A 解决了", "reason": "三段式列举"},
        ],
    })
    assert "最像 AI 写的段落" in rendered
    assert "首先, A 解决了" in rendered
    assert "三段式列举" in rendered


def test_format_report_renders_worst_sections_as_strings() -> None:
    """The schema permits bare strings as a fallback shape."""
    rendered = format_report({
        "publishable": False,
        "worst_ai_sections": ["开篇就是 AI 套话"],
    })
    assert "开篇就是 AI 套话" in rendered


def test_format_report_renders_unsupported_claims_dict_and_string() -> None:
    rendered = format_report({
        "publishable": False,
        "unsupported_claims": [
            {"claim": "用户增长 200%", "missing_evidence": "无来源链接"},
            "另一条没证据的断言",
        ],
    })
    assert "无证据支撑的判断" in rendered
    assert "用户增长 200%" in rendered
    assert "无来源链接" in rendered
    assert "另一条没证据的断言" in rendered


def test_format_report_renders_template_smell_and_fake_human() -> None:
    rendered = format_report({
        "publishable": False,
        "template_smell": ["首先/其次/最后 三段式"],
        "fake_human_details": ["凌晨 3 点的虚假场景"],
    })
    assert "模板感问题" in rendered
    assert "首先/其次/最后" in rendered
    assert "编造的人味细节" in rendered
    assert "高风险" in rendered  # fake_human carries the warning marker


def test_format_report_includes_rewrite_brief() -> None:
    rendered = format_report({
        "publishable": False,
        "rewrite_brief": "删除三段式开场, 改成自然过渡",
    })
    assert "改稿建议" in rendered
    assert "删除三段式开场" in rendered


def test_format_report_includes_meta_footer() -> None:
    rendered = format_report({
        "publishable": True,
        "_meta": {
            "judge_provider": "fake-judge::j1",
            "writer_provider": "fake-writer::w1",
            "article_length": 3210,
            "lang": "zh",
        },
    })
    assert "fake-judge::j1" in rendered
    assert "fake-writer::w1" in rendered
    assert "3,210" in rendered  # article_length formatted with thousands sep


# ─── Integration: bad LLM response surfaces as parse_error ─────────────────


def test_judge_on_non_json_llm_response_returns_parse_error(ai_article_zh) -> None:
    """If the judge LLM returns prose, the parse error must reach the caller."""
    def _prose_llm(_: str) -> str:
        return "I think the article is fine, no JSON needed."

    llm.use_callable(_prose_llm, name="prose", model="m1")
    result = judge(ai_article_zh)
    assert "_parse_error" in result
    assert result["_parse_error"] == "no json found"


def test_judge_on_empty_llm_response_surfaces_error(ai_article_zh) -> None:
    """LLM returns empty: judge should not crash — caller sees a sensible error."""
    llm.use_callable(lambda _: "", name="empty", model="m1")
    result = judge(ai_article_zh)
    # Either `_error` (no usable text) or empty parsed dict — both are acceptable
    # ways to surface this; we just demand the call does not raise.
    assert isinstance(result, dict)


def test_parse_json_pure_array_returns_error() -> None:
    """A bare array (no embedded object) is rejected at the substring stage."""
    parsed = _parse_json(json.dumps([1, 2, 3]))
    assert "_parse_error" in parsed


# ─── Phase 1.10: LanguageProfile injection ──────────────────────────────


def test_judge_profile_overrides_lang_template(ai_article_zh, fake_judge_fn) -> None:
    """When a ``LanguageProfile`` is passed, its ``judge_user_template``
    drives the prompt — the ``lang``-keyed module fallback should be
    bypassed even if ``lang="zh"``.
    """
    from dataclasses import replace

    from humanize_zh._lang.zh.profile import zh_profile

    captured: list[str] = []

    def _capture_fn(prompt: str) -> str:
        captured.append(prompt)
        return fake_judge_fn(prompt)

    sentinel_template = "SENTINEL-PROMPT::{ARTICLE}"
    custom_pack = replace(zh_profile.prompt_pack, judge_user_template=sentinel_template)
    custom_profile = replace(zh_profile, prompt_pack=custom_pack)

    j = CallableProvider(_capture_fn, name="cap", model="m1")
    judge(ai_article_zh, profile=custom_profile, judge_provider=j)
    assert captured, "judge() did not call the LLM"
    assert captured[0].startswith("SENTINEL-PROMPT::"), captured[0][:60]


def test_judge_profile_lang_mismatch_returns_error(ai_article_en, fake_judge_fn) -> None:
    """Passing ``lang="en"`` with a ZH profile must be flagged early
    rather than silently using the wrong template."""
    from humanize_zh._lang.zh.profile import zh_profile

    j = CallableProvider(fake_judge_fn, name="j", model="j1")
    result = judge(ai_article_en, lang="en", profile=zh_profile, judge_provider=j)
    assert "_error" in result
    assert "profile.code='zh'" in result["_error"]
    assert "lang='en'" in result["_error"]


def test_judge_no_profile_keeps_v0_1_0a1_behavior(ai_article_zh, fake_judge_fn) -> None:
    """With ``profile=None`` (default), the prompt must still be the
    canonical ZH ``JUDGE_PROMPT`` from ``_lang.zh.prompts``.
    """
    from humanize_zh._lang.zh.prompts import JUDGE_PROMPT

    captured: list[str] = []

    def _capture_fn(prompt: str) -> str:
        captured.append(prompt)
        return fake_judge_fn(prompt)

    j = CallableProvider(_capture_fn, name="cap", model="m1")
    judge(ai_article_zh, lang="zh", judge_provider=j)
    assert captured
    expected_prefix = JUDGE_PROMPT.split("{ARTICLE}", 1)[0][:40]
    assert captured[0].startswith(expected_prefix), (
        f"default ZH judge prompt drifted from JUDGE_PROMPT; got prefix {captured[0][:60]!r}"
    )
