"""humanize_zh.web — FastAPI + Jinja2 + HTMX + Tailwind UI

Run with::

    humanize-zh ui                     # CLI subcommand (recommended)
    python -m humanize_zh.web          # equivalent
    uvicorn humanize_zh.web.app:app    # production via uvicorn directly
"""
from .app import create_app

__all__ = ["create_app"]
