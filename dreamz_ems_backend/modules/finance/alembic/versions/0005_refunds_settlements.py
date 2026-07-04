"""finance — Cluster F slice 4 (sprint-4/07): refunds + settlements.

Adds:
- ``refunds`` + ``refund_lines`` tables (per-ticket refunds, AC-07-37..40).
- ``settlements`` + ``settlement_lines`` tables (agency give-back, AC-07-45..48).

Backfill (AC-07-53): every existing tenant invoice graph gains the new refund
auto-edges (Partially Refunded / Refunded) and a refund + settlement status graph
is seeded/backfilled per tenant (seed-if-absent in update_tenant does NOT repair
a graph that already exists). Postgres only; SQLite tests use create_all + the
in-tenant install path.

Revision ID: 0005_refunds_settlements  (≤ 32 chars — alembic_version VARCHAR(32))
Revises: 0004_payment_graph_states
Create Date: 2026-06-23
"""
import app.models.utc_datetime  # noqa: F401 (UTCDateTime column type)
import sqlalchemy as sa
from alembic import op

revision = "0005_refunds_settlements"
down_revision = "0004_payment_graph_states"
branch_labels = None
depends_on = None

SCHEMA = "app_finance"
MONEY = sa.Numeric(14, 4)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite tests use create_all off the updated models
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names(schema=SCHEMA))

    if "refunds" not in tables:
        op.create_table(
            "refunds",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("invoice_id", sa.String(), nullable=False, index=True),
            sa.Column("payment_id", sa.String(), nullable=True),
            sa.Column("amount", MONEY, nullable=False, server_default="0"),
            sa.Column("method", sa.String(), nullable=False),
            sa.Column("status_id", sa.String(), nullable=True),
            sa.Column("credit_note_number", sa.String(), nullable=True, index=True),
            sa.Column("gateway_ref", sa.String(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["invoice_id"], [f"{SCHEMA}.invoices.id"]),
            schema=SCHEMA,
        )
    if "refund_lines" not in tables:
        op.create_table(
            "refund_lines",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("refund_id", sa.String(), nullable=False, index=True),
            sa.Column("ticket_id", sa.String(), nullable=False, index=True),
            sa.Column("amount", MONEY, nullable=False, server_default="0"),
            sa.ForeignKeyConstraint(["refund_id"], [f"{SCHEMA}.refunds.id"]),
            schema=SCHEMA,
        )
    if "settlements" not in tables:
        op.create_table(
            "settlements",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("project_id", sa.String(), nullable=False, index=True),
            sa.Column("client_id", sa.String(), nullable=True, index=True),
            sa.Column("kind", sa.String(), nullable=False, server_default="PRIMARY"),
            sa.Column("gross_collected", MONEY, nullable=False, server_default="0"),
            sa.Column("gateway_fees", MONEY, nullable=False, server_default="0"),
            sa.Column("fee_type", sa.String(), nullable=True),
            sa.Column("fee_amount", MONEY, nullable=False, server_default="0"),
            sa.Column("net_payable", MONEY, nullable=False, server_default="0"),
            sa.Column("status_id", sa.String(), nullable=True),
            sa.Column("remittance_ref", sa.String(), nullable=True),
            sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("remitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            schema=SCHEMA,
        )
    if "settlement_lines" not in tables:
        op.create_table(
            "settlement_lines",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("settlement_id", sa.String(), nullable=False, index=True),
            sa.Column("invoice_id", sa.String(), nullable=False, index=True),
            sa.Column("amount", MONEY, nullable=False, server_default="0"),
            sa.ForeignKeyConstraint(["settlement_id"], [f"{SCHEMA}.settlements.id"]),
            schema=SCHEMA,
        )

    # ── per-tenant GRAPH backfill (AC-07-08/43/53) ──
    from sqlalchemy.orm import Session

    from modules.finance.bootstrap import (
        INVOICE_EDGE_SEED,
        INVOICE_STATUS_SEED,
        REFUND_EDGE_SEED,
        REFUND_STATUS_SEED,
        SETTLEMENT_EDGE_SEED,
        SETTLEMENT_STATUS_SEED,
        _seed_unscoped_graph,
        backfill_graph,
    )

    sess = Session(bind=bind)
    tenant_ids = [
        r[0]
        for r in sess.execute(
            sa.text(
                "SELECT DISTINCT tenant_id FROM public.statuses "
                "WHERE entity_type = 'invoice' AND scope_id IS NULL"
            )
        )
    ]
    from modules.finance.bootstrap import _grant_new_keys_to_admin

    for tid in tenant_ids:
        # invoice gains the refund-derived auto edges
        backfill_graph(sess, "invoice", tid, INVOICE_STATUS_SEED, INVOICE_EDGE_SEED)
        # refund + settlement graphs (seed if missing, else backfill)
        _seed_unscoped_graph(sess, "refund", tid, REFUND_STATUS_SEED, REFUND_EDGE_SEED)
        backfill_graph(sess, "refund", tid, REFUND_STATUS_SEED, REFUND_EDGE_SEED)
        _seed_unscoped_graph(sess, "settlement", tid, SETTLEMENT_STATUS_SEED, SETTLEMENT_EDGE_SEED)
        backfill_graph(sess, "settlement", tid, SETTLEMENT_STATUS_SEED, SETTLEMENT_EDGE_SEED)
        # Grant sweep (AC-07-53): the new settlements.* keys reach every existing
        # tenant's Admin role here (bootstrap catalog-sync alone does NOT re-grant).
        _grant_new_keys_to_admin(sess, tid)
    sess.flush()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_table("settlement_lines", schema=SCHEMA)
    op.drop_table("settlements", schema=SCHEMA)
    op.drop_table("refund_lines", schema=SCHEMA)
    op.drop_table("refunds", schema=SCHEMA)
