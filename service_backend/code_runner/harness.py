"""Child-process harness: reads ONE job as JSON on stdin, executes it under the
restricted builtins table, writes ONE JSON result line on stdout.

Started by ``sandbox.execute`` as ``python -I -S -B harness.py`` with an empty
environment and resource limits already applied (see ``sandbox``). Nothing in
here trusts the job: the policy runs again before execution, and ``_harden``
then strips the interpreter so that even a policy bypass that reaches the
harness frames (generator ``gi_frame`` -> ``f_back`` -> ``f_builtins``) finds
no importer, no ``open`` and no module namespace to walk (AC-SAR-64).
"""
from __future__ import annotations

import io
import json
import math
import re
import sys
import types
from typing import Any, Dict

# Bound at import time so the post-exec code never needs the module globals
# that ``_harden`` removes.
_MappingProxy = types.MappingProxyType
_json_dumps = json.dumps
_json_loads = json.loads

# Modules a walked-to ``sys`` (or a survivor import) could turn into reach.
_EVICT_MODULES = (
    "os", "posix", "nt", "socket", "_socket", "select", "selectors", "subprocess",
    "ctypes", "_ctypes", "signal", "_signal", "resource", "shutil", "pathlib",
    "tempfile", "io", "_io", "importlib", "_imp", "_frozen_importlib",
    "_frozen_importlib_external", "zipimport", "marshal", "threading", "_thread",
)

# Harness globals that must not survive into the builder's reach.
_STRIP_GLOBALS = ("io", "json", "math", "re", "sys", "types", "Any", "Dict", "_harden", "_safe_builtins")


def _safe_builtins():
    import builtins

    from code_runner.policy import SAFE_BUILTIN_NAMES

    table: Dict[str, Any] = {}
    for name in SAFE_BUILTIN_NAMES:
        if hasattr(builtins, name):
            table[name] = getattr(builtins, name)
    return table


def _denied(*_args, **_kwargs):
    raise RuntimeError("not available in the sandbox")


def _harden() -> None:
    """Runtime denial layer, applied AFTER the policy passed and the job was
    parsed, BEFORE builder code runs. Neuters the REAL builtins (the ones a
    frame walk lands on), evicts platform modules from ``sys.modules`` and
    strips this module's namespace down to inert helpers."""
    import builtins

    for name in ("__import__", "open", "exec", "eval", "compile", "breakpoint", "input", "help", "exit", "quit"):
        setattr(builtins, name, _denied)
    for name in list(sys.modules):
        root = name.split(".", 1)[0]
        if name in _EVICT_MODULES or root in _EVICT_MODULES:
            sys.modules.pop(name, None)
    module_globals = globals()
    for name in _STRIP_GLOBALS:
        module_globals.pop(name, None)


class _ReadOnlyJson:
    """The ``json`` helper: loads/dumps only."""

    loads = staticmethod(json.loads)

    @staticmethod
    def dumps(value, **kwargs):
        kwargs.pop("default", None)
        return _json_dumps(value, **kwargs)


def _read_only_math():
    module = types.SimpleNamespace()
    for name in dir(math):
        if not name.startswith("_"):
            setattr(module, name, getattr(math, name))
    return module


def _read_only_re():
    module = types.SimpleNamespace()
    for name in ("match", "search", "fullmatch", "findall", "sub", "split", "escape", "IGNORECASE", "MULTILINE"):
        setattr(module, name, getattr(re, name))
    return module


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return _MappingProxy({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, _MappingProxy):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    if isinstance(value, dict):
        return {k: _thaw(v) for k, v in value.items()}
    return value


class _BoundedIO(io.StringIO):
    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit
        self.truncated = False

    def write(self, text: str) -> int:  # type: ignore[override]
        remaining = self.limit - self.tell()
        if remaining <= 0:
            self.truncated = True
            return 0
        if len(text) > remaining:
            self.truncated = True
            text = text[:remaining]
        return super().write(text)


def main() -> int:
    # ``-I -P`` leave neither cwd nor the script dir on sys.path - make the
    # package importable explicitly (the runner image ships only this package).
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    del os
    real_stdout = sys.stdout
    real_stderr = sys.stderr
    sys.stdout = sys.stderr  # nothing user-visible may reach the protocol stream
    job = _json_loads(sys.stdin.read())
    source = job.get("source") or ""
    user_input = job.get("input") or {}
    console_limit = int(job.get("consoleLimit") or 4096)
    output_limit = int(job.get("outputLimit") or 65536)

    from code_runner.policy import validate_source

    issues = validate_source(source)
    out: Dict[str, Any] = {"ok": False, "termination": "policy", "error": "; ".join(issues)}
    if not issues:
        stdout = _BoundedIO(console_limit)
        stderr = _BoundedIO(console_limit)
        env: Dict[str, Any] = {
            "__builtins__": _safe_builtins(),
            "input": _freeze(user_input),
            "json": _ReadOnlyJson,
            "math": _read_only_math(),
            "re": _read_only_re(),
        }
        # Everything the harness needs after this point is bound locally or on
        # inert module-level helpers; ``sys`` is the last thing to go.
        try:
            code = compile(source, "<code.run>", "exec")
        except (SyntaxError, ValueError) as exc:
            out = {"ok": False, "termination": "policy", "error": f"{type(exc).__name__}: {exc}"}
            real_stdout.write(_json_dumps(out))
            real_stdout.flush()
            return 0
        sys.stdout, sys.stderr = stdout, stderr
        run_code = exec  # bound BEFORE the real builtin is neutered
        _harden()
        del job, validate_source
        try:
            run_code(code, env)  # noqa: S102 - the jailed child, by design
            result = env.get("result")
            if isinstance(result, _MappingProxy):
                result = _thaw(result)
            if not isinstance(result, dict):
                out = {"ok": False, "termination": "invalid_result", "error": "Code must assign a dictionary to result."}
            else:
                encoded = _json_dumps(_thaw(result))
                if len(encoded) > output_limit:
                    out = {"ok": False, "termination": "output_limit", "error": "Result exceeds the output size limit."}
                else:
                    out = {"ok": True, "termination": "completed", "result": _json_loads(encoded)}
        except MemoryError:
            out = {"ok": False, "termination": "memory_limit", "error": "Code exceeded the memory limit."}
        except RecursionError:
            out = {"ok": False, "termination": "error", "error": "Maximum recursion depth exceeded."}
        except (TypeError, ValueError) as exc:
            # json.dumps failures (non-serializable) land here too.
            out = {"ok": False, "termination": "error", "error": f"{type(exc).__name__}: {exc}"}
        except BaseException as exc:  # noqa: BLE001 - report, never crash silently
            out = {"ok": False, "termination": "error", "error": f"{type(exc).__name__}: {exc}"}
        out["stdout"] = stdout.getvalue()
        out["stderr"] = stderr.getvalue()
        out["consoleTruncated"] = stdout.truncated or stderr.truncated
    real_stdout.write(_json_dumps(out))
    real_stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
