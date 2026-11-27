"""Sandbox for model-written Python (plan planner3d-claude-procedural-engine, D6).

Defence in depth, outermost last:

1. ``check_script``: an AST allowlist. NOT a security boundary, only catches the
   obvious before anything runs.
2. The child is ``python -I gen.py`` with an EMPTY environment (so the API key can
   never reach it), cwd = the work dir, its own session/process group.
3. ``resource.setrlimit`` in the child: CPU seconds, file size, open files, processes, no core.
4. A macOS ``sandbox-exec`` deny-default profile (the real boundary): no network,
   file writes only in the work dir, file reads only the Python install, system
   libraries and the work dir, no fork.
5. A parent monitor: wall clock and RSS polling; the whole process group is killed on breach.

Non-darwin or no ``/usr/bin/sandbox-exec``: ``run_script`` raises ``SandboxUnavailable``
(fail closed, the engine refuses to run model code).
"""

from __future__ import annotations

import ast
import json
import os
import resource
import signal
import subprocess
import sys
import sysconfig
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import psutil

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
POLL_S = 0.1
ALLOWED_IMPORTS = {"numpy", "math", "trimesh", "manifold3d", "scipy", "json", "itertools", "functools", "collections"}
BANNED_NAMES = {"eval", "exec", "compile", "__import__", "globals", "locals", "vars", "breakpoint", "input", "delattr", "setattr"}
ALLOWED_OPEN_FILES = {"params.json", "model.glb"}


class ScriptRejected(Exception):
    pass


class SandboxUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Limits:
    cpu_s: int = 240
    wall_s: int = 300
    mem_mb: int = 3072
    file_mb: int = 200


@dataclass
class RunResult:
    ok: bool
    glb: Optional[Path]
    stderr_tail: str
    seconds: float
    reason: Optional[str]  # timeout | cpu | memory | exit | no_output


# ── 1. AST pre-check ────────────────────────────────────────────────────────


def _reject(node: ast.AST, why: str) -> None:
    raise ScriptRejected(f"line {getattr(node, 'lineno', '?')}: {why}")


def _is_str_const(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def check_script(src: str) -> None:
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        raise ScriptRejected(f"syntax error: {exc.msg} (line {exc.lineno})") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    _reject(node, f"import of '{alias.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.level or root not in ALLOWED_IMPORTS:
                _reject(node, f"import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                _reject(node, f"attribute '{node.attr}' is not allowed")
        elif isinstance(node, ast.Name):
            if node.id in BANNED_NAMES or node.id.startswith("__"):
                _reject(node, f"name '{node.id}' is not allowed")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "getattr" and any(_is_str_const(a) and a.value.startswith("__") for a in node.args):
                _reject(node, "getattr on a dunder name is not allowed")
            if node.func.id == "open":
                first = node.args[0] if node.args else None
                if not (_is_str_const(first) and first.value in ALLOWED_OPEN_FILES):
                    _reject(node, "open() is only allowed for params.json and model.glb")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("__") and node.value.endswith("__"):
            _reject(node, "dunder strings are not allowed")
    # a bare reference to open (e.g. passed around) is rejected too
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "open":
            parent_ok = False
            for p in ast.walk(tree):
                if isinstance(p, ast.Call) and p.func is node:
                    parent_ok = True
                    break
            if not parent_ok:
                _reject(node, "open may only be called directly")


# ── availability ────────────────────────────────────────────────────────────


def available() -> bool:
    return sys.platform == "darwin" and os.path.exists(SANDBOX_EXEC)


# ── 4. sandbox profile ──────────────────────────────────────────────────────

# Every allow line, and why. Anything not listed is denied (deny default), so
# there is no network, no keychain, no mach service and no fork.
PROFILE = """\
(version 1)
(deny default)
; exec the interpreter (the venv symlink) and the framework binary it re-execs inside the base install. No process-fork: a fork bomb cannot start.
(allow process-exec (literal (param "PYEXE")) (subpath (param "PYBASE")))
; path traversal (lstat/stat of parent dirs, realpath) needs metadata only, never contents.
(allow file-read-metadata)
; the interpreter, its stdlib, site-packages (numpy/trimesh/manifold3d/scipy) and dylibs it links.
(allow file-read* (subpath (param "PYPREFIX")) (subpath (param "PYBASE")) (subpath (param "VENV")))
; system frameworks and libs every Mach-O binary needs (dyld shared cache, libSystem, Accelerate for numpy).
(allow file-read* (subpath "/System") (subpath "/usr/lib") (subpath "/usr/share") (subpath "/private/var/db/dyld") (subpath "/Library/Apple"))
; the filesystem root directory itself (getcwd/realpath open "/"; its entries stay unreadable below it).
(allow file-read-data (literal "/"))
; random + null devices (hash seeds, numpy RNG, os.devnull).
(allow file-read* (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))
(allow file-write* (literal "/dev/null"))
; the only writable place: the per-job work dir (gen.py, params.json, model.glb, scratch).
(allow file-read* file-write* (subpath (param "WORK")))
; CPython and numpy read cpu/hw facts at import.
(allow sysctl-read)
; a process may signal itself (threads, faulthandler).
(allow signal (target self))
"""


def _real(p: str | Path) -> str:
    return os.path.realpath(str(p))


def _profile_params(work: Path) -> list[str]:
    exe = sys.executable
    prefix = _real(sys.prefix)
    base = _real(sys.base_prefix)
    venv = prefix
    params = {
        "PYEXE": exe,
        "PYREAL": _real(exe),
        "PYPREFIX": prefix,
        "PYBASE": base,
        "VENV": venv,
        "WORK": _real(work),
    }
    out: list[str] = []
    for k, v in params.items():
        out += ["-D", f"{k}={v}"]
    return out


# CPython itself injects LC_CTYPE (locale coercion) into an empty environment at start-up;
# clear it so the script sees a truly empty os.environ, then run gen.py as __main__.
BOOTSTRAP = "import os, runpy; os.environ.clear(); runpy.run_path('gen.py', run_name='__main__')"


# ── 3. rlimits (run in the child between fork and exec) ─────────────────────


def _child_limits(limits: Limits):
    def apply() -> None:
        mb = 1024 * 1024
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_s, limits.cpu_s + 5))
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.file_mb * mb, limits.file_mb * mb))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (8, 8))
        except (ValueError, OSError):
            pass

    return apply


