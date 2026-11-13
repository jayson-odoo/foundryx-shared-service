"""Module migrations 0010/0011/0012 must run on a DB stamped at 0009.

Verified facts (the bug):

- ``modules/autocount/alembic/versions/0010_autocount_document_line_mapping.py:93``
  calls ``backfill_document_line_mapping_pickers(session, tenant_id,
  company_id, entity_type)`` for every document-entity ``ac_entity_config`` row,
  on a ``Session(bind=op.get_bind())``.
- ``backfill_document_line_mapping_pickers`` (``modules/autocount/backfill.py``) does ``db.query(AcEntityConfig)...
  one_or_none()`` on the LIVE ORM model. That model
  (``modules/autocount/models.py:239`` ``delivery_mode``, ``:298``
  ``preview_job_id``) carries columns that only arrive in LATER migrations
  (``delivery_mode`` in 0020, ``preview_job_id`` in 0022). On a DB whose
  ``ac_entity_config`` is at stamp 0009/0010/0011 with document rows, the
  SELECT raises UndefinedColumn (sqlite: ``no such column:
  ac_entity_config.delivery_mode``) and the migration fails.
- 0011 (``0011_autocount_doc_line_fixed_fields.py:64``) calls the same function;
  0012 (``0012_autocount_disable_stale_line_rows.py:62``) calls
  ``disable_line_rows_missing_from_preview`` (``backfill.py``) with the
  identical ``db.query(AcEntityConfig)`` pattern.

Module Alembic never runs under pytest, so (per the ``backfill.py`` docstring)
the FUNCTIONS are tested directly on a raw-DDL sqlite engine carrying exactly
the older stamp's columns (same convention as
``test_autocount_backfill_schema_tolerance.py``).
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from modules.autocount.backfill import (
    backfill_document_line_mapping_pickers,
    disable_line_rows_missing_from_preview,
)
from modules.autocount.mapping import DOCUMENT_LINE_FIXED_FIELDS
from modules.autocount.models import AcFieldMapping

_PICKER_KEYS = ("lineKeyColumn", "lineProductColumn", "lineWarehouseColumn")

# ac_entity_config as the 0009 stamp (+ 0010's own line_result_columns, added
# BEFORE it calls the backfill) leaves it. NO delivery_mode (0020), NO
# preview_job_id (0022).
_ENTITY_CONFIG_DDL = """
CREATE TABLE ac_entity_config (
    id VARCHAR PRIMARY KEY,
    tenant_id VARCHAR NOT NULL,
    company_id VARCHAR NOT NULL,
    entity_type VARCHAR NOT NULL,
    sync_mode VARCHAR NOT NULL,
    source_impl VARCHAR NOT NULL,
    record_cap INTEGER NOT NULL,
    initial_lookback_days INTEGER NOT NULL,
    enabled BOOLEAN NOT NULL,
    created_at DATETIME,
    updated_at DATETIME,
    envelope VARCHAR NOT NULL,
    initial_load VARCHAR NOT NULL,
    source_config TEXT,
    etl_status VARCHAR NOT NULL,
    activated_at DATETIME,
    next_incremental_at DATETIME,
    next_reconcile_at DATETIME,
    last_run_error TEXT,
    last_run_error_code VARCHAR,
    result_columns TEXT,
    last_preview_at DATETIME,
    last_run_at DATETIME,
    last_preview_failed_count INTEGER,
    line_result_columns TEXT
)
"""

_FIELD_MAPPING_DDL = """
CREATE TABLE ac_field_mapping (
    id VARCHAR PRIMARY KEY,
    tenant_id VARCHAR NOT NULL,
    company_id VARCHAR NOT NULL,
    entity_type VARCHAR NOT NULL,
    scope VARCHAR NOT NULL,
    source_path VARCHAR NOT NULL,
    canonical_field VARCHAR NOT NULL,
    transform VARCHAR NOT NULL,
    formula TEXT,
    is_required BOOLEAN NOT NULL,
    is_enabled BOOLEAN NOT NULL,
    is_source_owned BOOLEAN NOT NULL,
    sort_order INTEGER NOT NULL,
    created_at DATETIME,
    updated_at DATETIME,
    CONSTRAINT uq_ac_field_mapping UNIQUE
        (tenant_id, company_id, entity_type, scope, canonical_field)
)
"""


def _build_stamp_0009_engine() -> sa.engine.Engine:
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    ).execution_options(schema_translate_map={"app_autocount": None})
    with engine.begin() as conn:
        conn.execute(sa.text(_ENTITY_CONFIG_DDL))
        conn.execute(sa.text(_FIELD_MAPPING_DDL))
    return engine


def _insert_config(engine, entity_type, source_config=None, line_result_columns=None):
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO ac_entity_config (id, tenant_id, company_id, entity_type,"
                " sync_mode, source_impl, record_cap, initial_lookback_days, enabled,"
                " envelope, initial_load, source_config, etl_status, line_result_columns)"
                " VALUES (:id, 't1', 'c1', :et, 'manual', 'autocount_read', 200, 30, 1,"
                " 'status_dict', 'windowed', :sc, 'draft', :lrc)"
            ),
            {
                "id": f"cfg-{entity_type}",
                "et": entity_type,
                "sc": json.dumps(source_config) if source_config is not None else None,
                "lrc": json.dumps(line_result_columns) if line_result_columns is not None else None,
            },
        )


def _insert_line_mapping(engine, source_path, canonical_field, enabled=True):
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO ac_field_mapping (id, tenant_id, company_id, entity_type,"
                " scope, source_path, canonical_field, transform, is_required,"
                " is_enabled, is_source_owned, sort_order)"
                " VALUES (:id, 't1', 'c1', 'sales_order', 'line', :sp, :cf, 'string',"
                " 0, :en, 1, 0)"
            ),
            {"id": f"m-{canonical_field}", "sp": source_path, "cf": canonical_field, "en": int(enabled)},
        )


def _line_rows(engine):
    with engine.connect() as conn:
        return {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                sa.text(
                    "SELECT canonical_field, source_path, is_enabled FROM ac_field_mapping"
                    " WHERE scope = 'line'"
                )
            )
        }


def _source_config(engine, entity_type="sales_order"):
    with engine.connect() as conn:
        raw = conn.execute(
            sa.text("SELECT source_config FROM ac_entity_config WHERE entity_type = :et"),
            {"et": entity_type},
        ).scalar_one()
    return json.loads(raw)


_SO_SOURCE_CONFIG = {
    "query": "SELECT * FROM SO",
    "lineQuery": "SELECT * FROM SODtl",
    "lineKeyColumn": "DtlKey",
    "lineProductColumn": "ItemCode",
    "lineWarehouseColumn": "Location",
}


def test_fixture_lacks_the_later_columns():
    """Control: the fixture really is 0009-shaped, so the tests below cannot
    silently become HEAD-shaped."""
    names = {c["name"] for c in sa.inspect(_build_stamp_0009_engine()).get_columns("ac_entity_config")}
    assert "delivery_mode" not in names
    assert "preview_job_id" not in names
    assert "line_result_columns" in names


def test_backfill_document_line_mapping_pickers_runs_on_a_0009_shaped_config_table():
    engine = _build_stamp_0009_engine()
    _insert_config(engine, "sales_order", source_config=_SO_SOURCE_CONFIG)

    session = Session(bind=engine)
    created = backfill_document_line_mapping_pickers(session, "t1", "c1", "sales_order")
    session.flush()
    session.commit()

    fixed = DOCUMENT_LINE_FIXED_FIELDS["sales_order"]
    assert created == 3 + len(fixed)

    rows = _line_rows(engine)
    assert rows["source_ref"][0] == "DtlKey"
    assert rows["product_ref"][0] == "ItemCode"
    assert rows["warehouse_ref"][0] == "Location"
    for canonical_field, _transform, _required in fixed:
        assert rows[canonical_field][0] == canonical_field
    # never previewed (line_result_columns NULL) -> everything enabled
    assert all(enabled == 1 for _src, enabled in rows.values())

    cfg = _source_config(engine)
    assert not any(k in cfg for k in _PICKER_KEYS)
    assert cfg["query"] == "SELECT * FROM SO"
    assert cfg["lineQuery"] == "SELECT * FROM SODtl"

    # idempotent
    before = _line_rows(engine)
    assert backfill_document_line_mapping_pickers(session, "t1", "c1", "sales_order") == 0
    session.commit()
    assert _line_rows(engine) == before
    assert _source_config(engine) == cfg
    session.close()


def test_backfill_document_line_mapping_pickers_is_a_no_op_on_a_0009_shaped_table_without_document_rows():
    engine = _build_stamp_0009_engine()
    _insert_config(engine, "debtor", source_config={"query": "SELECT * FROM Debtor"})

    session = Session(bind=engine)
    assert backfill_document_line_mapping_pickers(session, "t1", "c1", "debtor") == 0
    # A document entity with no config row is also a clean zero.
    assert backfill_document_line_mapping_pickers(session, "t1", "c1", "sales_order") == 0
    session.commit()
    session.close()

    assert _line_rows(engine) == {}
    assert _source_config(engine, "debtor") == {"query": "SELECT * FROM Debtor"}


def test_disable_line_rows_missing_from_preview_runs_on_a_0011_shaped_config_table():
    engine = _build_stamp_0009_engine()  # 0010 + 0011 add no further columns
    _insert_config(engine, "sales_order", source_config={}, line_result_columns=["DtlKey", "ItemCode"])
    _insert_line_mapping(engine, "DtlKey", "source_ref")
    _insert_line_mapping(engine, "Location", "warehouse_ref")

    session = Session(bind=engine)
    assert disable_line_rows_missing_from_preview(session, "t1", "c1", "sales_order") == 1
    session.commit()

    rows = _line_rows(engine)
    assert rows["warehouse_ref"] == ("Location", 0)
    assert rows["source_ref"] == ("DtlKey", 1)

    assert disable_line_rows_missing_from_preview(session, "t1", "c1", "sales_order") == 0
    session.commit()
    session.close()
    assert _line_rows(engine) == rows


def test_ac_field_mapping_model_still_matches_the_0005_column_set():
    """Tripwire: ac_field_mapping = 0002 baseline + ``formula`` (0005)."""
    expected = {
        "id", "tenant_id", "company_id", "entity_type", "scope", "source_path",
        "canonical_field", "transform", "formula", "is_required", "is_enabled",
        "is_source_owned", "sort_order", "created_at", "updated_at",
    }
    actual = {c.name for c in AcFieldMapping.__table__.columns}
    assert actual == expected, (
        "backfill_document_line_mapping_pickers (ORM AcFieldMapping(...) insert) and "
        "disable_line_rows_missing_from_preview (db.query(AcFieldMapping)) run under "
        "migrations 0010/0011/0012 at a stamp where only these columns exist; a new "
        "ac_field_mapping column means those accesses must become column-only / "
        f"frozen sa.table first. Diff: {sorted(actual ^ expected)}"
    )
