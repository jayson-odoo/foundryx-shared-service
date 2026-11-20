"""A document task's fingerprint query survives a Source-tab Save (lane
SS-BILLING-PRESET-FIX, crew finding F-B, 27 Oct).

Before: the Save body schema had no ``fingerprintQuery`` and the router
passed ``model_dump()``, so the validator stored ``fingerprintQuery=None`` on
EVERY save - a task set up in the UI never had a line-fingerprint sweep and
any later Save wiped one the backfill had set (line-only edits and AR
knock-offs then waited for the daily reconcile).

Now: a save that sends no fingerprint query keeps the stored one; with none
stored, the entity's preset sweep query is used (company database
substituted) - the same policy as ``backfill_document_fingerprint_queries``.
An explicit one is stored as sent.

All rows below are fake. Never real AutoCount data.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict

from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.documents import ENTITY_SALES_ORDER
from modules.autocount.models import AcDocFingerprint, AcEntityConfig
from modules.autocount.presets import DOCUMENT_PRESETS
from modules.autocount.schemas import EtlSourceConfigIn
from modules.autocount.services.etl_service import EtlService

from tests.test_autocount_document_mapping import (
    HEADER_QUERY,
    LINE_QUERY,
    _company,
    _source_engine_typed,
    _sql_connection,
)

CUSTOM_SWEEP = (
    "SELECT doc_key AS DocKey, COUNT(*) AS LineFpCount FROM so_line GROUP BY doc_key"
)


def _raw(conn_id: str, **extra) -> Dict[str, object]:
    raw: Dict[str, object] = {
        "connectionId": conn_id, "query": HEADER_QUERY, "lineQuery": LINE_QUERY,
        "keyColumns": ["doc_key"], "watermarkColumn": "last_modified",
        "comparedColumns": [], "fromDate": "2026-01-01", "docDateColumn": "doc_date",
        "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
    }
    raw.update(extra)
    return raw


def _rig(db, database: str):
    header_rows = [
        ("D001", "SO-001", "open", "F", dt.date(2026, 8, 1), dt.datetime(2026, 8, 1, 9, 0, 0)),
    ]
    engine = _source_engine_typed(header_rows, {"D001": [("D001-1", "ITEM-A", "10", "0", 1)]})
    conn = _sql_connection(db, engine, database=database, name=f"src {database}")
    company = _company(db, conn.id, database=database, name=f"{database} Co")
    return conn, company


def _stored(db, company_id: str) -> Dict[str, object]:
    db.expire_all()
    config = db.query(AcEntityConfig).filter(
        AcEntityConfig.company_id == company_id,
        AcEntityConfig.entity_type == ENTITY_SALES_ORDER,
    ).one()
    return dict(config.source_config or {})


def test_a_first_save_without_a_sweep_query_takes_the_entity_presets(session_factory):
    db = session_factory()
    conn, company = _rig(db, "AED_FPKEEP1")
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, _raw(conn.id))
    expected = DOCUMENT_PRESETS[ENTITY_SALES_ORDER].fingerprint_query.replace(
        "{database}", "AED_FPKEEP1",
    )
    assert _stored(db, company.id)["fingerprintQuery"] == expected
    db.close()


def test_a_save_without_a_sweep_query_keeps_the_stored_one(session_factory):
    db = session_factory()
    conn, company = _rig(db, "AED_FPKEEP2")
    service = EtlService(db)
    service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER,
        _raw(conn.id, fingerprintQuery=CUSTOM_SWEEP),
    )
    assert _stored(db, company.id)["fingerprintQuery"] == CUSTOM_SWEEP
    # A later Source-tab Save sends no fingerprint query: the stored one stays.
    service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, _raw(conn.id, fromDate="2025-01-01"),
    )
    stored = _stored(db, company.id)
    assert stored["fromDate"] == "2025-01-01"
    assert stored["fingerprintQuery"] == CUSTOM_SWEEP
    # An explicit null is "not sent" too (the wire model's default).
    service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, _raw(conn.id, fingerprintQuery=None),
    )
    assert _stored(db, company.id)["fingerprintQuery"] == CUSTOM_SWEEP
    db.close()


def test_an_explicit_sweep_query_replaces_the_stored_one(session_factory):
    db = session_factory()
    conn, company = _rig(db, "AED_FPKEEP3")
    service = EtlService(db)
    service.update_task(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, _raw(conn.id))
    service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER,
        _raw(conn.id, fingerprintQuery=CUSTOM_SWEEP),
    )
    assert _stored(db, company.id)["fingerprintQuery"] == CUSTOM_SWEEP
    db.close()


def test_the_save_body_carries_a_sweep_query():
    """The wire model used to drop the key (no field, extras ignored)."""
    dumped = EtlSourceConfigIn(query="SELECT 1", fingerprintQuery=CUSTOM_SWEEP).model_dump()
    assert dumped["fingerprintQuery"] == CUSTOM_SWEEP
    assert EtlSourceConfigIn(query="SELECT 1").model_dump()["fingerprintQuery"] is None


def test_a_put_through_the_route_keeps_the_stored_sweep_query(client, session_factory):
    """The Source tab's real path: PUT .../etl-task with no fingerprintQuery."""
    db = session_factory()
    conn, company = _rig(db, "AED_FPKEEP4")
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER,
        _raw(conn.id, fingerprintQuery=CUSTOM_SWEEP),
    )
    company_id, conn_id = company.id, conn.id
    db.close()

    login = client.post("/auth/login", json={"email": "demo@example.com", "password": "demo1234"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.put(
        f"/autocount/companies/{company_id}/entities/{ENTITY_SALES_ORDER}/etl-task",
        json={"sourceConfig": _raw(conn_id, fromDate="2025-06-01")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    db = session_factory()
    stored = _stored(db, company_id)
    assert stored["fromDate"] == "2025-06-01"
    assert stored["fingerprintQuery"] == CUSTOM_SWEEP
    db.close()


# ── review round 1: a changed sweep query resets its fingerprint rows ───────


def _seed_fingerprints(db, company_id: str, *refs: str) -> None:
    for ref in refs:
        db.add(AcDocFingerprint(
            tenant_id=DEFAULT_TENANT_ID, company_id=company_id,
            entity_type=ENTITY_SALES_ORDER, source_ref=ref, fingerprint="old-sha",
        ))
    db.commit()


def _fingerprint_refs(db, company_id: str):
    db.expire_all()
    return sorted(r.source_ref for r in db.query(AcDocFingerprint).filter(
        AcDocFingerprint.tenant_id == DEFAULT_TENANT_ID,
        AcDocFingerprint.company_id == company_id,
        AcDocFingerprint.entity_type == ENTITY_SALES_ORDER,
    ))


def test_a_new_sweep_query_text_resets_the_stored_fingerprints(session_factory):
    """A different sweep text hashes every document differently: left in
    place, the next tick would re-stage the whole window unpaced. Same rule
    as backfill.py's fingerprint rewrites (plan 06 S1)."""
    db = session_factory()
    conn, company = _rig(db, "AED_FPKEEP5")
    service = EtlService(db)
    service.update_task(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, _raw(conn.id))
    _seed_fingerprints(db, company.id, "AED_FPKEEP5:D001", "AED_FPKEEP5:D002")
    service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER,
        _raw(conn.id, fingerprintQuery=CUSTOM_SWEEP),
    )
    assert _fingerprint_refs(db, company.id) == []
    db.close()


def test_a_wiped_sweep_refilled_by_the_preset_resets_the_stored_fingerprints(session_factory):
    """A pre-plan-36 Save left fingerprintQuery None but kept the old rows;
    the first plan-36 Save fills the preset text, so those rows go."""
    db = session_factory()
    conn, company = _rig(db, "AED_FPKEEP6")
    service = EtlService(db)
    service.update_task(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, _raw(conn.id))
    config = db.query(AcEntityConfig).filter(AcEntityConfig.company_id == company.id).one()
    config.source_config = {**config.source_config, "fingerprintQuery": None}
    db.commit()
    _seed_fingerprints(db, company.id, "AED_FPKEEP6:D001")
    service.update_task(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, _raw(conn.id))
    assert _stored(db, company.id)["fingerprintQuery"]
    assert _fingerprint_refs(db, company.id) == []
    db.close()


def test_a_save_that_keeps_the_sweep_query_keeps_the_fingerprints(session_factory):
    db = session_factory()
    conn, company = _rig(db, "AED_FPKEEP7")
    service = EtlService(db)
    service.update_task(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, _raw(conn.id))
    _seed_fingerprints(db, company.id, "AED_FPKEEP7:D001")
    service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, _raw(conn.id, fromDate="2025-01-01"),
    )
    assert _fingerprint_refs(db, company.id) == ["AED_FPKEEP7:D001"]
    db.close()


def test_the_update_tenant_backfill_filling_a_wiped_sweep_resets_its_fingerprints(session_factory):
    """Same gap on the App Store Update path: backfill_document_fingerprint_
    queries fills a None sweep with the preset text, so the old rows go."""
    from modules.autocount.backfill import backfill_document_fingerprint_queries

    db = session_factory()
    conn, company = _rig(db, "AED_FPKEEP8")
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, _raw(conn.id))
    config = db.query(AcEntityConfig).filter(AcEntityConfig.company_id == company.id).one()
    config.source_config = {**config.source_config, "fingerprintQuery": None}
    db.commit()
    _seed_fingerprints(db, company.id, "AED_FPKEEP8:D001")
    other = _rig(db, "AED_FPKEEP8B")[1]
    db.add(AcDocFingerprint(
        tenant_id=DEFAULT_TENANT_ID, company_id=other.id, entity_type=ENTITY_SALES_ORDER,
        source_ref="AED_FPKEEP8B:D001", fingerprint="other-sha",
    ))
    db.commit()
    assert backfill_document_fingerprint_queries(db, schema=None) >= 1
    db.commit()
    assert _stored(db, company.id)["fingerprintQuery"]
    assert _fingerprint_refs(db, company.id) == []
    # Another company's rows (no config to fill) are untouched.
    assert _fingerprint_refs(db, other.id) == ["AED_FPKEEP8B:D001"]
    db.close()
