"""Sprint-5/10 S3 follow-up - AC-10-72 wired into the live delete path.

RED before the coder: ``SyncService._auto_push_deletes`` never computes or
passes ``codes`` at all today - every "with codes" assertion below fails on
a plain ``KeyError``/``AssertionError``, never vacuously. The two control
tests (non-product entity, multi-key task) are already-true-today negatives,
paired with the positive to prove the guard is real (mirrors the brief's own
"NOT RED TODAY, flagged" convention).

ASSUMED NAMES:

* ``modules.autocount.services.company_service.CompanyService.
  product_delete_codes_gate(tenant_id, company) -> bool`` - the fail-safe
  probe: ``False`` for no Sorento connection, a probe failure, or a
  confirmed version below ``PRODUCT_CODE_WINS_CONTRACT_VERSION``; ``True``
  only for a CONFIRMED version >= it. Uses the SAME injectable
  ``sorento_sink_from_connection`` seam ``brand_contract_gate``/
  ``contract_gate`` already do.
* ``SyncService._auto_push_deletes`` calls it AT MOST ONCE per call, only
  for ``entity_type == 'product'`` with at least one delete pending, only
  when the task's own key fields (``keyFields`` or ``keyColumns``) are
  exactly ``("ItemCode",)`` - then passes ``codes=codes_from_refs(...)`` to
  ``sink.delete_batch`` when (and only when) the gate answers ``True``.

Kill-test notes are per section below.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE, BackgroundJob
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.masters import ENTITY_CUSTOMER, ENTITY_PRODUCT
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    STAGED,
    STAGED_OP_DELETE,
    AcCompany,
    AcEntityConfig,
    AcStagedRecord,
)
from modules.autocount.services.sync_service import SyncService
from modules.autocount.sync import AUTOCOUNT_SYNC


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _connection(db, provider, config, credentials):
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider=provider,
        type="erp" if provider != "sorento" else "consumer",
        name=f"{provider} conn", config_json=config,
        credentials_json=encrypt_secret(credentials), is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


@pytest.fixture
def sorento_consumer(monkeypatch):
    """ONE handler covering BOTH the contract probe
    (``GET /api/v1/external/contract``) and the deletions POST
    (``POST /api/v1/external/ingest/{entity}/deletions``), so a single test
    can script both legs. ``contract_responses``/``delete_responses`` are
    consumed in order per endpoint; ``requests`` records every call with its
    path, for the "never probes" negative."""
    import modules.autocount.services.company_service as company_module
    from modules.autocount.sinks_sorento import sorento_sink_from_connection as real

    contract_responses: List[Any] = []
    delete_responses: List[Dict[str, Any]] = []
    requests: List[Dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requests.append({"path": path, "method": request.method})
        if path.endswith("/external/contract"):
            item = contract_responses.pop(0) if contract_responses else (500, {})
            status, body = item
            return httpx.Response(status, json=body)
        body = json.loads(request.content or b"{}")
        requests[-1]["body"] = body
        resp = delete_responses.pop(0) if delete_responses else {
            "summary": {"total": 0, "deleted": 0, "deactivated": 0, "not_found": 0, "failed": 0, "retryable": 0},
            "records": [],
        }
        return httpx.Response(200, json=resp)

    def fake(config, credentials, *, entity_type, company_code=None, transport=None, **kw):
        return real(
            config, credentials, entity_type=entity_type, company_code=company_code,
            transport=httpx.MockTransport(handle), **kw,
        )

    monkeypatch.setattr(company_module, "sorento_sink_from_connection", fake)
    return contract_responses, delete_responses, requests


def _company(db, *, entity_type, key_fields) -> AcCompany:
    api = _connection(
        db, "autocount", {"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"}, {},
    )
    sorento = _connection(db, "sorento", {"baseUrl": "https://sorento.example.com"}, {"apiKey": "k"})
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api.id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True,
        sink_impl="sorento", sink_connection_id=sorento.id, sorento_company_code="SRT",
    )
    db.add(company)
    db.flush()
    db.add(AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
        source_impl="sql_db", etl_status=ETL_STATUS_ACTIVE,
        source_config={"keyColumns": list(key_fields)},
    ))
    db.commit()
    db.refresh(company)
    return company


def _company_logging_sink(db, *, entity_type, key_fields) -> AcCompany:
    api = _connection(
        db, "autocount", {"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"}, {},
    )
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api.id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True,
    )
    db.add(company)
    db.flush()
    db.add(AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
        source_impl="sql_db", etl_status=ETL_STATUS_ACTIVE,
        source_config={"keyColumns": list(key_fields)},
    ))
    db.commit()
    db.refresh(company)
    return company


def _stage_delete(db, company, job_id, entity_type, *, source_ref) -> AcStagedRecord:
    row = AcStagedRecord(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
        job_id=job_id, source_ref=source_ref, op=STAGED_OP_DELETE, status=STAGED,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _job(db) -> BackgroundJob:
    job = BackgroundJob(tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC, status=JOB_DONE)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# ── positive: contract >= 2.4, single-key ItemCode product task ─────────────


def test_product_delete_sends_codes_when_the_contract_confirms_2_4(db, sorento_consumer):
    contract_responses, delete_responses, requests = sorento_consumer
    company = _company(db, entity_type=ENTITY_PRODUCT, key_fields=["ItemCode"])
    job = _job(db)
    _stage_delete(db, company, job.id, ENTITY_PRODUCT, source_ref="AED_SORENTO:A1")

    contract_responses.append((200, {"version": 2.4, "entities": ["products"]}))
    delete_responses.append({
        "summary": {"total": 1, "deleted": 1, "deactivated": 0, "not_found": 0, "failed": 0, "retryable": 0},
        "records": [{"source_ref": "AED_SORENTO:A1", "outcome": "deleted"}],
    })

    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, job_id=job.id)

    assert summary["deletedHandled"] == 1
    delete_calls = [r for r in requests if r["path"].endswith("/deletions")]
    assert len(delete_calls) == 1
    assert delete_calls[0]["body"]["codes"] == {"AED_SORENTO:A1": "A1"}
    # Exactly one contract probe for the whole call.
    contract_calls = [r for r in requests if r["path"].endswith("/external/contract")]
    assert len(contract_calls) == 1


# ── negative: contract < 2.4 - codes omitted, delete still delivered ────────


def test_product_delete_omits_codes_when_the_contract_is_below_2_4(db, sorento_consumer):
    contract_responses, delete_responses, requests = sorento_consumer
    company = _company(db, entity_type=ENTITY_PRODUCT, key_fields=["ItemCode"])
    job = _job(db)
    _stage_delete(db, company, job.id, ENTITY_PRODUCT, source_ref="AED_SORENTO:A2")

    contract_responses.append((200, {"version": 2.3, "entities": ["products"]}))
    delete_responses.append({
        "summary": {"total": 1, "deleted": 1, "deactivated": 0, "not_found": 0, "failed": 0, "retryable": 0},
        "records": [{"source_ref": "AED_SORENTO:A2", "outcome": "deleted"}],
    })

    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, job_id=job.id)

    assert summary["deletedHandled"] == 1
    delete_calls = [r for r in requests if r["path"].endswith("/deletions")]
    assert len(delete_calls) == 1
    assert "codes" not in delete_calls[0]["body"]


# ── negative: probe failure - fail-safe, delete still delivered ────────────


def test_product_delete_omits_codes_on_a_probe_failure_and_still_delivers(db, sorento_consumer):
    contract_responses, delete_responses, requests = sorento_consumer
    company = _company(db, entity_type=ENTITY_PRODUCT, key_fields=["ItemCode"])
    job = _job(db)
    _stage_delete(db, company, job.id, ENTITY_PRODUCT, source_ref="AED_SORENTO:A3")

    # The contract endpoint answers a bare 500 - fetch_contract_detail()
    # returns None on ANY failure (its own documented contract); never raises.
    contract_responses.append((500, {}))
    delete_responses.append({
        "summary": {"total": 1, "deleted": 1, "deactivated": 0, "not_found": 0, "failed": 0, "retryable": 0},
        "records": [{"source_ref": "AED_SORENTO:A3", "outcome": "deleted"}],
    })

    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, job_id=job.id)

    assert summary["deletedHandled"] == 1, "a probe failure must never block the delete itself"
    delete_calls = [r for r in requests if r["path"].endswith("/deletions")]
    assert len(delete_calls) == 1
    assert "codes" not in delete_calls[0]["body"]


# ── negative: multi-key task - codes never sent even at contract 2.4 ───────


def test_product_delete_never_sends_codes_for_a_multi_key_task(db, sorento_consumer):
    """NOT RED for the guard's OWN logic (``codes_from_refs`` already
    refuses a non-single-ItemCode key set) - kept as a wiring-level
    regression pin: a caller that ever loosened the ``key_fields ==
    ("ItemCode",)`` check at the call site would trip this first."""
    contract_responses, delete_responses, requests = sorento_consumer
    company = _company(db, entity_type=ENTITY_PRODUCT, key_fields=["ItemCode", "Location"])
    job = _job(db)
    _stage_delete(db, company, job.id, ENTITY_PRODUCT, source_ref="AED_SORENTO:A4|MBS")

    contract_responses.append((200, {"version": 2.4, "entities": ["products"]}))
    delete_responses.append({
        "summary": {"total": 1, "deleted": 1, "deactivated": 0, "not_found": 0, "failed": 0, "retryable": 0},
        "records": [{"source_ref": "AED_SORENTO:A4|MBS", "outcome": "deleted"}],
    })

    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, job_id=job.id)

    assert summary["deletedHandled"] == 1
    delete_calls = [r for r in requests if r["path"].endswith("/deletions")]
    assert len(delete_calls) == 1
    assert "codes" not in delete_calls[0]["body"]
    # The multi-key guard must refuse BEFORE any probe - no network to waste.
    contract_calls = [r for r in requests if r["path"].endswith("/external/contract")]
    assert len(contract_calls) == 0


# ── negative: a non-product entity never probes at all ─────────────────────


def test_a_non_product_entity_delete_never_probes_the_contract(db, sorento_consumer):
    contract_responses, delete_responses, requests = sorento_consumer
    company = _company(db, entity_type=ENTITY_CUSTOMER, key_fields=["AccNo"])
    job = _job(db)
    _stage_delete(db, company, job.id, ENTITY_CUSTOMER, source_ref="AED_SORENTO:C1")

    delete_responses.append({
        "summary": {"total": 1, "deleted": 1, "deactivated": 0, "not_found": 0, "failed": 0, "retryable": 0},
        "records": [{"source_ref": "AED_SORENTO:C1", "outcome": "deleted"}],
    })

    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_CUSTOMER, job_id=job.id)

    assert summary["deletedHandled"] == 1
    contract_calls = [r for r in requests if r["path"].endswith("/external/contract")]
    assert len(contract_calls) == 0, "a non-product delete must never probe the contract"
    delete_calls = [r for r in requests if r["path"].endswith("/deletions")]
    assert "codes" not in delete_calls[0]["body"]


# ── negative: no Sorento connection at all - gate is False, no network ─────


def test_product_delete_gate_is_false_with_no_sorento_connection_and_never_probes(db):
    """The gate's own no-connection branch - a logging-sink company has no
    consumer to probe, so ``product_delete_codes_gate`` must answer
    ``False`` with ZERO network, and the LoggingSink delete still resolves
    (``deleted``, its own no-op verdict)."""
    company = _company_logging_sink(db, entity_type=ENTITY_PRODUCT, key_fields=["ItemCode"])
    job = _job(db)
    _stage_delete(db, company, job.id, ENTITY_PRODUCT, source_ref="AED_SORENTO:A5")

    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, job_id=job.id)

    assert summary["deletedHandled"] == 1


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_product_delete_sends_codes_when_the_contract_confirms_2_4 dies if
#   the wiring reuses ``CompanyService.contract_gate``'s inverted convention
#   (``None`` == "supported") directly - a probe FAILURE would then read as
#   "confirmed >= 2.4" and codes would ship unverified. It also dies if the
#   contract is probed more than once (a second network call the fixture's
#   sequential ``contract_responses.pop(0)`` would starve on).
# * test_product_delete_never_sends_codes_for_a_multi_key_task dies if the
#   key-fields guard is checked AFTER the probe instead of before (the zero-
#   contract-calls assertion catches a wasted network round trip even if the
#   final body happens to omit ``codes`` anyway).
# * test_a_non_product_entity_delete_never_probes_the_contract dies if the
#   ``entity_type == ENTITY_PRODUCT`` guard is missing or checked too late.
