"""Model routing by category DATA (plan D4): a JSON operator file maps a category
code to a profile; unknown or missing category = the default profile. No product
words in code."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

MIN_VERSIONS, MAX_VERSIONS = 2, 3
DEFAULT_PATH = Path(__file__).with_name("routing.default.json")


def default_path() -> Path:
    """The operator file: ``PLANNER3D_CLAUDE_ROUTING``, else ``~/planner3d/claude-routing.json`` when it
    exists, else the shipped default."""
    env = os.environ.get("PLANNER3D_CLAUDE_ROUTING")
    if env:
        return Path(env)
    home_file = Path.home() / "planner3d" / "claude-routing.json"
    return home_file if home_file.exists() else DEFAULT_PATH


@dataclass(frozen=True)
class Profile:
    model: str
    approach: str  # "primitives" | "sdf"
    max_versions: int
    effort: str


def _profile(raw: dict) -> Profile:
    approach = raw.get("approach", "primitives")
    if approach not in ("primitives", "sdf"):
        raise ValueError(f"unknown approach: {approach}")
    versions = max(MIN_VERSIONS, min(MAX_VERSIONS, int(raw.get("maxVersions", MIN_VERSIONS))))
    return Profile(model=str(raw["model"]), approach=approach, max_versions=versions, effort=str(raw.get("effort", "medium")))


class Routing:
    def __init__(self, spend_cap_usd: float, prices: dict, default: Profile, categories: dict[str, Profile]):
        self.spend_cap_usd = float(spend_cap_usd)
        self._prices = prices
        self._default = default
        self._categories = categories

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Routing":
        raw = json.loads(Path(path or default_path()).read_text(encoding="utf-8"))
        return cls(
            spend_cap_usd=raw["spendCapUsd"],
            prices=raw["prices"],
            default=_profile(raw["default"]),
            categories={code: _profile(p) for code, p in (raw.get("categories") or {}).items()},
        )

    def profile_for(self, category: Optional[dict]) -> Profile:
        code = (category or {}).get("code")
        return self._categories.get(code, self._default) if code else self._default

    def prices(self, model: str) -> dict:
        return self._prices[model]
