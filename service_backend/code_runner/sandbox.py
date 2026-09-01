"""Run one job in a fresh, resource-limited child process.

This is the security boundary of the runner: the child gets an EMPTY
environment, ``/`` as its working directory, hard ``resource`` limits, an
isolated interpreter (``-I -S -B``: no site, no user site, no env vars, no
cwd on sys.path, no bytecode writes) and a wall-clock kill. The parent never
executes builder code itself.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from code_runner import RUNNER_VERSION

_HARNESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.py")


@dataclass
class Limits:
    wall_seconds: float = 5.0
    cpu_seconds: int = 3
    memory_bytes: int = 128 * 1024 * 1024
    max_processes: int = 1
    max_open_files: int = 8
    source_bytes: int = 32 * 1024
    input_bytes: int = 256 * 1024
    output_bytes: int = 64 * 1024
    console_bytes: int = 4096

    @classmethod
    def from_env(cls, env: Optional[Dict[str, str]] = None) -> "Limits":
        env = os.environ if env is None else env

        def _get(name: str, default: Any, cast):
            raw = env.get(name)
            if raw is None or raw == "":
                return default
            try:
                return cast(raw)
            except (TypeError, ValueError):
                return default

        return cls(
            wall_seconds=_get("CODE_RUNNER_WALL_SECONDS", 5.0, float),
            cpu_seconds=_get("CODE_RUNNER_CPU_SECONDS", 3, int),
            memory_bytes=_get("CODE_RUNNER_MEMORY_BYTES", 128 * 1024 * 1024, int),
            max_processes=_get("CODE_RUNNER_MAX_PROCESSES", 1, int),
            max_open_files=_get("CODE_RUNNER_MAX_OPEN_FILES", 8, int),
            source_bytes=_get("CODE_RUNNER_SOURCE_BYTES", 32 * 1024, int),
            input_bytes=_get("CODE_RUNNER_INPUT_BYTES", 256 * 1024, int),
            output_bytes=_get("CODE_RUNNER_OUTPUT_BYTES", 64 * 1024, int),
            console_bytes=_get("CODE_RUNNER_CONSOLE_BYTES", 4096, int),
        )


@dataclass
class RunResult:
    ok: bool
    termination: str
    result: Optional[Dict[str, Any]] = None
    error: str = ""
    stdout: str = ""
    stderr: str = ""
    console_truncated: bool = False
    duration_ms: int = 0
    runner_version: str = RUNNER_VERSION
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "termination": self.termination,
            "result": self.result,
            "error": self.error,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "consoleTruncated": self.console_truncated,
            "durationMs": self.duration_ms,
            "runnerVersion": self.runner_version,
        }


def _apply_limits(limits: Limits):
    """preexec_fn: runs in the child between fork and exec."""
    import resource

    def _set(kind, value):
        try:
            resource.setrlimit(kind, (value, value))
        except (ValueError, OSError):
            pass

    _set(resource.RLIMIT_CPU, limits.cpu_seconds)
    _set(resource.RLIMIT_FSIZE, 0)  # no file writes at all
    _set(resource.RLIMIT_NOFILE, limits.max_open_files)
    if hasattr(resource, "RLIMIT_NPROC"):
        _set(resource.RLIMIT_NPROC, limits.max_processes)
    if sys.platform != "darwin":
        # RLIMIT_AS is unreliable on macOS (interpreter start fails); Linux
        # (the deployed runner) enforces it. macOS dev relies on the CPU/wall
        # limits and the Docker memory cap in compose.
        _set(resource.RLIMIT_AS, limits.memory_bytes)
    try:
        os.nice(10)
    except OSError:
        pass


def execute(source: str, inputs: Dict[str, Any], limits: Optional[Limits] = None) -> RunResult:
    limits = limits or Limits()
    if not isinstance(source, str):
        return RunResult(False, "policy", error="Code must be text.")
    if len(source.encode("utf-8")) > limits.source_bytes:
        return RunResult(False, "source_limit", error="Code exceeds the source size limit.")
    try:
        job = json.dumps(
            {
                "source": source,
                "input": inputs,
                "consoleLimit": limits.console_bytes,
                "outputLimit": limits.output_bytes,
            }
        )
    except (TypeError, ValueError):
        return RunResult(False, "input_invalid", error="Inputs must be JSON-compatible.")
    if len(job.encode("utf-8")) > limits.input_bytes + limits.source_bytes + 256:
        return RunResult(False, "input_limit", error="Inputs exceed the size limit.")

    started = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-B", _HARNESS],
            input=job.encode("utf-8"),
            capture_output=True,
            timeout=limits.wall_seconds,
            env={},
            cwd="/",
            preexec_fn=lambda: _apply_limits(limits),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            False,
            "timeout",
            error=f"Code exceeded the {limits.wall_seconds:g}s time limit.",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except OSError as exc:
        return RunResult(False, "runner_error", error=f"Runner could not start the sandbox: {exc}")
    duration_ms = int((time.monotonic() - started) * 1000)

    if proc.returncode != 0:
        if proc.returncode < 0 or proc.returncode in (137, 152, 158):
            # Killed by a signal (SIGKILL from RLIMIT_AS/OOM, SIGXCPU from RLIMIT_CPU).
            return RunResult(False, "resource_limit", error="Code exceeded a CPU or memory limit.", duration_ms=duration_ms)
        if b"MemoryError" in proc.stderr:
            return RunResult(False, "memory_limit", error="Code exceeded the memory limit.", duration_ms=duration_ms)
        return RunResult(False, "runner_error", error="The sandbox exited unexpectedly.", duration_ms=duration_ms)
    try:
        payload = json.loads(proc.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return RunResult(False, "runner_error", error="The sandbox returned no result.", duration_ms=duration_ms)
    return RunResult(
        ok=bool(payload.get("ok")),
        termination=str(payload.get("termination") or ("completed" if payload.get("ok") else "error")),
        result=payload.get("result") if payload.get("ok") else None,
        error=str(payload.get("error") or ""),
        stdout=str(payload.get("stdout") or ""),
        stderr=str(payload.get("stderr") or ""),
        console_truncated=bool(payload.get("consoleTruncated")),
        duration_ms=duration_ms,
    )
