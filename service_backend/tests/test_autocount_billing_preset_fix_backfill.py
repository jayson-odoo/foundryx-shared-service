"""Plan 35 (lane SS-BILLING-PRESET-FIX) - existing billing / AR tasks move to
the fixed preset text (module Alembic 0033 + ``update_tenant`` below 0.19.0).

A stored query byte-identical to the FROZEN previous preset text becomes the
new text; anything else is customised and left alone with one WARNING. A
blank ``filterFormula`` on a billing task gets the draft filter. The IV/CS
DODTL join comes back with its ``LinkDODocKey`` column and line row; the DN
``FromDoc*`` columns leave with their rows.

All rows below are fake. Never real AutoCount data.
"""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import List, Optional

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.documents import (
    ENTITY_AR_OUTSTANDING,
    ENTITY_CASH_SALE,
    ENTITY_CREDIT_NOTE,
    ENTITY_DEBIT_NOTE,
    ENTITY_INVOICE,
)
from modules.autocount.mapping import SCOPE_LINE
from modules.autocount.models import (
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)
from modules.autocount.presets import DOCUMENT_PRESETS

KEYS = {"query": "header_query", "lineQuery": "line_query", "fingerprintQuery": "fingerprint_query"}
BILLING = (ENTITY_INVOICE, ENTITY_CASH_SALE, ENTITY_CREDIT_NOTE, ENTITY_DEBIT_NOTE)


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _company(db, database: str) -> AcCompany:
    api = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name=f"AC {database}",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}),
        is_active=True,
    )
    db.add(api)
    db.flush()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api.id, database_name=database,
        company_name=f"{database} Sdn Bhd", name=database, is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _old(entity_type: str, key: str, database: str) -> str:
    """The pre-plan-35 stored text for ``key``: the frozen old text where
    plan 35 changes it, else today's preset (unchanged by plan 35)."""
    from modules.autocount.backfill import _PRE35_BILLING_TEXTS

    text = _PRE35_BILLING_TEXTS.get(entity_type, {}).get(key)
    if text is None:
        text = getattr(DOCUMENT_PRESETS[entity_type], KEYS[key])
    return text.replace("{database}", database)


def _new(entity_type: str, key: str, database: str) -> str:
    return getattr(DOCUMENT_PRESETS[entity_type], KEYS[key]).replace("{database}", database)


def _config(
    db, company, entity_type, *, overrides: Optional[dict] = None,
    result_columns: Optional[List[str]] = None, line_columns: Optional[List[str]] = None,
) -> AcEntityConfig:
    database = company.database_name
    source_config = {
        "connectionId": "conn-x", "keyColumns": list(DOCUMENT_PRESETS[entity_type].key_columns),
        "watermarkColumn": "LastModified", "comparedColumns": [], "filterFormula": None,
    }
    for key in KEYS:
        source_config[key] = _old(entity_type, key, database)
    source_config.update(overrides or {})
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
        source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = source_config
    config.result_columns = result_columns
    config.line_result_columns = line_columns
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _line_row(db, company, entity_type, source_path, canonical_field, *, enabled=True):
    db.add(AcFieldMapping(
        id=str(uuid.uuid4()), tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
        entity_type=entity_type, scope=SCOPE_LINE, source_path=source_path,
        canonical_field=canonical_field, transform="string", is_required=False,
        is_enabled=enabled, sort_order=20,
    ))
    db.commit()


def _rows(db, company_id, entity_type, source_path) -> List[AcFieldMapping]:
    return db.query(AcFieldMapping).filter(
        AcFieldMapping.company_id == company_id,
        AcFieldMapping.entity_type == entity_type,
        AcFieldMapping.scope == SCOPE_LINE,
        AcFieldMapping.source_path == source_path,
    ).all()


def _run(db, **kwargs) -> int:
    from modules.autocount.backfill import backfill_billing_preset_fix

    touched = backfill_billing_preset_fix(db, schema=None, **kwargs)
    db.commit()
    db.expire_all()
    return touched


