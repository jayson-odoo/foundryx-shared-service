"""finance — Cluster F slice 3 (sprint-4/07): payment graph Expired/Disputed/Refunded.

Backfills every EXISTING tenant payment status graph with the new Cluster-F
slice-3 states + edges (AC-07-30/33/36/53) — seed-if-absent in update_tenant does
NOT repair a graph that already exists, so this migration runs ``backfill_graph``
for each tenant that already has a payment graph. Postgres only; SQLite tests use
create_all + the in-tenant install path.

Revision ID: 0004_payment_graph_states
Revises: 0003_finance_cluster_f
Create Date: 2026-06-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_payment_graph_states"
down_revision = "0003_finance_cluster_f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from sqlalchemy.orm import Session

    from modules.finance.bootstrap import (
        PAYMENT_EDGE_SEED,
        PAYMENT_STATUS_SEED,
        backfill_graph,
    )

    sess = Session(bind=bind)
    tenant_ids = [
        r[0]
        for r in sess.execute(
            sa.text(
                "SELECT DISTINCT tenant_id FROM public.statuses "
                "WHERE entity_type = 'payment' AND scope_id IS NULL"
            )
        )
    ]
    for tid in tenant_ids:
        backfill_graph(sess, "payment", tid, PAYMENT_STATUS_SEED, PAYMENT_EDGE_SEED)
    sess.flush()


def downgrade() -> None:
    # States are additive + system-locked; no clean automatic removal.
    pass