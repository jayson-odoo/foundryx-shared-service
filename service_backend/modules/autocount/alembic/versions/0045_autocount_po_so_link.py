"""autocount over-link index (plan 62 D8)

* ``ac_po_so_link``: one row per linked line (``FromSODtlKey``) of a purchase order's NEWEST
  staged copy, so the over-link check sums an indexed table instead of walking every staged PO
  (and counts a PO's history copies once). Two indexes: (tenant, company, so_dtl_key) for the
  sum, (tenant, company, po_source_ref) for the per-PO rewrite.
* BACKFILL: every existing PO gets its rows from its newest staged copy (a cancelled PO or a PO with a live delete intent gets none; a discarded intent is ignored). Read through a frozen ``sa.table``; never commits.

Revision ID: 0045_autocount_po_so_link   (26 chars <= 32)
Revises: 0044_autocount_api_call_log
Create Date: 2026-11-11
"""
import uuid
from decimal import Decimal, InvalidOperation
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0045_autocount_po_so_link"
down_revision: Union[str, Sequence[str], None] = "0044_autocount_api_call_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_po_so_link"
ENTITY_PURCHASE_ORDER = "purchase_order"
CHUNK = 1000

staged = sa.table(
    "ac_staged_record",
    sa.column("id", sa.String),
    sa.column("tenant_id", sa.String),
    sa.column("company_id", sa.String),
    sa.column("entity_type", sa.String),
    sa.column("source_ref", sa.String),
    sa.column("op", sa.String),
    sa.column("status", sa.String),
    sa.column("raw_json", sa.JSON),
    sa.column("created_at", sa.DateTime(timezone=True)),
    schema=SCHEMA,
)
link = sa.table(
    TABLE,
    sa.column("id", sa.String),
    sa.column("tenant_id", sa.String),
    sa.column("company_id", sa.String),
    sa.column("po_source_ref", sa.String),
    sa.column("po_dtl_key", sa.BigInteger),
    sa.column("so_dtl_key", sa.BigInteger),
    sa.column("qty", sa.Numeric(20, 8)),
    schema=SCHEMA,
)


def _int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("po_source_ref", sa.String(), nullable=False),
        sa.Column("po_dtl_key", sa.BigInteger(), nullable=True),
        sa.Column("so_dtl_key", sa.BigInteger(), nullable=False),
        sa.Column("qty", sa.Numeric(20, 8), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_ac_po_so_link_so_dtl", TABLE, ["tenant_id", "company_id", "so_dtl_key"], schema=SCHEMA)
    op.create_index("ix_ac_po_so_link_po_ref", TABLE, ["tenant_id", "company_id", "po_source_ref"], schema=SCHEMA)

    # backfill: the newest staged row of each PO that is not a discarded delete intent (as the runtime newest()
    # reads it); a live delete intent or a cancelled PO adds nothing
    newest = (
        sa.select(
            staged.c.tenant_id, staged.c.company_id, staged.c.source_ref, staged.c.op, staged.c.raw_json,
            staged.c.status,
        )
        .where(
            staged.c.entity_type == ENTITY_PURCHASE_ORDER,
            # a cancelled (DISCARDED) delete intent is ignored; every other row counts, as the runtime newest() reads
            sa.not_(sa.and_(staged.c.op == "delete", staged.c.status == "DISCARDED")),
        )
        .distinct(staged.c.tenant_id, staged.c.company_id, staged.c.source_ref)
        .order_by(staged.c.tenant_id, staged.c.company_id, staged.c.source_ref,
                  staged.c.created_at.desc(), staged.c.id)
    )
    batch = []
    for tenant_id, company_id, source_ref, row_op, raw, _status in bind.execute(newest).yield_per(500):
        if row_op == "delete" or not isinstance(raw, dict) or raw.get("Cancelled") == "T":
            continue
        for line in raw.get("_lines") or []:
            if not isinstance(line, dict):
                continue
            so_key = _int(line.get("FromSODtlKey"))
            if not so_key:
                continue
            try:
                qty = Decimal(str(line.get("Qty") if line.get("Qty") is not None else 0))
            except InvalidOperation:
                continue
            if qty <= 0:
                continue
            batch.append({
                "id": str(uuid.uuid4()), "tenant_id": tenant_id, "company_id": company_id,
                "po_source_ref": source_ref, "po_dtl_key": _int(line.get("DtlKey")),
                "so_dtl_key": so_key, "qty": qty,
            })
    for start in range(0, len(batch), CHUNK):
        bind.execute(sa.insert(link), batch[start:start + CHUNK])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_index("ix_ac_po_so_link_po_ref", table_name=TABLE, schema=SCHEMA)
    op.drop_index("ix_ac_po_so_link_so_dtl", table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