# ── frozen texts ─────────────────────────────────────────────────────────────


def test_the_frozen_new_texts_are_todays_preset():
    from modules.autocount.backfill import _BILLING_DRAFT_FILTER, _POST35_BILLING_TEXTS

    for entity_type, texts in _POST35_BILLING_TEXTS.items():
        for key, text in texts.items():
            assert text == getattr(DOCUMENT_PRESETS[entity_type], KEYS[key]), (entity_type, key)
    for entity_type in BILLING:
        assert DOCUMENT_PRESETS[entity_type].filter_formula == _BILLING_DRAFT_FILTER


def test_the_frozen_old_texts_are_what_plan_35_fixes():
    from modules.autocount.backfill import (
        _NEW_BILLING_DO_LINE_QUERIES,
        _POST35_BILLING_TEXTS,
        _PRE35_BILLING_TEXTS,
    )

    # CN queries are unchanged by plan 35 (only its filter moves).
    assert set(_PRE35_BILLING_TEXTS) == {
        ENTITY_INVOICE, ENTITY_CASH_SALE, ENTITY_DEBIT_NOTE, ENTITY_AR_OUTSTANDING,
    }
    for entity_type, texts in _PRE35_BILLING_TEXTS.items():
        assert set(texts) == set(_POST35_BILLING_TEXTS[entity_type]), entity_type
        for key, old in texts.items():
            assert old != _POST35_BILLING_TEXTS[entity_type][key], (entity_type, key)
    # IV/CS lines: what 0032 wrote, so a task 0032 moved comes straight back.
    for entity_type in (ENTITY_INVOICE, ENTITY_CASH_SALE):
        assert _PRE35_BILLING_TEXTS[entity_type]["lineQuery"] == _NEW_BILLING_DO_LINE_QUERIES[entity_type]
    assert "h.DocStatus AS DocStatus" in _PRE35_BILLING_TEXTS[ENTITY_CASH_SALE]["query"]
    for key in ("query", "lineQuery", "fingerprintQuery"):
        assert "FromDoc" in _PRE35_BILLING_TEXTS[ENTITY_DEBIT_NOTE][key]
        assert "n.Cancelled" not in _PRE35_BILLING_TEXTS[ENTITY_AR_OUTSTANDING][key]


# ── rewrites ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("entity_type", [ENTITY_INVOICE, ENTITY_CASH_SALE])
def test_an_invoice_task_gets_the_dodtl_join_back_with_its_row(db, entity_type):
    """0032 disabled the LinkDODocKey row; it comes back enabled."""
    company = _company(db, f"FAKE_DB_P35_{entity_type.upper()}")
    database = company.database_name
    config = _config(
        db, company, entity_type, line_columns=["DocKey", "DtlKey", "FromDocDtlKey", "LinkSODocKey"],
    )
    _line_row(db, company, entity_type, "LinkDODocKey", "link_do_doc_key", enabled=False)
    config_id = config.id

    assert _run(db) > 0
    after = db.get(AcEntityConfig, config_id)
    for key in KEYS:
        assert after.source_config[key] == _new(entity_type, key, database), key
    assert "DODTL" in after.source_config["lineQuery"]
    assert after.line_result_columns == [
        "DocKey", "DtlKey", "FromDocDtlKey", "LinkSODocKey", "LinkDODocKey",
    ]
    assert after.source_config["filterFormula"] == DOCUMENT_PRESETS[entity_type].filter_formula
    [row] = _rows(db, company.id, entity_type, "LinkDODocKey")
    assert row.is_enabled is True
    # Idempotent: a second pass changes nothing.
    assert _run(db) == 0


