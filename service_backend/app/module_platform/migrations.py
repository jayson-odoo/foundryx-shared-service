"""Per-module Alembic orchestration (sprint-3/10 D3, closes BL-029).

Each module owns ``modules/<name>/alembic/`` (its own ``env.py`` + ``versions/``)
and an isolated version table (``alembic_version_<name>`` in the module schema,
declared in the manifest) - dodging the core cross-branch-pin gotcha. Per module:

  version-row exists            → ``upgrade head``
  no row + module tables exist  → ``stamp head``  (legacy create_all, no DDL)
  no row + no tables            → ``upgrade head``

NO-OP when: the engine isn't Postgres (module schema-isolation needs Postgres;
the SQLite test suite keeps the ``create_all`` path), or the module has no
``alembic/`` dir (a legacy module that hasn't adopted per-module migrations yet).
Per-tenant uninstall NEVER drops the schema/tables (shared across tenants); a
global schema-drop is operator-only + explicit (never automatic).
"""
import logging
from pathlib import Path
from typing import List, Optional

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.module_loader import MODULES_DIR, discover_manifests

logger = logging.getLogger(__name__)


def _manifest_for(name: str) -> Optional[dict]:
    for m in discover_manifests():
        if m["module_name"] == name:
            return m
    return None


def _module_metadata(name: str):
    """The module's declarative ``Base.metadata`` (for table-existence checks).
    Imported lazily from ``modules.<name>.db`` (convention: a ``*Base`` there)."""
    import importlib

    try:
        db_mod = importlib.import_module(f"modules.{name}.db")
    except ModuleNotFoundError:
        return None
    for attr in dir(db_mod):
        obj = getattr(db_mod, attr)
        meta = getattr(obj, "metadata", None)
        if meta is not None and hasattr(meta, "sorted_tables"):
            return meta
    return None


def _is_postgres(engine) -> bool:
    dialect = getattr(engine, "dialect", None)
    return getattr(dialect, "name", None) == "postgresql"


def _module_alembic(name: str):
    """``(manifest, alembic_dir, schema, version_table)`` for a module under
    per-module Alembic, or ``None`` (unknown module / legacy create_all
    module with no ``alembic/`` dir)."""
    manifest = _manifest_for(name)
    if manifest is None:
        return None
    alembic_dir = MODULES_DIR / manifest["_dir"] / "alembic"
    if not alembic_dir.is_dir():
        return None
    schema = manifest.get("schema")
    version_table = manifest.get("alembic_version_table") or f"alembic_version_{name}"
    return manifest, alembic_dir, schema, version_table


def _migration_state(engine, name: str, schema, version_table) -> str:
    """``versioned`` | ``legacy`` | ``fresh`` for a Postgres module under
    per-module Alembic (see the module docstring's decision table)."""
    metadata = _module_metadata(name)
    insp = inspect(engine)
    existing = set(insp.get_table_names(schema=schema)) if schema else set(insp.get_table_names())
    if version_table in existing:
        return "versioned"
    module_tables = (
        {t.name for t in metadata.sorted_tables} if metadata is not None else set()
    )
    if module_tables & existing:
        return "legacy"
    return "fresh"


def module_migration_state(engine, name: str) -> str:
    """Where a module's schema stands BEFORE bootstrap touches it:

    - ``unmanaged`` - not Postgres, unknown module, or no ``alembic/`` dir
      (``run_module_migrations`` is a no-op; order does not matter)
    - ``versioned`` - the module's version table exists (normal deploy)
    - ``legacy``    - module tables exist but were never stamped
    - ``fresh``     - nothing of the module exists in this database yet

    ``_bootstrap_one_module`` uses this to pick the order (issue #89): an
    already-migrated module runs its migrations BEFORE its install/seed hook
    (schema before seed, and no open seed write can block the migration's
    DDL); a ``fresh`` one keeps the long-standing install-then-stamp path,
    because the chain was never written to replay from zero on top of the
    create_all baselines.
    """
    if not _is_postgres(engine):
        return "unmanaged"
    found = _module_alembic(name)
    if found is None:
        return "unmanaged"
    _manifest, _dir, schema, version_table = found
    # A missing schema simply lists no tables -> ``fresh``.
    return _migration_state(engine, name, schema, version_table)


# ── lock-holder report (issue #89, W2) ──────────────────────────────────────

_LOCK_HOLDERS_SQL = """
SELECT
    a.pid AS pid,
    a.state AS state,
    (now() - a.xact_start)::text AS xact_age,
    a.query AS query,
    a.application_name AS application_name,
    a.backend_type AS backend_type,
    a.client_addr::text AS client_addr,
    string_agg(DISTINCT n.nspname || '.' || c.relname || ' ' || l.mode, ', ') AS locks
FROM pg_locks l
JOIN pg_class c ON c.oid = l.relation
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_stat_activity a ON a.pid = l.pid
WHERE l.granted
  AND n.nspname = :schema
  AND a.pid <> pg_backend_pid()
GROUP BY a.pid, a.state, a.xact_start, a.query, a.application_name,
         a.backend_type, a.client_addr
ORDER BY a.pid
"""


