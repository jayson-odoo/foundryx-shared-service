"""Line fingerprint sweep table + watermark column (feat/line-fingerprint-sweep)

Prod finding: SO419208 (DocKey 45672056) had a delivery transfer after our
initial staging. AutoCount updates ``SODTL.TransferedQty`` WITHOUT bumping
``SO.LastModified``, the SODTL ``Last*Modified`` stamps are NULL and the ESB
login cannot read DO/DODTL, so an incremental run (``LastModified > :since``)
never sees the change and the CRM copy stays stale until the daily reconcile.

This migration ships the two pieces of state the sweep needs:

* ``ac_doc_fingerprint(tenant_id, company_id, entity_type, source_ref,
  fingerprint, seen_at)`` - one row per document header ever seen by an
  incremental sweep, holding the sha256 of its OWN fingerprint query's
  ordered aggregate values (``sql_source.hashing.document_fingerprint``).
  Deliberately a separate table from ``ac_row_hash``: this fingerprint
  refreshes on every sweep tick regardless of whether the header's own
  row hash changed.
* ``ac_watermark.last_fingerprint_sweep_at`` - when the sweep last ran
  cleanly for a task; ``NULL``/older than
  ``settings.autocount_fingerprint_sweep_minutes`` means due.

Then ``backfill_document_fingerprint_queries`` (see that function's own
docstring, ``modules/autocount/backfill.py``) sets
``source_config["fingerprintQuery"]`` from the entity's own preset on
every EXISTING document task that has none yet - a task saved before this
lane never selected a fingerprint query, so without this it simply never
sweeps (silent, not broken, but pointless to ship a repair nobody's
existing tasks pick up).

    !!  FROZEN ``sa.table`` BACKFILL - NEVER THE LIVE ORM MODEL.  !!
Same rule, same incident, as 0016's ``backfill_shipping_order_container_
number``: this runs from module Alembic 0017 and must survive a FUTURE
migration adding columns to ``ac_entity_config``/``ac_company`` on a
fresh ``0001`` -> head replay
(``documentation/engineering/storage-and-background-jobs.md``, module
Alembic 0006 incident). ``backfill_document_fingerprint_queries``
therefore selects/updates through frozen ``sa.table`` snapshots naming
only the columns it needs, and is schema-tolerant on its own
(``existing_columns`` first).

Revision ID: 0017_autocount_fingerprint   (25 chars <= 32)
Revises: 0016_autocount_spo_container
Create Date: 2026-09-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime  # noqa: F401 - UTCDateTime columns
from app.models.utc_datetime import UTCDateTime
from modules.autocount.backfill import backfill_document_fingerprint_queries

revision: str = "0017_autocount_fingerprint"
down_revision: Union[str, Sequence[str], None] = "0016_autocount_spo_container"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"


def _tables() -> set:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names(schema=SCHEMA))


def _columns(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if table not in _tables():
        return set()
    return {col["name"] for col in inspector.get_columns(table, schema=SCHEMA)}


def add_column(table: str, column: sa.Column) -> None:
    """Existence-checked ADD - a ``create_all``-first host already has this
    from the model."""
    if column.name not in _columns(table):
        op.add_column(table, column, schema=SCHEMA)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    if "ac_doc_fingerprint" not in _tables():
        op.create_table(
            "ac_doc_fingerprint",
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("company_id", sa.String(), nullable=False),
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("source_ref", sa.String(), nullable=False),
            sa.Column("fingerprint", sa.String(), nullable=False),
            sa.Column(
                "seen_at", UTCDateTime(), server_default=sa.text("now()"), nullable=False
            ),
            sa.PrimaryKeyConstraint("tenant_id", "company_id", "entity_type", "source_ref"),
            schema=SCHEMA,
        )
        op.create_index(
            "ix_ac_doc_fingerprint_scope",
            "ac_doc_fingerprint",
            ["tenant_id", "company_id", "entity_type"],
            schema=SCHEMA,
        )

    add_column("ac_watermark", sa.Column("last_fingerprint_sweep_at", UTCDateTime(), nullable=True))

    backfill_document_fingerprint_queries(bind, schema=SCHEMA)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    existing = _columns("ac_watermark")
    if "last_fingerprint_sweep_at" in existing:
        op.drop_column("ac_watermark", "last_fingerprint_sweep_at", schema=SCHEMA)
    if "ac_doc_fingerprint" in _tables():
        op.drop_table("ac_doc_fingerprint", schema=SCHEMA)
