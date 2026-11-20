"""Subprocess driver for the pilot's ``mlx-whisper`` (S3 plan §3.1, R1).

Runs ``mlx_runner.py`` through a DEDICATED python (``settings.
meetings_stt_python``, built by ``scripts/setup_stt_venv.sh``) via
``subprocess.run`` - never an in-process import: mlx needs its own dependency
set (Metal, a pinned mlx-whisper version) and a crash there must never take
the worker process down.

Serialized by a host-level ``flock`` held for the WHOLE subprocess call (R1):
the pilot's 16 GB host shares Metal with live bot containers, so at most one
transcription runs at a time. The lock is a FIXED absolute path
(``settings.meetings_stt_lock_path``), not the OS temp dir - ``TMPDIR``
differs per-user/per-shell, and the flock only serializes anything if every
process opens the SAME file. ``flock`` is per-open-file-description, so two
independent ``open()`` calls (different processes, or different threads each
opening the file themselves) correctly serialize even within one process.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from app.config import settings

from . import SttResult, SttSegment

logger = logging.getLogger("foundryx.meetings")

RUNNER_PATH = Path(__file__).resolve().parent / "mlx_runner.py"
# Module-level (not a function-local constant) so a test can monkeypatch it to
# a tmp-path lock file and run fully isolated from any other test/process.
LOCK_PATH = Path(settings.meetings_stt_lock_path)
STDERR_TAIL_CHARS = 4000


class SttTranscriptionError(Exception):
    """The subprocess failed, timed out, or produced no usable JSON."""


class MlxLocalProvider:
    """The v1 (and, in S3, only built) ``SttProvider`` driver."""

    def transcribe(self, audio_path: Path) -> SttResult:
        python = os.path.expanduser(settings.meetings_stt_python)
        model = settings.meetings_stt_model
        timeout_s = settings.meetings_stt_timeout_s

        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOCK_PATH.touch(exist_ok=True)
        with open(LOCK_PATH, "r+") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                completed = self._run(python, audio_path, model, timeout_s)
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

        return self._parse(completed)

    def _run(
        self, python: str, audio_path: Path, model: str, timeout_s: int
    ) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                [
                    python,
                    str(RUNNER_PATH),
                    str(audio_path),
                    model,
                    str(settings.meetings_stt_chunk_s),
                    settings.meetings_stt_languages,
                ],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise SttTranscriptionError(
                f"mlx transcription timed out after {timeout_s}s"
            ) from exc

    def _parse(self, completed: subprocess.CompletedProcess) -> SttResult:
        if completed.returncode != 0:
            tail = (completed.stderr or "")[-STDERR_TAIL_CHARS:]
            raise SttTranscriptionError(
                f"mlx transcription failed (exit {completed.returncode}): {tail}"
            )

        payload: Optional[dict] = None
        for line in reversed((completed.stdout or "").strip().splitlines()):
            try:
                payload = json.loads(line)
                break
            except ValueError:
                continue
        if payload is None:
            raise SttTranscriptionError(
                f"mlx transcription produced no parseable JSON on stdout: "
                f"{(completed.stdout or '')[:500]!r}"
            )

        segments = [
            SttSegment(
                start_ms=int(seg["start_ms"]),
                end_ms=int(seg["end_ms"]),
                text=str(seg["text"]),
                language=seg.get("language"),  # absent (older runner) -> None
            )
            for seg in payload.get("segments", [])
        ]
        return SttResult(language=payload.get("language"), segments=segments)
