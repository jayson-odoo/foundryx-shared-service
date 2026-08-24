"""Meetings bootstrap — the App-Store module contract (plan 08 §4).

``install`` is GLOBAL and idempotent (schema + tables + permission-catalog sync);
the per-tenant hooks (``install_tenant`` / ``update_tenant`` / ``uninstall_tenant``)
are driven by AppStoreService when a tenant installs/updates/uninstalls. Permission
GRANTS are the store's concern (it grants the module keys to the tenant's roles).

The optional ``register_capabilities`` / ``tenant_has_data`` hooks are absent on
purpose: the loader reaches for them with ``getattr``, and meetings has neither a
cross-module capability to publish nor any pre-App-Store data to backfill.
"""
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.repositories.permission_repository import PermissionRepository
from app.services.permission_service import load_csv

from . import models  # noqa: F401 — register module tables on MeetingsBase.metadata
from .db import MEETINGS_SCHEMA, MeetingsBase

MODULE_NAME = "meetings"
MODULE_CSV = Path(__file__).resolve().parent / "permissions" / "permissions.csv"


def register_engine_entities() -> None:
    """Boot-time registration into shared CORE registries (plan 11 D9). Idempotent.

    Registers:
      * the two connection providers (``google_dwd``, ``meet_bot``) so both are
        configured from the standard ``/settings/integrations`` surface — no
        bespoke connection UI (AC-S0-4 / AC-S0-5);
      * the ``meetings.calendar_sync`` background-job handler.

    The job handler must be registered in EVERY process that touches a sync job:
    the API process creates jobs (``JobService.create`` validates the type is
    registered) and — under eager dev/test — runs them inline. The Celery worker
    boots no FastAPI lifespan, so it gets the handler from an explicit import in
    ``app/workflow_engine/worker.py``. Missing EITHER path leaves the job Pending
    forever with no error.

    The meeting lifecycle is a plain enum column, not a status entity (spine M19)
    — nothing to register on the status engine."""
    from app.integrations import register_provider

    from .jobs import register_calendar_sync_handler
    from .providers import GoogleDwdProvider, MeetBotProvider

    register_provider(GoogleDwdProvider())
    register_provider(MeetBotProvider())
    register_calendar_sync_handler()


def create_schema_and_tables(engine: Engine) -> None:
    """Create the module schema (Postgres) + all module tables. Idempotent."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{MEETINGS_SCHEMA}"'))
    MeetingsBase.metadata.create_all(bind=engine)


def install(engine: Engine, db: Session) -> None:
    """Global install (plan 08 §4): schema + tables + permission catalog sync.

    Runs at every bootstrap (idempotent). Per-tenant seeding happens in
    ``install_tenant`` when a tenant actually installs the module."""
    create_schema_and_tables(engine)
    PermissionRepository(db).sync(MODULE_NAME, load_csv(MODULE_CSV))


def install_tenant(db: Session, tenant_id: str) -> None:
    """Per-tenant seed (plan 08 §4). Idempotent.

    Seeds the tenant's settings row at platform defaults so the module behaves
    sanely for a tenant that never opens the settings page (AC-S0-1)."""
    from .services.settings import MeetingsSettingsService

    MeetingsSettingsService(db).ensure(tenant_id)
    db.commit()


def update_tenant(db: Session, tenant_id: str, from_version: str) -> None:
    """Per-tenant data migration between provisioned versions (plan 08 D3).

    All of meetings is 0.1.0 — nothing to backfill yet. A tenant provisioned
    before the settings row existed is still covered: ``ensure`` is
    seed-if-absent and runs on every settings read."""
    from .services.settings import MeetingsSettingsService

    MeetingsSettingsService(db).ensure(tenant_id)
    db.commit()


def uninstall_tenant(db: Session, tenant_id: str) -> None:
    """Wipe THIS tenant's rows from every module table (plan 08 §5, AC-S0-3).

    The module SCHEMA and every other tenant's rows are untouched — uninstall is
    per-tenant, never global. Reverse dependency order avoids FK violations."""
    for table in reversed(MeetingsBase.metadata.sorted_tables):
        if "tenant_id" in table.c:
            db.execute(table.delete().where(table.c.tenant_id == tenant_id))
    db.flush()

