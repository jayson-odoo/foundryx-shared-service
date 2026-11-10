"""Backfill helpers must tolerate a schema an OLDER module stamp does not carry.

Production incident (2026-09-06): module migration 0007 calls the SHARED helper
``backfill_etl_defaults`` (``modules/autocount/backfill.py``). Its
``_ETL_DEFAULTS`` tuple now also names ``ac_sync_run.added_count`` /
``updated_count`` (columns 0008 adds LATER) and ``ac_entity_config.etl_status``.
On a host whose module stamp predates a column, ``UPDATE ... SET <col>`` raises
``UndefinedColumn``, 0007 fails, ``bootstrap_modules`` swallows it, and the host
is stranded (prod log: ``column "etl_status" does not exist`` from
``update_tenant`` / company create).

The helpers are shared across migrations and the install path, so each must
skip a column (or a whole table) the bind does not have and still fill what IS
there. Today they raise ``sqlalchemy.exc.OperationalError`` on SQLite for a
missing column, so these are red.

Built on a plain SQLite engine with raw DDL (no ORM metadata, no schema): the
tables carry exactly the columns the helpers reference, minus the ones each
scenario withholds - the same shape an older stamp leaves behind.
"""
from __future__ import annotations

from typing import Iterable, Optional

import pytest
import sqlalchemy as sa

from modules.autocount.backfill import (
    backfill_entity_config_defaults,
    backfill_etl_defaults,
    backfill_sink_impl_defaults,
)

# ── the columns each helper touches, per table ─────────────────────────────

FULL_COLUMNS = {
    "ac_company": ("sink_impl",),
    "ac_entity_config": ("envelope", "initial_load", "etl_status"),
    "ac_staged_record": ("op",),
    "ac_sync_run": ("mode", "rows_scanned", "deleted_count", "added_count", "updated_count"),
}
_NUMERIC = {"rows_scanned", "deleted_count", "added_count", "updated_count"}


def _build(
    *,
    without_columns: Iterable[str] = (),
    without_tables: Iterable[str] = (),
) -> sa.engine.Engine:
    """A fresh in-memory SQLite engine carrying every helper-referenced table
    and column EXCEPT the ones withheld (``table.column`` / table names)."""
    engine = sa.create_engine("sqlite://")
    withheld_columns = set(without_columns)
    withheld_tables = set(without_tables)
    with engine.begin() as conn:
        for table, columns in FULL_COLUMNS.items():
            if table in withheld_tables:
                continue
            kept = [c for c in columns if f"{table}.{c}" not in withheld_columns]
            defs = "".join(
                f", {c} {'INTEGER' if c in _NUMERIC else 'VARCHAR(50)'}" for c in kept
            )
            conn.execute(sa.text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY{defs})"))
    return engine


def _insert(conn: sa.Connection, table: str, **values: Optional[object]) -> None:
    cols = ", ".join(values)
    params = ", ".join(f":{c}" for c in values)
    conn.execute(sa.text(f"INSERT INTO {table} ({cols}) VALUES ({params})"), values)


def _rows(conn: sa.Connection, table: str) -> list:
    return [tuple(r) for r in conn.execute(sa.text(f"SELECT * FROM {table} ORDER BY id"))]


# ── (1) ac_sync_run predates 0008's added_count / updated_count ─────────────


def test_etl_defaults_skip_sync_run_counters_an_older_stamp_lacks():
    engine = _build(without_columns=("ac_sync_run.added_count", "ac_sync_run.updated_count"))
    with engine.begin() as conn:
        # id 1: a pre-plan-22 row, everything NULL -> must be filled.
        _insert(conn, "ac_sync_run", id=1, mode=None, rows_scanned=None, deleted_count=None)
        # id 2: already populated -> must be left alone.
        _insert(conn, "ac_sync_run", id=2, mode="scheduled", rows_scanned=7, deleted_count=2)
        _insert(conn, "ac_entity_config", id=1, envelope="e", initial_load="i", etl_status=None)
        _insert(conn, "ac_staged_record", id=1, op=None)

        touched = backfill_etl_defaults(conn, schema=None)

        assert _rows(conn, "ac_sync_run") == [
            (1, "manual", 0, 0),
            (2, "scheduled", 7, 2),
        ]
        # The other tables were still filled - the skip is per column, not
        # an early return.
        assert _rows(conn, "ac_entity_config") == [(1, "e", "i", "draft")]
        assert _rows(conn, "ac_staged_record") == [(1, "upsert")]
        # mode + rows_scanned + deleted_count on row 1, etl_status, op.
        assert touched == 5


def test_etl_defaults_leave_a_fully_populated_older_sync_run_untouched():
    engine = _build(without_columns=("ac_sync_run.added_count", "ac_sync_run.updated_count"))
    with engine.begin() as conn:
        _insert(conn, "ac_sync_run", id=1, mode="manual", rows_scanned=3, deleted_count=1)
        before = _rows(conn, "ac_sync_run")

        touched = backfill_etl_defaults(conn, schema=None)

        assert _rows(conn, "ac_sync_run") == before
        assert touched == 0


