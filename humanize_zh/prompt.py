#!/usr/bin/env python3
"""humanize.prompt — 生成可注入到任何写作 prompt 的「去 AI 味」规则段

用法:
    from humanize import build_humanize_prompt
    rules_section = build_humanize_prompt(scene="analysis")
    full_prompt = my_template.replace("{HUMANIZE_RULES}", rules_section)

支持场景:
    - "analysis"  分析/研究/选题报告 (默认, 适合 site-digester)
    - "essay"     评论/散文 (允许更多第一人称, 厚段)
    - "academic"  学术论文 (保持严谨, 加 hedging)
    - "blog"      博客 (中等口语化)

设计目标:
    把 6 个开源去 AI 味项目的精华浓缩成 ~200 行可注入的 Markdown 段。
"""

from __future__ import annotations

import json
from pathlib import Path

PATTERNS_PATH = Path(__file__).parent / "patterns.json"


def _load_patterns() -> dict:
    return json.loads(PATTERNS_PATH.read_text(encoding="utf-8"))


# ── 5 大写作铁律(综合 Humanizer-zh + writing-humanizer)─────────
CORE_RULES = """## 5 大铁律(违反 = 退稿)

1. **删除填充短语** — 去除「值得注意的是」「综上所述」「不难发现」开场白和强调拐杖词
2. **打破公式结构** — 消灭三段式列举、二元对比、戏剧性分段;两项优于三项
3. **变化节奏** — 句长长短交替,段落开头 ≥ 3 种类型,禁止砖墙式均匀段
4. **信任读者** — 直接陈述事实, 删除软化、解释隐喻、手把手引导
5. **删除金句** — 听起来像可引用的格言,必须重写
"""


# ── 顶格律: 永远不允许的句式 ────────────────────
HARD_NEVER = """## 鐵律: 永远不允许的句式

```
1. 「不仅...而是...」「不只是...更是...」「不仅仅是...而是...」 — 否定式排比, 命中即删
2. 「而是」 — 全文搜索, 命中即改(豁免: 直接引语 / 严格逻辑「不是 A 而是 B」科学定义)
3. 「首先...其次...最后」「一方面...另一方面」 — 三段式套路, 改成自然过渡
4. 「希望对您有帮助」「请告诉我」 — 协作交流痕迹, 命中即删
5. 「为了实现这一目标」「在这个时间点」 — 填充开场, 直接删
```
"""


# ── 硬约束清单 ────────────────────
HARD_LIMITS = """## 量化硬约束

| 项目 | 硬上限 | 说明 |
|---|---|---|
| 「或许 / 也许 / 大概 / 暗示」总数 | ≤ 3 | AI 体骑墙保护, 用敢断言代替 |
| 「推断 / 推测」总数 | ≤ 3 | 用「估算约」「按行业基准」代替 |
| AI 分析动词(拆解/梳理/剖析/解构/聚焦/洞察/深耕/赋能/助力/构建/打造) | ≤ 1 | 改为具体动作 |
| 极值判断(「最残酷的地方在于」「真正可怕的是」「更讽刺的是」) | ≤ 1 | 删除框架,直接给事实 |
| 降维引导语(「说白了」「本质上」「归根结底」「换个角度看」) | ≤ 1 | 删 |
| 二人称「你/你会/你将」 | ≤ 1 | 仅在归谬推演时用 |
| 路标词(「换句话说」「事实上」「值得注意」「与此同时」「总之」) | ≤ 2 | |
| 全角冒号「:」 | ≤ 2 | 仅在直接引语提示语 |
| emoji 段落标签(✅⚠️💰🧠🤔🗣️🧪👤🧭) | ≤ 5 | 只用在大节标题, 不要每段加 |
| 段落以「第N个 X 是」开头 | ≤ 2 | AI 列举懒散标志 |
| 判断式陈述堆叠(「A 是 B」「必然/显然/毋庸置疑」) | ≤ 3 | 每处必须紧跟机制/事实 |
"""


