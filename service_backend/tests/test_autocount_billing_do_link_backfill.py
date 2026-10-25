"""Lane SS-BILLING-DO-API - existing invoice / cash-sale tasks stored the
plan-32 line query that joins `DODTL`. The AutoCount admin will not grant it
(owner ruling 25 Oct), so module Alembic 0032 (+ `update_tenant` below
0.17.0) rewrites a byte-identical stored line query to the DODTL-free preset,
drops `LinkDODocKey` from the line columns, and disables the now-unselected
`LinkDODocKey -> link_do_doc_key` mapping row. A customised query is left
alone with a WARNING.

All rows below are fake. Never real AutoCount data.
"""
from __future__ import annotations

import logging
import uuid
from typing import List

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.documents import (
    ENTITY_CASH_SALE,
    ENTITY_CREDIT_NOTE,
    ENTITY_INVOICE,
)
from modules.autocount.mapping import SCOPE_LINE
from modules.autocount.models import (
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)
from modules.autocount.presets import CASH_SALE_PRESET, INVOICE_PRESET

PRESETS = {ENTITY_INVOICE: INVOICE_PRESET, ENTITY_CASH_SALE: CASH_SALE_PRESET}
LINE_COLUMNS = ["DocKey", "DtlKey", "FromDocType", "FromDocNo", "FromDocDtlKey",
                "LinkSODocKey", "LinkDODocKey"]


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


def _old_line(entity_type: str, database: str) -> str:
    from modules.autocount.backfill import _OLD_BILLING_DO_LINE_QUERIES

    return _OLD_BILLING_DO_LINE_QUERIES[entity_type].replace("{database}", database)


def _config(db, company, entity_type, *, line_query, line_columns=LINE_COLUMNS) -> AcEntityConfig:
    preset = PRESETS.get(entity_type, INVOICE_PRESET)
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
        source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = {
        "connectionId": "conn-x",
        "query": preset.header_query.replace("{database}", company.database_name),
        "lineQuery": line_query, "keyColumns": ["DocKey"],
        "watermarkColumn": "LastModified", "comparedColumns": [],
    }
    config.result_columns = ["DocKey", "DocNo", "LastModified"]
    config.line_result_columns = None if line_columns is None else list(line_columns)
    db.add(config)
    db.add(AcFieldMapping(
        id=str(uuid.uuid4()), tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
        entity_type=entity_type, scope=SCOPE_LINE, source_path="LinkDODocKey",
        canonical_field="link_do_doc_key", transform="int", is_required=False,
        is_enabled=True, sort_order=20,
    ))
    db.add(AcFieldMapping(
        id=str(uuid.uuid4()), tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
        entity_type=entity_type, scope=SCOPE_LINE, source_path="LinkSODocKey",
        canonical_field="link_so_doc_key", transform="int", is_required=False,
        is_enabled=True, sort_order=19,
    ))
    db.commit()
    db.refresh(config)
    return config


def _do_rows(db, company_id: str, entity_type: str) -> List[AcFieldMapping]:
    return (
        db.query(AcFieldMapping)
        .filter(
            AcFieldMapping.company_id == company_id,
            AcFieldMapping.entity_type == entity_type,
            AcFieldMapping.canonical_field == "link_do_doc_key",
        )
        .all()
    )


def test_the_frozen_new_texts_are_todays_preset():
    from modules.autocount.backfill import _NEW_BILLING_DO_LINE_QUERIES

    for entity_type, preset in PRESETS.items():
        assert _NEW_BILLING_DO_LINE_QUERIES[entity_type] == preset.line_query


def test_never_previewed_line_columns_stay_null(db):
    """NULL = never previewed (the mapping save skips its column check);
    the backfill must not turn it into "zero columns"."""
    from modules.autocount.backfill import backfill_billing_do_link_queries

    company = _company(db, "FAKE_DB_NULLCOLS")
    config = _config(
        db, company, ENTITY_INVOICE,
        line_query=_old_line(ENTITY_INVOICE, "FAKE_DB_NULLCOLS"), line_columns=None,
    )
    config_id = config.id
    db.expire_all()
    assert backfill_billing_do_link_queries(db, schema=None) == 2
    db.expire_all()
    after = db.get(AcEntityConfig, config_id)
    assert "DODTL" not in after.source_config["lineQuery"]
    assert after.line_result_columns is None


def test_the_frozen_old_texts_are_the_plan_32_dodtl_join():
    from modules.autocount.backfill import _OLD_BILLING_DO_LINE_QUERIES

    assert set(_OLD_BILLING_DO_LINE_QUERIES) == {ENTITY_INVOICE, ENTITY_CASH_SALE}
    for entity_type, old in _OLD_BILLING_DO_LINE_QUERIES.items():
        new = PRESETS[entity_type].line_query
        assert "DODTL" in old and "DODTL" not in new
        assert old.replace(", dd.DocKey AS LinkDODocKey", "", 1).replace(
            " LEFT JOIN {database}.dbo.DODTL AS dd ON d.FromDocType = 'DO' "
            "AND dd.DtlKey = d.FromDocDtlKey", "", 1,
        ) == new


