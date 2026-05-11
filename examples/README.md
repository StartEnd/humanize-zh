# Examples

Standalone scripts that exercise the four main entry points of `humanize-zh`.
Run from the repo root with `uv run python examples/<file>.py`.

| File                                  | What it shows                          | LLM key needed?                     |
|---------------------------------------|----------------------------------------|-------------------------------------|
| `01_detect_only.py`                   | three-layer scoring, no LLM            | no                                  |
| `02_polish_with_llm.py`               | LLM polish + before/after scores       | one of OPENAI / DEEPSEEK / ...      |
| `03_iterative_loop.py`                | writer ↔ judge multi-round loop        | two distinct providers              |
| `04_inject_rules_into_prompt.py`      | splice rules into your own prompt      | no (pure string assembly)           |

Each script is self-contained and ~50 lines — copy-paste them as a starting
point for your own integration. The scoring layers (`01`, `04`) work
offline; only the polish + iterative paths actually call out to an LLM.