# ── 高频禁用词清单 ────────────────────
WORDS_BLACKLIST = """## 高频 AI 词汇 — 命中即改写或删除

**协作交流痕迹**(整句必删):
- 希望这对您有帮助 / 当然! / 一定! / 您说得完全正确 / 请告诉我 / 这是一个

**空洞宏大词**:
- 赋能 / 闭环 / 数字化转型 / 协同增效 / 降本增效 / 全方位 / 多维度 / 系统性 / 高质量发展 / 助力 / 底层逻辑 / 抓手 / 触达 / 沉淀 / 复盘 / 迭代 / 破圈 / 颠覆 / 舆论场 / 话语场

**AI 高频隐喻词**(命中即改):
- 噪音 / 信号 / 底色 / 光谱 / 滤镜 / 解药 / 土壤 / 基因 / 拼图 / 镜像 / 尺子 / 标尺 / 切面 / 切片 / 透镜 / 棱镜 / 缩影

**AI 伪口语化**(命中即删):
- 拆一拆 / 盘一盘 / 捋一捋 / 盘点一下 / 划重点 / 敲黑板 / 聊一聊

**戏剧化揭露修辞**(默认清零, 改为直接给事实):
- 撕下/扯下/揭下 + 遮羞布/面具/画皮/伪装/外衣/幌子
- 剥开/戳穿/戳破/揭穿/撕开 + 表象/真面目/本质/真相

**模板段**(必须删除):
- 「尽管面临 X 挑战」「未来展望」「未来可期」「前景广阔」「应运而生」

**模糊归因**(必须降级):
- 行业报告显示 / 观察者指出 / 专家认为 / 一些批评者认为 / 多个来源 → 给具体出处或删除
"""


# ── 段落开头多样化 ────────────────────
OPENING_DIVERSITY = """## 段落开头多样化(强制)

**禁止**:全文 80% 段落以「第一个/第二个/第三个 X 是」开头(AI 列举懒散标志)。

**至少使用 3 种**不同的段落开头:

1. **具体数字开头**:「`6.7M` 这个数字背后藏着两个事实...」
2. **反问开头**:「为什么 `43%` 的付费引荐没换来一条 Reddit 讨论?」
3. **对照开头**:「同样是游戏站, friv.com 用 8 年做到这个流量, X 用了 30 天。」
4. **引用开头**:「HN 用户 `xyz` 在评论里写道...」
5. **叙事开头**:「它拒绝被存档。」/「凌晨 3 点, 智能体还在不停运转。」
6. **断言开头**:「它就是 X, 不是 Y。」(配 2 个证据)
"""


# ── 注入灵魂 ────────────────────
SOUL_INJECTION = """## 注入灵魂(避免无菌写作)

去除 AI 模式只是一半工作。无菌、没有声音的写作和机器生成的内容一样明显。

**必须做到**:
- **有判断**: 不要只报告事实, 对它们做出反应。基于数据的反直觉判断比中立列利弊更有信息量
- **变化节奏**: 短促有力的句子。然后是需要时间慢慢展开的长句。混合使用
- **承认复杂性**: 「这数字令人印象深刻, 但 X 维度仍然存疑」胜过「这令人印象深刻」
- **允许一些混乱**: 完美的结构感觉像算法, 让句长和段落长度自然起伏

**严禁伪人味**(以下行为比 AI 体更危险):
- ❌ 编造没有发生过的具体场景(「凌晨三点没人看着的时候...」、「周三晚上我打开...」)
- ❌ 虚构第一人称经历(「去年我接触过这个站...」、「我朋友买了这种站...」)
- ❌ 编造对话或引用(「他在 Discord 里告诉我...」)

**第一人称的合法用法(仅在 `notes.md` 存在且记录了真实操作时)**:
- ✅ 「我跑了一遍站内的 X 流程, 发现 Y」(notes.md 记录了 X 流程)
- ✅ 「我注意到 sitemap 里 241 个页面分布很可疑」(对公开数据的观察, 不是私人经历)
- ❌ 没 notes.md 时, 整篇文章用第三方视角(数据 + 分析), 不用「我」
"""


# ── 强制断言模板 ────────────────────
ASSERTION_TEMPLATE = """## 断言模板(每个核心判断必须遵守)

**格式**:【判断】 + 因为【数据 1】 + 因为【数据 2】

```
❌ AI 体: "运营者可能是单兵或两人小组,因为没有招聘页"

✅ 顶尖: "运营者就是单兵 — 三个证据:
   (1) sitemap 241 个页面整齐分 6 类各 40 个,只有自动化批处理能产生这种工整度;
   (2) 没有 /careers /about, Google Workspace MX 只配 1 个邮箱;
   (3) SSL 证书全是 Let's Encrypt 免费版, 没付费 EV 证书。"
```

**条件式废话禁令**:
```
❌ "如果买量成本上升, 网站可能会受到影响, 但也有可能继续生存..."

✅ "买量成本一旦涨 30%, 这站当月就死。算账: 43% × 6.7M = 2.88M 次付费点击,
    按 CPC \\$0.05-0.15 计, 月 \\$144K-432K 是硬支出。它的广告收入按 eCPM \\$2 估算只有 \\$30K-50K。"
```

**铁律**: 每个「如果 X」必须给出「那么 Y」的确切数字预测, 不能只列可能性。
"""


