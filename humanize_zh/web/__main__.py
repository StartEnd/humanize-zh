"""Allow ``python -m humanize_zh.web`` to launch a dev server."""
from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m humanize_zh.web",
        description="Run the humanize-zh web UI (FastAPI + Jinja2 + HTMX).",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reload", action="store_true", help="auto-reload on code change (dev only)")
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        print(
            "error: 'uvicorn' is required. Install with: pip install 'humanize-zh[ui]'",
            file=sys.stderr,
        )
        return 2

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"humanize-zh UI: http://{args.host}:{args.port}/")
    uvicorn.run(
        "humanize_zh.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
