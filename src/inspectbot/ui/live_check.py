"""What Live mode needs before it can start, in plain words for the app to show."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

# The packages Live mode imports first; they come with the `agents` extra.
LIVE_PACKAGES = ("crewai", "crewai_files", "langchain_chroma", "anthropic")


def _key_in_env_file(env_file: Path) -> bool:
    if not env_file.exists():
        return False
    for line in env_file.read_text(errors="ignore").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "ANTHROPIC_API_KEY" and value.strip().strip('"').strip("'"):
            return True
    return False


def live_problems(root: Path, find_spec=importlib.util.find_spec, environ=os.environ) -> list[str]:
    """Return one sentence per missing requirement; an empty list means Live mode can start."""
    problems = []
    if not (3, 11) <= sys.version_info[:2] <= (3, 13):
        problems.append(f"Python {sys.version_info.major}.{sys.version_info.minor} is running, but CrewAI needs "
                        "Python 3.11–3.13. Recreate the virtual environment with `python3.13`.")
    missing = [p for p in LIVE_PACKAGES if find_spec(p) is None]
    if missing:
        problems.append("The agent packages aren't installed (" + ", ".join(missing) + "). "
                        'Run `pip install -e ".[dev,agents,ui]"`')
    if not environ.get("ANTHROPIC_API_KEY") and not _key_in_env_file(root / ".env"):
        problems.append("No `ANTHROPIC_API_KEY` found. Run `cp .env.example .env`, then add your key to `.env`.")
    return problems
