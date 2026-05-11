"""Worker script: print JSON scores for a single file using the humanize package
available on sys.path. Used by test_regression_templeluck.py in subprocess mode
to avoid sys.modules collisions between humanize vs humanize_zh.

Usage: python _regression_score.py <package_name> <article_path>
  package_name: "humanize" (site-digester) or "humanize_zh"
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print(json.dumps({"_error": "usage: worker <pkg> <path>"}))
        return 2

    pkg_name = sys.argv[1]
    article_path = Path(sys.argv[2])
    if not article_path.exists():
        print(json.dumps({"_error": f"file not found: {article_path}"}))
        return 2

    try:
        pkg = importlib.import_module(pkg_name)
    except ImportError as e:
        print(json.dumps({"_error": f"cannot import {pkg_name}: {e}"}))
        return 3

    # postprocess is a submodule, import explicitly
    postprocess_mod = importlib.import_module(f"{pkg_name}.postprocess")

    text = article_path.read_text(encoding="utf-8")

    rule = pkg.score(text)
    ngram = pkg.ngram_score(text)
    combined = pkg.combined_score(text)

    cleanup_out = postprocess_mod._deterministic_cleanup(text)
    strip_out = postprocess_mod._strip_number_backticks(text)

    payload = {
        "pkg": pkg_name,
        "chars": len(text),
        "rule": {
            "total": rule.total,
            "level": rule.level,
            "violations": [
                {"category": v.category, "rule": v.rule, "count": v.count}
                for v in rule.violations
            ],
        },
        "ngram": {
            "ai_probability": ngram.ai_probability,
            "level": ngram.level,
            "available": ngram.available,
        },
        "combined": {
            "probability": combined.combined_probability,
            "level": combined.combined_level,
        },
        # sha256 是 deterministic (与 Python 启动的 PYTHONHASHSEED 无关)
        "cleanup_len": len(cleanup_out),
        "cleanup_sha256": hashlib.sha256(cleanup_out.encode("utf-8")).hexdigest(),
        "strip_len": len(strip_out),
        "strip_sha256": hashlib.sha256(strip_out.encode("utf-8")).hexdigest(),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
