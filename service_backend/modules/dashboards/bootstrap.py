"""Dashboards bootstrap - the App-Store module contract.

Install: schema + tables + permission catalog sync. The tenant Admin receives
``dashboards.keys.manage`` from AppStoreService on install and on every update
(idempotent). Nothing is seeded per tenant: the builder's system agent is
ensured lazily on the first builder turn, so existing tenants need no backfill.
Registers no workflow trigger or action (no WhatsApp path).
"""

from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.repositories.permission_repository import PermissionRepository
from app.services.permission_service import load_csv

from . import models  # noqa: F401 - register tables on DashboardsBase.metadata
from .db import DASHBOARDS_SCHEMA, DashboardsBase

MODULE_NAME = "dashboards"
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
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{DASHBOARDS_SCHEMA}"'))
    DashboardsBase.metadata.create_all(bind=engine)


# Public Anthropic list prices, USD per million tokens (input, output, cache read), with where they came
# from and when they were checked. Insert-if-missing: an operator's edit of a price row survives re-install.
# Source: https://platform.claude.com/docs/en/about-claude/pricing (Model pricing table, fetched 2026-11-28)
PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing (Model pricing table, fetched 2026-11-28)"
SEED_PRICES = {"claude-sonnet-5-5": ("2.00", "10.00", "0.10", PRICING_URL, datetime(2026, 11, 28, tzinfo=timezone.utc))}


def seed_prices(db: Session) -> None:
    for model, (inp, out, cache, source, verified) in SEED_PRICES.items():
        if db.get(models.DashModelPrice, model) is None:
            db.add(models.DashModelPrice(model=model, input_per_mtok=Decimal(inp), output_per_mtok=Decimal(out),
                                         cache_read_per_mtok=Decimal(cache), currency="USD", source=source,
                                         verified_at=verified))
    db.flush()


def install(engine: Engine, db: Session) -> None:
    create_schema_and_tables(engine)
    PermissionRepository(db).sync(MODULE_NAME, load_csv(MODULE_CSV))
    seed_prices(db)


def install_tenant(db: Session, tenant_id: str) -> None:
    return None


def update_tenant(db: Session, tenant_id: str, from_version: str) -> None:
    return None


def uninstall_tenant(db: Session, tenant_id: str) -> None:
    """Wipe ONLY this tenant's rows (never the schema)."""
    for table in reversed(DashboardsBase.metadata.sorted_tables):
        if "tenant_id" in table.c:
            db.execute(table.delete().where(table.c.tenant_id == tenant_id))
    db.flush()


def tenant_has_data(db: Session, tenant_id: str) -> bool:
    return False
