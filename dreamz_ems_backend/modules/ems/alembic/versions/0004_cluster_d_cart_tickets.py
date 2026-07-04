"""ems — Cluster D slice 2 (sprint-4/05): carts + holds + tickets + payment_policy.

Adds carts / cart_items / capacity_holds / tickets to ``app_ems`` and the
``projects.payment_policy`` column. New tables via create_all (checkfirst);
payment_policy via add_column. Postgres only; SQLite tests use create_all.

Revision ID: 0004_cluster_d_cart_tickets
Revises: 0003_cluster_d_venues_offerings
Create Date: 2026-06-20
"""
import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime  # noqa: F401

revision = "0004_cluster_d_cart_tickets"
down_revision = "0003_cluster_d_venues_offerings"
branch_labels = None
depends_on = None

_NEW_TABLES = ("carts", "cart_items", "capacity_holds", "tickets")


def upgrade() -> None:
    import modules.ems.models  # noqa: F401
    from modules.ems.db import EmsBase

    bind = op.get_bind()
    op.add_column(
        "projects",
        sa.Column("payment_policy", sa.String(), nullable=False, server_default="pay_now_required"),
        schema="app_ems",
    )
    tables = [EmsBase.metadata.tables[f"app_ems.{n}"] for n in _NEW_TABLES]
    EmsBase.metadata.create_all(bind=bind, tables=tables, checkfirst=True)


def downgrade() -> None:
    import modules.ems.models  # noqa: F401
    from modules.ems.db import EmsBase

    bind = op.get_bind()
    tables = [EmsBase.metadata.tables[f"app_ems.{n}"] for n in reversed(_NEW_TABLES)]
    EmsBase.metadata.drop_all(bind=bind, tables=tables, checkfirst=True)
    op.drop_column("projects", "payment_policy", schema="app_ems")
