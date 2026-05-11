# Security Policy

## Supported versions

`humanize-zh` is in **alpha** (`0.1.0a1`). Only the latest release on `main`
receives security fixes. Pinning a pre-1.0 version means accepting that the
API may shift without deprecation cycles.

## Reporting a vulnerability

Please email the maintainer (see `pyproject.toml::authors`) — **do not**
open a public GitHub issue.

Include:

- Affected version (`humanize-zh --version`)
- Reproduction steps
- Impact assessment (data exposure / RCE / DoS / etc.)

Initial response within 7 days; coordinated disclosure timeline agreed
per-case.

## Threat model

`humanize-zh` is primarily a **library + CLI**. The deployment surface is
limited:

1. **`humanize-zh` SDK / CLI** — runs locally; no listening sockets.
   Trust boundary is the local user.
2. **`humanize-zh ui` (FastAPI + HTMX)** — opt-in Web UI. By default
   binds to `0.0.0.0:8080` with **no authentication and no rate limit**.
   It is not safe to expose on the public internet without a reverse
   proxy that adds auth + abuse controls.

## What we do

- **No API keys hit disk** unless the user puts them in `.env` /
  `~/.humanize-zh.env`. The CLI loads these for convenience; the SDK does
  not. Both files should be `chmod 600` (verify yourself — the project
  does not enforce this).
- **No API keys in logs**: provider implementations never log credentials
  or full request bodies, only error messages from the upstream SDK.
- **HTML auto-escape**: the Web UI uses Jinja2 with default autoescape
  on `.html` templates. User-submitted article text renders inside
  `{{ text }}` blocks and is escaped before injection.
- **Test isolation**: `tests/conftest.py` runs `HUMANIZE_ZH_NO_DOTENV=1`
  to prevent accidental .env loading during local test runs.

## What we don't do (yet)

- **No auth on the Web UI**. If you deploy it, put nginx + basic auth or
  an OAuth proxy in front. Tracking issue in `CHANGELOG.md::[Unreleased]`.
- **No rate limiting on the Web UI**. Every request can trigger an LLM
  call that costs money. Self-hosted or behind a private network only.
- **No CSP / HSTS headers**. The UI is for local dev / private deploys.
- **No supply-chain pinning** beyond `uv.lock`. Run `uv lock` and review
  the diff if you depend on full deterministic builds.

## Dependencies

We use `uv` for dependency resolution. Lockfile lives at `uv.lock`. If a
transitive dependency CVE affects us, we'll bump the constraint in
`pyproject.toml` and refresh the lockfile in the same release.
