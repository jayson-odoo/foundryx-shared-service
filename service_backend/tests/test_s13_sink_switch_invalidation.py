"""Plan 13 review round 2 (S3 fix) - a sink-target switch (`CompanyService.
set_sink_target`) must never silently strand records: an `autocount_http`
task's own `ac_row_hash` population is a diff baseline against whatever the
OLD target already received (D6, changed-only staging), so a record
unchanged since then would never restage for a NEW target that has no idea
it exists. A genuine `sink_impl`/`sink_connection_id` change INVALIDATES
(the SAME mechanism Re-push uses, `RowHashRepository.invalidate_all` -
never a delete) every `autocount_http` task's hashes for that company; a
call that changes NOTHING (same impl, same connection) must leave them
alone; a `sql_db` task's hashes are untouched either way (this plan's own
scope is HTTP tasks only).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import (
    SINK_IMPL_LOGGING,
    SINK_IMPL_SORENTO,
    AcCompany,
    AcEntityConfig,
)
from modules.autocount.repositories import RowHashRepository
from modules.autocount.services.company_service import CompanyService

NOW = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)


def _api_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="api",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _sorento_connection(db, name="Sorento 1") -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sorento", type="consumer", name=name,
        config_json={"baseUrl": "https://sorento.example.com"},
        credentials_json=encrypt_secret({"apiKey": "k"}), is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, api_conn_id) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api_conn_id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _http_task(db, company_id, entity_type=ENTITY_PRODUCT):
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company_id, entity_type=entity_type,
        source_impl="autocount_http",
        source_config={"path": "/itembypage", "keyFields": ["ItemCode"], "watermarkField": None},
    )
    db.add(config)
    db.commit()
    return config


def _sql_task(db, company_id, entity_type="customer"):
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company_id, entity_type=entity_type,
        source_impl="sql_db",
        source_config={"query": "SELECT 1 AS code", "keyColumns": ["code"]},
    )
    db.add(config)
    db.commit()
    return config


def test_a_genuine_sink_switch_invalidates_an_http_tasks_hashes(session_factory):
    db = session_factory()
    api_conn = _api_connection(db)
    company = _company(db, api_conn.id)
    _http_task(db, company.id, ENTITY_PRODUCT)
    sorento = _sorento_connection(db)

    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        {"AED_SORENTO:A1": "real-hash-a1", "AED_SORENTO:A2": "real-hash-a2"},
        seen_at=NOW,
    )
    db.commit()

    # logging -> sorento is a genuine sink_impl change.
    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id,
        sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento.id,
        sorento_company_code="SRT",
    )

    rows = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert set(rows) == {"AED_SORENTO:A1", "AED_SORENTO:A2"}, (
        "a sink switch must INVALIDATE, never delete - every ref stays known"
    )
    assert all(v.startswith("repush:") for v in rows.values()), (
        "every hash must be stamped unrecognisable so the next run restages it"
    )


def test_switching_between_two_different_sorento_companies_also_invalidates(session_factory):
    """Same impl (`sorento`), DIFFERENT connection id - still a genuine
    switch. `connections` carries a UNIQUE (tenant, provider) constraint
    (one Sorento connection per tenant), so the second connection is
    minted under the SAME tenant after the first is deleted (the unique
    slot cleared first, never a second live row) - the point under test
    is purely the id comparison inside `set_sink_target`, tenant-scoped
    like every other read there."""
    db = session_factory()
    api_conn = _api_connection(db)
    company = _company(db, api_conn.id)
    _http_task(db, company.id, ENTITY_PRODUCT)
    sorento_a = _sorento_connection(db, name="Sorento A")

    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id,
        sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento_a.id,
        sorento_company_code="SRT",
    )
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        {"AED_SORENTO:A1": "real-hash-a1"}, seen_at=NOW,
    )
    db.commit()

    # Simulate a rotated connection id the same way an operator deleting
    # and re-adding the Sorento connection would produce - a fresh row,
    # same provider slot cleared first (the unique constraint forbids two
    # live rows at once).
    db.delete(db.get(Connection, sorento_a.id))
    db.commit()
    sorento_b = _sorento_connection(db, name="Sorento A (re-added)")

    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id,
        sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento_b.id,
        sorento_company_code="SRT",
    )

    rows = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert rows["AED_SORENTO:A1"].startswith("repush:")


def test_a_no_op_sink_save_never_invalidates_anything(session_factory):
    """Control - saving the SAME sink target (no impl/connection change,
    e.g. re-saving the company code) must never touch the hashes."""
    db = session_factory()
    api_conn = _api_connection(db)
    company = _company(db, api_conn.id)
    _http_task(db, company.id, ENTITY_PRODUCT)
    sorento = _sorento_connection(db)

    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id,
        sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento.id,
        sorento_company_code="SRT",
    )
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        {"AED_SORENTO:A1": "real-hash-a1"}, seen_at=NOW,
    )
    db.commit()

    # Same sink_impl, SAME connection id - genuinely nothing changed.
    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id,
        sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento.id,
        sorento_company_code="SRT",
    )

    rows = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert rows["AED_SORENTO:A1"] == "real-hash-a1"


def test_changing_only_the_sorento_company_code_also_invalidates(session_factory):
    """F2 (plan 13 round-2 review fixes) - same `sink_impl`, same
    connection, but a DIFFERENT `sorento_company_code`: one connection can
    host more than one downstream Sorento company, so re-pointing the code
    alone must invalidate exactly like a sink_impl/connection change - the
    old code's push history has no idea the new company's baseline needs
    a full re-offer."""
    db = session_factory()
    api_conn = _api_connection(db)
    company = _company(db, api_conn.id)
    _http_task(db, company.id, ENTITY_PRODUCT)
    sorento = _sorento_connection(db)

    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id,
        sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento.id,
        sorento_company_code="SRT",
    )
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        {"AED_SORENTO:A1": "real-hash-a1"}, seen_at=NOW,
    )
    db.commit()

    # Same impl, same connection, DIFFERENT company code.
    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id,
        sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento.id,
        sorento_company_code="MCH",
    )

    rows = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert rows["AED_SORENTO:A1"].startswith("repush:")


def test_resaving_the_same_company_code_with_different_case_never_invalidates(session_factory):
    """Control - the code comparison is normalized (stripped, upper-cased):
    a save that only touches case/whitespace on the SAME code must not
    read as a change."""
    db = session_factory()
    api_conn = _api_connection(db)
    company = _company(db, api_conn.id)
    _http_task(db, company.id, ENTITY_PRODUCT)
    sorento = _sorento_connection(db)

    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id,
        sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento.id,
        sorento_company_code="SRT",
    )
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        {"AED_SORENTO:A1": "real-hash-a1"}, seen_at=NOW,
    )
    db.commit()

    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id,
        sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento.id,
        sorento_company_code="  srt  ",
    )

    rows = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert rows["AED_SORENTO:A1"] == "real-hash-a1"


def test_a_sink_switch_never_touches_a_sql_db_tasks_hashes(session_factory):
    """S3's own scope: `autocount_http` tasks only (D6, changed-only
    staging, applies to HTTP tasks) - a `sql_db` task's hashes are its
    OWN, pre-plan-13 reconcile-diff baseline and must be untouched."""
    db = session_factory()
    api_conn = _api_connection(db)
    company = _company(db, api_conn.id)
    _sql_task(db, company.id, "customer")
    sorento = _sorento_connection(db)

    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, "customer",
        {"AED_SORENTO:C1": "real-hash-c1"}, seen_at=NOW,
    )
    db.commit()

    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id,
        sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento.id,
        sorento_company_code="SRT",
    )

    rows = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, "customer")
    assert rows["AED_SORENTO:C1"] == "real-hash-c1"


def test_switching_back_to_logging_also_invalidates(session_factory):
    db = session_factory()
    api_conn = _api_connection(db)
    company = _company(db, api_conn.id)
    _http_task(db, company.id, ENTITY_PRODUCT)
    sorento = _sorento_connection(db)

    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id,
        sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento.id,
        sorento_company_code="SRT",
    )
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        {"AED_SORENTO:A1": "real-hash-a1"}, seen_at=NOW,
    )
    db.commit()

    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id, sink_impl=SINK_IMPL_LOGGING,
    )

    rows = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert rows["AED_SORENTO:A1"].startswith("repush:")
