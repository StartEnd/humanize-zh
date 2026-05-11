"""Phase 4: CLI end-to-end via subprocess."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PYTHON = sys.executable


def run_cli(argv: list[str], *, repo_root: Path, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke ``python -m humanize_zh.cli`` and capture result.

    All LLM env vars are stripped by default so tests can't accidentally call
    a real service. Pass ``env_overrides`` to re-enable specific ones.
    """
    base_env = {**os.environ}
    for k in [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY",
        "OPENROUTER_API_KEY", "MOONSHOT_API_KEY", "GLM_API_KEY", "DASHSCOPE_API_KEY",
        "OLLAMA_BASE_URL",
    ]:
        base_env.pop(k, None)
    # Disable .env auto-load so tests are deterministic regardless of cwd state.
    base_env["HUMANIZE_ZH_NO_DOTENV"] = "1"
    if env_overrides:
        base_env.update(env_overrides)
    return subprocess.run(
        [PYTHON, "-m", "humanize_zh.cli", *argv],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=base_env,
        timeout=30,
    )


def test_version(repo_root) -> None:
    r = run_cli(["--version"], repo_root=repo_root)
    assert r.returncode == 0
    assert "humanize-zh" in r.stdout


def test_help_lists_subcommands(repo_root) -> None:
    r = run_cli(["--help"], repo_root=repo_root)
    assert r.returncode == 0
    for sub in ["detect", "polish", "judge", "providers"]:
        assert sub in r.stdout


def test_missing_subcommand_exits_2(repo_root) -> None:
    r = run_cli([], repo_root=repo_root)
    assert r.returncode == 2


def test_providers_no_env(repo_root) -> None:
    r = run_cli(["providers"], repo_root=repo_root)
    assert r.returncode == 0
    assert "(not set)" in r.stdout
    assert "openai" in r.stdout and "anthropic" in r.stdout


def test_providers_detects_fake_deepseek(repo_root) -> None:
    r = run_cli(["providers"], repo_root=repo_root, env_overrides={"DEEPSEEK_API_KEY": "sk-fake"})
    assert r.returncode == 0
    assert "deepseek" in r.stdout
    assert "available" in r.stdout


def test_detect_text_output(repo_root, tmp_path, ai_article_zh) -> None:
    tmp = tmp_path / "a.md"
    tmp.write_text(ai_article_zh, encoding="utf-8")
    r = run_cli(["detect", str(tmp)], repo_root=repo_root)
    assert r.returncode == 0, r.stderr
    assert "rule:" in r.stdout
    assert "ngram:" in r.stdout
    assert "combined:" in r.stdout


def test_detect_json_output(repo_root, tmp_path, ai_article_zh) -> None:
    tmp = tmp_path / "a.md"
    tmp.write_text(ai_article_zh, encoding="utf-8")
    r = run_cli(["detect", str(tmp), "--json"], repo_root=repo_root)
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert payload["rule"]["probability"] > 0
    assert payload["combined"]["probability"] > 0
    assert isinstance(payload["rule"]["violations"], list)


def test_detect_missing_file(repo_root) -> None:
    r = run_cli(["detect", "/nonexistent.md"], repo_root=repo_root)
    assert r.returncode == 2
    assert "file not found" in r.stderr


def test_polish_without_provider_fails(repo_root, tmp_path, ai_article_zh) -> None:
    tmp = tmp_path / "a.md"
    tmp.write_text(ai_article_zh, encoding="utf-8")
    r = run_cli(["polish", str(tmp)], repo_root=repo_root)
    assert r.returncode == 1
    assert "no LLM provider" in r.stderr


def test_judge_without_provider_fails(repo_root, tmp_path, ai_article_zh) -> None:
    tmp = tmp_path / "a.md"
    tmp.write_text(ai_article_zh, encoding="utf-8")
    r = run_cli(["judge", str(tmp)], repo_root=repo_root)
    assert r.returncode == 1
    assert "no LLM provider" in r.stderr


def test_detect_lang_en_early_return(repo_root, tmp_path, ai_article_en) -> None:
    tmp = tmp_path / "a.md"
    tmp.write_text(ai_article_en, encoding="utf-8")
    r = run_cli(["detect", str(tmp), "--lang", "en"], repo_root=repo_root)
    assert r.returncode == 0
    assert "lang=en" in r.stdout


def test_unknown_subcommand_exits_2(repo_root) -> None:
    r = run_cli(["nonsense"], repo_root=repo_root)
    assert r.returncode == 2


# ─── In-process tests (improve coverage of humanize_zh.cli.main) ─────────────


def test_in_process_parser_builds() -> None:
    from humanize_zh.cli.main import build_parser
    parser = build_parser()
    args = parser.parse_args(["detect", "foo.md", "--json"])
    assert args.command == "detect"
    assert args.file == "foo.md"
    assert args.json is True


def test_in_process_detect_command(tmp_path, ai_article_zh, capsys) -> None:
    from humanize_zh.cli.main import main
    tmp = tmp_path / "a.md"
    tmp.write_text(ai_article_zh, encoding="utf-8")
    code = main(["detect", str(tmp), "--json"])
    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["rule"]["probability"] > 0


def test_in_process_providers_command(capsys) -> None:
    from humanize_zh.cli.main import main
    code = main(["providers"])
    assert code == 0
    out = capsys.readouterr().out
    assert "openai" in out and "deepseek" in out


def test_in_process_polish_uses_active_llm(tmp_path, ai_article_zh, fake_polish_fn, capsys) -> None:
    from humanize_zh import llm
    from humanize_zh.cli.main import main
    tmp = tmp_path / "a.md"
    tmp.write_text(ai_article_zh, encoding="utf-8")
    llm.use_callable(fake_polish_fn, name="in-proc", model="v1")
    code = main(["polish", str(tmp), "-o", str(tmp_path / "out.md")])
    assert code == 0
    assert (tmp_path / "out.md").exists()


def test_in_process_judge_uses_active_llm(tmp_path, ai_article_zh, fake_judge_fn, capsys) -> None:
    from humanize_zh import llm
    from humanize_zh.cli.main import main
    tmp = tmp_path / "a.md"
    tmp.write_text(ai_article_zh, encoding="utf-8")
    llm.use_callable(fake_judge_fn, name="in-proc-j", model="v1")
    code = main(["judge", str(tmp), "-o", str(tmp_path / "judge.md")])
    assert code == 0
    assert (tmp_path / "judge.md").exists()