@pytest.mark.parametrize("entity_type", [ENTITY_INVOICE, ENTITY_CASH_SALE])
def test_backfill_rewrites_a_plan_32_task(db, entity_type):
    from modules.autocount.backfill import backfill_billing_do_link_queries

    company = _company(db, f"FAKE_DB_{entity_type.upper()}")
    database = company.database_name
    config = _config(db, company, entity_type, line_query=_old_line(entity_type, database))
    config_id = config.id
    db.expire_all()

    assert backfill_billing_do_link_queries(db, schema=None) == 2
    db.expire_all()
    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["lineQuery"] == PRESETS[entity_type].line_query.replace(
        "{database}", database,
    )
    assert "LinkDODocKey" not in after.line_result_columns
    assert after.line_result_columns == [c for c in LINE_COLUMNS if c != "LinkDODocKey"]
    [row] = _do_rows(db, company.id, entity_type)
    assert row.is_enabled is False
    # Only the DO link row - the SO link row (still selected) stays enabled.
    so_row = db.query(AcFieldMapping).filter(
        AcFieldMapping.company_id == company.id,
        AcFieldMapping.entity_type == entity_type,
        AcFieldMapping.canonical_field == "link_so_doc_key",
    ).one()
    assert so_row.is_enabled is True
    # Idempotent: a second pass changes nothing.
    assert backfill_billing_do_link_queries(db, schema=None) == 0


def test_a_customised_line_query_is_left_alone_with_a_warning(db, caplog):
    from modules.autocount.backfill import backfill_billing_do_link_queries

    company = _company(db, "FAKE_DB_CUSTOM")
    custom = _old_line(ENTITY_INVOICE, "FAKE_DB_CUSTOM") + " AND 1 = 1"
    config = _config(db, company, ENTITY_INVOICE, line_query=custom)
    config_id = config.id
    db.expire_all()
    with caplog.at_level(logging.WARNING):
        assert backfill_billing_do_link_queries(db, schema=None) == 0
    assert config_id in caplog.text
    db.expire_all()
    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["lineQuery"] == custom
    assert "LinkDODocKey" in after.line_result_columns
    [row] = _do_rows(db, company.id, ENTITY_INVOICE)
    assert row.is_enabled is True


def test_other_billing_entities_are_never_touched(db):
    from modules.autocount.backfill import backfill_billing_do_link_queries

    company = _company(db, "FAKE_DB_CN")
    line = _old_line(ENTITY_INVOICE, "FAKE_DB_CN")
    config = _config(db, company, ENTITY_CREDIT_NOTE, line_query=line)
    config_id = config.id
    db.expire_all()
    assert backfill_billing_do_link_queries(db, schema=None) == 0
    db.expire_all()
    assert db.get(AcEntityConfig, config_id).source_config["lineQuery"] == line


def test_a_config_never_resolves_another_tenants_company(db):
    from app.models.tenant import Tenant
    from modules.autocount.backfill import backfill_billing_do_link_queries

    other_tenant = db.query(Tenant).filter(Tenant.id != DEFAULT_TENANT_ID).first()
    assert other_tenant is not None
    foreign = _company(db, "FAKE_DB_FOREIGN")
    foreign.tenant_id = other_tenant.id
    db.commit()
    config = _config(db, foreign, ENTITY_INVOICE, line_query=_old_line(ENTITY_INVOICE, "FAKE_DB_FOREIGN"))
    config.tenant_id = DEFAULT_TENANT_ID
    db.commit()
    config_id = config.id
    db.expire_all()
    assert backfill_billing_do_link_queries(db, schema=None) == 0
    db.expire_all()
    assert "DODTL" in db.get(AcEntityConfig, config_id).source_config["lineQuery"]


@pytest.mark.parametrize("from_version,rewritten", [("0.16.0", True), ("0.17.0", False)])
def test_update_tenant_runs_the_backfill_below_0_17_only(db, from_version, rewritten):
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, f"FAKE_DB_UPD_{from_version.replace('.', '')}")
    config = _config(db, company, ENTITY_INVOICE, line_query=_old_line(ENTITY_INVOICE, company.database_name))
    config_id = config.id
    db.expire_all()
    update_tenant(db, DEFAULT_TENANT_ID, from_version)
    db.commit()
    db.expire_all()
    after = db.get(AcEntityConfig, config_id)
    assert ("DODTL" not in after.source_config["lineQuery"]) is rewritten
