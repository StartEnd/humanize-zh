"""humanize_zh.web.app — FastAPI application factory.

Endpoints:
    GET  /                       — single-page UI (three tabs: detect/polish/judge)
    POST /htmx/detect            — HTMX HTML fragment (rule + ngram + combined)
    POST /htmx/polish            — HTMX HTML fragment (LLM polish)
    POST /htmx/judge             — HTMX HTML fragment (LLM judge)
    POST /api/detect             — JSON detection result
    POST /api/polish             — JSON polish result
    POST /api/judge              — JSON judge result
    GET  /api/providers          — JSON list of detected providers
    GET  /health                 — JSON liveness probe
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, Form, HTTPException, Request
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.templating import Jinja2Templates
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "humanize-zh web UI requires the 'ui' extra. "
        "Run: pip install 'humanize-zh[ui]'"
    ) from e

from .. import __version__
from .. import llm as _llm_module
from ..combined import combined_score
from ..detect import score
from ..iterative import iterative_polish
from ..judge import format_report as format_judge_report
from ..judge import judge as run_judge
from ..ngram_check import ngram_score
from ..postprocess import postprocess_humanize
from ._security import AbuseControlConfig, AbuseControlMiddleware

logger = logging.getLogger("humanize_zh.web")

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"


# ─── Provider helpers ───────────────────────────────────────────────────────


def _provider_state() -> dict[str, Any]:
    """Snapshot of detectable providers from env, sourced from the registry."""
    rows = _llm_module.list_providers()
    available = [r["name"] for r in rows if r["available"]]
    return {
        "rows": rows,
        "available": available,
        "active_will_be": available[0] if available else None,
    }


def _ensure_provider() -> str | None:
    """Activate a provider if none yet, return error message on failure."""
    if _llm_module.has_active():
        return None
    if _llm_module.autodetect() is not None:
        return None
    return (
        "no LLM provider configured — set one of "
        f"{_llm_module.required_env_keys_hint()}"
    )


# ─── App factory ────────────────────────────────────────────────────────────

def create_app(
    *,
    abuse_control: AbuseControlConfig | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    Args:
        abuse_control: Optional explicit auth / rate-limit config. When
            ``None`` the config is read from environment variables; tests
            inject an explicit config to avoid leaking process env into the
            app instance.
    """
    app = FastAPI(
        title="humanize-zh",
        description="Chinese AI text humanization — detect / polish / judge",
        version=__version__,
    )

    # Auth + rate-limit middleware — only attached when at least one of the
    # two env vars is set, so the default deployment is byte-identical to
    # pre-Pass-E behavior (and existing tests need no changes).
    cfg = abuse_control if abuse_control is not None else AbuseControlConfig.from_env()
    if cfg.any_enabled:
        app.add_middleware(AbuseControlMiddleware, config=cfg)
        logger.info(
            "[humanize_zh.web] abuse control: auth=%s rate_limit=%s",
            cfg.auth_enabled, cfg.rate_per_minute or "off",
        )

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Any:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "version": __version__,
                "providers": _provider_state(),
            },
        )

    # ─── Detection ──────────────────────────────────────────────────────

    def _do_detect(text: str, has_notes: bool) -> dict[str, Any]:
        rule = score(text, has_notes=has_notes)
        ng = ngram_score(text)
        cs = combined_score(text, has_notes=has_notes)
        return {
            "chars": len(text),
            "rule": {
                "probability": rule.total,
                "level": rule.level,
                "violations": [
                    {
                        "category": v.category,
                        "rule": v.rule,
                        "count": v.count,
                        "sample": v.sample,
                    }
                    for v in rule.violations[:20]
                ],
            },
            "ngram": {
                "probability": ng.ai_probability,
                "level": ng.level,
                "available": ng.available,
            },
            "combined": {
                "probability": cs.combined_probability,
                "level": cs.combined_level,
            },
        }

    @app.post("/api/detect")
    def api_detect(text: str = Form(...), has_notes: bool = Form(False)) -> JSONResponse:
        if not text.strip():
            raise HTTPException(status_code=400, detail="text is empty")
        return JSONResponse(_do_detect(text, has_notes))

    @app.post("/htmx/detect", response_class=HTMLResponse)
    def htmx_detect(
        request: Request,
        text: str = Form(...),
        has_notes: bool = Form(False),
    ) -> Any:
        if not text.strip():
            return templates.TemplateResponse(
                request, "_error.html", {"message": "请粘贴需要检测的文章内容"}, status_code=400
            )
        result = _do_detect(text, has_notes)
        return templates.TemplateResponse(request, "_detect_result.html", {"r": result})

    # ─── Polish ─────────────────────────────────────────────────────────

    @app.post("/api/polish")
    def api_polish(
        text: str = Form(...),
        scene: str = Form("analysis"),
        lang: str = Form("zh"),
    ) -> JSONResponse:
        if not text.strip():
            raise HTTPException(status_code=400, detail="text is empty")
        err = _ensure_provider()
        if err:
            raise HTTPException(status_code=503, detail=err)

        try:
            polished, after, before = postprocess_humanize(text, scene=scene, lang=lang)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        payload: dict[str, Any] = {
            "polished": polished,
            "lang": lang,
            "scene": scene,
            "chars": {"before": len(text), "after": len(polished)},
        }
        if before is not None and after is not None:
            payload["scores"] = {
                "before": {"total": before.total, "level": before.level},
                "after": {"total": after.total, "level": after.level},
                "delta": before.total - after.total,
            }
        else:
            payload["scores"] = None
        return JSONResponse(payload)

    @app.post("/htmx/polish", response_class=HTMLResponse)
    def htmx_polish(
        request: Request,
        text: str = Form(...),
        scene: str = Form("analysis"),
        lang: str = Form("zh"),
        force_llm: bool = Form(False),
    ) -> Any:
        if not text.strip():
            return templates.TemplateResponse(
                request, "_error.html", {"message": "请粘贴需要润色的文章内容"}, status_code=400
            )
        err = _ensure_provider()
        if err:
            return templates.TemplateResponse(
                request, "_error.html", {"message": err}, status_code=503
            )
        try:
            polished, after, before = postprocess_humanize(
                text, scene=scene, lang=lang, force_llm=force_llm
            )
        except ValueError as e:
            return templates.TemplateResponse(
                request, "_error.html", {"message": str(e)}, status_code=400
            )

        return templates.TemplateResponse(
            request,
            "_polish_result.html",
            {
                "polished": polished,
                "before": before,
                "after": after,
                "lang": lang,
                "scene": scene,
                "len_before": len(text),
                "len_after": len(polished),
                "unchanged": polished == text,
                "force_llm": force_llm,
            },
        )

    # ─── One-shot pipeline (detect → polish → detect) ──────────────────

    @app.post("/htmx/oneshot", response_class=HTMLResponse)
    def htmx_oneshot(
        request: Request,
        text: str = Form(...),
        scene: str = Form("analysis"),
        lang: str = Form("zh"),
        force_llm: bool = Form(False),
    ) -> Any:
        if not text.strip():
            return templates.TemplateResponse(
                request, "_error.html", {"message": "请粘贴文章内容"}, status_code=400
            )
        err = _ensure_provider()
        if err:
            return templates.TemplateResponse(
                request, "_error.html", {"message": err}, status_code=503
            )
        try:
            polished, after, before = postprocess_humanize(
                text, scene=scene, lang=lang, force_llm=force_llm
            )
        except ValueError as e:
            return templates.TemplateResponse(
                request, "_error.html", {"message": str(e)}, status_code=400
            )
        return templates.TemplateResponse(
            request,
            "_oneshot_result.html",
            {
                "polished": polished,
                "before": before,
                "after": after,
                "lang": lang,
                "scene": scene,
                "len_before": len(text),
                "len_after": len(polished),
                "unchanged": polished == text,
                "force_llm": force_llm,
            },
        )

    # ─── Iterative closed-loop pipeline (writer ↔ judge, N rounds) ─────

    @app.post("/htmx/oneshot-loop", response_class=HTMLResponse)
    def htmx_oneshot_loop(
        request: Request,
        text: str = Form(...),
        scene: str = Form("analysis"),
        lang: str = Form("zh"),
        rounds: int = Form(3),
        target_ai_score: int = Form(30),
        writer: str | None = Form(None),
        judge_p: str | None = Form(None, alias="judge"),
        allow_self_judge: bool = Form(False),
    ) -> Any:
        if not text.strip():
            return templates.TemplateResponse(
                request, "_error.html", {"message": "请粘贴文章内容"}, status_code=400,
            )
        # Need an active provider for whichever side defaults to None.
        if writer is None or judge_p is None:
            err = _ensure_provider()
            if err:
                return templates.TemplateResponse(
                    request, "_error.html", {"message": err}, status_code=503,
                )
        rounds = max(1, min(rounds, 5))  # clamp 1-5 to bound LLM cost
        target_ai_score = max(0, min(target_ai_score, 100))

        try:
            result = iterative_polish(
                text,
                rounds=rounds,
                target_ai_score=target_ai_score,
                scene=scene,
                lang=lang,
                writer_provider=writer,
                judge_provider=judge_p,
                allow_self_judge=allow_self_judge,
            )
        except ValueError as e:
            return templates.TemplateResponse(
                request, "_error.html", {"message": str(e)}, status_code=400,
            )

        # Compute first/last AI scores for headline.
        first = next((r for r in result.rounds if r.ai_score is not None), None)
        last = next(
            (r for r in reversed(result.rounds) if r.ai_score is not None), None,
        )
        delta_ai = (
            (first.ai_score - last.ai_score)
            if first and last and first.ai_score is not None and last.ai_score is not None
            else None
        )
        return templates.TemplateResponse(
            request,
            "_loop_result.html",
            {
                "result": result,
                "first_round": first,
                "last_round": last,
                "delta_ai": delta_ai,
                "len_before": len(text),
                "len_after": len(result.final_text),
                "lang": lang,
                "scene": scene,
            },
        )

    # ─── Judge ──────────────────────────────────────────────────────────

    @app.post("/api/judge")
    def api_judge(
        text: str = Form(...),
        lang: str = Form("zh"),
        writer: str | None = Form(None),
        judge_p: str | None = Form(None, alias="judge"),
        allow_self_judge: bool = Form(False),
    ) -> JSONResponse:
        if not text.strip():
            raise HTTPException(status_code=400, detail="text is empty")
        if judge_p is None:
            err = _ensure_provider()
            if err:
                raise HTTPException(status_code=503, detail=err)

        result = run_judge(
            text,
            lang=lang,
            writer_provider=writer,
            judge_provider=judge_p,
            allow_self_judge=allow_self_judge,
        )
        return JSONResponse(result)

    @app.post("/htmx/judge", response_class=HTMLResponse)
    def htmx_judge(
        request: Request,
        text: str = Form(...),
        lang: str = Form("zh"),
        writer: str | None = Form(None),
        judge_p: str | None = Form(None, alias="judge"),
        allow_self_judge: bool = Form(False),
    ) -> Any:
        if not text.strip():
            return templates.TemplateResponse(
                request, "_error.html", {"message": "请粘贴需要评审的文章内容"}, status_code=400
            )
        if judge_p is None:
            err = _ensure_provider()
            if err:
                return templates.TemplateResponse(
                    request, "_error.html", {"message": err}, status_code=503
                )

        result = run_judge(
            text,
            lang=lang,
            writer_provider=writer or None,
            judge_provider=judge_p,
            allow_self_judge=allow_self_judge,
        )
        return templates.TemplateResponse(
            request,
            "_judge_result.html",
            {"r": result, "report": format_judge_report(result)},
        )

    # ─── Providers ──────────────────────────────────────────────────────

    @app.get("/api/providers")
    def api_providers() -> JSONResponse:
        return JSONResponse(_provider_state())

    return app


# Module-level app for `uvicorn humanize_zh.web.app:app`
app = create_app()
