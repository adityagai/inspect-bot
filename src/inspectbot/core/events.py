"""Append-only event log per run (runs/<task_id>/events.jsonl).

The Streamlit app tails this file in live mode and replays it in replay mode,
so every tool call, message and decision is written here as one JSON line.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EventLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = sum(1 for _ in self.path.open()) if self.path.exists() else 0

    def emit(self, kind: str, **data: Any) -> dict[str, Any]:
        self._seq += 1
        event = {"seq": self._seq, "ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **data}
        with self.path.open("a") as f:
            f.write(json.dumps(event, default=str) + "\n")
        return event

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
