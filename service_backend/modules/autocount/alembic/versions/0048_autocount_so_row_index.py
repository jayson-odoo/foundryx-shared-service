"""autocount SO-row index (lane AUTOCOUNT-STRANDED-OPS, C.d)

* ``ac_so_row_index``: one row per line (``DtlKey``) of a sales order's NEWEST staged copy (every copy
  staged at that same newest moment), with the SO number and the line's location; ``ambiguous`` = equally
  new copies disagree on the location. The unlink snapshot (the SO number of a PO row that reads back
  without ``FromDocNo``) and the relocate (the SO row's location) become one indexed query instead of
  loading every staged sales order into the request. Two indexes: (tenant, company, so_dtl_key) for the
  lookups, (tenant, company, so_source_ref) for the per-SO rewrite.
* ``ix_ac_staged_doc_no`` on ``ac_staged_record`` (tenant, company, entity_type, doc_no): the SPO re-stage
  finds the POs its lines name by number instead of loading every staged PO.
* BACKFILL: every existing SO gets its rows from its newest staged copies (an SO whose newest row is a
  live delete intent gets none; a discarded intent is ignored). Read through a frozen ``sa.table``;
  streamed; never commits.

Revision ID: 0048_autocount_so_row_index   (27 chars <= 32)
Revises: 0047_autocount_spo_po_link
Create Date: 2026-11-17
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0048_autocount_so_row_index"
down_revision: Union[str, Sequence[str], None] = "0047_autocount_spo_po_link"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_so_row_index"
ENTITY_SALES_ORDER = "sales_order"
CHUNK = 2000

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
index = sa.table(
    TABLE,
    sa.column("id", sa.String),
    sa.column("tenant_id", sa.String),
    sa.column("company_id", sa.String),
    sa.column("so_source_ref", sa.String),
    sa.column("so_doc_no", sa.String),
    sa.column("so_dtl_key", sa.BigInteger),
    sa.column("location", sa.String),
    sa.column("ambiguous", sa.Boolean),
    sa.column("staged_at", sa.DateTime(timezone=True)),
    schema=SCHEMA,
)


def _int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def rows_of(tenant_id, company_id, source_ref, doc_no, staged_at, copies):
    """The index rows of one SO's equally-newest copies (mirrors ``link_index.so_rows_of``)."""
    seen = {}
    for raw in copies:
        lines = (raw or {}).get("_lines") if isinstance(raw, dict) else None
        for line in lines if isinstance(lines, list) else []:
            if not isinstance(line, dict):
                continue
            key = _int(line.get("DtlKey"))
            if key:
                seen.setdefault(key, set()).add(str(line.get("Location") or ""))
    first = next((r for r in copies if isinstance(r, dict)), {}) or {}
    number = str(first.get("DocNo") or doc_no or "")
    return [{
        "id": str(uuid.uuid4()), "tenant_id": tenant_id, "company_id": company_id, "so_source_ref": source_ref,
        "so_doc_no": number, "so_dtl_key": key, "location": next(iter(locs)) if len(locs) == 1 else None,
        "ambiguous": len(locs) > 1, "staged_at": staged_at,
    } for key, locs in seen.items()]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # tolerant of a table created ahead of this revision (the crew test copy's idempotent SQL): create if absent,
    # then rebuild the rows from scratch
    if not sa.inspect(bind).has_table(TABLE, schema=SCHEMA):
        _create()
    op.create_index("ix_ac_so_row_index_dtl", TABLE, ["tenant_id", "company_id", "so_dtl_key"], schema=SCHEMA,
                    if_not_exists=True)
    op.create_index("ix_ac_so_row_index_so_ref", TABLE, ["tenant_id", "company_id", "so_source_ref"], schema=SCHEMA,
                    if_not_exists=True)
    # the SPO re-stage finds the POs its lines name by number (write_back/doc_mapping._po_dtl_lookup)
    op.create_index("ix_ac_staged_doc_no", "ac_staged_record", ["tenant_id", "company_id", "entity_type", "doc_no"],
                    schema=SCHEMA, if_not_exists=True)
    bind.execute(sa.delete(index))
    _backfill(bind)


def _create() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("so_source_ref", sa.String(), nullable=False),
        sa.Column("so_doc_no", sa.String(), nullable=True),
        sa.Column("so_dtl_key", sa.BigInteger(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("ambiguous", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("staged_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )


def _backfill(bind) -> None:

    # backfill: per SO, the rows ranked newest (dense_rank keeps equally new copies), ignoring discarded delete
    # intents; an SO whose newest rank holds a live delete intent gets nothing (as refresh(deleted=True) leaves it)
    ranked = (
        sa.select(
            staged.c.tenant_id, staged.c.company_id, staged.c.source_ref, staged.c.doc_no, staged.c.op,
            staged.c.raw_json, staged.c.created_at,
            sa.func.dense_rank().over(
                partition_by=(staged.c.tenant_id, staged.c.company_id, staged.c.source_ref),
                order_by=staged.c.created_at.desc(),
            ).label("rnk"),
        )
        .where(
            staged.c.entity_type == ENTITY_SALES_ORDER,
            sa.not_(sa.and_(staged.c.op == "delete", staged.c.status == "DISCARDED")),
        )
        .subquery()
    )
    newest = (
        sa.select(ranked.c.tenant_id, ranked.c.company_id, ranked.c.source_ref, ranked.c.doc_no, ranked.c.op,
                  ranked.c.raw_json, ranked.c.created_at)
        .where(ranked.c.rnk == 1)
        .order_by(ranked.c.tenant_id, ranked.c.company_id, ranked.c.source_ref)
    )
    batch = []
    current, group = None, []

    def flush_group():
        if current is None or any(g[4] == "delete" for g in group):
            return []
        tenant_id, company_id, source_ref = current
        return rows_of(tenant_id, company_id, source_ref, group[0][3], group[0][6], [g[5] for g in group])

    for row in bind.execute(newest).yield_per(500):
        key = (row[0], row[1], row[2])
        if key != current:
            batch.extend(flush_group())
            current, group = key, []
        group.append(row)
        if len(batch) >= CHUNK:
            bind.execute(sa.insert(index), batch)
            batch = []
    batch.extend(flush_group())
    for start in range(0, len(batch), CHUNK):
        bind.execute(sa.insert(index), batch[start:start + CHUNK])
    bind.execute(sa.text(f"ANALYZE {SCHEMA}.{TABLE}"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_index("ix_ac_staged_doc_no", table_name="ac_staged_record", schema=SCHEMA, if_exists=True)
    op.drop_index("ix_ac_so_row_index_so_ref", table_name=TABLE, schema=SCHEMA)
    op.drop_index("ix_ac_so_row_index_dtl", table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