# ── (2) ac_entity_config predates etl_status ───────────────────────────────


def test_etl_defaults_skip_etl_status_when_entity_config_lacks_it():
    engine = _build(without_columns=("ac_entity_config.etl_status",))
    with engine.begin() as conn:
        _insert(conn, "ac_entity_config", id=1, envelope="e", initial_load="i")
        _insert(conn, "ac_staged_record", id=1, op=None)
        _insert(conn, "ac_staged_record", id=2, op="delete")
        _insert(
            conn, "ac_sync_run", id=1, mode=None, rows_scanned=None, deleted_count=None,
            added_count=None, updated_count=None,
        )

        touched = backfill_etl_defaults(conn, schema=None)

        assert _rows(conn, "ac_entity_config") == [(1, "e", "i")]
        assert _rows(conn, "ac_staged_record") == [(1, "upsert"), (2, "delete")]
        assert _rows(conn, "ac_sync_run") == [(1, "manual", 0, 0, 0, 0)]
        # op on row 1 + the five sync_run columns on row 1.
        assert touched == 6


# ── (3) the two single-table helpers: absent column, absent table ──────────


def test_entity_config_defaults_return_zero_when_the_column_is_absent():
    engine = _build(without_columns=("ac_entity_config.initial_load",))
    with engine.begin() as conn:
        _insert(conn, "ac_entity_config", id=1, envelope="dict", etl_status="draft")
        # envelope is present and populated; initial_load is absent -> nothing
        # to do, and nothing to raise.
        assert backfill_entity_config_defaults(conn, schema=None) == 0
        assert _rows(conn, "ac_entity_config") == [(1, "dict", "draft")]


def test_entity_config_defaults_return_zero_when_the_table_is_absent():
    engine = _build(without_tables=("ac_entity_config",))
    with engine.begin() as conn:
        assert backfill_entity_config_defaults(conn, schema=None) == 0


def test_sink_impl_defaults_return_zero_when_the_column_is_absent():
    engine = _build(without_columns=("ac_company.sink_impl",))
    with engine.begin() as conn:
        _insert(conn, "ac_company", id=1)
        assert backfill_sink_impl_defaults(conn, schema=None) == 0
        assert _rows(conn, "ac_company") == [(1,)]


def test_sink_impl_defaults_return_zero_when_the_table_is_absent():
    engine = _build(without_tables=("ac_company",))
    with engine.begin() as conn:
        assert backfill_sink_impl_defaults(conn, schema=None) == 0


def test_etl_defaults_return_zero_when_every_table_is_absent():
    engine = _build(without_tables=tuple(FULL_COLUMNS))
    with engine.begin() as conn:
        assert backfill_etl_defaults(conn, schema=None) == 0


# ── (4) control: every column present, exactly the NULL/blank rows filled ──


def test_control_all_three_helpers_fill_exactly_the_null_or_blank_rows():
    engine = _build()
    with engine.begin() as conn:
        _insert(conn, "ac_company", id=1, sink_impl=None)
        _insert(conn, "ac_company", id=2, sink_impl="")
        _insert(conn, "ac_company", id=3, sink_impl="sorento")

        _insert(conn, "ac_entity_config", id=1, envelope=None, initial_load="", etl_status=None)
        _insert(conn, "ac_entity_config", id=2, envelope="list", initial_load="full", etl_status="ready")

        _insert(conn, "ac_staged_record", id=1, op=None)
        _insert(conn, "ac_staged_record", id=2, op="")
        _insert(conn, "ac_staged_record", id=3, op="delete")

        _insert(
            conn, "ac_sync_run", id=1, mode=None, rows_scanned=None, deleted_count=None,
            added_count=None, updated_count=None,
        )
        _insert(
            conn, "ac_sync_run", id=2, mode="scheduled", rows_scanned=10, deleted_count=1,
            added_count=2, updated_count=3,
        )

        assert backfill_sink_impl_defaults(conn, schema=None) == 2
        assert backfill_entity_config_defaults(conn, schema=None) == 2
        # etl_status (row 1) + op (rows 1, 2) + five sync_run columns (row 1).
        assert backfill_etl_defaults(conn, schema=None) == 8

        assert _rows(conn, "ac_company") == [(1, "logging"), (2, "logging"), (3, "sorento")]
        rows = _rows(conn, "ac_entity_config")
        assert rows[0][0] == 1 and rows[0][3] == "draft"
        assert rows[0][1] is not None and rows[0][1] != ""
        assert rows[0][2] is not None and rows[0][2] != ""
        assert rows[1] == (2, "list", "full", "ready")
        assert _rows(conn, "ac_staged_record") == [(1, "upsert"), (2, "upsert"), (3, "delete")]
        assert _rows(conn, "ac_sync_run") == [
            (1, "manual", 0, 0, 0, 0),
            (2, "scheduled", 10, 1, 2, 3),
        ]

        # Idempotent: a second pass touches nothing.
        assert backfill_sink_impl_defaults(conn, schema=None) == 0
        assert backfill_entity_config_defaults(conn, schema=None) == 0
        assert backfill_etl_defaults(conn, schema=None) == 0
