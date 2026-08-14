"""autocount masters - per-entity response envelope + initial-load policy

Two columns on ``ac_entity_config``:

* ``envelope``     - which OUTER response shape this entity returns
                     (``status_dict`` for GRN, ``row_array`` for masters).
* ``initial_load`` - whether the FIRST sync is ``windowed`` (a document stream)
                     or ``full`` (a master list, which must be mirrored whole).

    !!  EXISTING ROWS NEED A REAL BACKFILL, NOT JUST A COLUMN DEFAULT.  !!

Every row that predates this revision is a GRN one and must end up
``status_dict``/``windowed``. A ``server_default`` alone is not enough, because
of the ordering below: on a host where the column already arrived via
``create_all`` there is no ADD to carry the default, and the rows would sit NULL
against a model that declares the column NOT NULL. So the DDL is
existence-checked AND ``backfill_entity_config_defaults`` runs unconditionally.

    !!  IDEMPOTENT BY NECESSITY, NOT BY TASTE.  !!

``bootstrap_modules`` runs each module's ``install()`` - which is ``create_all``
- BEFORE ``run_module_migrations``. On a deployment already stamped at 0002,
``create_all`` cannot ALTER the existing ``ac_entity_config`` (create_all only
creates MISSING TABLES), so the columns are genuinely absent and must be added
here. On a FRESH deployment ``create_all`` builds the table WITH both columns
from the model, and an unguarded ``add_column`` would then explode with
``DuplicateColumn``. pytest sees neither path (conftest is pure ``create_all``
and module Alembic is a Postgres-only no-op), so a green suite proves nothing
about this file - the only gates are code review and a real
``alembic upgrade head``.

Revision ID: 0003_autocount_masters
Revises: 0002_autocount_grn
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from modules.autocount.backfill import backfill_entity_config_defaults
from modules.autocount.envelopes import ENVELOPE_STATUS_DICT
from modules.autocount.sources import INITIAL_LOAD_WINDOWED

# Revision ids MUST be <= 32 chars - ``alembic_version.version_num`` is
# VARCHAR(32). "0003_autocount_masters" is 22.
revision: str = "0003_autocount_masters"
down_revision: Union[str, Sequence[str], None] = "0002_autocount_grn"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_entity_config"


def _columns() -> set:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in set(inspector.get_table_names(schema=SCHEMA)):
        return set()
    return {col["name"] for col in inspector.get_columns(TABLE, schema=SCHEMA)}


def add_column(name: str, column: sa.Column) -> None:
    """Existence-checked ADD - see the module docstring for why this is not
    optional. A bare ``op.add_column`` below should be rejected on sight."""
    if name not in _columns():
        op.add_column(TABLE, column, schema=SCHEMA)


def upgrade() -> None:
    add_column(
        "envelope",
        sa.Column(
            "envelope",
            sa.String(),
            nullable=False,
            server_default=ENVELOPE_STATUS_DICT,
        ),
    )
    add_column(
        "initial_load",
        sa.Column(
            "initial_load",
            sa.String(),
            nullable=False,
            server_default=INITIAL_LOAD_WINDOWED,
        ),
    )
    # Runs on BOTH orderings (see the docstring): after an ADD it is a no-op
    # because the server default already populated the rows; after a
    # create_all-first host it is the only thing that populates them.
    backfill_entity_config_defaults(op.get_bind(), schema=SCHEMA)


def downgrade() -> None:
    existing = _columns()
    for name in ("initial_load", "envelope"):
        if name in existing:
            op.drop_column(TABLE, name, schema=SCHEMA)
