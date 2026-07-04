"""ems — Cluster D slice 3 (sprint-4/05): ticket status engine + checkpoints.

Adds ``tickets.status_id`` (status-engine adoption) + ``tickets.qr_nonce`` (QR
rotation on transfer/void/refund) and the ``checkpoints`` / ``checkpoint_logs``
tables (event-day preview; full orchestration = Cluster H). New columns via
add_column; new tables via create_all (checkfirst). Postgres only; SQLite tests
use create_all.

Revision ID: 0005_ticket_status_checkpoints
Revises: 0004_cluster_d_cart_tickets
Create Date: 2026-06-21
"""
import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime  # noqa: F401

revision = "0005_ticket_status_checkpoints"
down_revision = "0004_cluster_d_cart_tickets"
branch_labels = None
depends_on = None

_NEW_TABLES = ("checkpoints", "checkpoint_logs")


def upgrade() -> None:
    import modules.ems.models  # noqa: F401
    from modules.ems.db import EmsBase

    bind = op.get_bind()
    op.add_column(
        "tickets",
        sa.Column("status_id", sa.String(), nullable=True),
        schema="app_ems",
    )
    op.add_column(
        "tickets",
        sa.Column("qr_nonce", sa.String(), nullable=True),
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
    op.drop_column("tickets", "qr_nonce", schema="app_ems")
    op.drop_column("tickets", "status_id", schema="app_ems")
