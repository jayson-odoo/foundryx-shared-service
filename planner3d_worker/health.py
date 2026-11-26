"""Host health gate: refuse to start a job when the machine is already under pressure."""

from __future__ import annotations

import re
import subprocess

import psutil

_SWAP_RE = re.compile(r"(total|used)\s*=\s*([0-9.]+)M")


def parse_swapusage(text: str) -> tuple[float, float]:
    found = {k: float(v) for k, v in _SWAP_RE.findall(text)}
    return found.get("used", 0.0), found.get("total", 0.0)


def swap_used_pct() -> float:
    try:
        out = subprocess.run(
            ["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True, timeout=5, check=True
        ).stdout
        used, total = parse_swapusage(out)
    except (OSError, subprocess.SubprocessError):
        swap = psutil.swap_memory()
        return float(swap.percent)
    return (used / total * 100.0) if total > 0 else 0.0


def free_ram_mb() -> float:
    return psutil.virtual_memory().available / (1024 * 1024)


def can_start(
    swap_used_pct: float,
    free_ram_mb: float,
    max_swap_pct: float = 80,
    min_free_mb: float = 2048,
) -> tuple[bool, str]:
    if swap_used_pct > max_swap_pct:
        return False, f"swap_high: {swap_used_pct:.0f}% used (max {max_swap_pct:.0f}%)"
    if free_ram_mb < min_free_mb:
        return False, f"ram_low: {free_ram_mb:.0f} MB free (min {min_free_mb:.0f} MB)"
    return True, ""