# ── 结尾自检清单 ────────────────────
SELF_CHECK = """## 写完通读自检(交付前必须确认)

```
[ ] 「而是」命中数 = 0?(豁免: 直接引语 / 科学定义)
[ ] 「不仅...更是...」/「不只是...而是...」否定式排比 = 0?
[ ] 「或许 / 可能 / 推断」总数 ≤ 5?
[ ] emoji 段落标签 ≤ 5?
[ ] 段落开头「第 N 个 X 是」≤ 2 段?
[ ] 用了 ≥ 3 种不同类型的段落开头(数字 / 反问 / 对照 / 引用 / 叙事)?
[ ] 每个核心判断后跟 ≥ 2 个具体数据?
[ ] 模板段(「未来展望」「应运而生」「蓬勃发展」)= 0?
[ ] 协作交流痕迹(「希望这对您有帮助」「请告诉我」)= 0?
[ ] 三段式列举(「首先...其次...最后」)= 0?
[ ] 极值判断(「最残酷的地方在于」「真正可怕的是」)≤ 1?
[ ] AI 分析动词(拆解 / 梳理 / 剖析)总数 ≤ 1?
[ ] 段落长度有起伏(不是每段都一样长)?
[ ] 没有编造的具体场景(「凌晨三点」「他告诉我」类未发生事件)?
[ ] 没有伪造的第一人称经历(无 `notes.md` 时不应出现「我去年/上周/亲自」)?
```

**任何一条不通过, 必须再改一轮**。第一轮永远会漏东西。

**特别提醒: 伪人味比 AI 腔更危险**。读者一旦发现你编造了具体场景或经历, 全文可信度归零。
宁可保持冷静的第三方分析视角, 也不要为了「显得有人味」编故事。
"""


SCENES = {
    "analysis": [CORE_RULES, HARD_NEVER, HARD_LIMITS, WORDS_BLACKLIST,
                 OPENING_DIVERSITY, SOUL_INJECTION, ASSERTION_TEMPLATE, SELF_CHECK],
    "essay":    [CORE_RULES, HARD_NEVER, HARD_LIMITS, WORDS_BLACKLIST,
                 OPENING_DIVERSITY, SOUL_INJECTION, SELF_CHECK],
    "academic": [CORE_RULES, HARD_NEVER, HARD_LIMITS, WORDS_BLACKLIST, SELF_CHECK],
    "blog":     [CORE_RULES, HARD_NEVER, WORDS_BLACKLIST, OPENING_DIVERSITY,
                 SOUL_INJECTION, SELF_CHECK],
}


def build_humanize_prompt(scene: str = "analysis", *, compact: bool = False) -> str:
    """生成可注入到任何写作 prompt 的「去 AI 味」规则段。

    Args:
        scene: 文体场景, 影响选用的规则集
        compact: 是否压缩(去掉示例, 只留规则)

    Returns:
        Markdown 字符串, 可直接拼到 prompt
    """
    if scene not in SCENES:
        scene = "analysis"
    sections = SCENES[scene]
    head = "# 去 AI 味写作纪律(必须严格遵守)\n\n这是顶尖付费内容 vs 免费 AI 灌水文的分水岭。违反任何一条都会让整篇沦为 AI 体。\n\n---\n\n"
    body = "\n\n---\n\n".join(sections)
    return head + body + "\n"


