"""Phase 7 regression: humanize-zh vs site-digester/humanize on real articles.

核心门控: detect / ngram / combined 三层评分 + deterministic cleanup 输出必须与
原 humanize 模块 **完全一致**, 否则说明 Phase 1-3 的重构破坏了检测能力.

用 subprocess 隔离两套包: 避免 humanize / humanize_zh 共用 sys.modules 冲突
(ngram_check.py 里的 sys.path.insert + _ngram_engine 动态加载会串).

Skipped automatically when site-digester checkout is not available.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
HUMANIZE_ZH_ROOT = HERE.parent.parent
SITE_DIGESTER_ROOT = HUMANIZE_ZH_ROOT.parent / "site-digester"

WORKER = HERE.parent / "_regression_score.py"

# 3 个真实站点 × (raw, polished) = 6 个 case
CASES: list[tuple[str, Path]] = [
    ("templeluck-raw",      SITE_DIGESTER_ROOT / "output/sites/templeluck.com/article.v09.md"),
    ("templeluck-polished", SITE_DIGESTER_ROOT / "output/sites/templeluck.com/article.v09.polished.md"),
    ("rpedia-raw",          SITE_DIGESTER_ROOT / "output/sites/rpedia.me/article.v09.md"),
    ("rpedia-polished",     SITE_DIGESTER_ROOT / "output/sites/rpedia.me/article.v09.polished.md"),
    ("yourais-raw",         SITE_DIGESTER_ROOT / "output/sites/youraislopbores.me/article.v09.md"),
    ("yourais-polished",    SITE_DIGESTER_ROOT / "output/sites/youraislopbores.me/article.v09.polished.md"),
]

_SITE_DIGESTER_AVAILABLE = (SITE_DIGESTER_ROOT / "humanize" / "__init__.py").exists()

pytestmark = pytest.mark.skipif(
    not _SITE_DIGESTER_AVAILABLE,
    reason="site-digester repository not checked out alongside humanize-zh",
)


def _run_worker(pkg_name: str, cwd: Path, article_path: Path) -> dict:
    """Run worker script in a fresh Python process, pkg_name resolved from cwd.

    PYTHONPATH=cwd so that ``humanize`` (from site-digester) or ``humanize_zh``
    resolves from the expected repo root regardless of the current venv.
    """
    env = {**os.environ, "PYTHONPATH": str(cwd)}
    r = subprocess.run(
        [sys.executable, str(WORKER), pkg_name, str(article_path)],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"worker failed for {pkg_name} at {cwd}:\n"
            f"  exit: {r.returncode}\n"
            f"  stderr: {r.stderr}\n"
            f"  stdout: {r.stdout}"
        )
    return json.loads(r.stdout.strip().splitlines()[-1])


def _cmp_scores(label: str, article_path: Path) -> dict:
    sd = _run_worker("humanize", SITE_DIGESTER_ROOT, article_path)
    hz = _run_worker("humanize_zh", HUMANIZE_ZH_ROOT, article_path)

    rule_match = (
        abs(sd["rule"]["total"] - hz["rule"]["total"]) < 0.01
        and sd["rule"]["level"] == hz["rule"]["level"]
    )
    ngram_match = abs(sd["ngram"]["ai_probability"] - hz["ngram"]["ai_probability"]) < 0.01
    combined_match = abs(sd["combined"]["probability"] - hz["combined"]["probability"]) < 0.01

    sd_viols = sd["rule"]["violations"]
    hz_viols = hz["rule"]["violations"]
    violations_match = (
        len(sd_viols) == len(hz_viols)
        and all(a == b for a, b in zip(sd_viols, hz_viols, strict=True))
    )

    # cleanup / strip: compare length + sha256 (deterministic across processes)
    cleanup_match = (
        sd["cleanup_len"] == hz["cleanup_len"]
        and sd["cleanup_sha256"] == hz["cleanup_sha256"]
    )
    strip_match = (
        sd["strip_len"] == hz["strip_len"]
        and sd["strip_sha256"] == hz["strip_sha256"]
    )

    return {
        "label": label,
        "chars": sd["chars"],
        "rule": {"sd": sd["rule"]["total"], "hz": hz["rule"]["total"], "match": rule_match},
        "ngram": {
            "sd": sd["ngram"]["ai_probability"],
            "hz": hz["ngram"]["ai_probability"],
            "sd_avail": sd["ngram"]["available"],
            "hz_avail": hz["ngram"]["available"],
            "match": ngram_match,
        },
        "combined": {
            "sd": sd["combined"]["probability"],
            "hz": hz["combined"]["probability"],
            "match": combined_match,
        },
        "violations_match": violations_match,
        "viol_count_sd": len(sd_viols),
        "viol_count_hz": len(hz_viols),
        "cleanup_match": cleanup_match,
        "strip_match": strip_match,
    }


@pytest.mark.parametrize("label,path", CASES)
def test_regression_vs_site_digester(label: str, path: Path) -> None:
    """Each (site × version) article must score identically across both packages."""
    if not path.exists():
        pytest.skip(f"{label}: article not found at {path}")

    r = _cmp_scores(label, path)

    assert r["rule"]["match"], (
        f"[{label}] rule score diverges: sd={r['rule']['sd']} vs hz={r['rule']['hz']}"
    )
    assert r["ngram"]["match"], (
        f"[{label}] ngram score diverges: sd={r['ngram']['sd']} vs hz={r['ngram']['hz']}"
    )
    assert r["combined"]["match"], (
        f"[{label}] combined score diverges: sd={r['combined']['sd']} vs hz={r['combined']['hz']}"
    )
    assert r["violations_match"], (
        f"[{label}] violations list diverges "
        f"(sd={r['viol_count_sd']} vs hz={r['viol_count_hz']})"
    )
    assert r["cleanup_match"], f"[{label}] _deterministic_cleanup output diverges"
    assert r["strip_match"], f"[{label}] _strip_number_backticks output diverges"


def test_worker_script_exists() -> None:
    assert WORKER.exists(), f"regression worker script missing: {WORKER}"
