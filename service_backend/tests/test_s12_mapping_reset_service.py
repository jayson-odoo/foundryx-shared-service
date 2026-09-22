"""Sprint-5/12 S2 - RED before the coder: `CompanyService.reset_mapping_to_
preset(tenant_id, company_id, entity_type, *, dry_run)` and `presets.
resolve_preset_rows(config)` (plan section 2.2).

AC-12-11 (one resolver, parity with the first-save seed), AC-12-12 (dry-run
diff classification + zero writes), AC-12-13 (apply is one transaction,
rollback on a forced mid-way failure, line rows untouched), AC-12-14 (no
other `ac_entity_config` side effect, deltas identical to a PUT), AC-12-15
(an un-previewed column lands disabled, never dropped; a never-previewed
task enables everything except a preset's own deliberate withholding).

RED before the coder: `CompanyService` has no `reset_mapping_to_preset`
method and `presets.py` has no `resolve_preset_rows` - every call below
fails with a real `AttributeError`/`ImportError`, never a fixture bug.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pytest
import sqlalchemy as sa

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount import presets as presets_module
from modules.autocount.canonical.documents import ENTITY_SALES_ORDER
from modules.autocount.canonical.masters import ENTITY_PRODUCT, ENTITY_SUPPLIER
from modules.autocount.mapping import SCOPE_HEADER, SCOPE_LINE
from modules.autocount.models import (
    ETL_STATUS_DRAFT,
    SOURCE_IMPL_AUTOCOUNT_HTTP,
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)
from modules.autocount.presets import PRODUCT_HTTP_PRESET, SO_PRESET
from modules.autocount.services import company_service as company_service_module
from modules.autocount.services.company_service import CompanyService, MappingWriteRow


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _auth(client, email="demo@example.com", password="demo1234") -> Dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _connection(db, *, tenant_id: str = DEFAULT_TENANT_ID, name: str = "Mocha REST") -> Connection:
    conn = Connection(
        tenant_id=tenant_id, provider="autocount", type="erp", name=name,
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db2", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str, *, database_name: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name=database_name,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _product_config(
    db, company: AcCompany, connection_id: str, *,
    result_columns: Optional[List[str]], lookups: Optional[List[dict]] = None,
) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl=SOURCE_IMPL_AUTOCOUNT_HTTP,
        source_config={
            "connectionId": connection_id, "path": "/itembypage", "keyFields": ["ItemCode"],
            "watermarkField": "LastModified", "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": lookups or [],
        },
        result_columns=result_columns,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _no_preset_config(db, company: AcCompany, connection_id: str) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_SUPPLIER,
        source_impl=SOURCE_IMPL_AUTOCOUNT_HTTP,
        source_config={
            "connectionId": connection_id, "path": "/creditorbypage", "keyFields": ["AccNo"],
            "watermarkField": "LastModified", "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": [],
        },
        result_columns=None,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


DOC_HEADER_QUERY = "SELECT doc_key, doc_no, status, cancelled FROM so_header"
DOC_LINE_QUERY = "SELECT dtl_key, item_code, qty FROM so_line WHERE doc_key = :doc_key"


def _document_config(db, company: AcCompany, connection_id: str) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_SALES_ORDER,
        source_impl=SOURCE_IMPL_SQL_DB, etl_status=ETL_STATUS_DRAFT,
        source_config={
            "connectionId": connection_id, "query": DOC_HEADER_QUERY, "lineQuery": DOC_LINE_QUERY,
            "keyColumns": ["doc_key"], "watermarkColumn": None, "comparedColumns": [],
            "fromDate": "2026-01-01", "docDateColumn": None, "lineKeyColumn": "dtl_key",
            "lineProductColumn": "item_code", "lineWarehouseColumn": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
        },
        result_columns=None,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _mapping_row(company: AcCompany, entity_type: str, *, scope: str, source_path: str,
                  canonical_field: str, transform: str = "string", formula: Optional[str] = None,
                  is_required: bool = False, is_enabled: bool = True, sort_order: int = 0) -> AcFieldMapping:
    return AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type, scope=scope,
        source_path=source_path, canonical_field=canonical_field, transform=transform, formula=formula,
        is_required=is_required, is_enabled=is_enabled, sort_order=sort_order,
    )


def _rows(db, company_id: str, entity_type: str, *, scope: str) -> List[AcFieldMapping]:
    return (
        db.query(AcFieldMapping)
        .filter(
            AcFieldMapping.tenant_id == DEFAULT_TENANT_ID,
            AcFieldMapping.company_id == company_id,
            AcFieldMapping.entity_type == entity_type,
            AcFieldMapping.scope == scope,
        )
        .order_by(AcFieldMapping.sort_order)
        .all()
    )


def _header_rows(db, company_id: str, entity_type: str) -> List[AcFieldMapping]:
    return _rows(db, company_id, entity_type, scope=SCOPE_HEADER)


def _line_rows(db, company_id: str, entity_type: str) -> List[AcFieldMapping]:
    return _rows(db, company_id, entity_type, scope=SCOPE_LINE)


def _row_tuples(rows: List[AcFieldMapping]) -> List[Tuple]:
    return [
        (r.source_path, r.canonical_field, r.transform, r.formula, r.is_required, r.is_enabled, r.sort_order)
        for r in rows
    ]


CONFIG_SNAPSHOT_FIELDS = [
    "source_config", "result_columns", "etl_status", "last_preview_at",
    "last_preview_failed_count", "activated_at", "preview_job_id",
]


def _snapshot(config: AcEntityConfig) -> Dict[str, object]:
    return {f: getattr(config, f) for f in CONFIG_SNAPSHOT_FIELDS}


def _reset_url(company_id: str, entity_type: str) -> str:
    return f"/autocount/companies/{company_id}/entities/{entity_type}/mapping/reset-preset"


# ── AC-12-11: one resolver, parity with the first-save seed ────────────────


def test_ac_12_11_resolve_preset_rows_returns_the_http_preset_for_a_product_task(db):
    from modules.autocount.presets import resolve_preset_rows

    conn = _connection(db)
    company = _company(db, conn.id, database_name="MOCHA-RESOLVE-1")
    config = _product_config(db, company, conn.id, result_columns=None)

    resolved = resolve_preset_rows(config)
    assert resolved is not None
    label, rows = resolved
    assert label == PRODUCT_HTTP_PRESET.label
    assert tuple(rows) == PRODUCT_HTTP_PRESET.rows


def test_ac_12_11_resolve_preset_rows_returns_none_for_an_entity_with_no_preset(db):
    from modules.autocount.presets import resolve_preset_rows

    conn = _connection(db)
    company = _company(db, conn.id, database_name="MOCHA-RESOLVE-2")
    config = _no_preset_config(db, company, conn.id)

    assert resolve_preset_rows(config) is None


def test_ac_12_11_reset_on_empty_mapping_equals_seed_http_preset_mapping_rows(db):
    """The rows a reset produces on an EMPTY mapping must equal, row for
    row, the rows `seed_http_preset_mapping` produces for the SAME task -
    one registry, never two copies to drift apart."""
    conn = _connection(db)

    control_company = _company(db, conn.id, database_name="MOCHA-PARITY-CTRL")
    _product_config(db, control_company, conn.id, result_columns=None)
    presets_module.seed_http_preset_mapping(
        db, DEFAULT_TENANT_ID, control_company.id, ENTITY_PRODUCT, columns=None,
    )
    db.commit()
    control_rows = _row_tuples(_header_rows(db, control_company.id, ENTITY_PRODUCT))
    assert control_rows, "the control fixture itself produced no rows - broken test setup"

    reset_company = _company(db, conn.id, database_name="MOCHA-PARITY-RESET")
    _product_config(db, reset_company, conn.id, result_columns=None)
    CompanyService(db).reset_mapping_to_preset(
        DEFAULT_TENANT_ID, reset_company.id, ENTITY_PRODUCT, dry_run=False,
    )
    reset_rows = _row_tuples(_header_rows(db, reset_company.id, ENTITY_PRODUCT))

    assert reset_rows == control_rows


# ── AC-12-12: dry-run diff classification (via the route) + zero writes ────


def test_ac_12_12_dry_run_returns_the_exact_diff_classification(client, db):
    conn = _connection(db)
    company = _company(db, conn.id, database_name="MOCHA-DIFF")
    _product_config(
        db, company, conn.id,
        # A REAL, non-empty preview - deliberately missing `BaseUOMPrice`
        # (no `uom` lookup configured) so `list_price` lands disabled.
        result_columns=["ItemCode", "Description", "ItemGroup", "ItemBrand", "BaseUOM", "IsActive", "Discontinued"],
        lookups=[],
    )
    rows = [
        # unchanged: byte-identical to the preset row
        _mapping_row(company, ENTITY_PRODUCT, scope=SCOPE_HEADER, source_path="ItemCode",
                     canonical_field="code", is_required=True, sort_order=0),
        # changed: source path deviates from the preset (the baseline's own
        # "ItemCode -> name" prod finding)
        _mapping_row(company, ENTITY_PRODUCT, scope=SCOPE_HEADER, source_path="ItemCode",
                     canonical_field="name", sort_order=1),
        # changed: formula deviates (plain text vs the preset's Desc2 join)
        _mapping_row(company, ENTITY_PRODUCT, scope=SCOPE_HEADER, source_path="Description",
                     canonical_field="description", sort_order=2),
        _mapping_row(company, ENTITY_PRODUCT, scope=SCOPE_HEADER, source_path="ItemGroup",
                     canonical_field="category_code", sort_order=3),
        _mapping_row(company, ENTITY_PRODUCT, scope=SCOPE_HEADER, source_path="ItemBrand",
                     canonical_field="brand_code", sort_order=4),
        # changed: enabled deviates - operator turned this ON, preset keeps
        # it deliberately withheld (AC-10-74)
        _mapping_row(company, ENTITY_PRODUCT, scope=SCOPE_HEADER, source_path="BaseUOM",
                     canonical_field="uom_code", is_enabled=True, sort_order=5),
        _mapping_row(company, ENTITY_PRODUCT, scope=SCOPE_HEADER, source_path="IsActive",
                     canonical_field="is_active", transform="t_f_bool", sort_order=6),
        # a stray operator-added row the preset does not carry at all
        _mapping_row(company, ENTITY_PRODUCT, scope=SCOPE_HEADER, source_path="InternalRemark",
                     canonical_field="custom_note", sort_order=7),
    ]
    for row in rows:
        db.add(row)
    db.commit()

    headers = _auth(client)
    response = client.post(_reset_url(company.id, ENTITY_PRODUCT), json={"dryRun": True}, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["label"] == PRODUCT_HTTP_PRESET.label

    rows_by_field = {r["canonicalField"]: r for r in body["rows"]}
    assert rows_by_field["code"]["change"] == "unchanged", rows_by_field["code"]
    assert rows_by_field["name"]["change"] == "changed", rows_by_field["name"]
    assert rows_by_field["description"]["change"] == "changed", rows_by_field["description"]
    assert rows_by_field["category_code"]["change"] == "unchanged"
    assert rows_by_field["brand_code"]["change"] == "unchanged"
    assert rows_by_field["is_active"]["change"] == "unchanged"

    assert rows_by_field["uom_code"]["change"] == "changed"
    assert rows_by_field["uom_code"]["enabled"] is False
    assert rows_by_field["uom_code"]["disabledReason"] == "column not returned by the source"

    assert rows_by_field["list_price"]["change"] == "added"
    assert rows_by_field["list_price"]["enabled"] is False
    assert rows_by_field["list_price"]["disabledReason"] == "column not returned by the source"

    assert rows_by_field["is_discontinued"]["change"] == "added"
    assert rows_by_field["is_discontinued"]["enabled"] is True

    removed_by_field = {r["canonicalField"]: r for r in body["removed"]}
    assert "custom_note" in removed_by_field
    assert removed_by_field["custom_note"]["sourcePath"] == "InternalRemark"
    assert removed_by_field["custom_note"]["transform"] == "string"
    assert removed_by_field["custom_note"]["formula"] is None

    # Dry run must write NOTHING - the current (pre-reset) rows are still
    # exactly what was seeded above.
    after = _row_tuples(_header_rows(db, company.id, ENTITY_PRODUCT))
    before = _row_tuples(rows)
    assert sorted(after) == sorted(before), "a dryRun=true call must never write to ac_field_mapping"


def test_ac_12_12_dry_run_issues_zero_ac_field_mapping_statements_apply_writes_control(db):
    """Statement-count pin (AC-12-12): no INSERT/UPDATE/DELETE against
    `ac_field_mapping` for `dry_run=True`. Paired with a POSITIVE CONTROL in
    the SAME test - `dry_run=False` on an equivalent task DOES write - so
    this absence assertion cannot pass for the wrong reason (e.g. a listener
    that never fires, or a route/method that silently no-ops for any input).
    """
    conn = _connection(db)
    dry_company = _company(db, conn.id, database_name="MOCHA-STMT-DRY")
    _product_config(db, dry_company, conn.id, result_columns=None)

    engine = db.get_bind()
    calls = {"insert": 0, "update": 0, "delete": 0}

    def before_cursor_execute(conn_, cursor, statement, parameters, context, executemany):
        lowered = statement.strip().lower()
        if "ac_field_mapping" not in lowered:
            return
        for verb in calls:
            if lowered.startswith(verb):
                calls[verb] += 1

    sa.event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        CompanyService(db).reset_mapping_to_preset(
            DEFAULT_TENANT_ID, dry_company.id, ENTITY_PRODUCT, dry_run=True,
        )
    finally:
        sa.event.remove(engine, "before_cursor_execute", before_cursor_execute)
    assert calls == {"insert": 0, "update": 0, "delete": 0}, calls

    # Positive control - apply DOES write.
    apply_company = _company(db, conn.id, database_name="MOCHA-STMT-APPLY")
    _product_config(db, apply_company, conn.id, result_columns=None)
    apply_calls = {"insert": 0, "update": 0, "delete": 0}

    def before_cursor_execute_apply(conn_, cursor, statement, parameters, context, executemany):
        lowered = statement.strip().lower()
        if "ac_field_mapping" not in lowered:
            return
        for verb in apply_calls:
            if lowered.startswith(verb):
                apply_calls[verb] += 1

    sa.event.listen(engine, "before_cursor_execute", before_cursor_execute_apply)
    try:
        CompanyService(db).reset_mapping_to_preset(
            DEFAULT_TENANT_ID, apply_company.id, ENTITY_PRODUCT, dry_run=False,
        )
    finally:
        sa.event.remove(engine, "before_cursor_execute", before_cursor_execute_apply)
    assert apply_calls["insert"] > 0, (
        "the positive control never wrote either - the listener/table filter "
        "is broken, so the dry-run absence assertion above is not trustworthy"
    )


# ── AC-12-13: apply is ONE transaction; line rows untouched ────────────────


def test_ac_12_13_apply_replaces_header_rows_with_the_preset_shape(db):
    conn = _connection(db)
    company = _company(db, conn.id, database_name="MOCHA-APPLY")
    _product_config(db, company, conn.id, result_columns=None)
    db.add(_mapping_row(company, ENTITY_PRODUCT, scope=SCOPE_HEADER, source_path="ItemCode",
                         canonical_field="name", sort_order=0))
    db.commit()

    CompanyService(db).reset_mapping_to_preset(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, dry_run=False)

    rows = _header_rows(db, company.id, ENTITY_PRODUCT)
    assert {r.canonical_field for r in rows} == {f.canonical_field for f in PRODUCT_HTTP_PRESET.rows}
    name_row = next(r for r in rows if r.canonical_field == "name")
    assert name_row.source_path == "Description", "the stale ItemCode->name row must be REPLACED"


def test_ac_12_13_a_forced_failure_after_delete_leaves_the_previous_rows_intact(db, monkeypatch):
    # Guard against a vacuous pass (kill-test discipline): `pytest.raises
    # (Exception)` below would ALSO catch the pre-implementation
    # `AttributeError('reset_mapping_to_preset')` and this test would then
    # "pass" for entirely the wrong reason (nothing was ever written because
    # nothing ever ran). Fail loudly, explicitly, until the method exists.
    assert hasattr(CompanyService, "reset_mapping_to_preset"), (
        "RED before the coder: CompanyService.reset_mapping_to_preset does "
        "not exist yet"
    )

    conn = _connection(db)
    company = _company(db, conn.id, database_name="MOCHA-FAIL")
    _product_config(db, company, conn.id, result_columns=None)
    db.add(_mapping_row(company, ENTITY_PRODUCT, scope=SCOPE_HEADER, source_path="ItemCode",
                         canonical_field="code", is_required=True, sort_order=0))
    db.commit()
    before = _row_tuples(_header_rows(db, company.id, ENTITY_PRODUCT))
    assert before, "broken fixture - no baseline row to protect"

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated failure mid-reset (AC-12-13 kill test)")

    # Defensive double-patch (ambiguity, flagged in the final report): the
    # plan's own prose names `_seed_rows` as the re-seed call inside
    # `reset_mapping_to_preset` (company_service.py) - patch it on BOTH the
    # module it is DEFINED in (presets.py, if the coder calls it qualified)
    # and the module it might be IMPORTED BY NAME into (company_service.py).
    monkeypatch.setattr(presets_module, "_seed_rows", _boom)
    if hasattr(company_service_module, "_seed_rows"):
        monkeypatch.setattr(company_service_module, "_seed_rows", _boom)

    with pytest.raises(Exception):
        CompanyService(db).reset_mapping_to_preset(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, dry_run=False)
    db.rollback()

    after = _row_tuples(_header_rows(db, company.id, ENTITY_PRODUCT))
    assert after == before, (
        "a forced failure mid-reset must leave the PREVIOUS rows intact - "
        "delete + reseed must be ONE transaction"
    )


def test_ac_12_13_line_scope_rows_are_untouched_by_a_document_reset(db):
    conn = _connection(db)
    company = _company(db, conn.id, database_name="MOCHA-DOC-LINES")
    _document_config(db, company, conn.id)
    for i, (source_path, canonical_field) in enumerate([("DtlKey", "source_ref"), ("ItemAutoKey", "product_ref")]):
        db.add(_mapping_row(company, ENTITY_SALES_ORDER, scope=SCOPE_LINE, source_path=source_path,
                             canonical_field=canonical_field, is_required=True, sort_order=i))
    db.commit()
    before_lines = _row_tuples(_line_rows(db, company.id, ENTITY_SALES_ORDER))
    assert before_lines

    CompanyService(db).reset_mapping_to_preset(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, dry_run=False)

    after_lines = _row_tuples(_line_rows(db, company.id, ENTITY_SALES_ORDER))
    assert after_lines == before_lines, "reset must touch HEADER scope only (AC-12-11/13)"

    header_rows = _header_rows(db, company.id, ENTITY_SALES_ORDER)
    assert {r.canonical_field for r in header_rows} == {f.canonical_field for f in SO_PRESET.header}


# ── AC-12-14: no OTHER ac_entity_config side effect ─────────────────────────


def test_ac_12_14_reset_leaves_ac_entity_config_byte_identical(db):
    conn = _connection(db)
    company = _company(db, conn.id, database_name="MOCHA-CFG")
    config = _product_config(db, company, conn.id, result_columns=None)
    before = _snapshot(config)

    CompanyService(db).reset_mapping_to_preset(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, dry_run=False)

    db.refresh(config)
    after = _snapshot(config)
    assert after == before, {k: (before[k], after[k]) for k in before if before[k] != after.get(k)}


def test_ac_12_14_reset_and_put_produce_identical_ac_entity_config_deltas(db):
    """Whatever `replace_mapping` does to the Activate gate today, a reset
    does the same and nothing else - pinned by comparing the ac_entity_config
    DELTA of a PUT carrying the (accepted subset of the) preset rows against
    the reset's own delta."""
    conn = _connection(db)

    reset_company = _company(db, conn.id, database_name="MOCHA-CFG-RESET")
    reset_config = _product_config(db, reset_company, conn.id, result_columns=None)
    before_reset = _snapshot(reset_config)
    CompanyService(db).reset_mapping_to_preset(DEFAULT_TENANT_ID, reset_company.id, ENTITY_PRODUCT, dry_run=False)
    db.refresh(reset_config)
    delta_reset = {k: v for k, v in _snapshot(reset_config).items() if v != before_reset[k]}

    put_company = _company(db, conn.id, database_name="MOCHA-CFG-PUT")
    put_config = _product_config(db, put_company, conn.id, result_columns=None)
    before_put = _snapshot(put_config)
    # `is_discontinued` is captured but NOT a Sorento-accepted target
    # (absent from `CanonicalProduct.SINK_FIELDS`) - the save gate would
    # 422 it, so the PUT-equivalent excludes it; the reset seeds it anyway
    # (it bypasses the accepted-field guard the same way first-save seeding
    # always has) - a mapping-ROW difference, not an ac_entity_config one.
    put_rows = [
        MappingWriteRow(f.source_path, f.transform, f.canonical_field, formula=f.formula, is_enabled=f.enabled)
        for f in PRODUCT_HTTP_PRESET.rows if f.canonical_field != "is_discontinued"
    ]
    CompanyService(db).replace_mapping(DEFAULT_TENANT_ID, put_company.id, ENTITY_PRODUCT, put_rows)
    db.refresh(put_config)
    delta_put = {k: v for k, v in _snapshot(put_config).items() if v != before_put[k]}

    assert delta_reset == delta_put == {}, (delta_reset, delta_put)


