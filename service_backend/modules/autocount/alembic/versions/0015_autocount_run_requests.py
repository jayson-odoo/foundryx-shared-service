"""autocount push request accounting + offer starvation guard (fix/push-marks-per-chunk)

Prod finding 2026-09-07 (Sorento api_call_log, sales_order task): a lone 502
from Sorento's own nginx on roughly 1 in 25 chunk POSTs discarded every OTHER
chunk's verdict too (``write_batch``'s old all-or-nothing contract), so a
clean run's own marks were lost and the Runs list showed ``pushed_count 0`` /
``error NULL`` with no way to tell a chunk-level fault had even happened. The
push is now per-CHUNK (marks + commit as each chunk resolves - the service
layer, unchanged by this migration) and needs somewhere to persist what it
saw:

* ``ac_sync_run`` += ``requests`` / ``requests_failed`` (how many chunk POSTs
  this run's push made, how many failed) and ``first_failure`` (JSON -
  ``{status, message}``, the first one's account).
* ``ac_staged_record`` += ``last_offered_at`` - the starvation guard:
  stamped on every offer so a permanently ``retryable`` head of the
  oldest-first queue cannot starve a fresh row forever
  (``list_pending_for_entity`` orders ``last_offered_at`` NULLS FIRST).

Every column is NULLABLE with no server default - a pre-existing run/staged
row simply carries no accounting/offer history, which is the correct reading
(nothing forces a backfill value onto history that was never measured).
Existence-checked ADDs (0007's discipline): a ``create_all``-first host
already has these from the model.

Revision ID: 0015_autocount_run_requests   (28 chars <= 32)
Revises: 0014_autocount_db_entity_source
Create Date: 2026-09-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.utc_datetime  # noqa: F401 - UTCDateTime columns
from app.models.utc_datetime import UTCDateTime

revision: str = "0015_autocount_run_requests"
down_revision: Union[str, Sequence[str], None] = "0014_autocount_db_entity_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"


def _columns(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names(schema=SCHEMA)):
        return set()
    return {col["name"] for col in inspector.get_columns(table, schema=SCHEMA)}


def add_column(table: str, column: sa.Column) -> None:
    """Existence-checked ADD - a bare ``op.add_column`` below should be
    rejected on sight (see the module docstring)."""
    if column.name not in _columns(table):
        op.add_column(table, column, schema=SCHEMA)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    add_column("ac_sync_run", sa.Column("requests", sa.Integer(), nullable=True))
    add_column("ac_sync_run", sa.Column("requests_failed", sa.Integer(), nullable=True))
    add_column("ac_sync_run", sa.Column("first_failure", sa.JSON(none_as_null=True), nullable=True))

    add_column("ac_staged_record", sa.Column("last_offered_at", UTCDateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table, columns in (
        ("ac_sync_run", ("requests", "requests_failed", "first_failure")),
        ("ac_staged_record", ("last_offered_at",)),
    ):
        existing = _columns(table)
        for column in columns:
            if column in existing:
                op.drop_column(table, column, schema=SCHEMA)
