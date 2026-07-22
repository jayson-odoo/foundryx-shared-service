"""autocount mapping transform formula — a safe expression per mapping row (plan 16)

One nullable column on ``ac_field_mapping``:

* ``formula`` — an optional safe transform expression over the input ``value``
  (evaluated by ``modules/autocount/formula.py``). NULL ⇒ the named ``transform``
  runs, exactly as before this revision (back-compat). Set ⇒ the formula is
  authoritative for that field's value.

    !!  EXISTENCE-CHECKED BY NECESSITY, NOT BY TASTE (the module's standing rule).  !!

``bootstrap_modules`` runs each module's ``install()`` — ``create_all`` — BEFORE
``run_module_migrations``. On a deployment already stamped at 0004, ``create_all``
cannot ALTER the existing ``ac_field_mapping`` (create_all only creates MISSING
tables), so the column is genuinely absent and must be added here. On a FRESH
deployment ``create_all`` builds the table WITH the column from the model, and an
unguarded ``add_column`` would then explode with ``DuplicateColumn``. pytest sees
NEITHER path (conftest is pure ``create_all`` and module Alembic is a
Postgres-only no-op), so a green suite proves nothing about this file — the only
gates are code review and a real ``alembic upgrade head``.

Existing rows keep ``formula = NULL`` and behave byte-identically (pinned by
``test_a_null_formula_row_behaves_exactly_as_the_named_transform``). No backfill
is needed: a formula is a purely additive operator opt-in — no existing row's
behaviour changes, so the "new column on an existing entity needs a backfill"
rule is satisfied by "NULL is the correct, behaviour-preserving value".

Revision ID: 0005_autocount_mapping_formula   (30 chars ≤ 32)
Revises: 0004_autocount_sink
Create Date: 2026-07-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision ids MUST be <= 32 chars — ``alembic_version.version_num`` is
# VARCHAR(32). "0005_autocount_mapping_formula" is 30.
revision: str = "0005_autocount_mapping_formula"
down_revision: Union[str, Sequence[str], None] = "0004_autocount_sink"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_field_mapping"
COLUMN = "formula"


def _columns() -> set:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in set(inspector.get_table_names(schema=SCHEMA)):
        return set()
    return {col["name"] for col in inspector.get_columns(TABLE, schema=SCHEMA)}


def upgrade() -> None:
    if COLUMN not in _columns():
        op.add_column(
            TABLE,
            sa.Column(COLUMN, sa.Text(), nullable=True),
            schema=SCHEMA,
        )


def downgrade() -> None:
    if COLUMN in _columns():
        op.drop_column(TABLE, COLUMN, schema=SCHEMA)