def test_an_invoice_task_without_a_do_row_gets_one(db):
    """A task created after 0032 shipped was seeded from the DODTL-free preset."""
    company = _company(db, "FAKE_DB_P35_NOROW")
    config = _config(db, company, ENTITY_INVOICE, line_columns=None)
    config_id = config.id

    assert _run(db) > 0
    after = db.get(AcEntityConfig, config_id)
    assert after.line_result_columns is None  # never previewed stays NULL
    [row] = _rows(db, company.id, ENTITY_INVOICE, "LinkDODocKey")
    assert (row.canonical_field, row.transform, row.is_enabled) == ("link_do_doc_key", "int", True)
    assert _run(db) == 0


def test_a_cash_sale_header_stops_reading_doc_status(db):
    company = _company(db, "FAKE_DB_P35_CS")
    config = _config(db, company, ENTITY_CASH_SALE, result_columns=["DocKey", "DocStatus"])
    config_id = config.id
    assert _run(db) > 0
    after = db.get(AcEntityConfig, config_id)
    assert "NULL AS DocStatus" in after.source_config["query"]
    assert after.result_columns == ["DocKey", "DocStatus"]  # same column name


def test_a_debit_note_task_drops_the_from_doc_columns_and_rows(db):
    company = _company(db, "FAKE_DB_P35_DN")
    database = company.database_name
    config = _config(
        db, company, ENTITY_DEBIT_NOTE,
        result_columns=["DocKey", "LineFpCount", "LineFpLinked", "LastModified"],
        line_columns=["DocKey", "DtlKey", "FromDocType", "FromDocNo", "FromDocDtlKey", "SubTotal"],
    )
    for source, target in (
        ("FromDocType", "from_doc_type"), ("FromDocNo", "from_doc_no"),
        ("FromDocDtlKey", "from_doc_line_key"),
    ):
        _line_row(db, company, ENTITY_DEBIT_NOTE, source, target)
    _line_row(db, company, ENTITY_DEBIT_NOTE, "SubTotal", "line_total")
    config_id = config.id

    assert _run(db) > 0
    after = db.get(AcEntityConfig, config_id)
    for key in KEYS:
        assert after.source_config[key] == _new(ENTITY_DEBIT_NOTE, key, database), key
    assert after.result_columns == ["DocKey", "LineFpCount", "LastModified"]
    assert after.line_result_columns == ["DocKey", "DtlKey", "SubTotal"]
    for source in ("FromDocType", "FromDocNo", "FromDocDtlKey"):
        [row] = _rows(db, company.id, ENTITY_DEBIT_NOTE, source)
        assert row.is_enabled is False, source
    [kept] = _rows(db, company.id, ENTITY_DEBIT_NOTE, "SubTotal")
    assert kept.is_enabled is True
    assert after.source_config["filterFormula"] == DOCUMENT_PRESETS[ENTITY_DEBIT_NOTE].filter_formula
    assert _run(db) == 0


def test_a_credit_note_task_gets_the_draft_filter(db):
    company = _company(db, "FAKE_DB_P35_CN")
    config = _config(db, company, ENTITY_CREDIT_NOTE)
    config_id = config.id
    assert _run(db) > 0
    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["filterFormula"] == DOCUMENT_PRESETS[ENTITY_CREDIT_NOTE].filter_formula
    assert _run(db) == 0


def test_an_ar_task_stops_counting_cancelled_notes(db):
    company = _company(db, "FAKE_DB_P35_AR")
    database = company.database_name
    config = _config(db, company, ENTITY_AR_OUTSTANDING)
    config_id = config.id
    assert _run(db) > 0
    after = db.get(AcEntityConfig, config_id)
    for key in KEYS:
        assert after.source_config[key] == _new(ENTITY_AR_OUTSTANDING, key, database), key
    assert after.source_config["filterFormula"] is None  # no draft filter on AR
    assert _run(db) == 0


# ── customised tasks ─────────────────────────────────────────────────────────


