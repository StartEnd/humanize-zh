# LLM provider guide

`humanize-zh` ships with four provider classes and a global "active provider"
registry. The polish and judge layers always call `llm.get_active().complete(prompt)`
internally, so once you've configured a provider, all downstream code uses it.

## Quickstart

```python
from humanize_zh import llm

# Pick exactly one of these:
llm.autodetect()                                # 1. From env vars (recommended for CLI tools)
llm.use("openai", api_key="sk-...")             # 2. Built-in: OpenAI / Anthropic
llm.use_openai_compat(name="deepseek", ...)     # 3. Any OpenAI-API service
llm.use_callable(my_func, name="custom")        # 4. Your own function
```

After this, `postprocess_humanize`, `judge`, and the CLI all use the same provider.

## Built-in providers

### `OpenAIProvider`

```python
llm.use(
    "openai",
    api_key="sk-...",
    model="gpt-4o-mini",                # default if env $OPENAI_MODEL not set
    base_url=None,                      # optional; for Azure OpenAI
    organization=None,                  # optional
    timeout=120.0,
)
```

Requires the `openai` extra: `pip install "humanize-zh[openai]"`.

### `AnthropicProvider`

```python
llm.use(
    "anthropic",
    api_key="sk-ant-...",
    model="claude-3-5-sonnet-20241022",
    timeout=120.0,
)
```

Requires the `anthropic` extra: `pip install "humanize-zh[anthropic]"`.

## OpenAI-compatible providers

`OpenAICompatProvider` drives any service that implements the OpenAI Chat
Completions wire format. You can choose any `name` you like — it surfaces in
logs and the `_meta.judge_provider` field.

| Service | `base_url` | Default model env |
|---|---|---|
| DeepSeek | `https://api.deepseek.com` | `DEEPSEEK_MODEL` |
| Groq | `https://api.groq.com/openai/v1` | `GROQ_MODEL` |
| OpenRouter | `https://openrouter.ai/api/v1` | `OPENROUTER_MODEL` |
| Together AI | `https://api.together.xyz/v1` | (none — set explicitly) |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `GLM_MODEL` |
| Moonshot Kimi | `https://api.moonshot.cn/v1` | `MOONSHOT_MODEL` |
| 阿里 Qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `QWEN_MODEL` |
| 火山引擎豆包 | `https://ark.cn-beijing.volces.com/api/v3` | (set explicitly) |
| Ollama (local) | `http://localhost:11434/v1` | `OLLAMA_MODEL` |
| vLLM / SGLang / LM Studio | wherever you host them | (set explicitly) |
| Azure OpenAI | `https://YOUR.openai.azure.com/openai/deployments/<DEPLOYMENT>` | (set explicitly) |

```python
llm.use_openai_compat(
    name="groq",
    base_url="https://api.groq.com/openai/v1",
    api_key="gsk-...",
    model="llama-3.3-70b-versatile",
    timeout=60.0,
)
```

For Ollama, `api_key` is unused but the underlying client still requires a
non-empty string — pass `"ollama"` as a placeholder.

## Custom callable

When you have a corporate LLM gateway, want to inject retry/cache logic, or
need to test with mocks:

```python
def my_llm(prompt: str) -> str:
    return company_internal_api(prompt)

llm.use_callable(my_llm, name="company-llm", model="v3")
```

`humanize-zh` will treat the callable like any other provider, including
collusion detection (compares `(name, model)`).

## Auto-detection chain

`llm.autodetect()` walks env vars in this order and stops on first hit:

```
OPENAI_API_KEY        → OpenAIProvider (model: $OPENAI_MODEL or "gpt-4o-mini")
ANTHROPIC_API_KEY     → AnthropicProvider (model: $ANTHROPIC_MODEL or "claude-3-5-sonnet-20241022")
DEEPSEEK_API_KEY      → OpenAICompatProvider name="deepseek" (model: $DEEPSEEK_MODEL or "deepseek-chat")
GROQ_API_KEY          → name="groq"   (model: $GROQ_MODEL  or "llama-3.3-70b-versatile")
OPENROUTER_API_KEY    → name="openrouter" (model: $OPENROUTER_MODEL or "anthropic/claude-3.5-sonnet")
MOONSHOT_API_KEY      → name="moonshot"
GLM_API_KEY           → name="glm"
DASHSCOPE_API_KEY     → name="qwen"
OLLAMA_BASE_URL       → name="ollama" (no key)
```

Override the order:

```python
llm.autodetect(prefer=["anthropic", "openai"])    # Try Anthropic first
```

`autodetect()` returns the active provider, or `None` if no env vars are set.

## Multi-provider workflow (writer vs judge)

To run `judge` against a *different* model than the one that wrote the
article — strongly recommended to avoid LLM collusion:

```python
from humanize_zh import postprocess_humanize, judge, llm
from humanize_zh.llm.openai_compat import OpenAICompatProvider
from humanize_zh.llm.anthropic_provider import AnthropicProvider

# Writer = DeepSeek
writer = OpenAICompatProvider(
    name="deepseek",
    base_url="https://api.deepseek.com",
    api_key=os.environ["DEEPSEEK_API_KEY"],
    model="deepseek-chat",
)
polished, _, _ = postprocess_humanize(article, provider=writer)

# Judge = Claude
judge_p = AnthropicProvider(api_key=os.environ["ANTHROPIC_API_KEY"])
verdict = judge(polished, writer_provider=writer, judge_provider=judge_p)
```

If both `writer_provider` and `judge_provider` resolve to the same
`(name, model)`, `judge` returns:

```json
{"_error": "writer and judge are both deepseek::deepseek-chat. Collusion risk is high. ..."}
```

Pass `allow_self_judge=True` to override (not recommended).

## Error handling

```python
from humanize_zh.llm import LLMRateLimitError, LLMTimeoutError, LLMError

try:
    polished, _, _ = postprocess_humanize(article)
except LLMRateLimitError as e:
    time.sleep(e.retry_after_seconds or 30)
    # retry
except LLMTimeoutError:
    # back off and retry
except LLMError as e:
    log.error("LLM call failed: %s", e)
```

Inside `postprocess_humanize` and `judge`, LLM errors are *caught and logged*,
and the function falls back gracefully (deterministic cleanup for polish,
`_error` dict for judge). The exceptions surface only when you call
`provider.complete(prompt)` directly.
