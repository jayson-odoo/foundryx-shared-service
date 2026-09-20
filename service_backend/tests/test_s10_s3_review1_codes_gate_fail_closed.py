"""Sprint-5/10 S3 review round 1 - kill-test finding (b): a mutation that
made ``CompanyService.product_delete_codes_gate`` fail-OPEN on a probe error
survived the existing suite. The existing coverage
(``test_s10_s3_product_delete_codes_wiring.py``) only exercises a plain 500
HTTP response; this file closes the gap for the OTHER failure shapes the
gate's own docstring claims to treat identically: a genuine transport error
(the request never gets a response at all) and a 200 whose body is not
JSON. All three must answer the SAME way as the already-pinned 500 case:
``codes`` absent from the delete POST body, the delete still delivered,
``deletedHandled`` unchanged.

RED before the fix (proven by a local mutation, restored after - see the
kill-test note at the bottom of this file for the full correction): the
gate's real fail-open surface for these three failure shapes is
``version is not None and version >= PRODUCT_CODE_WINS_CONTRACT_VERSION`` -
flipping it to ``contract is None or version >= ...`` (treat "unprovable"
as "assume new enough" instead of "assume not") makes every test below
fail: ``codes`` would ship with an UNVERIFIED, guessed ``ItemCode -> code``
mapping on a consumer that never confirmed it understands the wire shape.
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
from modules.autocount.canonical.masters import ENTITY_PRODUCT
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


def _company(db) -> AcCompany:
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
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="sql_db", etl_status=ETL_STATUS_ACTIVE,
        source_config={"keyColumns": ["ItemCode"]},
    ))
    db.commit()
    db.refresh(company)
    return company


def _stage_delete(db, company, job_id, *, source_ref) -> AcStagedRecord:
    row = AcStagedRecord(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
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


def _sorento_consumer(monkeypatch, *, contract_handler):
    """Mirrors ``test_s10_s3_product_delete_codes_wiring.py``'s own fixture,
    but lets the CONTRACT leg raise/answer arbitrarily (a plain status-code
    tuple there cannot express a transport error or a non-JSON 200)."""
    import modules.autocount.services.company_service as company_module
    from modules.autocount.sinks_sorento import sorento_sink_from_connection as real

    delete_responses: List[Dict[str, Any]] = []
    requests: List[Dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/external/contract"):
            requests.append({"path": path, "method": request.method})
            return contract_handler(request)
        requests.append({"path": path, "method": request.method})
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
    return delete_responses, requests


def _run_and_assert_fail_closed(db, monkeypatch, contract_handler):
    delete_responses, requests = _sorento_consumer(monkeypatch, contract_handler=contract_handler)
    company = _company(db)
    job = _job(db)
    _stage_delete(db, company, job.id, source_ref="AED_SORENTO:A1")
    delete_responses.append({
        "summary": {"total": 1, "deleted": 1, "deactivated": 0, "not_found": 0, "failed": 0, "retryable": 0},
        "records": [{"source_ref": "AED_SORENTO:A1", "outcome": "deleted"}],
    })

    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, job_id=job.id)

    assert summary["deletedHandled"] == 1, "a probe failure of ANY kind must never block the delete itself"
    delete_calls = [r for r in requests if r["path"].endswith("/deletions")]
    assert len(delete_calls) == 1
    assert "codes" not in delete_calls[0]["body"], (
        "an unverified probe must never let codes ship - fail-open would guess"
    )


# ── the probe never gets a response at all (a genuine transport error) ─────


def test_codes_are_omitted_when_the_contract_probe_raises_a_transport_error(db, monkeypatch):
    def raising_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _run_and_assert_fail_closed(db, monkeypatch, raising_handler)


# ── the probe answers 200 but the body is not JSON at all ──────────────────


def test_codes_are_omitted_when_the_contract_probe_returns_non_json(db, monkeypatch):
    def non_json_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    _run_and_assert_fail_closed(db, monkeypatch, non_json_handler)


# ── the probe answers a 5xx OTHER than the already-pinned bare 500 ─────────


def test_codes_are_omitted_when_the_contract_probe_returns_503(db, monkeypatch):
    def unavailable_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "service unavailable"})

    _run_and_assert_fail_closed(db, monkeypatch, unavailable_handler)


# ── kill tests ────────────────────────────────────────────────────────────
#
# Correction to an earlier draft of this note: NONE of the three scenarios
# below actually reach ``product_delete_codes_gate``'s own outer
# ``except Exception`` - ``sinks_sorento.fetch_contract_detail`` already
# wraps a transport error, a non-200 and a non-JSON body in its OWN
# bulletproof try/except and returns ``None`` for all of them, well before
# ``product_delete_codes_gate`` ever sees an exception. Verified by
# mutation: flipping that OUTER except to fail-open (``return True``) left
# all three tests GREEN (proven locally, reverted after) - it is genuinely
# unreachable for these three failure shapes, though it may still matter for
# a fault in connection resolution/decryption or sink construction, which is
# out of this round's scope.
#
# The mutation these three tests DO kill (proven locally, reverted after) is
# the actual fail-open path every one of them traverses: swapping
# ``return version is not None and version >= PRODUCT_CODE_WINS_CONTRACT_
# VERSION`` for ``return contract is None or version >= ...`` - i.e. reading
# "the probe could not confirm a version" as "assume it is new enough"
# instead of "assume it is not". All three fail red under that mutation.