# ── 强力重写 prompt(force_llm=True 时使用)─────────────
# 普通 POSTPROCESS_PROMPT 是"逐项修违规", 适合刚生成的文章做小幅清理.
# 第三方 AI 检测器 (朱雀/Originality) 看的是统计/transformer 困惑度,
# 不是关键词命中, 所以光替换"综上所述"远远不够 —— 必须**重写句式**.
POSTPROCESS_PROMPT_AGGRESSIVE = """# 任务: AI 文本深度去味改写 (重写级别)

输入是一篇已被 AI 检测器(朱雀 / Originality / GPTZero)识别为 **>50% AI 概率** 的中文文章.
仅做关键词替换无效——必须**改写句式结构**, 让 transformer 困惑度上升.

## 输入
---
{ARTICLE}
---

## 已知违规清单(仅供参考, 真正问题在句式)
{VIOLATIONS}

## 改写硬规则(每条都要做到, 不是建议)

### 1. 句式打散 — 这是最重要的一条
AI 习惯写**长复合句**(主谓宾 + 修饰从句 + "并 / 同时 / 此外"). 你必须:
- 把长句拆成 1-2 个短句 + 1 个中句的节奏
- 同一段内, 句子长度差至少 2 倍 (不能全是 30 字句, 也不能全是 10 字句)
- 删除"并""同时""此外""值得一提的是""不仅...而且"这类拼接连词, 改用句号或转折

### 2. 段落起手必须不一样
连续 3 段的开头不能用相似结构. 至少混用 3 种:
- 具体数字开头 ("8 个 subreddit 转发") - 反问 / 设问 ("这能算独立站吗?") - 转折 ("不过 ...")
- 引语 / 直白断言 ("没人会读 1500 字的 about 页.")- 名词短语 + 句号 ("一个被低估的事实.") - 时间锚点 ("2024 年 3 月发的, 现在还在涨")

### 3. 删 AI 套话(不是替换, 是**删掉整句**)
看到下面任意句式, 整句删除, 让段落变短不补回:
- "综上所述/总而言之/总之"开头的总结句- "值得一提的是/不容忽视/毋庸置疑/众所周知"
- "在...的背景下/随着...的发展" - "为...提供了/带来了/注入了" + 抽象动词("活力""动能""赋能""生态")
- "高质量发展/数字化转型/新质生产力"等政策套话

### 4. 用具体替代抽象
"取得了显著成效" → 删掉, 改成具体的数字 / 例子 / 时间- "广泛应用" → "已在 X 公司用了 6 个月" 之类的具体话- "推动行业变革" → 删整句

### 5. 加人味标记(关键!)AI 写作没有"作者立场". 至少加 2 处:
- 主观判断: "我觉得这套路不对" "说实话有点扯"
- 不确定承认: "这个数没核实" "可能我看漏了"
- 自嘲 / 元评论: "(说着说着又跑题了)" - 直接称呼读者: "你要是做独立开发就懂"

### 6. 标点更新
- 至少 1 处破折号 (—— 不是 -)
- 至少 1 处分号或冒号
- 长段中插入短句独占一行(夹注效果)

## 输出格式

直接输出**完整改写后文章**. 不要前言, 不要解释为什么这么改.

## 必须保留(死线)
- 所有 markdown 结构(标题/列表/表格)
- 所有截图引用 `![alt](screenshots/xxx.png)`- 所有数字 / 百分比 / 金额 / 日期(`6.7M` `$30K` 这类反引号包裹的, 一字不改)
- 末尾「参考来源」段, 链接一条不能少
- 域名 / 用户名 / 产品名

**改写句式而非删事实**. 长度控制在原文的 80%-120%, 允许稍短(因为删了套话).
"""


# ── 后处理 prompt(对已生成的文章润色)─────────────────
POSTPROCESS_PROMPT = """# 任务: 去 AI 味润色 pass

你是一位资深中文文字编辑, 专门识别和去除 AI 生成文本的痕迹。

## 输入

下面是一篇 AI 生成的中文长文, 由 LLM 在严格规则下生成, 但仍有 AI 体残留:

---
{ARTICLE}
---

## 现有问题清单(机器自动检测)

{VIOLATIONS}

---

## 你的任务

针对上述命中的违规, **逐项修复**。改写规则:

{HUMANIZE_RULES}

## 输出格式

直接输出**完整的润色后文章**, 不要加前言/后语/解释。

**必须保留的内容(严禁删除)**:
- 所有 markdown 结构(标题层级/列表/表格)
- 所有截图引用 `![alt](screenshots/xxx.png)`
- 所有数字、百分比、金额、日期(用反引号包裹的 `6.7M` `$30K-50K` 等不能改)
- **末尾的「参考来源」「参考原文信息列表」段必须原样保留**, 链接一条不能少
- 域名、用户名、产品名等专有名词

**只改**: 语言风格、句式、连接词、AI 套话。**不改**: 信息事实、数字、章节结构、链接。
"""


# ── 英文 LLM-only 模式 ────────────────────
# 英文场景没有配套的 detect/ngram 引擎, 所以只给 LLM 一套英文润色 prompt,
# 内嵌 5 大原则 (self-contained, 不依赖 HUMANIZE_RULES).
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


if __name__ == "__main__":
    # 测试: 输出 analysis 场景的完整 prompt
    print(build_humanize_prompt("analysis"))
