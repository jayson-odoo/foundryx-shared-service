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
    created = PermissionRepository(db).sync(MODULE_NAME, load_csv(MODULE_CSV))
    # Existing tenants: their Admin role (if it already holds connector.manage) gets
    # connector.settings. ONE-SHOT - only when this very sync created the key, so a
    # later deliberate removal is respected.
    if SETTINGS_PERMISSION in created:
        sweep_settings_grant(db)
        db.commit()


SETTINGS_PERMISSION = "connector.settings"
MANAGE_PERMISSION = "connector.manage"


def sweep_settings_grant(db: Session) -> None:
    """Grant ``connector.settings`` to every tenant's system Admin role that holds
    ``connector.manage``. Idempotent; stamped with the role's own tenant_id. No
    commit - the caller owns the transaction."""
    from sqlalchemy import select

    from app.models import Role
    from app.models.permission import Permission, role_permissions

    ids = dict(db.execute(select(Permission.key, Permission.id).where(
        Permission.key.in_([MANAGE_PERMISSION, SETTINGS_PERMISSION]))).all())
    manage_id, settings_id = ids.get(MANAGE_PERMISSION), ids.get(SETTINGS_PERMISSION)
    if manage_id is None or settings_id is None:
        return
    holders = db.execute(
        select(Role.id, Role.tenant_id)
        .join(role_permissions, role_permissions.c.role_id == Role.id)
        .where(role_permissions.c.permission_id == manage_id, Role.name == "Admin")
    ).all()
    already = set(db.execute(select(role_permissions.c.role_id).where(
        role_permissions.c.permission_id == settings_id)).scalars())
    new = [{"role_id": rid, "permission_id": settings_id, "tenant_id": tid}
           for rid, tid in holders if rid not in already]
    if new:
        db.execute(role_permissions.insert(), new)
    db.flush()


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
