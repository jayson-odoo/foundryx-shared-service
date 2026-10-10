"""Health check route."""
import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import APIRouter

router = APIRouter()


@lru_cache(maxsize=1)
def _git_sha() -> Optional[str]:
    """The running code's commit: ``GIT_SHA`` if the deploy sets it, else the
    checkout's HEAD (resolved once per process), else None."""
    sha = (os.environ.get("GIT_SHA") or "").strip()
    if sha:
        return sha[:40]
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent,
                             capture_output=True, text=True, timeout=2, check=True)
        return out.stdout.strip()[:40] or None
    except (OSError, subprocess.SubprocessError):
        return None


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "git_sha": _git_sha()}
