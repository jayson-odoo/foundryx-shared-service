"""Per-module Alembic orchestration (sprint-3/10 D3, closes BL-029).

Each module owns ``modules/<name>/alembic/`` (its own ``env.py`` + ``versions/``)
and an isolated version table (``alembic_version_<name>`` in the module schema,
declared in the manifest) — dodging the core cross-branch-pin gotcha. Per module:

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
from typing import Optional

from sqlalchemy import inspect
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


def run_module_migrations(engine: Engine, name: str) -> None:
    """Stamp-if-legacy-else-upgrade for one module. Safe no-op when not
    applicable (see module docstring)."""
    if engine.dialect.name != "postgresql":
        return
    manifest = _manifest_for(name)
    if manifest is None:
        return
    alembic_dir = MODULES_DIR / manifest["_dir"] / "alembic"
    if not alembic_dir.is_dir():
        return  # legacy module — create_all path

    schema = manifest.get("schema")
    version_table = manifest.get("alembic_version_table") or f"alembic_version_{name}"
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
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

    insp = inspect(engine)
    existing = set(insp.get_table_names(schema=schema)) if schema else set(insp.get_table_names())
    has_version_table = version_table in existing
    module_tables = (
        {t.name for t in metadata.sorted_tables} if metadata is not None else set()
    )
    has_module_tables = bool(module_tables & existing)

    if has_version_table:
        # Already under Alembic — apply any new revisions.
        command.upgrade(cfg, "head")
    elif has_module_tables:
        # Legacy create_all schema — adopt Alembic with NO DDL.
        command.stamp(cfg, "head")
        logger.info("Module '%s' stamped to head (legacy tables adopted).", name)
    else:
        # Fresh DB — build from migrations.
        command.upgrade(cfg, "head")