def test_a_customised_query_is_left_alone_with_a_warning(db, caplog):
    company = _company(db, "FAKE_DB_P35_CUSTOM")
    custom = _old(ENTITY_DEBIT_NOTE, "query", company.database_name) + " WHERE 1 = 1"
    config = _config(db, company, ENTITY_DEBIT_NOTE, overrides={"query": custom})
    config_id = config.id
    with caplog.at_level(logging.WARNING):
        _run(db)
    assert config_id in caplog.text
    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == custom
    # The untouched-by-hand queries still move: each key stands on its own.
    assert after.source_config["lineQuery"] == _new(ENTITY_DEBIT_NOTE, "lineQuery", company.database_name)


def test_a_hand_written_filter_is_left_alone_with_a_warning(db, caplog):
    company = _company(db, "FAKE_DB_P35_FILTER")
    config = _config(db, company, ENTITY_INVOICE, overrides={"filterFormula": 'DocNo != "X"'})
    config_id = config.id
    with caplog.at_level(logging.WARNING):
        _run(db)
    assert config_id in caplog.text
    assert db.get(AcEntityConfig, config_id).source_config["filterFormula"] == 'DocNo != "X"'


def test_other_entities_are_never_touched(db):
    company = _company(db, "FAKE_DB_P35_SO")
    line = _old(ENTITY_INVOICE, "lineQuery", company.database_name)
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type="sales_order",
        source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = {"lineQuery": line, "filterFormula": None}
    db.add(config)
    db.commit()
    config_id = config.id
    assert _run(db) == 0
    after = db.get(AcEntityConfig, config_id)
    assert after.source_config == {"lineQuery": line, "filterFormula": None}


def test_a_config_never_resolves_another_tenants_company(db):
    from app.models.tenant import Tenant

    other_tenant = db.query(Tenant).filter(Tenant.id != DEFAULT_TENANT_ID).first()
    assert other_tenant is not None
    foreign = _company(db, "FAKE_DB_P35_FOREIGN")
    foreign.tenant_id = other_tenant.id
    db.commit()
    config = _config(db, foreign, ENTITY_INVOICE)
    config.tenant_id = DEFAULT_TENANT_ID
    db.commit()
    config_id = config.id
    assert _run(db) == 0
    assert "DODTL" not in db.get(AcEntityConfig, config_id).source_config["lineQuery"]


def test_the_pass_scopes_to_one_tenant(db):
    company = _company(db, "FAKE_DB_P35_SCOPE")
    config = _config(db, company, ENTITY_CREDIT_NOTE)
    config_id = config.id
    assert _run(db, tenant_id="some-other-tenant") == 0
    assert db.get(AcEntityConfig, config_id).source_config["filterFormula"] is None


# ── wiring ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("from_version,rewritten", [("0.18.0", True), ("0.19.0", False)])
def test_update_tenant_runs_the_pass_below_0_19_only(db, from_version, rewritten):
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, f"FAKE_DB_P35_UPD_{from_version.replace('.', '')}")
    config = _config(db, company, ENTITY_CREDIT_NOTE)
    config_id = config.id
    update_tenant(db, DEFAULT_TENANT_ID, from_version)
    db.commit()
    db.expire_all()
    after = db.get(AcEntityConfig, config_id)
    assert (after.source_config["filterFormula"] is not None) is rewritten


def test_the_manifest_is_0_19_0():
    import json

    manifest = Path(__file__).resolve().parents[1] / "modules" / "autocount" / "manifest.json"
    assert json.loads(manifest.read_text())["version"] == "0.19.0"


def test_module_migration_0033_runs_the_pass():
    versions = Path(__file__).resolve().parents[1] / "modules" / "autocount" / "alembic" / "versions"
    [path] = list(versions.glob("0033_*.py"))
    text = path.read_text()
    revision = re.search(r'^revision: str = "([^"]+)"', text, re.M).group(1)
    assert len(revision) <= 32
    assert re.search(r'^down_revision[^=]*= "0032_autocount_so_remark"', text, re.M)
    assert "backfill_billing_preset_fix" in text
