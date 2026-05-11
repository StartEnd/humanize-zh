.PHONY: help install test test-fast lint fmt typecheck cov dev web build clean providers

PY := .venv/bin/python
UV := uv

help:  ## Show this help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:  ## Sync deps + dev/ui extras via uv.
	$(UV) sync --extra dev --extra ui --extra openai --extra anthropic

test:  ## Run the full test suite with coverage (matches CI).
	HUMANIZE_ZH_NO_DOTENV=1 $(PY) -m pytest --no-header

test-fast:  ## Run tests without coverage (faster local loop).
	HUMANIZE_ZH_NO_DOTENV=1 $(PY) -m pytest --no-header -q --no-cov

lint:  ## ruff check (no auto-fix).
	$(PY) -m ruff check humanize_zh tests

fmt:  ## ruff check --fix + format.
	$(PY) -m ruff check --fix humanize_zh tests
	$(PY) -m ruff format humanize_zh tests

typecheck:  ## mypy on the package (CI-equivalent).
	$(PY) -m mypy humanize_zh

cov:  ## Detailed coverage report by module.
	HUMANIZE_ZH_NO_DOTENV=1 $(PY) -m pytest --no-header --cov-report=term-missing

dev: web  ## Alias: start the Web UI on port 8080 with reload.

web:  ## Run the FastAPI web UI on port 8080 with autoreload.
	$(PY) -m humanize_zh.web --reload --port 8080

providers:  ## Show detected LLM providers from env.
	$(PY) -m humanize_zh providers

build:  ## Build sdist + wheel into dist/.
	$(UV) build

clean:  ## Remove caches and build artifacts.
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache .mypy_cache coverage.xml
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
