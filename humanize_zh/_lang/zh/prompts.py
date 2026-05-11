#!/usr/bin/env python3
"""humanize_zh._lang.zh.prompts — Chinese prompt templates + scene builder.

Canonical home of the ZH plugin's prompt content. The historical import
path ``humanize_zh.prompt`` still works via a compat shim
(``humanize_zh/prompt.py``) that re-exports every public symbol below.

This file owns:

- The 8 ZH writing-discipline section constants
  (``CORE_RULES``, ``HARD_NEVER``, ``HARD_LIMITS``, ``WORDS_BLACKLIST``,
  ``OPENING_DIVERSITY``, ``SOUL_INJECTION``, ``ASSERTION_TEMPLATE``,
  ``SELF_CHECK``).
- The ``SCENES`` dispatch table (``analysis`` / ``essay`` /
  ``academic`` / ``blog``) and the assembler :func:`build_humanize_prompt`.
- The ZH postprocess templates ``POSTPROCESS_PROMPT`` (rule-by-rule
  light polish) and ``POSTPROCESS_PROMPT_AGGRESSIVE`` (full-rewrite for
  third-party detector failures).

The cross-language dispatcher ``build_humanize_postprocess_prompt`` and
the EN placeholder template ``POSTPROCESS_PROMPT_EN`` live in
``humanize_zh._core.prompt``; they choose between ZH templates (here)
and EN templates based on the ``lang`` argument.

支持场景:
    - "analysis"  分析/研究/选题报告 (默认, 适合 site-digester)
    - "essay"     评论/散文 (允许更多第一人称, 厚段)
    - "academic"  学术论文 (保持严谨, 加 hedging)
    - "blog"      博客 (中等口语化)
"""

from __future__ import annotations

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


# ── 终审 judge prompt(用于 ``humanize_zh.judge.judge``)─────────────────
# Phase 1.8 moved this from ``judge.py`` so the entire ZH prompt surface
# lives in one module. ``LanguageProfile.prompt_pack.judge_user_template``
# wraps this string for protocol-driven dispatch.
JUDGE_PROMPT = """# 任务: 给一篇网站分析文章做终审编辑审稿

你是一位独立编辑, 专门审稿"网站流量深度分析"类的中文长文。
你不写文章, 不点评作者, 只输出**结构化的审稿意见 JSON**。

## 评判标准

文章发表标准是: **读者愿意相信、愿意转发、读完能记住 1-2 个判断**。

具体标准:
1. **有可反驳的判断** — 不是常识句(「用户体验很重要」), 是能被一句反例推翻的具体断言
2. **判断背后有证据链** — 每个核心断言后跟 ≥ 2 条具体数据或事实
3. **结构由问题驱动** — 不是模板填空(总分总 / 11 节大纲 / 5W2H 套壳)
4. **没有伪人味** — 没有编造的具体场景(凌晨三点 / 周三晚上)、没有虚构的第一人称经历(去年我接触过)、没有编造的对话(他在 Discord 里告诉我)
5. **能记住 1-2 个判断** — 读完后读者应该能复述至少一个反直觉的具体结论

## 你必须输出的 JSON

严格按以下 schema, 不要加 markdown 代码块包裹:

```
{{
  "publishable": <bool>,
  "worst_ai_sections": [
    {{"para": "<原文段落第一句的前 30 字>", "reason": "<具体的 AI 体特征>"}}
  ],
  "unsupported_claims": [
    {{"claim": "<原文里的判断>", "missing_evidence": "<缺失的证据类型>"}}
  ],
  "template_smell": [
    "<具体的模板感描述, 不是空话>"
  ],
  "fake_human_details": [
    "<编造的具体场景或经历, 写出原文片段>"
  ],
  "best_theses": [
    "<文章里最强的判断, 写出原文片段, 说明为什么强>"
  ],
  "rewrite_brief": "<3-5 句话告诉作者重点改哪里, 不超过 200 字>"
}}
```

## 字段说明

- `publishable`: true 仅当所有问题都是小问题, 且 best_theses 至少 1 条
- `worst_ai_sections`: 最像 AI 写的 2-5 段(不是全部, 只挑最差的)
- `unsupported_claims`: 没有数据支撑的判断, 最多 5 条
- `template_smell`: 文章是否按模板填空, 给具体例子(不是"有点模板感"这种空话)
- `fake_human_details`: 凌晨三点 / 去年我 / 朋友买过 / 他在 Discord 告诉我 等编造场景
- `best_theses`: 最强的 1-3 个判断 — 这些可以保留
- `rewrite_brief`: 给作者的 3-5 句话改稿建议, 不要废话

## 严禁

- 不要在 JSON 外加任何文字、解释、markdown
- 不要在每个字段值里加 emoji
- 不要给出"很好"、"还需努力"类空话
- 不要重复检测器规则能抓的事(禁词、句式), 只看语义层面

---

## 待审稿文章

{ARTICLE}
"""


# ── Loop-judge prompt(用于 ``iterative_polish``)─────────────────────────
# Phase 1.10 moved this from ``iterative.py`` so the entire ZH judge
# prompt surface lives in one module. Distinct from ``JUDGE_PROMPT``:
# the iterative loop only needs ``ai_score`` / ``tells`` / ``verdict``,
# not the full 7-field editorial review.
LOOP_JUDGE_PROMPT = """你是 AI 文本检测员. 评估下面这段中文文章看起来多大概率是 AI(LLM) 生成.

评估维度 (与朱雀 / GPTZero 同源, transformer 困惑度视角):
- 句式整齐度 (越像模板越像 AI)
- 段落开头多样性 (越统一越像 AI)
- 套话密度 (综上所述/赋能/不容忽视/在...背景下/为...提供)
- 抽象 vs 具体 (越抽象越像 AI)
- 人味标记 (主观判断/不确定承认/自嘲/口语 — 越缺越像 AI)

输入:
---
{ARTICLE}
---

严格输出 JSON, 不要 markdown 包裹:

{{
  "ai_score": <int 0-100, 0=完全人写, 100=完全 AI>,
  "tells": [
    "<具体哪一句/哪一段像 AI, 用不超过 30 字描述>"
  ],
  "verdict": "<HUMAN_LIKE | BORDERLINE | AI_LIKE>"
}}

tells 数组至少给 3 条, 最多 8 条. 不要泛泛而谈, 必须是文章里能 grep 到的具体片段.
"""


if __name__ == "__main__":
    # 测试: 输出 analysis 场景的完整 prompt
    print(build_humanize_prompt("analysis"))