# ── AC-12-15: un-previewed column disabled, never dropped ──────────────────


def test_ac_12_15_unpreviewed_column_lands_disabled_never_dropped(db):
    conn = _connection(db)
    company = _company(db, conn.id, database_name="MOCHA-15A")
    _product_config(
        db, company, conn.id,
        result_columns=["ItemCode", "Description", "ItemGroup", "ItemBrand", "BaseUOM", "IsActive", "Discontinued"],
        lookups=[],  # no uom lookup -> BaseUOMPrice never available
    )

    CompanyService(db).reset_mapping_to_preset(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, dry_run=False)

    rows = _header_rows(db, company.id, ENTITY_PRODUCT)
    list_price_rows = [r for r in rows if r.canonical_field == "list_price"]
    assert len(list_price_rows) == 1, "the row must be SEEDED disabled, never omitted (AC-02-16 rule)"
    assert list_price_rows[0].is_enabled is False


def test_ac_12_15_never_previewed_result_columns_null_every_row_enabled_except_the_preset_withhold(db):
    conn = _connection(db)
    company = _company(db, conn.id, database_name="MOCHA-15B")
    _product_config(db, company, conn.id, result_columns=None)

    CompanyService(db).reset_mapping_to_preset(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, dry_run=False)

    rows = _header_rows(db, company.id, ENTITY_PRODUCT)
    disabled = {r.canonical_field: r.is_enabled for r in rows if not r.is_enabled}
    # `uom_code` stays disabled regardless of "never previewed" - AC-10-74's
    # deliberate withholding is a policy orthogonal to column availability.
    assert disabled == {"uom_code": False}, disabled
