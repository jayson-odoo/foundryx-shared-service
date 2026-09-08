"""Backfill for EXISTING ``purchase_order`` / ``shipping_order`` tasks
(sprint-5/06 slice S2, Group D: AC-06-16..AC-06-19).

Red tests written BEFORE the coder, mirroring the shape of
``test_autocount_spo_container_number.py`` section 4 (module Alembic 0016's
``backfill_shipping_order_container_number``) one-to-one:

* **AC-06-16** ``backfill.backfill_document_line_linkage(bind)`` adds the six
  preset LINE rows of AC-06-14 (``FromSODocKey -> from_so_doc_key`` ...
  ``FromPODocNo -> from_po_number``, all enabled, not required) to every
  existing ``purchase_order`` and ``shipping_order`` ``ac_entity_config``
  across every tenant when a row for that target is not already there; an
  operator's own row for the same target, in ANY state, is left alone; a
  ``sales_order`` task gets nothing; idempotent (second pass adds 0).
* **AC-06-17** When the task's stored ``query`` / ``lineQuery`` /
  ``fingerprintQuery`` is byte-identical to the OLD preset text (this
  branch's text BEFORE slice S1, frozen below from ``git show
  21e2df32:service_backend/modules/autocount/presets.py`` - HEAD at the time
  this file was written) with the task's own company ``database_name``
  substituted, it is replaced by the NEW text (whatever ``presets`` exports
  at import time, so this pins the BEHAVIOUR, never a guessed string) and
  the four header aggregate names of AC-06-13 (``LinkedSOCount``,
  ``FromSOKeySum``, ``LinkedPOCount``, ``FromPOKeySum``) are appended to
  ``result_columns``; a customised statement is left untouched with a
  WARNING naming the config id (the AC-06-16 mapping rows still land,
  independently); a statement matching a SIBLING company's substitution
  counts as customised; every other ``source_config`` key is untouched.
* **AC-06-18** Schema-tolerant: a bind without ``ac_field_mapping`` /
  ``source_config`` / any module table returns 0 cleanly.
* **AC-06-19** Module Alembic ``0018_autocount_line_linkage`` chains onto
  ``0017_autocount_fingerprint``, revision id <= 32 chars, single head,
  calls the helper; ``update_tenant`` runs the same helper; ``manifest.json``
  bumps 0.7.0 -> 0.8.0.

AC-06-20 ([T], live Postgres replay) is tester-owned proof outside pytest -
not covered here.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import pathlib
import re

import pytest
import sqlalchemy as sa

import modules.autocount as autocount_module
from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.documents import (
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
)
from modules.autocount.mapping import SCOPE_LINE
from modules.autocount.models import (
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)
from modules.autocount.presets import (
    _PO_FINGERPRINT_QUERY,
    _PO_HEADER_QUERY,
    _PO_LINE_QUERY,
)

MODULE_ROOT = pathlib.Path(autocount_module.__file__).resolve().parent
VERSIONS_DIR = MODULE_ROOT / "alembic" / "versions"
REPO_ROOT = MODULE_ROOT.parents[2]

HELPER_NAME = "backfill_document_line_linkage"
PREVIOUS_REVISION = "0017_autocount_fingerprint"
NEW_REVISION_GLOB = "0018_*.py"

# The generic PO/SPO header/line/fingerprint queries EXACTLY as they shipped
# on THIS branch before slice S1 (frozen on purpose - the backfill's
# byte-identity check is against THIS text, with `{database}` substituted
# the way the "Use preset" picker hands it out). Taken verbatim from
# `git show 21e2df32:service_backend/modules/autocount/presets.py`.
OLD_PO_HEADER_QUERY = (
    "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, s.AutoKey AS CreditorAutoKey, "
    "h.PurchaseAgent AS SalesAgent, h.DocDate AS DocDate, "
    "CAST(l.FirstDeliveryDate AS date) AS ExpectedDate, h.Cancelled AS Cancelled, "
    "h.CreditorCode AS CreditorCode, h.CreditorName AS CreditorName, "
    "h.CurrencyCode AS CurrencyCode, h.LastModified AS LastModified, h.Ref AS Ref, "
    "l.LineCount AS LineCount, l.QtySum AS QtySum, l.TransferedSum AS TransferedSum, "
    "l.SubTotalSum AS SubTotalSum, l.MaxDtlKey AS MaxDtlKey "
    "FROM {database}.dbo.PO AS h "
    "LEFT JOIN {database}.dbo.Creditor AS s ON s.AccNo = h.CreditorCode "
    "OUTER APPLY ("
    "SELECT MIN(d.DeliveryDate) AS FirstDeliveryDate, COUNT(*) AS LineCount, "
    "SUM(d.Qty) AS QtySum, SUM(d.TransferedQty) AS TransferedSum, "
    "SUM(d.SubTotal) AS SubTotalSum, MAX(d.DtlKey) AS MaxDtlKey "
    "FROM {database}.dbo.PODTL AS d "
    "WHERE d.DocKey = h.DocKey AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
    ") AS l"
)
OLD_PO_LINE_QUERY = (
    "SELECT d.DtlKey AS DtlKey, i.AutoKey AS ItemAutoKey, "
    "w.AutoKey AS LocationAutoKey, d.Qty AS Qty, "
    "d.TransferedQty AS TransferedQty, d.UnitPrice AS UnitPrice, "
    "d.DiscountAmt AS DiscountAmt, d.SubTotal AS SubTotal, d.UOM AS UOM, "
    "d.DeliveryDate AS ExpectedDate, d.ItemCode AS ItemCode, "
    "d.Description AS Description, d.Location AS Location, d.Seq AS Seq "
    "FROM {database}.dbo.PODTL AS d "
    "LEFT JOIN {database}.dbo.Item AS i ON i.ItemCode = d.ItemCode "
    "LEFT JOIN {database}.dbo.Location AS w ON w.Location = d.Location "
    "WHERE d.DocKey = :doc_key AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
)
OLD_PO_FINGERPRINT_QUERY = (
    "SELECT d.DocKey AS DocKey, COUNT(*) AS LineCount, SUM(d.Qty) AS QtySum, "
    "SUM(d.TransferedQty) AS TransferedSum, MAX(d.DtlKey) AS MaxDtlKey "
    "FROM {database}.dbo.PODTL AS d JOIN {database}.dbo.PO AS h ON h.DocKey = d.DocKey "
    "WHERE h.DocDate >= :from_date AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL "
    "GROUP BY d.DocKey"
)

# AC-06-14: the six enabled, not-required line rows PO_PRESET/SPO_PRESET
# gain, as (source_path, canonical_field, transform).
LINE_LINKAGE_PRESET_FIELDS = (
    ("FromSODocKey", "from_so_doc_key", "int"),
    ("FromSODtlKey", "from_so_line_key", "int"),
    ("FromSODocList", "from_so_numbers", "string_list"),
    ("FromPODocKey", "from_po_doc_key", "int"),
    ("FromPODtlKey", "from_po_line_key", "int"),
    ("FromPODocNo", "from_po_number", "string"),
)
LINE_LINKAGE_TARGETS = tuple(target for _src, target, _tf in LINE_LINKAGE_PRESET_FIELDS)

# AC-06-13's four header aggregate names, in the exact order they are named
# in the plan/UAC - the backfill appends them to `result_columns` verbatim.
AGGREGATE_RESULT_COLUMNS = ["LinkedSOCount", "FromSOKeySum", "LinkedPOCount", "FromPOKeySum"]

_BASE_RESULT_COLUMNS = ["DocKey", "DocNo", "Cancelled", "DocDate", "LastModified"]


def _backfill():
    from modules.autocount import backfill

    helper = getattr(backfill, HELPER_NAME, None)
    if helper is None:
        pytest.fail(f"modules.autocount.backfill has no `{HELPER_NAME}` helper yet")
    return helper


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _api_company(db, *, database: str, tenant_id: str = DEFAULT_TENANT_ID) -> AcCompany:
    api = Connection(
        tenant_id=tenant_id, provider="autocount", type="erp", name=f"AutoCount {database}",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}),
        is_active=True,
    )
    db.add(api)
    db.flush()
    company = AcCompany(
        tenant_id=tenant_id, connection_id=api.id, database_name=database,
        company_name=f"{database} Sdn Bhd", name=database, is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _document_config(
    db, company: AcCompany, entity_type: str, *,
    query: str, line_query: str = None, fingerprint_query: str = None,
    result_columns=None,
) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=company.tenant_id, company_id=company.id, entity_type=entity_type,
        source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = {
        "connectionId": "conn-x",
        "query": query,
        "lineQuery": (
            line_query
            if line_query is not None
            else "SELECT d.DtlKey AS DtlKey FROM PODTL AS d WHERE d.DocKey = :doc_key"
        ),
        "fingerprintQuery": fingerprint_query,
        "keyColumns": ["DocKey"],
        "watermarkColumn": "LastModified",
        "comparedColumns": [],
        "fromDate": "2026-01-01",
        "docDateColumn": "DocDate",
        "filterFormula": 'startswith(upper(trim(DocNo)), "SPO-")',
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileAt": "02:00",
    }
    config.result_columns = list(result_columns or _BASE_RESULT_COLUMNS)
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _line_rows(db, company_id: str, entity_type: str):
    return (
        db.query(AcFieldMapping)
        .filter(
            AcFieldMapping.company_id == company_id,
            AcFieldMapping.entity_type == entity_type,
            AcFieldMapping.scope == SCOPE_LINE,
            AcFieldMapping.canonical_field.in_(LINE_LINKAGE_TARGETS),
        )
        .order_by(AcFieldMapping.canonical_field)
        .all()
    )


# ── AC-06-16: the six line rows, across tenants, SO untouched, idempotent ──


@pytest.mark.parametrize("entity_type", [ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER])
def test_backfill_adds_the_six_linkage_rows_to_po_and_spo_tasks_across_tenants(db, entity_type):
    helper = _backfill()
    company_a = _api_company(db, database="AED_A")
    company_b = _api_company(db, database="AED_B", tenant_id="tenant-b")
    config_a = _document_config(
        db, company_a, entity_type,
        query=OLD_PO_HEADER_QUERY.replace("{database}", "AED_A"),
        line_query=OLD_PO_LINE_QUERY.replace("{database}", "AED_A"),
        fingerprint_query=OLD_PO_FINGERPRINT_QUERY.replace("{database}", "AED_A"),
    )
    config_b = _document_config(
        db, company_b, entity_type,
        query=OLD_PO_HEADER_QUERY.replace("{database}", "AED_B"),
        line_query=OLD_PO_LINE_QUERY.replace("{database}", "AED_B"),
        fingerprint_query=OLD_PO_FINGERPRINT_QUERY.replace("{database}", "AED_B"),
    )
    assert config_a.id and config_b.id
    db.expire_all()

    touched = helper(db, schema=None)
    assert touched > 0, f"helper reported {touched} rows touched"
    db.expire_all()

    for company in (company_a, company_b):
        rows = _line_rows(db, company.id, entity_type)
        assert [row.canonical_field for row in rows] == sorted(LINE_LINKAGE_TARGETS), (
            f"{company.database_name} {entity_type}: {[r.canonical_field for r in rows]}"
        )
        by_target = {row.canonical_field: row for row in rows}
        for source_path, target, transform in LINE_LINKAGE_PRESET_FIELDS:
            row = by_target[target]
            assert row.tenant_id == company.tenant_id
            assert row.source_path == source_path, (target, row.source_path)
            assert row.transform == transform, (target, row.transform)
            assert row.scope == SCOPE_LINE
            assert row.is_enabled is True
            assert row.is_required is False
            assert row.formula is None

    # Idempotent: a second pass over the now-clean state adds nothing.
    db.expire_all()
    second = helper(db, schema=None)
    assert second == 0, f"second pass touched {second} rows - not idempotent"
    db.expire_all()
    assert len(_line_rows(db, company_a.id, entity_type)) == 6
    assert len(_line_rows(db, company_b.id, entity_type)) == 6


def test_backfill_gives_a_sales_order_task_none_of_the_six_rows(db):
    helper = _backfill()
    company = _api_company(db, database="AED_SO_ONLY")
    so_config = _document_config(
        db, company, ENTITY_SALES_ORDER,
        query="SELECT h.DocKey AS DocKey FROM {database}.dbo.SO AS h".replace(
            "{database}", "AED_SO_ONLY"
        ),
    )
    assert so_config.id
    db.expire_all()

    helper(db, schema=None)
    db.expire_all()

    assert _line_rows(db, company.id, ENTITY_SALES_ORDER) == [], (
        "a sales_order task must never get any of the six line linkage rows"
    )


def test_backfill_leaves_an_operators_own_row_for_a_target_alone(db):
    helper = _backfill()
    company = _api_company(db, database="AED_OWN")
    config = _document_config(
        db, company, ENTITY_PURCHASE_ORDER,
        query=OLD_PO_HEADER_QUERY.replace("{database}", "AED_OWN"),
    )
    assert config.id
    existing = AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PURCHASE_ORDER,
        scope=SCOPE_LINE, source_path="FromSODocKey", canonical_field="from_so_doc_key",
        transform="int", formula="coalesce(FromSODocKey, 0)", is_enabled=False, is_required=False,
    )
    db.add(existing)
    db.commit()
    existing_id = existing.id
    db.expire_all()

    helper(db, schema=None)
    db.expire_all()

    rows = _line_rows(db, company.id, ENTITY_PURCHASE_ORDER)
    by_target = {row.canonical_field: row for row in rows}
    assert by_target["from_so_doc_key"].id == existing_id, "the operator's own row was duplicated"
    assert by_target["from_so_doc_key"].is_enabled is False, "the operator's disabled row was flipped"
    assert by_target["from_so_doc_key"].formula == "coalesce(FromSODocKey, 0)"
    # The other five targets are untouched by the operator's row and must
    # still land - "in any state, is left alone" is per-target, not all-
    # or-nothing for the task.
    assert sorted(by_target) == sorted(LINE_LINKAGE_TARGETS)


# ── AC-06-17: byte-identical query / lineQuery / fingerprintQuery rewrite ──


def test_backfill_replaces_byte_identical_old_text_and_appends_aggregate_names(db):
    helper = _backfill()
    company = _api_company(db, database="AED_OLD")
    config = _document_config(
        db, company, ENTITY_SHIPPING_ORDER,
        query=OLD_PO_HEADER_QUERY.replace("{database}", "AED_OLD"),
        line_query=OLD_PO_LINE_QUERY.replace("{database}", "AED_OLD"),
        fingerprint_query=OLD_PO_FINGERPRINT_QUERY.replace("{database}", "AED_OLD"),
    )
    before = dict(config.source_config)
    config_id = config.id
    db.expire_all()

    helper(db, schema=None)
    db.expire_all()

    after = db.get(AcEntityConfig, config_id)
    expected_query = _PO_HEADER_QUERY.replace("{database}", "AED_OLD")
    expected_line = _PO_LINE_QUERY.replace("{database}", "AED_OLD")
    expected_fingerprint = _PO_FINGERPRINT_QUERY.replace("{database}", "AED_OLD")
    assert after.source_config["query"] == expected_query
    assert after.source_config["lineQuery"] == expected_line
    assert after.source_config["fingerprintQuery"] == expected_fingerprint
    assert "{database}" not in after.source_config["query"]
    assert "{database}" not in after.source_config["lineQuery"]
    assert "{database}" not in after.source_config["fingerprintQuery"]
    # Only the three statements moved - every other stored key is
    # byte-identical.
    for key, value in before.items():
        if key not in ("query", "lineQuery", "fingerprintQuery"):
            assert after.source_config.get(key) == value, key
    # The four aggregate names are APPENDED (order verbatim from AC-06-13),
    # the original result_columns prefix is untouched - the compared set
    # derives from result_columns, so without this the new aggregates never
    # enter the row hash and the one-time re-stage never fires.
    assert after.result_columns[: len(_BASE_RESULT_COLUMNS)] == _BASE_RESULT_COLUMNS
    assert after.result_columns[len(_BASE_RESULT_COLUMNS):] == AGGREGATE_RESULT_COLUMNS


def test_backfill_treats_a_partially_customised_task_per_statement(db, caplog):
    """``query`` / ``fingerprintQuery`` are byte-identical to the OLD preset
    and get rewritten; ``lineQuery`` was hand-edited and is left untouched -
    each of the three statements is its own independent check, and the
    config still gets a WARNING (naming it) because at least one statement
    was not recognised."""
    helper = _backfill()
    company = _api_company(db, database="AED_MIXED")
    customised_line_query = (
        OLD_PO_LINE_QUERY.replace("{database}", "AED_MIXED")
        + " AND d.ItemCode NOT LIKE 'ZZ%'"
    )
    config = _document_config(
        db, company, ENTITY_PURCHASE_ORDER,
        query=OLD_PO_HEADER_QUERY.replace("{database}", "AED_MIXED"),
        line_query=customised_line_query,
        fingerprint_query=OLD_PO_FINGERPRINT_QUERY.replace("{database}", "AED_MIXED"),
    )
    config_id = config.id
    db.expire_all()

    with caplog.at_level(logging.WARNING):
        helper(db, schema=None)
    db.expire_all()

    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == _PO_HEADER_QUERY.replace("{database}", "AED_MIXED")
    assert after.source_config["lineQuery"] == customised_line_query, "a customised lineQuery was overwritten"
    assert after.source_config["fingerprintQuery"] == _PO_FINGERPRINT_QUERY.replace(
        "{database}", "AED_MIXED"
    )
    warnings = [
        record for record in caplog.records
        if record.levelno >= logging.WARNING and config_id in record.getMessage()
    ]
    assert warnings, (
        f"no WARNING names the config id {config_id} for its customised lineQuery; "
        f"warnings seen: {[r.getMessage() for r in caplog.records]}"
    )


def test_backfill_leaves_a_fully_customised_task_alone_and_warns_naming_the_config_id(db, caplog):
    helper = _backfill()
    company = _api_company(db, database="AED_CUSTOM")
    customised_query = (
        OLD_PO_HEADER_QUERY.replace("{database}", "AED_CUSTOM")
        + " WHERE h.DocDate >= '2025-01-01'"
    )
    customised_line = OLD_PO_LINE_QUERY.replace("{database}", "AED_CUSTOM") + " AND 1=1"
    customised_fingerprint = (
        OLD_PO_FINGERPRINT_QUERY.replace("{database}", "AED_CUSTOM") + " HAVING COUNT(*) > 0"
    )
    config = _document_config(
        db, company, ENTITY_SHIPPING_ORDER,
        query=customised_query, line_query=customised_line,
        fingerprint_query=customised_fingerprint,
    )
    config_id = config.id
    db.expire_all()

    with caplog.at_level(logging.WARNING):
        helper(db, schema=None)
    db.expire_all()

    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == customised_query, "a customised query was overwritten"
    assert after.source_config["lineQuery"] == customised_line
    assert after.source_config["fingerprintQuery"] == customised_fingerprint
    assert after.result_columns == _BASE_RESULT_COLUMNS, "no aggregate name may land untouched"
    warnings = [
        record for record in caplog.records
        if record.levelno >= logging.WARNING and config_id in record.getMessage()
    ]
    assert warnings, (
        f"no WARNING names the customised config id {config_id}; "
        f"warnings seen: {[r.getMessage() for r in caplog.records]}"
    )
    # (a) is independent of (b): the six mapping rows still land even though
    # every statement was left alone.
    assert len(_line_rows(db, company.id, ENTITY_SHIPPING_ORDER)) == 6


def test_backfill_treats_a_sibling_companys_substitution_as_customised(db):
    """Byte identity is against the OWN company's database name - a query
    pasted from a sibling company's picker is a customisation, not the
    preset."""
    helper = _backfill()
    company = _api_company(db, database="AED_MINE")
    config = _document_config(
        db, company, ENTITY_PURCHASE_ORDER,
        query=OLD_PO_HEADER_QUERY.replace("{database}", "AED_OTHER"),
        line_query=OLD_PO_LINE_QUERY.replace("{database}", "AED_OTHER"),
        fingerprint_query=OLD_PO_FINGERPRINT_QUERY.replace("{database}", "AED_OTHER"),
    )
    config_id = config.id
    stored = dict(config.source_config)
    db.expire_all()

    helper(db, schema=None)
    db.expire_all()

    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == stored["query"]
    assert after.source_config["lineQuery"] == stored["lineQuery"]
    assert after.source_config["fingerprintQuery"] == stored["fingerprintQuery"]
    assert after.result_columns == _BASE_RESULT_COLUMNS


def test_backfill_leaves_a_sales_order_tasks_query_completely_alone(db, caplog):
    """A ``sales_order`` task given the SAME generic PO/SPO OLD text (shared
    byte-for-byte, same company database) must still not be touched at all:
    no query/lineQuery/fingerprintQuery rewrite, no aggregate name in
    ``result_columns``, no mapping row, and no warning naming it either (it
    is not a customised PO/SPO query, it is simply not a PO/SPO task) -
    proves the filter is by ``entity_type``, never by matching query text."""
    helper = _backfill()
    company = _api_company(db, database="AED_SOONLY")
    so_config = _document_config(
        db, company, ENTITY_SALES_ORDER,
        query=OLD_PO_HEADER_QUERY.replace("{database}", "AED_SOONLY"),
        line_query=OLD_PO_LINE_QUERY.replace("{database}", "AED_SOONLY"),
        fingerprint_query=OLD_PO_FINGERPRINT_QUERY.replace("{database}", "AED_SOONLY"),
    )
    so_id = so_config.id
    stored_source = dict(so_config.source_config)
    stored_columns = list(so_config.result_columns)
    mapping_before = (
        db.query(AcFieldMapping).filter(AcFieldMapping.company_id == company.id).count()
    )
    db.expire_all()

    with caplog.at_level(logging.WARNING):
        touched = helper(db, schema=None)
    db.expire_all()

    assert touched == 0, "a company with only a sales_order task must count as zero rows touched"
    after = db.get(AcEntityConfig, so_id)
    assert after.source_config == stored_source
    assert list(after.result_columns) == stored_columns
    assert _line_rows(db, company.id, ENTITY_SALES_ORDER) == []
    assert (
        db.query(AcFieldMapping).filter(AcFieldMapping.company_id == company.id).count()
        == mapping_before
    )
    assert not [r for r in caplog.records if so_id in r.getMessage()], (
        "the backfill logged about a sales_order task"
    )


# ── AC-06-18: schema-tolerant ────────────────────────────────────────────


def test_backfill_is_a_no_op_on_a_schema_that_predates_its_tables():
    """Runs at ANY module stamp (0018 and ``update_tenant`` both call it), so
    a bind without ``ac_field_mapping`` / without ``source_config`` must be a
    clean 0, never an UndefinedColumn / OperationalError."""
    helper = _backfill()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE ac_entity_config (id TEXT PRIMARY KEY, tenant_id TEXT, "
            "company_id TEXT, entity_type TEXT)"
        )
        conn.exec_driver_sql(
            "INSERT INTO ac_entity_config VALUES ('cfg-1', 't', 'c', 'purchase_order')"
        )
    with engine.begin() as conn:
        assert helper(conn, schema=None) == 0

    bare = sa.create_engine("sqlite://")
    with bare.begin() as conn:
        assert helper(conn, schema=None) == 0


# ── AC-06-19: update_tenant + module Alembic 0018 + manifest bump ─────────


def test_update_tenant_runs_the_line_linkage_backfill(db):
    """The App Store update path (an already-installed tenant moving past
    the version that ships this lane) delivers both halves without
    Alembic."""
    from modules.autocount.bootstrap import update_tenant

    company = _api_company(db, database="AED_UPD")
    config = _document_config(
        db, company, ENTITY_PURCHASE_ORDER,
        query=OLD_PO_HEADER_QUERY.replace("{database}", "AED_UPD"),
        line_query=OLD_PO_LINE_QUERY.replace("{database}", "AED_UPD"),
        fingerprint_query=OLD_PO_FINGERPRINT_QUERY.replace("{database}", "AED_UPD"),
    )
    config_id = config.id
    db.expire_all()

    update_tenant(db, DEFAULT_TENANT_ID, "0.7.0")
    db.commit()
    db.expire_all()

    rows = _line_rows(db, company.id, ENTITY_PURCHASE_ORDER)
    assert len(rows) == 6, [row.canonical_field for row in rows]
    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == _PO_HEADER_QUERY.replace("{database}", "AED_UPD")
    assert AGGREGATE_RESULT_COLUMNS[0] in (after.result_columns or [])


def test_manifest_version_is_bumped_past_0_7_0():
    """``update_tenant`` only runs when the manifest version moves - without
    the bump an already-installed tenant never receives the backfill."""
    manifest = json.loads((MODULE_ROOT / "manifest.json").read_text())
    version = tuple(int(part) for part in manifest["version"].split("."))
    assert version > (0, 7, 0), f"manifest still at {manifest['version']}"


def test_revision_0018_chains_onto_0017_and_calls_the_helper():
    candidates = sorted(VERSIONS_DIR.glob(NEW_REVISION_GLOB))
    assert candidates, "no 0018_* module revision under modules/autocount/alembic/versions"
    assert len(candidates) == 1, [p.name for p in candidates]
    path = candidates[0]
    text = path.read_text()
    revision = re.search(r'^revision[^=]*=\s*"([^"]+)"', text, re.M)
    assert revision and len(revision.group(1)) <= 32, "revision id missing or > 32 chars"
    spec = importlib.util.spec_from_file_location("_ac_rev_0018", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == PREVIOUS_REVISION
    assert HELPER_NAME in text, f"{path.name} does not call {HELPER_NAME}"
    # No sibling revision may also claim 0017 as its parent (single head).
    for other in VERSIONS_DIR.glob("*.py"):
        if other == path:
            continue
        down = re.search(r'^down_revision[^=]*=\s*"([^"]+)"', other.read_text(), re.M)
        assert not (down and down.group(1) == PREVIOUS_REVISION), (
            f"{other.name} also chains onto {PREVIOUS_REVISION}"
        )
