"""Static language policy for builder Python (shared by backend + runner).

This is a LANGUAGE policy, not the security boundary - the subprocess jail in
``sandbox`` is. It exists so obviously unsafe or unsupported code fails fast
with a readable message at publish time.
"""
from __future__ import annotations

import ast
from typing import List

# Builtins exposed to builder code. Pure, side-effect-free helpers only.
SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float",
    "format", "frozenset", "hash", "int", "isinstance", "issubclass", "iter", "len",
    "list", "map", "max", "min", "next", "pow", "print", "range", "repr",
    "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple", "zip",
    "True", "False", "None",
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "ZeroDivisionError", "ArithmeticError", "LookupError", "RuntimeError",
    "StopIteration",
)

# Helper modules exposed as read-only objects (no ``import`` needed).
SAFE_MODULE_NAMES = ("json", "math", "re")

# Names that are never callable/referenced from builder code.
FORBIDDEN_NAMES = frozenset(
    {
        "exec", "eval", "compile", "__import__", "open", "globals",
        "locals", "vars", "getattr", "setattr", "delattr", "hasattr", "type",
        "object", "super", "breakpoint", "exit", "quit", "memoryview",
        "classmethod", "staticmethod", "property", "help", "dir", "id",
        "__builtins__", "__loader__", "__spec__", "__file__", "__name__",
        "__build_class__",
    }
)

# Attribute names that expose frames, code objects, globals or the MRO - the
# reflection routes out of the exec'd module (a generator's ``gi_frame`` walks
# ``f_back`` into the harness and its real builtins). ``format``/``format_map``
# on a literal are covered separately (``'{0.__class__}'.format(x)``).
FORBIDDEN_ATTRS = frozenset(
    {
        "gi_frame", "gi_code", "gi_yieldfrom", "gi_running",
        "cr_frame", "cr_code", "cr_await", "cr_running", "cr_origin",
        "ag_frame", "ag_code", "ag_await", "ag_running",
        "f_back", "f_globals", "f_builtins", "f_locals", "f_code", "f_trace",
        "f_lineno", "f_lasti",
        "tb_frame", "tb_next", "tb_lineno", "tb_lasti",
        "co_code", "co_consts", "co_names", "co_varnames", "co_filename",
        "mro", "format_map",
    }
)

FORBIDDEN_NODE_TYPES = (
    ast.Import,
    ast.ImportFrom,
    ast.Global,
    ast.Nonlocal,
    ast.AsyncFunctionDef,
    ast.AsyncFor,
    ast.AsyncWith,
    ast.Await,
    ast.ClassDef,
    ast.With,
    ast.Yield,
    ast.YieldFrom,
)

# Human-readable capability summary (the frontend "Runtime capabilities" list
# and the runner contract must agree - pinned by a test).
CAPABILITIES = (
    "Read-only `input` dictionary of the mapped values",
    "Assign a JSON dictionary to `result`",
    "Pure builtins: abs, all, any, bool, dict, enumerate, filter, float, int, len, list, map, max, min, range, round, set, sorted, str, sum, tuple, zip, print",
    "Helpers: json, math, re",
    "No imports, files, network, environment, subprocesses, or reflection",
)


def validate_source(source: str) -> List[str]:
    """Return the policy violations in ``source`` (empty = allowed)."""
    issues: List[str] = []
    if not isinstance(source, str) or not source.strip():
        return ["Code is empty."]
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        return [f"Python syntax error on line {exc.lineno or 1}."]
    assigns_result = False
    for node in ast.walk(tree):
        if isinstance(node, FORBIDDEN_NODE_TYPES):
            issues.append(f"Unsupported syntax on line {getattr(node, 'lineno', 1)}.")
            continue
        if isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES or node.id.startswith("__"):
                issues.append(f'"{node.id}" is not available (line {node.lineno}).')
            if node.id == "result" and isinstance(node.ctx, ast.Store):
                assigns_result = True
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") or node.attr in FORBIDDEN_ATTRS:
                issues.append(f'Attribute "{node.attr}" is not allowed (line {node.lineno}).')
        elif isinstance(node, ast.Subscript):
            # ``obj["__import__"]`` is attribute access in disguise.
            key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value.startswith("__"):
                issues.append(f'Key "{key.value}" is not allowed (line {node.lineno}).')
        elif isinstance(node, ast.Call):
            # ``"{0.__class__}".format(x)`` reads attributes through the
            # format mini-language; a dunder inside a format literal is never
            # legitimate data.
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "format"
                and isinstance(func.value, ast.Constant)
                and isinstance(func.value.value, str)
                and "__" in func.value.value
            ):
                issues.append(f"Format strings may not reference dunder attributes (line {node.lineno}).")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Plain strings that spell dunder attributes are only dangerous
            # with getattr/eval/format, which are handled above - allowed as data.
            continue
    if not assigns_result:
        issues.append("Code must assign a result dictionary.")
    # Stable order, no duplicates.
    seen: set[str] = set()
    ordered: List[str] = []
    for issue in issues:
        if issue not in seen:
            seen.add(issue)
            ordered.append(issue)
    return ordered
