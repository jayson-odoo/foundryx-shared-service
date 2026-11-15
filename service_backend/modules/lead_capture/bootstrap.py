"""Lead Capture bootstrap - the App-Store module contract (plan 08 section 4).

Boot (``register_engine_entities``): claims the Meta ``page``/``leadgen``
webhook change (plan 64 D5, core registry) and declares ``leadgen`` as a Page
field this Service subscribes (D15 union fallback). Install: schema + tables +
permission catalog sync; tenant Admin receives the module keys through
AppStoreService on tenant install / update (AC-64-03).
"""

from __future__ import annotations
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.repositories.permission_repository import PermissionRepository
from app.services.permission_service import load_csv

from . import models  # noqa: F401 - register tables on LeadCaptureBase.metadata
from .db import LEAD_CAPTURE_SCHEMA, LeadCaptureBase

MODULE_NAME = "lead_capture"
MODULE_CSV = Path(__file__).resolve().parent / "permissions" / "permissions.csv"
LEADGEN_FIELD = "leadgen"


def register_capabilities() -> None:
    return None


def register_engine_entities() -> None:
    """Idempotent boot registration of the Meta webhook change handler."""
    from app.integrations.meta.pages import register_page_fields
    from app.integrations.meta.webhook_registry import register_meta_change_handler

    from .services.leadgen_service import handle_leadgen_change

    register_meta_change_handler("page", LEADGEN_FIELD, MODULE_NAME, handle_leadgen_change)
    register_page_fields(MODULE_NAME, [LEADGEN_FIELD])


def create_schema_and_tables(engine: Engine) -> None:
    """Idempotent. Postgres: schema first; tables via create_all (the module
    Alembic baseline adopts them on existing DBs)."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{LEAD_CAPTURE_SCHEMA}"'))
    LeadCaptureBase.metadata.create_all(bind=engine)


def install(engine: Engine, db: Session) -> None:
    create_schema_and_tables(engine)
    PermissionRepository(db).sync(MODULE_NAME, load_csv(MODULE_CSV))


def install_tenant(db: Session, tenant_id: str) -> None:
    return None


def update_tenant(db: Session, tenant_id: str, from_version: str) -> None:
    return None


def uninstall_tenant(db: Session, tenant_id: str) -> None:
    """Wipe ONLY this tenant's rows (never the schema). A Page left with no
    live source keeps its ``leadgen`` subscription: unsubscribing needs the
    Page token, and a stale field only means Meta sends webhooks nobody
    claims (dropped at resolve)."""
    for table in reversed(LeadCaptureBase.metadata.sorted_tables):
        if "tenant_id" in table.c:
            db.execute(table.delete().where(table.c.tenant_id == tenant_id))
    db.flush()


def tenant_has_data(db: Session, tenant_id: str) -> bool:
    return False
