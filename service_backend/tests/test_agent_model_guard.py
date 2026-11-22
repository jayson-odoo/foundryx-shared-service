"""Guard: no agent instruction file may pin the retired Fable model.

Owner ruling 21-22 Nov 2026: Fable is retired; review + planner seats run on
Opus 5.5 medium, execution on Sonnet. This scans the agent-instruction surface
(`.claude/` minus handoffs/evidence, `AGENTS.md`, `CLAUDE.md`) for any
`model: fable` / `--model fable` / `claude-fable` pin and fails on a hit.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

FABLE_PIN = re.compile(
    r"""["']?model["']?\s*[:=]\s*["']?fable|--model[= ]fable|claude-fable""",
    re.IGNORECASE,
)

EXCLUDED_DIRS = {"handoffs", "evidence", "worktrees"}


def _instruction_files() -> list[Path]:
    files: list[Path] = []
    claude_dir = REPO_ROOT / ".claude"
    if claude_dir.is_dir():
        for path in claude_dir.rglob("*"):
            rel_parts = path.relative_to(claude_dir).parts
            if any(part in EXCLUDED_DIRS for part in rel_parts):
                continue
            if path.is_file():
                files.append(path)
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = REPO_ROOT / name
        if path.is_file():
            files.append(path)
    return files


def test_pattern_catches_known_pins() -> None:
    for bad in (
        "model: fable",
        'model: "fable"',
        "'model': 'fable'",
        "model=fable",
        "--model fable",
        "--model=fable",
        "claude-fable-5-2",
    ):
        assert FABLE_PIN.search(bad), bad
    for ok in ("model: opus", "model: sonnet", "no Fable, owner 21-22 Nov"):
        assert not FABLE_PIN.search(ok), ok


def test_no_fable_model_pins_in_agent_instructions() -> None:
    files = _instruction_files()
    assert files, "expected agent instruction files to scan"
    hits: list[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if FABLE_PIN.search(line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not hits, "Fable is retired (owner 21-22 Nov 2026); use opus/sonnet:\n" + "\n".join(hits)
