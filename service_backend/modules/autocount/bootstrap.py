"""AutoCount bootstrap — the App-Store module contract (plan 08 §4, AC-13-45).

``install`` is GLOBAL and idempotent (schema + tables + permission-catalog sync);
the per-tenant hooks (``install_tenant`` / ``update_tenant`` / ``uninstall_tenant``)
are driven by AppStoreService when a tenant installs/updates/uninstalls.
Permission GRANTS are the store's concern — it grants the module keys to the
tenant's Admin role at install, which is why a brand-new module needs no grant
sweep for existing tenants (nobody has it installed yet).

Stage 1 scaffold: schema + (currently empty) tables + permission CSV + the
integration provider. Companies, watermarks, entity config, staging and the sync
job handler are filled in by later slices — the hooks are wired now so the
module contract is complete from day one.
"""
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.repositories.permission_repository import PermissionRepository
from app.services.permission_service import load_csv

from . import models  # noqa: F401 — register module tables on AutocountBase.metadata
from .db import AUTOCOUNT_SCHEMA, AutocountBase

MODULE_NAME = "autocount"
MODULE_CSV = Path(__file__).resolve().parent / "permissions" / "permissions.csv"


def register_capabilities() -> None:
    """Boot-time capability registration (sprint-3/10 D5). Idempotent.

    AutoCount provides no cross-module capability yet. The read pipeline exposes
    its canonical records to consumers over the public gateway, not the in-process
    capability seam, so this stays a no-op unless a sibling module needs a direct
    call."""
    return None


def register_engine_entities() -> None:
    """Boot-time registration into shared CORE registries (plan 11 D9).

    Idempotent — ``register_module_boot`` calls this on every boot/bootstrap, and
    the provider registry is a keyed dict (re-registering replaces in place).

    Registers:
      * the AutoCount ``erp`` connection provider, so it appears in
        ``GET /integrations/providers`` and is configurable from the standard
        integrations surface (AC-13-01);
      * the ``autocount_sync`` background-job handler.

    The job handler must be registered in EVERY process that touches a sync job:
    the API process creates jobs (``JobService.create`` validates the type is
    registered) and — under eager dev/test — runs them inline. The Celery worker
    boots no FastAPI lifespan, so it gets the handler from an explicit import in
    ``app/workflow_engine/worker.py`` instead. Missing EITHER path leaves jobs
    Pending forever with no error.

    Status entities, importer defs and terminology land with the entities they
    describe in later slices.
    """
    from app.integrations import register_provider

    from .provider import AutoCountProvider
    from .sync import register_autocount_sync_handler

    register_provider(AutoCountProvider())
    register_autocount_sync_handler()


def create_schema_and_tables(engine: Engine) -> None:
    """Create the module schema (Postgres) + all module tables. Idempotent."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{AUTOCOUNT_SCHEMA}"'))
    AutocountBase.metadata.create_all(bind=engine)


def install(engine: Engine, db: Session) -> None:
    """Global install (plan 08 §4): schema + tables + permission catalog sync.

    Runs at every bootstrap (idempotent). Per-tenant seeding happens in
    ``install_tenant`` when a tenant actually installs the module.
    """
    create_schema_and_tables(engine)
    PermissionRepository(db).sync(MODULE_NAME, load_csv(MODULE_CSV))


def install_tenant(db: Session, tenant_id: str) -> None:
    """Per-tenant seed (plan 08 §4). Idempotent.

    Still nothing to seed: a tenant's AutoCount footprint begins when an
    operator registers a COMPANY, and a company cannot exist before its
    connection does. Per-company entity configs + mapping rows are seeded by
    ``CompanyService.seed_company_defaults`` at that moment — seeding them here
    would mean guessing a company that has not been discovered yet."""
    return None


def update_tenant(db: Session, tenant_id: str, from_version: str) -> None:
    """Per-tenant data migration between provisioned versions (plan 08 D3).

    All of autocount is 0.1.0 and every table in it is NEW in this slice, so
    there is genuinely nothing to backfill — no tenant holds a row that predates
    these columns.

    NOTE for the next slice that touches an EXISTING table: adding a column or
    an engine adoption needs a REAL BACKFILL here (and in module Alembic), not
    seed-if-absent. ``install_tenant``-style seeding does not repair rows that
    already exist — that is exactly how rows end up stranded with a NULL in a
    column the code assumes is populated."""
    return None


def uninstall_tenant(db: Session, tenant_id: str) -> None:
    """Wipe THIS tenant's rows from every module table (plan 08 §5).

    The module schema and other tenants' rows are untouched — uninstall is
    per-tenant, never global. Reverse dependency order avoids FK violations.
    (No module tables in the scaffold slice — a safe no-op that automatically
    covers every table added later.)"""
    for table in reversed(AutocountBase.metadata.sorted_tables):
        if "tenant_id" in table.c:
            db.execute(table.delete().where(table.c.tenant_id == tenant_id))
    db.flush()


def tenant_has_data(db: Session, tenant_id: str) -> bool:
    """Backfill detection (loader) for pre-App-Store installs. AutoCount is a
    net-new module — no legacy data ever existed — so no tenant backfills."""
    return False
