"""humanize_zh.cli — Command-line interface for humanize-zh

Entry point: ``humanize-zh`` (installed via pyproject ``[project.scripts]``).

Subcommands:
    humanize-zh detect    <file>   rule + ngram + combined score
    humanize-zh polish    <file>   LLM 润色 (去 AI 味)
    humanize-zh judge     <file>   LLM 终审
    humanize-zh providers          list auto-detectable providers
"""
from .main import main

__all__ = ["main"]
