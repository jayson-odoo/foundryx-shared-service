"""autocount sink target - a company's outbound push destination (plan 14 hop 2)

Two columns on ``ac_company``:

* ``sink_impl``          - which consumer sink this company delivers to
                           (``logging`` no-op default, or ``sorento`` real push).
* ``sink_connection_id`` - the core ``connections.id`` of the ``consumer``
                           connection to push to (NULL for the logging sink).

    !!  EXISTING ROWS NEED A REAL BACKFILL, NOT JUST A COLUMN DEFAULT.  !!

Every ``ac_company`` row that predates this revision must end up on the
``'logging'`` sink - the behaviour it had before a push target existed. A
``server_default`` alone is not enough because of the ordering below, so the DDL
is existence-checked AND ``backfill_sink_impl_defaults`` runs unconditionally.

    !!  IDEMPOTENT BY NECESSITY, NOT BY TASTE.  !!

``bootstrap_modules`` runs each module's ``install()`` - which is ``create_all``
- BEFORE ``run_module_migrations``. On a deployment already stamped at 0003,
``create_all`` cannot ALTER the existing ``ac_company`` (create_all only creates
MISSING TABLES), so the columns are genuinely absent and must be added here. On
a FRESH deployment ``create_all`` builds the table WITH both columns from the
model, and an unguarded ``add_column`` would then explode with
``DuplicateColumn``. pytest sees neither path (conftest is pure ``create_all``
and module Alembic is a Postgres-only no-op), so a green suite proves nothing
about this file - the only gates are code review and a real
``alembic upgrade head``.

Revision ID: 0004_autocount_sink
Revises: 0003_autocount_masters
Create Date: 2026-07-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from modules.autocount.backfill import backfill_sink_impl_defaults

# Revision ids MUST be <= 32 chars - ``alembic_version.version_num`` is
# VARCHAR(32). "0004_autocount_sink" is 19.
revision: str = "0004_autocount_sink"
down_revision: Union[str, Sequence[str], None] = "0003_autocount_masters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_company"


def _columns() -> set:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in set(inspector.get_table_names(schema=SCHEMA)):
        return set()
    return {col["name"] for col in inspector.get_columns(TABLE, schema=SCHEMA)}


def _indexes() -> set:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in set(inspector.get_table_names(schema=SCHEMA)):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(TABLE, schema=SCHEMA)}


def add_column(name: str, column: sa.Column) -> None:
    """Existence-checked ADD - see the module docstring for why this is not
    optional. A bare ``op.add_column`` below should be rejected on sight."""
    if name not in _columns():
        op.add_column(TABLE, column, schema=SCHEMA)


def upgrade() -> None:
    add_column(
        "sink_impl",
        sa.Column(
            "sink_impl",
            sa.String(),
            nullable=False,
            server_default="logging",
        ),
    )
    add_column(
        "sink_connection_id",
        sa.Column("sink_connection_id", sa.String(), nullable=True),
    )
    if (
        "sink_connection_id" in _columns()
        and "ix_ac_company_sink_connection_id" not in _indexes()
    ):
        op.create_index(
            "ix_ac_company_sink_connection_id",
            TABLE,
            ["sink_connection_id"],
            unique=False,
            schema=SCHEMA,
        )
    # Runs on BOTH orderings (see the docstring): after an ADD it is a no-op
    # because the server default already populated the rows; after a
    # create_all-first host it is the only thing that populates them.
    backfill_sink_impl_defaults(op.get_bind(), schema=SCHEMA)


def downgrade() -> None:
    existing = _columns()
    if "sink_connection_id" in existing:
        if "ix_ac_company_sink_connection_id" in _indexes():
            op.drop_index(
                "ix_ac_company_sink_connection_id",
                table_name=TABLE,
                schema=SCHEMA,
            )
        op.drop_column(TABLE, "sink_connection_id", schema=SCHEMA)
    if "sink_impl" in existing:
        op.drop_column(TABLE, "sink_impl", schema=SCHEMA)
