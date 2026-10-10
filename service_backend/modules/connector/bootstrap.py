"""Connector bootstrap - the App-Store module contract (plan 08 section 4)."""

from __future__ import annotations
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.repositories.permission_repository import PermissionRepository
from app.services.permission_service import load_csv

from . import models  # noqa: F401 - register tables on ConnectorBase.metadata
from .db import CONNECTOR_SCHEMA, ConnectorBase

MODULE_NAME = "connector"
MODULE_CSV = Path(__file__).resolve().parent / "permissions" / "permissions.csv"


def register_capabilities() -> None:
    return None


def register_engine_entities() -> None:
    return None


def create_schema_and_tables(engine: Engine) -> None:
    """Idempotent. Postgres: schema first; tables via create_all (the module
    Alembic baseline adopts them on existing DBs)."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{CONNECTOR_SCHEMA}"'))
    ConnectorBase.metadata.create_all(bind=engine)


def install(engine: Engine, db: Session) -> None:
    """Global install: schema + tables + permission catalog sync. Tenant Admin
    receives connector.read/manage via AppStoreService on tenant install."""
    create_schema_and_tables(engine)
    PermissionRepository(db).sync(MODULE_NAME, load_csv(MODULE_CSV))


def install_tenant(db: Session, tenant_id: str) -> None:
    return None


def update_tenant(db: Session, tenant_id: str, from_version: str) -> None:
    return None


def uninstall_tenant(db: Session, tenant_id: str) -> None:
    """Wipe ONLY this tenant's rows (never the schema)."""
    for table in reversed(ConnectorBase.metadata.sorted_tables):
        if "tenant_id" in table.c:
            db.execute(table.delete().where(table.c.tenant_id == tenant_id))
    db.flush()


def tenant_has_data(db: Session, tenant_id: str) -> bool:
    return False