# ── 2/5. run + monitor ──────────────────────────────────────────────────────


def _group_rss_mb(pid: int) -> float:
    try:
        root = psutil.Process(pid)
        procs = [root, *root.children(recursive=True)]
    except psutil.Error:
        return 0.0
    total = 0
    for p in procs:
        try:
            total += p.memory_info().rss
        except psutil.Error:
            continue
    return total / (1024 * 1024)


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        pass


def run_script(src: str, work_dir: Path, limits: Limits, check: bool = True) -> RunResult:
    if not available():
        raise SandboxUnavailable("the macOS sandbox is not available; model code is never run unsandboxed")
    if check:
        check_script(src)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    (work / "gen.py").write_text(src, encoding="utf-8")
    (work / "params.json").write_text(json.dumps(_read_params(work)), encoding="utf-8")
    glb = work / "model.glb"
    glb.unlink(missing_ok=True)

    cmd = [SANDBOX_EXEC, *_profile_params(work), "-p", PROFILE, sys.executable, "-I", "-c", BOOTSTRAP]
    started = time.monotonic()
    reason: Optional[str] = None
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(
            cmd,
            cwd=str(work),
            env={},  # truly empty: nothing (API key included) leaks into the child
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=err,
            start_new_session=True,
            preexec_fn=_child_limits(limits),
        )
        try:
            while proc.poll() is None:
                if time.monotonic() - started > limits.wall_s:
                    reason = "timeout"
                elif _group_rss_mb(proc.pid) > limits.mem_mb:
                    reason = "memory"
                if reason:
                    _kill_group(proc)
                    break
                time.sleep(POLL_S)
        finally:
            if proc.poll() is None:
                _kill_group(proc)
        seconds = time.monotonic() - started
        err.seek(0, os.SEEK_END)
        size = err.tell()
        err.seek(max(0, size - 2000))
        tail = err.read().decode("utf-8", "replace")
    # whatever the child left behind must not outlive it
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass

    if reason is None:
        code = proc.returncode
        if code == -signal.SIGXCPU or code == -signal.SIGKILL:
            reason = "cpu"
        elif code != 0:
            reason = "exit"
        elif not glb.exists() or glb.stat().st_size == 0:
            reason = "no_output"
    if reason:
        return RunResult(False, None, tail, seconds, reason)
    return RunResult(True, glb, tail, seconds, None)


def _read_params(work: Path) -> dict:
    """The engine writes ``inputs.json`` beside; here params come from an optional
    ``params.json`` already placed by the caller, else an empty object."""
    existing = work / "params.json"
    if existing.exists():
        try:
            return json.loads(existing.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}
