"""Append-only events.jsonl writer (AC-S1-6, AC-S1-9)."""
from __future__ import annotations

import json
import time
from pathlib import Path


class Events:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")

    def emit(self, kind: str, **data: object) -> None:
        row = {"ts": round(time.time(), 3), "kind": kind, **data}
        self._fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._fh.flush()
        print(f"[event] {kind} {json.dumps(data, ensure_ascii=False)}", flush=True)

    def close(self) -> None:
        self._fh.close()
