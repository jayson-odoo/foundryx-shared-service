"""ems — Cluster D (sprint-4/05): venue master + offerings + capacity.

Adds venues / venue_zones / venue_seats / project_venues / project_products
(offerings) / project_product_zones / capacity_units to ``app_ems``. Created via
``EmsBase.metadata.create_all`` (checkfirst — only the new tables are built;
existing spine tables are untouched). Postgres only; SQLite tests use create_all.

Revision ID: 0003_cluster_d_venues_offerings
Revises: 0002_project_dates_to_date
Create Date: 2026-06-20
"""
from alembic import op

# UTCDateTime columns need this import present for the metadata to resolve.
import app.models.utc_datetime  # noqa: F401

revision = "0003_cluster_d_venues_offerings"
down_revision = "0002_project_dates_to_date"
branch_labels = None
depends_on = None

_NEW_TABLES = (
    "venues",
    "venue_zones",
    "venue_seats",
    "project_venues",
    "project_products",
    "project_product_zones",
    "capacity_units",
)


def upgrade() -> None:
    import modules.ems.models  # noqa: F401 — register tables on EmsBase.metadata
    from modules.ems.db import EmsBase

    bind = op.get_bind()
    tables = [EmsBase.metadata.tables[f"app_ems.{name}"] for name in _NEW_TABLES]
    EmsBase.metadata.create_all(bind=bind, tables=tables, checkfirst=True)


def downgrade() -> None:
    import modules.ems.models  # noqa: F401
    from modules.ems.db import EmsBase

    bind = op.get_bind()
    tables = [EmsBase.metadata.tables[f"app_ems.{name}"] for name in reversed(_NEW_TABLES)]
    EmsBase.metadata.drop_all(bind=bind, tables=tables, checkfirst=True)
