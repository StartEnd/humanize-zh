"""Phase 5: FastAPI Web UI tests via httpx TestClient.

Skipped automatically if the 'ui' extra is not installed.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # required for fastapi.testclient.TestClient

from fastapi.testclient import TestClient

from humanize_zh import llm
from humanize_zh.web.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_index_renders(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "humanize-zh" in r.text
    assert "一键去 AI" in r.text  # primary tab (always visible)
    assert "仅检测分数" in r.text  # advanced tab (rendered, hidden behind toggle)
    assert "仅润色" in r.text
    assert "LLM 终审" in r.text
    assert "闭环改写" in r.text  # iterative loop tab
    assert "htmx" in r.text  # script loaded


def test_api_providers_no_env(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    for env in [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY",
        "OPENROUTER_API_KEY", "MOONSHOT_API_KEY", "GLM_API_KEY", "DASHSCOPE_API_KEY",
        "OLLAMA_BASE_URL",
    ]:
        monkeypatch.delenv(env, raising=False)
    r = client.get("/api/providers")
    assert r.status_code == 200
    body = r.json()
    assert body["active_will_be"] is None
    assert all(not row["available"] for row in body["rows"])


def test_api_detect(client: TestClient, ai_article_zh: str) -> None:
    r = client.post("/api/detect", data={"text": ai_article_zh})
    assert r.status_code == 200
    body = r.json()
    assert body["chars"] == len(ai_article_zh)
    assert body["rule"]["probability"] > 0
    assert body["combined"]["probability"] > 0
    assert isinstance(body["rule"]["violations"], list)


def test_api_detect_empty_text(client: TestClient) -> None:
    r = client.post("/api/detect", data={"text": "   "})
    assert r.status_code == 400


def test_htmx_detect_returns_html_fragment(client: TestClient, ai_article_zh: str) -> None:
    r = client.post(
        "/htmx/detect",
        data={"text": ai_article_zh},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "/100" in r.text  # score block present
    assert "rule" in r.text and "ngram" in r.text and "combined" in r.text


def test_htmx_detect_empty_returns_error_fragment(client: TestClient) -> None:
    r = client.post("/htmx/detect", data={"text": ""})
    # FastAPI 422 since required field empty? Form requires non-empty so:
    # actual: text="" triggers our own emptiness check (we accept empty string in Form)
    # but Form(...) requires field present, not non-empty
    # Pass actual whitespace to trigger our 400 path:
    r = client.post("/htmx/detect", data={"text": "   "})
    assert r.status_code == 400
    assert "请粘贴" in r.text


def test_api_polish_without_provider_returns_503(client: TestClient, ai_article_zh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for env in [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY",
        "OPENROUTER_API_KEY", "MOONSHOT_API_KEY", "GLM_API_KEY", "DASHSCOPE_API_KEY",
        "OLLAMA_BASE_URL",
    ]:
        monkeypatch.delenv(env, raising=False)
    llm.clear()
    r = client.post("/api/polish", data={"text": ai_article_zh})
    assert r.status_code == 503
    assert "no LLM provider" in r.json()["detail"]


def test_api_polish_with_callable(client: TestClient, ai_article_zh: str, fake_polish_fn) -> None:
    llm.use_callable(fake_polish_fn, name="fake-polish", model="v1")
    r = client.post("/api/polish", data={"text": ai_article_zh})
    assert r.status_code == 200
    body = r.json()
    assert body["polished"]
    assert body["lang"] == "zh"
    assert body["chars"]["before"] == len(ai_article_zh)
    assert body["chars"]["after"] > 0


def test_htmx_polish_returns_html_fragment(client: TestClient, ai_article_zh: str, fake_polish_fn) -> None:
    llm.use_callable(fake_polish_fn, name="fake", model="v1")
    r = client.post(
        "/htmx/polish",
        data={"text": ai_article_zh, "scene": "analysis", "lang": "zh"},
    )
    assert r.status_code == 200
    assert "polished-text" in r.text  # the result wrapper id
    assert "AI 概率变化" in r.text  # before/after score block
    assert "拿去 judge" in r.text  # pipe button


def test_htmx_oneshot_returns_html_fragment(client: TestClient, ai_article_zh: str, fake_polish_fn) -> None:
    llm.use_callable(fake_polish_fn, name="fake", model="v1")
    r = client.post(
        "/htmx/oneshot",
        data={"text": ai_article_zh, "scene": "analysis", "lang": "zh"},
    )
    assert r.status_code == 200
    assert "AI 概率变化" in r.text
    assert "oneshot-polished-text" in r.text
    assert "下载" in r.text


def test_htmx_oneshot_loop_returns_html_fragment(client: TestClient, ai_article_zh: str) -> None:
    """Loop endpoint returns _loop_result.html with rounds table + final text."""
    import json as _json

    def _fn(prompt: str) -> str:
        if "AI 文本检测员" in prompt:
            return _json.dumps(
                {"ai_score": 20, "tells": ["a", "b", "c"], "verdict": "HUMAN_LIKE"},
                ensure_ascii=False,
            )
        return "# 改写后\n\n这是改写后的文章。\n"

    llm.use_callable(_fn, name="fake", model="v1")
    r = client.post(
        "/htmx/oneshot-loop",
        data={
            "text": ai_article_zh,
            "scene": "analysis",
            "lang": "zh",
            "rounds": "2",
            "target_ai_score": "30",
            "allow_self_judge": "true",
        },
    )
    assert r.status_code == 200, r.text
    assert "闭环改写完成" in r.text
    assert "loop-final-text" in r.text
    assert "各轮过程" in r.text
    assert "HUMAN_LIKE" in r.text
    # Self-judge warning should appear because writer == judge
    assert "共谋风险" in r.text


def test_htmx_oneshot_loop_collusion_blocked_without_flag(
    client: TestClient, ai_article_zh: str
) -> None:
    """Without allow_self_judge=True, single-provider loop should 400 with collusion error."""
    import json as _json

    def _fn(prompt: str) -> str:
        if "AI 文本检测员" in prompt:
            return _json.dumps({"ai_score": 25, "tells": [], "verdict": "HUMAN_LIKE"})
        return "x"

    llm.use_callable(_fn, name="fake", model="v1")
    r = client.post(
        "/htmx/oneshot-loop",
        data={"text": ai_article_zh, "rounds": "1"},  # no allow_self_judge
    )
    assert r.status_code == 400
    assert "collusion" in r.text.lower() or "both" in r.text.lower()


def test_htmx_oneshot_without_provider_returns_error(client: TestClient, ai_article_zh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for env in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY",
                "OPENROUTER_API_KEY", "MOONSHOT_API_KEY", "GLM_API_KEY", "DASHSCOPE_API_KEY",
                "OLLAMA_BASE_URL"]:
        monkeypatch.delenv(env, raising=False)
    llm.clear()
    r = client.post("/htmx/oneshot", data={"text": ai_article_zh})
    assert r.status_code == 503
    assert "no LLM provider" in r.text


def test_api_judge_without_provider_returns_503(client: TestClient, ai_article_zh: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for env in [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY",
        "OPENROUTER_API_KEY", "MOONSHOT_API_KEY", "GLM_API_KEY", "DASHSCOPE_API_KEY",
        "OLLAMA_BASE_URL",
    ]:
        monkeypatch.delenv(env, raising=False)
    llm.clear()
    r = client.post("/api/judge", data={"text": ai_article_zh})
    assert r.status_code == 503


def test_api_judge_with_callable(client: TestClient, ai_article_zh: str, fake_judge_fn) -> None:
    llm.use_callable(fake_judge_fn, name="fake-judge", model="j1")
    r = client.post("/api/judge", data={"text": ai_article_zh})
    assert r.status_code == 200
    body = r.json()
    assert "_error" not in body
    assert "publishable" in body


def test_htmx_judge_returns_report(client: TestClient, ai_article_zh: str, fake_judge_fn) -> None:
    llm.use_callable(fake_judge_fn, name="fake-judge", model="j1")
    r = client.post(
        "/htmx/judge",
        data={"text": ai_article_zh, "lang": "zh"},
    )
    assert r.status_code == 200
    # Either rendered the formatted report OR raised judge error; for our fixture it should render.
    assert "可发表" in r.text or "需修改" in r.text
