"""humanize_zh._core.prompt — language-agnostic prompt assembly.

Owns the cross-language dispatcher
:func:`build_humanize_postprocess_prompt` and the placeholder English
postprocess template :data:`POSTPROCESS_PROMPT_EN`.

Why these live in ``_core``:

The dispatcher's job is purely *which* language template to render —
it has no Chinese / English content of its own beyond delegating to
``humanize_zh._lang.zh.prompts`` for ZH and a built-in EN template for
EN. Once a real EN plugin is registered (Phase 3), the EN template
moves to that plugin's ``PromptPack`` and this module becomes a pure
registry-driven dispatcher.

The legacy public symbols ``POSTPROCESS_PROMPT_EN`` and
``build_humanize_postprocess_prompt`` are re-exported by the
``humanize_zh.prompt`` compat shim so external imports continue to
resolve unchanged.
"""

from __future__ import annotations

from .._lang.zh.prompts import (
    POSTPROCESS_PROMPT,
    POSTPROCESS_PROMPT_AGGRESSIVE,
    build_humanize_prompt,
)

# ── 英文 LLM-only 模式 ────────────────────
# 英文场景没有配套的 detect/ngram 引擎, 所以只给 LLM 一套英文润色 prompt,
# 内嵌 5 大原则 (self-contained, 不依赖 HUMANIZE_RULES). 当未来注册
# 真正的 EN LanguageProfile 时, 这段会迁到 plugin 自己的 PromptPack.
POSTPROCESS_PROMPT_EN = """# Task: De-AI polishing pass

You are a senior English editor trained to spot and strip AI-generated tell-signs.

## Input

Below is a long-form English article produced by an LLM. It may still carry AI
writing tics such as filler openers, templated structure, metaphor overload,
and sanitized neutrality.

---
{ARTICLE}
---

## Fix these categories (each is a retraction-level signal)

1. **Filler openers & bureaucratic hedging** — remove "It's worth noting",
   "In conclusion", "To put it simply", "At its core", "In today's world",
   "One might argue", "Needless to say".
2. **Template shapes** — no three-part enumerations ("First, Second, Finally"),
   no mechanical "On one hand / On the other hand", no uniformly-sized paragraphs.
3. **Rhythm** — mix sentence lengths. At least three distinct paragraph
   openings (concrete number / rhetorical question / contrast / quote /
   narrative / blunt claim). No brick-wall paragraphs.
4. **Trust the reader** — state facts directly. Cut metaphors that translate
   data into abstractions ("signal and noise", "the canvas", "a spectrum").
5. **No fake human details** — remove fabricated scenes ("at 3am last Tuesday"),
   invented first-person experience ("I spoke to a founder"), and made-up
   quotes unless explicitly grounded in the source material.

## Also watch for

- Sanitized hedges stacked together ("perhaps", "might", "could be").
- Collaborative chat residue ("Let me know if you need more!", "Hope this helps").
- Empty uplift ("the future looks bright", "a promising frontier").
- Universal claims dressed up as insight ("at the end of the day", "ultimately").

## Output

Return the **full polished article** only. No preface, no explanation.

**Preserve exactly**:
- All markdown structure (headings, lists, tables, fenced code)
- All inline code and URLs
- All numbers, percentages, currency, and dates (do not round or restate)
- Named entities (domains, usernames, product names)
- The final references / sources section, if any — every link must survive

**Only rewrite**: phrasing, transitions, sentence shape, AI-flavored clichés.
**Do not rewrite**: facts, numbers, section order, links.
"""


