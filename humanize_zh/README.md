# humanize/ — 综合去 AI 味工具模块

把中文 AI 写作里的"AI 味"系统性地降下来。**纯 Python**, 0 依赖, 也可以作为 prompt 段注入或调 LLM 做后处理。

## 设计来源

汇集了 6 个开源项目的精华:

| 项目 | 借鉴的部分 |
|---|---|
| [op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh) | 24 条 AI 写作模式 + 5 维评分 |
| [hylarucoder/ai-flavor-remover](https://github.com/hylarucoder/ai-flavor-remover) | LangGPT 角色扮演 prompt |
| [OUBIGFA/De-AI-Prompt-Enhancer](https://github.com/OUBIGFA/De-AI-Prompt-Enhancer-Writer-Booster-SKILL) | 18 条硬量化约束 + 段落节奏 |
| [nezhazheng/quaiwei-skill](https://github.com/nezhazheng/quaiwei-skill) | 引号 + 中英空格清理 |
| [shyuan/writing-humanizer](https://github.com/shyuan/writing-humanizer) | 双轮改写 + 红旗自检 |
| [voidborne-d/humanize-chinese](https://github.com/voidborne-d/humanize-chinese) | HC3 校准 + ML 评分 |

## 五种使用方式

### 1. 检测式(纯 Python, 不调 LLM)

```python
from humanize_zh import score
s = score(open("article.md").read())
print(s.total)        # 0-100 分
print(s.level)        # LOW / MEDIUM / HIGH / VERY HIGH
for v in s.violations:
    print(v)          # 哪条规则命中、几次、举例
```

CLI:

```bash
uv run python scripts/humanize.py detect article.md
uv run python scripts/humanize.py detect article.md --json
uv run python scripts/humanize.py detect article.md -v
```

输出示例:

```
AI 味评分: 42.6/100  (MEDIUM (有些 AI 痕迹))
文本长度: 9511 字符

命中规则:
  [+28.0] blacklist_words.fuzzy_modal: 命中 14 次 (阈值 5) | 例: 「...这个推断...」
  [+25.0] rhythm_rules.para_opening_diversity: 命中 7 次 (阈值 2) | 例: 「「第 N 个 X 是」开头 7 段」
  [+20.0] structural_rules.but_rather: 命中 2 次 (阈值 0) | 例: 「...而是...」
```

### 2. 注入式(在 LLM 写作时遵守)

把规则段拼到任何写作 prompt 末尾, LLM 在生成时就会避免 AI 体:

```python
from humanize_zh import build_humanize_prompt

rules = build_humanize_prompt(scene="analysis")  # 或 essay / academic / blog

template = open("templates/my-prompt.md").read()
full_prompt = template.replace("{HUMANIZE_RULES}", rules)
```

CLI 输出 prompt 段(可重定向到文件):

```bash
uv run python scripts/humanize.py prompt > rules.md
uv run python scripts/humanize.py prompt --scene academic
```

### 3. 后处理式(对已有文章做润色 pass)

调 LLM 做"去 AI 味第二轮"。先检测命中的规则, 再让 LLM 针对性修复:

```python
from humanize_zh import postprocess_humanize

article = open("article.md").read()
polished, after_score, before_score = postprocess_humanize(
    article,
    scene="analysis",
    provider="deepseek",  # 或 anthropic / glm / qwen 等
)
print(f"AI 分: {before_score.total} → {after_score.total}")
```

CLI:

```bash
uv run python scripts/humanize.py rewrite article.md -o polished.md
uv run python scripts/humanize.py compare article.md  # 前后对比 + 自动写出 polished
```

### 4. 终审式(LLM 判官, 输出 7 字段结构化审稿意见)

规则检测器(detect)便宜快, 但有语义盲区。终审层调**不同于 writer 的 LLM** 做审稿, 输出 codex 设计的 7 字段 JSON:

```python
from humanize_zh import judge, format_judge_report

article = open("article.md").read()
result = judge(
    article,
    writer_provider="deepseek",   # 防共谋: judge 默认会自动选 anthropic
    judge_provider="anthropic",   # 也可以手动指定
)

# result 字段:
#   publishable: bool                 是否可发表
#   worst_ai_sections: List[Dict]     最像 AI 写的 2-5 段
#   unsupported_claims: List[Dict]    没有数据支撑的判断
#   template_smell: List[str]         模板感问题
#   fake_human_details: List[str]     编造的人味细节(高风险)
#   best_theses: List[str]            最强的判断
#   rewrite_brief: str                3-5 句话改稿建议

print(format_judge_report(result))   # 渲染成可读 markdown 报告
```

**防 LLM 共谋**: 默认强制 `judge_provider != writer_provider`。同模型直接拒绝运行, 加 `allow_self_judge=True` 才能强行跑。

CLI:

```bash
# 自动选 judge 模型(writer=deepseek → judge=anthropic, 反之亦然)
uv run python scripts/humanize.py judge article.md

# 手动指定
uv run python scripts/humanize.py judge article.md --writer deepseek --judge anthropic

# JSON 输出
uv run python scripts/humanize.py judge article.md --json
```

输出示例:

```markdown
## 终审结果: ❌ 需修改

### 最强的判断 (2 条)
- "Direct 52% 实际是付费引荐二次回访" — 3 条证据支撑, 反直觉

### 最像 AI 写的段落 (3 处)
- 「templeluck.com 不是品牌资产...」 — 戏剧化揭露 + 模板段
- 「随着 H5 小游戏品类的发展...」 — 模板背景句

### 编造的人味细节 (1 处) ⚠️ 高风险
- 第七段「凌晨三点」是 AI 编造的, data.md 里没有这个时间点

### 改稿建议
重点改第三段和第七段, 删去伪场景, 把"专家认为"改为具体出处。
```

### 5. 综合式(rule + ngram, max-style 组合)

规则检测器抓语义模板(AI 黑名单词 / 三段式 / 「而是」句), 但它抓不到**字符级统计**。ngram 检测器补上这一块(perplexity / burstiness / entropy), 两者限制 max-style 组合 — 任一层判 HIGH 即报警, 适合发布门控。

```python
from humanize_zh import combined_score

cs = combined_score(open("article.md").read())
print(cs.combined_probability)  # max(rule, ngram)
print(cs.rule_probability)
print(cs.ngram_probability)
print(cs.combined_level)        # LOW / MEDIUM / HIGH / VERY HIGH
```

CLI:

```bash
uv run python scripts/humanize.py combined article.md
uv run python scripts/humanize.py combined article.md --json
```

输出示例:

```
综合 AI 概率: 27.8/100  (MEDIUM (有些 AI 痕迹))
  rule:  18.0/100  (LOW (基本像人写的))
  ngram: 27.8/100  (MEDIUM (有些 AI 痕迹))
```

**为什么 max 而不是 average**:

- `rule` 抓"语义模板", LLM 后处理改写**可以**降
- `ngram` 抓"字符级统计", LLM 后处理改写**改不掉**(Sadasivan et al. 2023)

平均会让 "rule 低但 ngram 高" 的文章看起来过关, 但它在底层分布上仍是 AI 体。max 更保守。

### ngram 单独调用

也可以单独不调 rule 只跑 ngram:

```python
from humanize_zh import ngram_score

ns = ngram_score(text)
print(ns.ai_probability)  # 0-100
print(ns.metrics)         # perplexity / burstiness / entropy / top_k_overlap 等
```

```bash
uv run python -m humanize.ngram_check article.md
```

资源(字符频率基线) 加载失败时, `ns.available = False`, 不破坏综合流程(自动 fallback 到 rule only)。

## 反伪经验检测器(`fake_human` 类)

LLM 在没有 `notes.md`(真实操作记录)时会**编造场景和经历**(凌晨三点 / 我去年 / 朋友买过 / 他在 Discord 告诉我), 这种伪人味比 AI 腔更危险, 因为伪造可信度。

**默认行为**:

| 场景 | 检测器 | 行为 |
|---|---|---|
| 没 `notes.md` | `fake_human` 启用 | 命中即扣分(weight=8, hard_threshold=0) |
| 有 `notes.md` (≥ 100 字节) | 自动豁免 | 允许第一人称和具体场景 |

**手动控制**:

```python
score(text, has_notes=True)   # 强制豁免
score(text, has_notes=False)  # 强制启用(默认)
```

```bash
# CLI 自动检测同级目录的 notes.md
uv run python scripts/humanize.py detect article.md

# 手动启用豁免
uv run python scripts/humanize.py detect article.md --notes
```

**3 个反伪经验检测器**:

```
fabricated_scene      凌晨三点 / 周三晚上 11 点 / 上周一打开 / 那天看到
fabricated_experience 我去年/上周/亲自接触 + 朋友买过 + 他跟我留言
fabricated_dialogue   我问他 / 他在 Discord 告诉我 / 他在微信跟我讲
```

## 评分体系

基于 HC3-Chinese 基准校准:

| 分数 | 等级 | 含义 |
|---|---|---|
| 0-24 | LOW | 基本像人写的 |
| 25-49 | MEDIUM | 有些 AI 痕迹 |
| 50-74 | HIGH | 大概率 AI 生成 |
| 75-100 | VERY HIGH | 几乎确定是 AI |

## 规则库结构

`patterns.json` 把所有规则数据驱动化, 共 6 大类:

### 1. 词汇黑名单 (`blacklist_words`)

| 类别 | 权重 | 示例 |
|---|---|---|
| `ai_high_freq` | 3 | 此外 / 然而 / 值得注意的是 / 综上所述 |
| `empty_grand` | 4 | 赋能 / 闭环 / 数字化转型 / 助力 / 底层逻辑 |
| `fake_metaphor` | 3 | 噪音 / 信号 / 底色 / 光谱 / 滤镜 / 解药 |
| `fake_oral` | 4 | 拆一拆 / 盘一盘 / 划重点 / 敲黑板 |
| `downgrade_intro` | 4 | 说白了 / 本质上 / 归根结底 |
| `fuzzy_modal` | 2 | 或许 / 可能 / 推断 / 暗示 (≤ 5 次) |
| `collab_marker` | 5 | 希望这对您有帮助 / 当然 / 请告诉我 |
| `ai_analysis_verb` | 3 | 拆解 / 梳理 / 剖析 (≤ 1 次) |
| `extreme_judgment` | 4 | 最残酷的地方在于 / 真正可怕的是 (≤ 1 次) |
| `vague_attribution` | 3 | 行业报告显示 / 专家认为 (无具体来源) |

### 2. 句式黑名单 (`blacklist_phrases`)

正则匹配:

- `negative_parallel`: 「不仅 A 而是 B」「不只是 A 更是 B」 — 鐵律 = 0
- `three_part_list`: 「首先...其次...最后」 — 三段式
- `drama_unmask`: 「撕下遮羞布」「剥开真相」 — 戏剧化揭露
- `template_section`: 「未来展望」「应运而生」 — 模板段
- `judgment_stack`: 「必然/显然/毋庸置疑」 — 绝对化副词
- `filler_intro`: 「为了实现」「众所周知」 — 填充开场

### 3. 结构性硬约束 (`structural_rules`)

| 规则 | 阈值 | 说明 |
|---|---|---|
| `but_rather` | hard 0 | 「而是」命中即改 |
| `second_person` | soft 1 | 「你/你会/你将」 |
| `colon_count` | soft 5 | 全角冒号数 |
| `marker_words` | hard 2 | 「换句话说/事实上/值得注意」 |
| `emoji_overuse` | soft 5 | 段落 emoji 装饰 |

### 4. 节奏规则 (`rhythm_rules`)

来自 humanize-chinese 的 HC3 d 值校准:

- `sentence_length_cv`: 句长变异系数(< 0.5 = AI 体)
- `short_sentence_ratio`: 短句占比(< 5% = 均匀机械)
- `paragraph_uniformity`: 段长 CV(< 0.3 = 砖墙)
- `para_opening_diversity`: 「第 N 个 X 是」开头 ≤ 2 段

### 5. 反伪经验 (`fake_human`) ⚠️ 高权重

LLM 在没有 `notes.md` 时会编造场景, 比 AI 腔更危险。**默认启用, 命中即重处**(weight=8, hard_threshold=0):

| 检测器 | 触发模式 |
|---|---|
| `fabricated_scene` | 凌晨三点 / 周三晚上 11 点 / 上周一打开 / 那天看到 |
| `fabricated_experience` | 我去年/上周/亲自接触 / 朋友买过 / 他跟我留言 |
| `fabricated_dialogue` | 我问他 / 他在 Discord 告诉我 / 在微信跟我讲 |

**豁免方式**: `score(text, has_notes=True)` 或同级目录有 `notes.md`(≥ 100 字节)。

### 6. 灵魂信号 (`soul_signals`)

中性的论证质量信号, 缺失轻微扣分(不强迫第一人称):

- `uncertainty_acknowledge`: 承认复杂性(「但 X 维度仍存疑」「不过」)
- `data_attribution`: 数据出处明确(「按 eCPM \$2 估算」「根据 SimilarWeb 4 月快照」)

## 集成模式

把 `humanize_zh` 当作可插拔的"去 AI 味"管线接到自己的写作流程上:

```python
from humanize_zh import build_humanize_prompt, postprocess_humanize, combined_score

# 1. 写作时把规则段注入到你的 LLM prompt 里
rules = build_humanize_prompt(scene="analysis")
final_prompt = my_template.replace("{HUMANIZE_RULES}", rules)

# 2. 生成完后做一遍去 AI 味润色
polished, after, before = postprocess_humanize(article, scene="analysis")

# 3. 发布门控: 任一层 HIGH 就阻拦
cs = combined_score(polished)
if cs.combined_probability >= 50:
    raise RuntimeError(f"still too AI: {cs.combined_level}")
```

或者直接用 CLI:

```bash
humanize-zh detect article.md           # 三层检测
humanize-zh polish article.md -o out.md # 润色 (需配 LLM provider)
humanize-zh judge  article.md           # 终审 (writer ≠ judge)
humanize-zh ui                          # FastAPI + HTMX Web UI
```

## 文件清单

```
humanize_zh/
├── __init__.py          API: score / build_humanize_prompt / postprocess_humanize / judge / ngram_score / combined_score / iterative_polish
├── patterns.json        规则数据(JSON,可外部修改, 6 大类规则 + replacements 表)
├── detect.py            Layer 1 规则检测(语义维度, 0-100 分, 含 fake_human + has_notes)
├── ngram_check.py       Layer 2 ngram 统计检测(字符级 perplexity/burstiness/entropy)
├── combined.py          综合 Layer 1+2 的 max-style 评分
├── prompt.py            注入式 prompt 段生成(反伪经验设计)
├── postprocess.py       后处理润色(调 LLM, 含 best-of-N 候选选择)
├── judge.py             Layer 3 LLM 终审(7 字段结构化 JSON, 防共谋)
├── iterative.py         writer ↔ judge 闭环, 多轮迭代到目标 AI 分
├── _format.py           共享分级标签 (level_label)
├── llm/                 Provider 抽象层 (OpenAI / Anthropic / Compat / Callable)
├── cli/                 humanize-zh CLI 入口
└── web/                 FastAPI + HTMX Web UI
```

## 自定义规则

修改 `patterns.json` 即可:

```json
{
  "blacklist_words": {
    "my_custom_pattern": {
      "weight": 5,
      "_desc": "我自己的禁用词",
      "patterns": ["小明", "小红"],
      "hard_threshold": 0
    }
  }
}
```

更细的字段:
- `weight`: 命中一次扣的分
- `patterns`: 词列表 / regex 列表
- `regex: true`: 把 patterns 当 regex
- `hard_threshold`: 超出即扣分(超几次扣几次)
- `soft_threshold`: 在阈值内只扣一半权重
- `min_threshold` (灵魂信号): 至少出现几次

## 评分调试

```bash
# 看哪些规则被触发, 各扣多少
uv run python scripts/humanize.py detect article.md -v

# 转成 JSON, 进一步处理
uv run python scripts/humanize.py detect article.md --json | jq '.violations[] | select(.score > 5)'
```
