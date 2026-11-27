"""Spend ledger (plan D8): one JSON line per API call; the engine sums it before every call."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_PATH = Path.home() / "planner3d" / "claude-ledger.jsonl"


def cost_usd(usage: dict, prices: dict) -> float:
    """``prices`` are US$ per million tokens; cache creation is billed as input."""
    inp = (usage.get("input_tokens") or 0) + (usage.get("cache_creation_input_tokens") or 0)
    out = usage.get("output_tokens") or 0
    cached = usage.get("cache_read_input_tokens") or 0
    return (inp * prices["input"] + out * prices["output"] + cached * prices["cacheRead"]) / 1_000_000


class Ledger:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else DEFAULT_PATH

    def total_usd(self) -> float:
        if not self.path.exists():
            return 0.0
        total = 0.0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                total += float(json.loads(line).get("usd") or 0.0)
            except (ValueError, AttributeError):
                continue
        return total

    def append(self, entry: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
