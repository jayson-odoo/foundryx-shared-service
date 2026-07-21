"""Data backfills for `app_autocount`, kept OUT of the migration file on purpose.

    !!  MODULE ALEMBIC NEVER RUNS UNDER pytest.  !!

conftest builds the schema with ``create_all`` and ``run_module_migrations`` is a
Postgres-only no-op, so a migration's body is executed by exactly nothing in the
suite. A green run says nothing about it. Extracting the backfill into an
ordinary function means the LOGIC is testable directly (which is what actually
catches a wrong default), leaving only the DDL wrapper to be verified by review
plus a real ``alembic upgrade head`` against live Postgres.

Adding a column with a ``server_default`` populates existing rows on the ADD —
but the ADD only happens on a host where the column was missing. On a host where
``bootstrap_modules`` already ran ``install()``/``create_all`` FIRST, the column
arrives from the model with no server default, and the migration must not assume
it is populated. So the backfill is written to be correct in BOTH orders: it
fills only rows that lack a value, and is safe to run repeatedly.
"""
from __future__ import annotations

from typing import Any, Optional

import sqlalchemy as sa

from .db import AUTOCOUNT_SCHEMA
from .envelopes import ENVELOPE_STATUS_DICT
from .sources import INITIAL_LOAD_WINDOWED

# Every entity config that predates this slice is a GRN one: a dict envelope with
# a lookback-windowed first read. Those were the only semantics available, so
# they are what those rows must end up with — stated as a backfill, not left to
# a column default that a create_all-first host would never apply.
_ENTITY_CONFIG_DEFAULTS = (
    ("envelope", ENVELOPE_STATUS_DICT),
    ("initial_load", INITIAL_LOAD_WINDOWED),
)


def default_schema(bind: Any) -> Optional[str]:
    """The schema to qualify with, for the engine actually in front of us.

    Postgres owns ``app_autocount``; SQLite (the test engine) has no schemas at
    all and a qualified name would be a syntax error.
    """
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    return AUTOCOUNT_SCHEMA if dialect == "postgresql" else None


def backfill_entity_config_defaults(
    bind: Any, *, schema: Optional[str] = AUTOCOUNT_SCHEMA
) -> int:
    """Give every pre-existing ``ac_entity_config`` row an envelope and an
    initial-load policy. Returns the number of rows touched.

    Does **not** commit: on the Alembic path this runs on the migration's own
    connection and must let Alembic's transaction own the commit (a
    ``db.commit()`` on ``op.get_bind()`` mid-migration corrupts the
    ``alembic_version`` stamp — learned on the storage-migration slice).

    ``schema=None`` for SQLite, which has no schemas.
    """
    prefix = f'"{schema}".' if schema else ""
    touched = 0
    for column, value in _ENTITY_CONFIG_DEFAULTS:
        # ``column`` comes from the fixed tuple above, never from input.
        result = bind.execute(
            sa.text(
                f"UPDATE {prefix}ac_entity_config SET {column} = :value "
                f"WHERE {column} IS NULL OR {column} = ''"
            ),
            {"value": value},
        )
        touched += result.rowcount or 0
    return touched
