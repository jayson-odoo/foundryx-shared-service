#!/usr/bin/env python3
"""Fast pre-check: fail in under a minute when an alembic migration graph
(core or any module) has more than one head, instead of discovering the same
thing a `pytest` run or `alembic upgrade head` in bootstrap. Two branches
each merging main and adding their own revision on top of the same head give
that graph two heads once both land - green individually, broken combined
(the exact class of bug this repo hit with 0011_ideation_br_is_test landing
next to a test file that hardcoded the previous head as "newer than code").

Adapted from sorento_crm's `.github/workflows/deploy.yml` `check-migration-
heads` job (stdlib-only AST parse, no pip install - alembic's `env.py`
imports the whole app), generalized from one alembic directory to every
directory this repo's per-module alembic convention creates:

  - the CORE graph:        service_backend/alembic/versions
  - each MODULE graph:     service_backend/modules/<name>/alembic/versions

Each directory is its OWN independent alembic history (own version table),
so each is checked for exactly one head on its own - a module being at two
heads must never be masked by another module (or core) being fine.

Usage: python3 scripts/check_migration_heads.py
Exits 1 (naming every offending directory) when any graph does not have
exactly one head; exits 0 and prints a summary line per directory otherwise.
"""
import ast
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "service_backend"


def _versions_dirs() -> list[pathlib.Path]:
    """Every alembic ``versions`` directory this repo owns: the core graph
    plus one per module under per-module alembic. A module without an
    ``alembic/`` dir (a legacy create_all module) is simply absent here -
    same convention as ``app.module_platform.migrations``."""
    dirs = []
    core = BACKEND_DIR / "alembic" / "versions"
    if core.is_dir():
        dirs.append(core)
    modules_dir = BACKEND_DIR / "modules"
    if modules_dir.is_dir():
        for module_dir in sorted(modules_dir.iterdir()):
            versions = module_dir / "alembic" / "versions"
            if versions.is_dir():
                dirs.append(versions)
    return dirs


def _heads(versions_dir: pathlib.Path) -> tuple[int, list[str]]:
    """(revision count, sorted heads) for one alembic ``versions`` directory,
    parsed with the stdlib ``ast`` module only - no alembic/app import."""
    revs: set[str] = set()
    downs: set[str] = set()
    for f in sorted(versions_dir.glob("*.py")):
        if f.name == "__init__.py":
            continue
        # encoding is explicit (see sorento_crm's own comment here): a bare
        # read_text() decodes with the runner's locale, which is ASCII
        # whenever LANG is unset, and a non-ASCII migration docstring/comment
        # would then die with UnicodeDecodeError instead of reporting heads.
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                name, value = node.targets[0].id, node.value
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.value is not None
            ):
                name, value = node.target.id, node.value
            else:
                continue
            if name not in ("revision", "down_revision"):
                continue
            val = ast.literal_eval(value)
            if name == "revision":
                revs.add(val)
            elif val is not None:
                downs.update([val] if isinstance(val, str) else val)
    heads = sorted(revs - downs)
    return len(revs), heads


def main() -> int:
    versions_dirs = _versions_dirs()
    if not versions_dirs:
        print("::error::no alembic versions directory found under service_backend/")
        return 1

    failed: list[str] = []
    print(f"checking {len(versions_dirs)} alembic graph(s):")
    for versions_dir in versions_dirs:
        label = versions_dir.relative_to(REPO_ROOT)
        rev_count, heads = _heads(versions_dir)
        print(f"  {label}: {rev_count} revision(s), {len(heads)} head(s): {heads}")
        if len(heads) != 1:
            failed.append(str(label))

    if failed:
        print(
            "::error::the migration graph must have exactly one head in "
            f"each of: {', '.join(failed)} - merge the base branch and add "
            "a merge revision joining the heads (core), or reconcile the "
            "module's alembic history by hand"
        )
        return 1

    print("every alembic graph has exactly one head")
    return 0


if __name__ == "__main__":
    sys.exit(main())
