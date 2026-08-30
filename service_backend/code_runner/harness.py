"""Child-process harness: reads ONE job as JSON on stdin, executes it under the
restricted builtins table, writes ONE JSON result line on stdout.

Started by ``sandbox.execute`` as ``python -I -S -m code_runner.harness`` with
an empty environment and resource limits already applied (see ``sandbox``).
Nothing in here trusts the job: the policy runs again before execution.
"""
from __future__ import annotations

import io
import json
import math
import re
import sys
import types
from typing import Any, Dict


def _safe_builtins():
    import builtins

    from code_runner.policy import SAFE_BUILTIN_NAMES

    table: Dict[str, Any] = {}
    for name in SAFE_BUILTIN_NAMES:
        if hasattr(builtins, name):
            table[name] = getattr(builtins, name)
    return table


class _ReadOnlyJson:
    """The ``json`` helper: loads/dumps only."""

    loads = staticmethod(json.loads)

    @staticmethod
    def dumps(value, **kwargs):
        kwargs.pop("default", None)
        return json.dumps(value, **kwargs)


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
        return types.MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, types.MappingProxyType):
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
    real_stdout = sys.stdout
    real_stderr = sys.stderr
    sys.stdout = sys.stderr  # nothing user-visible may reach the protocol stream
    job = json.loads(sys.stdin.read())
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
        sys.stdout, sys.stderr = stdout, stderr
        try:
            code = compile(source, "<code.run>", "exec")
            exec(code, env)  # noqa: S102 - the jailed child, by design
            result = env.get("result")
            if isinstance(result, types.MappingProxyType):
                result = _thaw(result)
            if not isinstance(result, dict):
                out = {"ok": False, "termination": "invalid_result", "error": "Code must assign a dictionary to result."}
            else:
                encoded = json.dumps(_thaw(result))
                if len(encoded) > output_limit:
                    out = {"ok": False, "termination": "output_limit", "error": "Result exceeds the output size limit."}
                else:
                    out = {"ok": True, "termination": "completed", "result": json.loads(encoded)}
        except MemoryError:
            out = {"ok": False, "termination": "memory_limit", "error": "Code exceeded the memory limit."}
        except RecursionError:
            out = {"ok": False, "termination": "error", "error": "Maximum recursion depth exceeded."}
        except (TypeError, ValueError) as exc:
            # json.dumps failures (non-serializable) land here too.
            out = {"ok": False, "termination": "error", "error": f"{type(exc).__name__}: {exc}"}
        except BaseException as exc:  # noqa: BLE001 - report, never crash silently
            out = {"ok": False, "termination": "error", "error": f"{type(exc).__name__}: {exc}"}
        finally:
            sys.stdout, sys.stderr = real_stderr, real_stderr
        out["stdout"] = stdout.getvalue()
        out["stderr"] = stderr.getvalue()
        out["consoleTruncated"] = stdout.truncated or stderr.truncated
    real_stdout.write(json.dumps(out))
    real_stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