# ── 英文 judge prompt(placeholder until an EN plugin is registered)──────
# Phase 1.8 moved this from ``judge.py`` for the same reason ``POSTPROCESS_PROMPT_EN``
# lives here: there is no EN ``LanguageProfile`` yet, but the cross-language
# dispatcher in ``humanize_zh.judge`` still needs *some* template to fall back to
# when ``lang="en"``. When a real EN plugin lands in Phase 3, this constant moves
# to that plugin's ``PromptPack`` and this module becomes a pure dispatcher.
JUDGE_PROMPT_EN = """# Task: Final editorial review of a long-form English article

You are an independent editor reviewing deep-analysis long-form articles.
You do not rewrite the piece. You output a **structured JSON review only**.

## Bar for publication

Publishable = a reader will believe it, share it, and remember 1-2 concrete
takeaways after closing the tab.

Concrete criteria:
1. **Falsifiable claims** — not universal truisms, but specific assertions
   that a counter-example could refute.
2. **Each claim has evidence chain** — every core assertion backed by ≥2
   specific numbers or facts.
3. **Structure driven by questions** — not template filling (intro / body /
   conclusion / 5W2H shell).
4. **No fabricated human flavor** — no invented scenes ("at 3am last Tuesday"),
   no fake first-person experience ("a founder told me"), no made-up quotes.
5. **Memorable takeaways** — reader can restate ≥1 counter-intuitive concrete
   conclusion from memory.

## Required JSON output (no markdown wrapper)

```
{{
  "publishable": <bool>,
  "worst_ai_sections": [
    {{"para": "<first 30 chars of paragraph>", "reason": "<specific AI tell>"}}
  ],
  "unsupported_claims": [
    {{"claim": "<claim from article>", "missing_evidence": "<what's missing>"}}
  ],
  "template_smell": ["<concrete templated structure, not vague>"],
  "fake_human_details": ["<fabricated scene / experience quoted from article>"],
  "best_theses": ["<strongest claim, quoted, why it works>"],
  "rewrite_brief": "<3-5 sentences telling the author what to change, <200 chars>"
}}
```

## Field notes

- `publishable`: true only if all issues are minor AND ≥1 best_thesis.
- `worst_ai_sections`: pick the worst 2-5 (not all paragraphs).
- `unsupported_claims`: up to 5.
- `template_smell`: give concrete examples, not vague "feels a bit template".
- `fake_human_details`: quote exact fabricated passages.
- `best_theses`: 1-3 strongest claims with reasoning.
- `rewrite_brief`: 3-5 sentences, no fluff.

## Forbidden

- No text outside the JSON (no markdown fences, no explanation).
- No emoji inside field values.
- No platitudes ("good start", "needs work").
- Do not duplicate things a regex detector already catches (bad phrases,
  cliche sentences); focus on semantic issues.

---

## Article under review

{ARTICLE}
"""


# ── Loop-judge prompt EN(placeholder until an EN plugin is registered)──
# Phase 1.10 moved this from ``iterative.py``. Same fallback rationale as
# ``JUDGE_PROMPT_EN`` above: when ``lang="en"`` and no EN ``LanguageProfile``
# is registered, the dispatcher uses this constant. A real EN plugin will
# ship its own copy on its ``PromptPack.loop_judge_user_template``.
LOOP_JUDGE_PROMPT_EN = """You are an AI-text detector. Estimate how likely the
text below is AI-generated (LLM-written).

Evaluation axes (same family as GPTZero / Originality — transformer perplexity):
- Sentence uniformity (template-like = AI)
- Paragraph opener diversity (uniform = AI)
- Filler density ("It's worth noting", "In conclusion", "needless to say")
- Abstract vs concrete (more abstract = more AI)
- Human markers (subjective claim, uncertainty, self-correction, voice)

Input:
---
{ARTICLE}
---

Output strict JSON, no markdown:

{{
  "ai_score": <int 0-100, 0=human-like, 100=clearly AI>,
  "tells": [
    "<concrete sentence/paragraph that looks AI, ≤30 words>"
  ],
  "verdict": "<HUMAN_LIKE | BORDERLINE | AI_LIKE>"
}}

tells: 3-8 entries, must be specific phrases visible in the input.
"""


def build_humanize_postprocess_prompt(
    article: str,
    violations: list,
    scene: str = "analysis",
    *,
    lang: str = "zh",
    aggressive: bool = False,
) -> str:
    """生成「对已有文章做去 AI 味润色」的 prompt.

    Args:
        article: 待润色文章.
        violations: detect.py 输出的违规列表; 英文模式忽略.
        scene: 中文模式下的 scene (analysis/essay/academic/blog).
        lang: "zh" (默认, 完整规则 + 违规清单) 或 "en" (LLM-only, 内嵌 5 原则).
        aggressive: True 用强力重写 prompt (改写句式结构, 不只是替换关键词);
                    用于第三方 AI 检测器仍报高分时. 仅 zh 模式生效.
    """
    if lang == "en":
        return POSTPROCESS_PROMPT_EN.format(ARTICLE=article)

    if violations:
        viol_text = "\n".join(
            f"- {v.category}.{v.rule}: 命中 {v.count} 次 | 例: 「{v.sample[:40]}」"
            for v in violations[:30]
        )
    else:
        viol_text = "(规则扫描器未命中, 但第三方检测器仍报高分 - 问题在句式结构)"

    if aggressive:
        return POSTPROCESS_PROMPT_AGGRESSIVE.format(
            ARTICLE=article,
            VIOLATIONS=viol_text,
        )

    rules = build_humanize_prompt(scene=scene, compact=True)
    return POSTPROCESS_PROMPT.format(
        ARTICLE=article,
        VIOLATIONS=viol_text,
        HUMANIZE_RULES=rules,
    )
