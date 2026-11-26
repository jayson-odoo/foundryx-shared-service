"""hub_connector init - creates every ``app_hub_connector`` table.

Tables: hc_hubs, hc_hub_customers, hc_customers, hc_items, hc_sent_views,
hc_api_keys, hc_deliveries. Postgres-only (per-module Alembic is a no-op on the
SQLite test engine).

Revision ID: 0001_hub_connector_init
Revises:
Create Date: 2026-11-26
"""

from __future__ import annotations
from alembic import op

revision = "0001_hub_connector_init"
down_revision = None
branch_labels = None
depends_on = None

_TABLES = (
    "hc_hubs",
    "hc_hub_customers",
    "hc_customers",
    "hc_items",
    "hc_sent_views",
    "hc_api_keys",
    "hc_deliveries",
)


def upgrade() -> None:
    from sqlalchemy import text

    from modules.hub_connector.db import HUB_CONNECTOR_SCHEMA, HubConnectorBase
    from modules.hub_connector import models  # noqa: F401

    bind = op.get_bind()
    bind.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{HUB_CONNECTOR_SCHEMA}"'))
    # Pin THIS revision's tables: a later revision adds its own columns/tables.
    tables = [HubConnectorBase.metadata.tables[f"{HUB_CONNECTOR_SCHEMA}.{name}"] for name in _TABLES]
    HubConnectorBase.metadata.create_all(bind=bind, tables=tables)


def downgrade() -> None:
    from modules.hub_connector.db import HUB_CONNECTOR_SCHEMA, HubConnectorBase
    from modules.hub_connector import models  # noqa: F401

    tables = [HubConnectorBase.metadata.tables[f"{HUB_CONNECTOR_SCHEMA}.{name}"] for name in _TABLES]
    HubConnectorBase.metadata.drop_all(bind=op.get_bind(), tables=tables)