def report_lock_holders(engine, schema: Optional[str]) -> List[dict]:
    """Log WHO holds a granted lock on any relation in the module's schema
    (``pg_locks`` joined to ``pg_stat_activity``): pid, state, transaction
    age and query text per holder, one ERROR line each. Returns the rows.

    Called when a module migration dies on ``LockNotAvailable`` so the
    operator never has to guess the holder again (issue #89: the holder was
    the bootstrap's own open seed transaction, invisible to a plain look at
    ``pg_stat_activity``). Scoped to the module's schema: the generic lock
    error does not reliably name the blocked relation, the schema does.
    """
    target = schema or "public"
    with engine.connect() as conn:
        rows = conn.execute(text(_LOCK_HOLDERS_SQL), {"schema": target}).mappings().all()
    holders = [dict(r) for r in rows]
    if not holders:
        logger.error(
            "lock holder report for schema '%s': no granted lock held by another "
            "session right now (the holder finished, or it was this process's "
            "own connection)", target,
        )
    for h in holders:
        logger.error(
            "lock holder on schema '%s': pid=%s state=%s xact_age=%s "
            "application_name=%s backend_type=%s client_addr=%s locks=[%s] query=%s",
            target, h.get("pid"), h.get("state"), h.get("xact_age"),
            h.get("application_name"), h.get("backend_type"), h.get("client_addr"),
            h.get("locks"), h.get("query"),
        )
    if holders:
        logger.error(
            "decide per holder before re-running bootstrap: wait for it, stop its "
            "container, or end it with SELECT pg_terminate_backend(<pid>) (DEPLOY.md, "
            "'Module migration lock timeout')"
        )
    return holders


def _is_lock_not_available(exc: BaseException) -> bool:
    """True for a ``lock_timeout`` cancel (SQLSTATE 55P03), raw or wrapped by
    SQLAlchemy/Alembic anywhere along the cause chain."""
    seen = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        for candidate in (cur, getattr(cur, "orig", None)):
            if candidate is None:
                continue
            if type(candidate).__name__ == "LockNotAvailable":
                return True
            if getattr(candidate, "pgcode", None) == "55P03":
                return True
        cur = cur.__cause__ or cur.__context__
    return False


def run_module_migrations(engine: Engine, name: str) -> None:
    """Stamp-if-legacy-else-upgrade for one module. Safe no-op when not
    applicable (see module docstring).

    Runs under the bootstrap's ``lock_timeout`` (``PGOPTIONS``, set by
    ``scripts.bootstrap_db._apply_bootstrap_lock_timeout`` before any
    connection opens, so Alembic's own engine inherits it). On a lock
    timeout the holders are reported (``report_lock_holders``) and the
    error PROPAGATES - bootstrap aborts, ``start.sh`` retries, the deploy
    never swaps onto a half-migrated schema (issue #89).
    """
    if not _is_postgres(engine):
        return
    found = _module_alembic(name)
    if found is None:
        return  # unknown module, or legacy module - create_all path
    _manifest, alembic_dir, schema, version_table = found
    metadata = _module_metadata(name)

    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir))
    from app.config import settings

    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    cfg.attributes["version_table"] = version_table
    cfg.attributes["version_table_schema"] = schema
    cfg.attributes["target_metadata"] = metadata
    cfg.attributes["module_schema"] = schema

    # The version table lives IN the module schema, so the schema must exist
    # before Alembic creates it (fresh DB). Idempotent.
    if schema:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

    state = _migration_state(engine, name, schema, version_table)
    try:
        if state == "versioned":
            # Already under Alembic - apply any new revisions.
            command.upgrade(cfg, "head")
        elif state == "legacy":
            # Legacy create_all schema - adopt Alembic with NO DDL.
            command.stamp(cfg, "head")
            logger.info("Module '%s' stamped to head (legacy tables adopted).", name)
        else:
            # Fresh DB - build from migrations.
            command.upgrade(cfg, "head")
    except Exception as exc:
        if _is_lock_not_available(exc):
            logger.error(
                "Module '%s' migration hit a lock timeout; reporting lock holders "
                "on schema '%s' before aborting", name, schema,
            )
            try:
                report_lock_holders(engine, schema)
            except Exception:  # noqa: BLE001 - the report must never mask the real error
                logger.exception("Module '%s' lock holder report itself failed", name)
        raise
