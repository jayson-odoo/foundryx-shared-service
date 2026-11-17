"""autocount SPO -> PO-row index (lane AUTOCOUNT-STRANDED-OPS, C.d)

* ``ac_spo_po_link``: one row per line (``FromDocDtlKey``) of a shipping purchase order's NEWEST
  staged copy, so the ROW_ON_SPO guard and the SPO over-link sum are one indexed query instead of
  loading every staged SPO into the request (prod 17 Nov: that load ran a worker past its timeout).
  Two indexes: (tenant, company, po_dtl_key) for the lookups, (tenant, company, spo_source_ref) for
  the per-SPO rewrite.
* BACKFILL: every existing SPO gets its rows from its newest staged copy (a cancelled SPO or an SPO with
  a live delete intent gets none; a discarded intent is ignored). Read through a frozen ``sa.table``;
  never commits.

Revision ID: 0047_autocount_spo_po_link   (27 chars <= 32)
Revises: 0046_autocount_call_person
Create Date: 2026-11-17
"""
import uuid
from decimal import Decimal, InvalidOperation
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0047_autocount_spo_po_link"
down_revision: Union[str, Sequence[str], None] = "0046_autocount_call_person"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_spo_po_link"
ENTITY_SHIPPING_ORDER = "shipping_order"
CHUNK = 1000

staged = sa.table(
    "ac_staged_record",
    sa.column("id", sa.String),
    sa.column("tenant_id", sa.String),
    sa.column("company_id", sa.String),
    sa.column("entity_type", sa.String),
    sa.column("source_ref", sa.String),
    sa.column("doc_no", sa.String),
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
    sa.column("spo_source_ref", sa.String),
    sa.column("spo_doc_no", sa.String),
    sa.column("spo_dtl_key", sa.BigInteger),
    sa.column("po_dtl_key", sa.BigInteger),
    sa.column("qty", sa.Numeric(20, 8)),
    schema=SCHEMA,
)


def _int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def rows_of(tenant_id, company_id, source_ref, doc_no, raw):
    """The index rows of one SPO's newest staged copy (mirrors ``link_index.spo_links_of``)."""
    if not isinstance(raw, dict) or raw.get("Cancelled") == "T":
        return []
    number = str(raw.get("DocNo") or doc_no or source_ref)
    out = []
    for line in raw.get("_lines") or []:
        if not isinstance(line, dict):
            continue
        po_key = _int(line.get("FromDocDtlKey"))
        if not po_key:
            continue
        try:
            qty = Decimal(str(line.get("Qty") if line.get("Qty") is not None else 0))
        except InvalidOperation:
            qty = Decimal(0)
        out.append({
            "id": str(uuid.uuid4()), "tenant_id": tenant_id, "company_id": company_id,
            "spo_source_ref": source_ref, "spo_doc_no": number, "spo_dtl_key": _int(line.get("DtlKey")),
            "po_dtl_key": po_key, "qty": qty,
        })
    return out


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # tolerant of a table created ahead of this revision (the crew test copy's idempotent SQL): create if absent,
    # then rebuild the rows from scratch
    if not sa.inspect(bind).has_table(TABLE, schema=SCHEMA):
        _create()
    op.create_index("ix_ac_spo_po_link_po_dtl", TABLE, ["tenant_id", "company_id", "po_dtl_key"], schema=SCHEMA,
                    if_not_exists=True)
    op.create_index("ix_ac_spo_po_link_spo_ref", TABLE, ["tenant_id", "company_id", "spo_source_ref"], schema=SCHEMA,
                    if_not_exists=True)
    bind.execute(sa.delete(link))
    _backfill(bind)


def _create() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("spo_source_ref", sa.String(), nullable=False),
        sa.Column("spo_doc_no", sa.String(), nullable=True),
        sa.Column("spo_dtl_key", sa.BigInteger(), nullable=True),
        sa.Column("po_dtl_key", sa.BigInteger(), nullable=False),
        sa.Column("qty", sa.Numeric(20, 8), nullable=False),
        schema=SCHEMA,
    )


def _backfill(bind) -> None:

    # backfill: the newest staged row of each SPO that is not a discarded delete intent (as the runtime
    # newest() reads it); a live delete intent or a cancelled SPO adds nothing. Streamed, inserted in chunks.
    newest = (
        sa.select(
            staged.c.tenant_id, staged.c.company_id, staged.c.source_ref, staged.c.doc_no, staged.c.op,
            staged.c.raw_json,
        )
        .where(
            staged.c.entity_type == ENTITY_SHIPPING_ORDER,
            sa.not_(sa.and_(staged.c.op == "delete", staged.c.status == "DISCARDED")),
        )
        .distinct(staged.c.tenant_id, staged.c.company_id, staged.c.source_ref)
        .order_by(staged.c.tenant_id, staged.c.company_id, staged.c.source_ref,
                  staged.c.created_at.desc(), staged.c.id)
    )
    batch = []
    for tenant_id, company_id, source_ref, doc_no, row_op, raw in bind.execute(newest).yield_per(500):
        if row_op == "delete":
            continue
        batch.extend(rows_of(tenant_id, company_id, source_ref, doc_no, raw))
        if len(batch) >= CHUNK:
            bind.execute(sa.insert(link), batch)
            batch = []
    if batch:
        bind.execute(sa.insert(link), batch)
    # fresh statistics, so the very first lookup plans on the po_dtl_key index (both indexes lead with
    # tenant + company; with no stats the planner can pick the wrong one and walk the company's rows)
    bind.execute(sa.text(f"ANALYZE {SCHEMA}.{TABLE}"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_index("ix_ac_spo_po_link_spo_ref", table_name=TABLE, schema=SCHEMA)
    op.drop_index("ix_ac_spo_po_link_po_dtl", table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
