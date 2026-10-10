"""connector settings in the database (lane SETTINGS-IN-DB-SS).

Adds "product_settings", "tenant_settings", "settings_audit" (schema
app_connector). Idempotent (checkfirst) because the module's global install
also runs create_all at boot. Postgres-only, like the baseline.

Revision ID: 0002_connector_settings
Revises: 0001_connector_baseline
Create Date: 2026-10-10
"""

from __future__ import annotations
from alembic import op

revision = "0002_connector_settings"
down_revision = "0001_connector_baseline"
branch_labels = None
depends_on = None

_TABLES = ("product_settings", "tenant_settings", "settings_audit")


def _tables():
    from modules.connector.db import ConnectorBase
    from modules.connector import models  # noqa: F401

    return [t for t in ConnectorBase.metadata.sorted_tables if t.name in _TABLES]


def upgrade() -> None:
    bind = op.get_bind()
    for table in _tables():
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind=bind, checkfirst=True)
