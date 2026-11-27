"""Planner 3D bootstrap - the App-Store module contract.

Install: schema + tables + permission catalog sync. The tenant Admin receives
the module keys (``planner3d.jobs.*``, and since S1 ``planner3d.keys.manage`` /
``planner3d.webhooks.manage``) from AppStoreService on
``install`` and again on every ``update`` (``_grant_admin``, idempotent), so a
tenant that already has the module picks up a later-added key on update; there
is no tenant-owned row to backfill in this version.
"""

from __future__ import annotations
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.repositories.permission_repository import PermissionRepository
from app.services.permission_service import load_csv

from . import models  # noqa: F401 - register tables on Planner3dBase.metadata
from .db import PLANNER3D_SCHEMA, Planner3dBase

MODULE_NAME = "planner3d"
MODULE_CSV = Path(__file__).resolve().parent / "permissions" / "permissions.csv"


def register_capabilities() -> None:
    return None


def register_engine_entities() -> None:
    from .deferred_actions import register_planner3d_deferred_actions

    register_planner3d_deferred_actions()


def create_schema_and_tables(engine: Engine) -> None:
    """Idempotent. Postgres: schema first; tables via create_all (the module
    Alembic baseline adopts them on existing DBs)."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{PLANNER3D_SCHEMA}"'))
    Planner3dBase.metadata.create_all(bind=engine)


def install(engine: Engine, db: Session) -> None:
    create_schema_and_tables(engine)
    PermissionRepository(db).sync(MODULE_NAME, load_csv(MODULE_CSV))


def install_tenant(db: Session, tenant_id: str) -> None:
    return None


def update_tenant(db: Session, tenant_id: str, from_version: str) -> None:
    return None


def uninstall_tenant(db: Session, tenant_id: str) -> None:
    """Wipe ONLY this tenant's rows (never the schema). Stored blobs are NOT
    deleted here and no sweep removes them (BL-SS-372)."""
    for table in reversed(Planner3dBase.metadata.sorted_tables):
        if "tenant_id" in table.c:
            db.execute(table.delete().where(table.c.tenant_id == tenant_id))
    db.flush()


def tenant_has_data(db: Session, tenant_id: str) -> bool:
    return False
