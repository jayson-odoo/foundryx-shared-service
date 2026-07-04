"""finance Cluster F slice 1 (sprint-4/07) — payments table + invoice depth cols
+ legacy backfill (AC-07-08/09/15/16).

Adds:
- ``payments`` table (manual + reserved gateway columns).
- invoice columns: invoice_number / issued_at / due_date / notes + reserved
  e-invoice fields (buyer_tin / sst_reg_no / tax_code / einvoice_type).
- invoice_line columns: tax_rate / tax_amount.

Backfill (AC-07-08/53): any legacy invoice row with status_id NULL is set to its
tenant's Draft status (so transition-from-None never 500s); each tenant's invoice
status graph gets the new states/auto-edges + the payment graph (handled by the
finance ``update_tenant`` self-heal run from ``bootstrap_modules`` — this
migration only repairs the ROW-level data Alembic can reach idempotently).

Revision ID: 0003_finance_cluster_f  (≤ 32 chars — alembic_version is VARCHAR(32))
Revises: 0002_finance_money_numeric
Create Date: 2026-06-23
"""
import app.models.utc_datetime  # noqa: F401 (UTCDateTime column type)
import sqlalchemy as sa
from alembic import op

revision = "0003_finance_cluster_f"
down_revision = "0002_finance_money_numeric"
branch_labels = None
depends_on = None

SCHEMA = "app_finance"
MONEY = sa.Numeric(14, 4)
RATE = sa.Numeric(6, 4)


def _has_column(insp, table: str, col: str) -> bool:
    return any(c["name"] == col for c in insp.get_columns(table, schema=SCHEMA))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite tests use create_all off the updated model
    insp = sa.inspect(bind)

    # ── payments table ──
    if "payments" not in insp.get_table_names(schema=SCHEMA):
        op.create_table(
            "payments",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("invoice_id", sa.String(), nullable=False, index=True),
            sa.Column("amount", MONEY, nullable=False, server_default="0"),
            sa.Column("method", sa.String(), nullable=False),
            sa.Column("status_id", sa.String(), nullable=True),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("gateway_connection_id", sa.String(), nullable=True),
            sa.Column("external_ref", sa.String(), nullable=True),
            sa.Column("external_payment_id", sa.String(), nullable=True),
            sa.Column("gateway_fee", MONEY, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["invoice_id"], [f"{SCHEMA}.invoices.id"]),
            schema=SCHEMA,
        )

    # ── invoice columns ──
    inv_cols = [
        ("invoice_number", sa.String(), True),
        ("issued_at", sa.DateTime(timezone=True), True),
        ("due_date", sa.DateTime(timezone=True), True),
        ("notes", sa.Text(), True),
        ("buyer_tin", sa.String(), True),
        ("sst_reg_no", sa.String(), True),
        ("tax_code", sa.String(), True),
        ("einvoice_type", sa.String(), True),
    ]
    for name, type_, nullable in inv_cols:
        if not _has_column(insp, "invoices", name):
            op.add_column("invoices", sa.Column(name, type_, nullable=nullable), schema=SCHEMA)
    op.create_index(
        "ix_invoices_invoice_number", "invoices", ["invoice_number"], schema=SCHEMA, if_not_exists=True
    )

    # ── invoice_line columns ──
    if not _has_column(insp, "invoice_lines", "tax_rate"):
        op.add_column("invoice_lines", sa.Column("tax_rate", RATE, nullable=False, server_default="0"), schema=SCHEMA)
    if not _has_column(insp, "invoice_lines", "tax_amount"):
        op.add_column("invoice_lines", sa.Column("tax_amount", MONEY, nullable=False, server_default="0"), schema=SCHEMA)
    # Backfill tax_amount from the legacy ``tax`` column on existing lines.
    op.execute(f'UPDATE "{SCHEMA}".invoice_lines SET tax_amount = tax WHERE tax_amount = 0 AND tax <> 0')

    # ── per-tenant GRAPH backfill (AC-07-08): every existing tenant invoice graph
    # gains the new states (Void / Partially Paid / Paid / Overdue / Refunded) +
    # auto-edges, and the payment graph is seeded if missing. seed-if-absent does
    # NOT repair an existing partial graph — call the module's backfill_graph for
    # each tenant that already has an invoice graph. ──
    from sqlalchemy.orm import Session

    from modules.finance.bootstrap import (
        INVOICE_EDGE_SEED,
        INVOICE_STATUS_SEED,
        PAYMENT_EDGE_SEED,
        PAYMENT_STATUS_SEED,
        _seed_unscoped_graph,
        backfill_graph,
    )

    # Join the migration's own transaction (do NOT commit — the alembic
    # transaction owns it; flush is enough to emit the inserts).
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
    for tid in tenant_ids:
        backfill_graph(sess, "invoice", tid, INVOICE_STATUS_SEED, INVOICE_EDGE_SEED)
        _seed_unscoped_graph(sess, "payment", tid, PAYMENT_STATUS_SEED, PAYMENT_EDGE_SEED)
    sess.flush()

    # ── legacy row backfill (AC-07-08): status_id NULL → the tenant's Draft ──
    op.execute(
        f"""
        UPDATE "{SCHEMA}".invoices inv
        SET status_id = s.id
        FROM public.statuses s
        WHERE inv.status_id IS NULL
          AND s.entity_type = 'invoice'
          AND s.tenant_id = inv.tenant_id
          AND s.scope_id IS NULL
          AND s.key = 'draft'
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_table("payments", schema=SCHEMA)
    op.drop_index("ix_invoices_invoice_number", table_name="invoices", schema=SCHEMA, if_exists=True)
    for name in (
        "invoice_number", "issued_at", "due_date", "notes",
        "buyer_tin", "sst_reg_no", "tax_code", "einvoice_type",
    ):
        op.drop_column("invoices", name, schema=SCHEMA)
    for name in ("tax_rate", "tax_amount"):
        op.drop_column("invoice_lines", name, schema=SCHEMA)
