"""Sprint-5/10 S3 - product identity, code wins (R8): AC-10-70, AC-10-72.

RED before the coder for two DIFFERENT reasons, pinned per section:

* AC-10-70's PARSING half (``_result_for`` already tolerates an unknown
  ``warnings`` key) is a REGRESSION PIN, not new behaviour - see the vacuous-
  pass guard note on ``test_updated_with_ref_mismatch_warning_parses_as_delivered``
  below.
* AC-10-70's COUNTING half and ALL of AC-10-72 are genuinely missing:
  ``WriteResult`` carries no ``warnings`` field, ``SyncService.auto_push``'s
  summary carries no warning aggregate, and ``SorentoSink.delete_batch`` has
  no ``codes`` parameter / helper at all - every one of those fails on a
  plain ``TypeError``/``AttributeError``/assertion, never vacuously.

ASSUMED NAMES the coder must conform to (none pinned elsewhere on this
branch):

* ``modules.autocount.sinks.WriteResult`` gains ``warnings: Tuple[str, ...]
  = ()``, populated by ``SorentoSink._result_for`` from
  ``verdict.get("warnings") or ()`` on the ``delivered`` branch only (an
  unknown code is informational per AC-10-70's own text - never read as
  significant here, just carried through).
* ``SyncService.auto_push``'s summary dict gains ``warningCounts: Dict[str,
  int]`` - one entry per DISTINCT warning code across the run's delivered
  results, mirroring the summary's existing per-run aggregates
  (``quarantined``, ``deletedHandled``, ``requests``). This is the ONE
  observable boundary this file pins for "counted... onto the run's
  activity" - the actual activity-log ROW/operation-constant plumbing
  downstream of this summary is a deliberate scope cut (not independently
  tested here), noted in the final report.
* ``modules.autocount.sinks_sorento.codes_from_refs(refs: Sequence[str], *,
  key_fields: Sequence[str]) -> Dict[str, str]`` - a PURE helper deriving
  ``{ref: code}`` by splitting each ref once on ``":"``, guarded exactly as
  AC-10-72 states: only when ``key_fields == ("ItemCode",)`` and the ref's
  suffix (everything after the FIRST ``:``) contains no ``"|"``. Returns
  ``{}`` (never raises) when the guard fails for the whole call.
* ``SorentoSink.delete_batch`` gains an optional ``codes: Optional[Dict[str,
  str]] = None`` kwarg; when given, each chunk's POST body carries
  ``"codes"`` restricted to that chunk's own refs (never the whole map),
  and a ref absent from ``codes`` (mixed guarded/unguarded refs in one
  call) is simply omitted from the sub-map rather than sent as ``null``.

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
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.canonical.masters import CanonicalProduct
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    STAGED,
    AcCompany,
    AcEntityConfig,
    AcStagedRecord,
)
from modules.autocount.services.sync_service import SyncService
from modules.autocount.sinks_sorento import sorento_sink_from_connection
from modules.autocount.sync import AUTOCOUNT_SYNC


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network. See
    ``test_s10_s3_delivery_mode.py``'s copy of this fixture for the full
    rationale (coordinator finding 2026-09-20)."""
    real_send = httpx.Client.send
    real_async_send = httpx.AsyncClient.send

    def guarded_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return real_send(self, request, *args, **kwargs)

    async def guarded_async_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return await real_async_send(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", guarded_send)
    monkeypatch.setattr(httpx.AsyncClient, "send", guarded_async_send)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


# ── AC-10-70(a): `_result_for` already tolerates `warnings` - regression pin ─


def test_updated_with_ref_mismatch_warning_parses_as_delivered():
    """The fixture record from Appendix A9 verbatim. This is a REGRESSION
    PIN, not a red test for new behaviour - ``_result_for`` keys only on
    ``outcome`` today, so this passes BEFORE any coder change too. Kept RED
    only by the `.warnings` attribute assertion below (`WriteResult` carries
    no such field yet) - without that second assertion this test would be a
    silent vacuous green, exactly the trap the brief warns about."""
    sink = sorento_sink_from_connection(
        {"baseUrl": "https://sorento.example.com"}, {"apiKey": "k"},
        entity_type=ENTITY_PRODUCT, company_code="SRT",
    )
    verdict = {
        "source_ref": "AED_SORENTO:SRT-01", "outcome": "updated", "entity_id": "prod-1",
        "diff": {"list_price": {"current": "63.00", "incoming": "0"}},
        "warnings": ["ref_mismatch"],
    }
    result = sink._result_for("AED_SORENTO:SRT-01", verdict)
    assert result.ok is True
    assert result.delivered is True
    assert result.outcome == "updated"
    # The genuinely NEW half - fails today (no such attribute at all).
    assert result.warnings == ("ref_mismatch",)


def test_an_unknown_warning_code_is_carried_through_not_downgraded():
    sink = sorento_sink_from_connection(
        {"baseUrl": "https://sorento.example.com"}, {"apiKey": "k"},
        entity_type=ENTITY_PRODUCT, company_code="SRT",
    )
    verdict = {
        "source_ref": "AED_SORENTO:SRT-02", "outcome": "created", "entity_id": "prod-2",
        "warnings": ["some_future_code"],
    }
    result = sink._result_for("AED_SORENTO:SRT-02", verdict)
    assert result.delivered is True
    assert result.warnings == ("some_future_code",)


# ── AC-10-70(b): warning codes counted onto the run's summary ───────────────


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
    """Mirrors ``test_autocount_masters_fanout.py``'s own fixture of the same
    name byte for byte - the proven rig for a REAL push through
    ``SorentoSink`` against a scripted transport."""
    import modules.autocount.services.company_service as company_module
    from modules.autocount.sinks_sorento import sorento_sink_from_connection as real

    responses: List[Dict[str, Any]] = []
    requests: List[Dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        requests.append(body)
        return httpx.Response(200, json=responses.pop(0))

    def fake(config, credentials, *, entity_type, company_code=None, transport=None):
        return real(
            config, credentials, entity_type=entity_type, company_code=company_code,
            transport=httpx.MockTransport(handle),
        )

    monkeypatch.setattr(company_module, "sorento_sink_from_connection", fake)
    return responses, requests


def _product_company(db) -> AcCompany:
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
    ))
    db.commit()
    db.refresh(company)
    return company


def _stage_product(db, company, job_id, *, source_ref) -> AcStagedRecord:
    record = CanonicalProduct(
        source_ref=source_ref, code=source_ref.split(":")[-1], name="Widget",
        category_code="CAT-1", uom_code="PCS", is_active=True,
    )
    row = AcStagedRecord(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        job_id=job_id, source_ref=source_ref, canonical_json=record.comparable(), status=STAGED,
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


def test_auto_push_counts_ref_mismatch_warnings_onto_the_summary(db, sorento_consumer):
    responses, _requests = sorento_consumer
    company = _product_company(db)
    job = _job(db)
    row = _stage_product(db, company, job.id, source_ref="AED_SORENTO:SRT-01")

    responses.append({
        "summary": {"total": 1, "created": 0, "updated": 1, "failed": 0, "retryable": 0},
        "records": [{
            "source_ref": row.source_ref, "outcome": "updated", "entity_id": "prod-1",
            "warnings": ["ref_mismatch"],
        }],
    })
    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, job_id=job.id)

    assert summary["pushed"] == 1
    assert summary["warningCounts"] == {"ref_mismatch": 1}


def test_auto_push_reports_no_warning_counts_when_none_are_returned_control(db, sorento_consumer):
    """NOT RED TODAY - flagged, not silent (brief mutation-test rule): this
    write-absence assertion is TRUE before the coder's change too (there is
    no ``warningCounts`` key at all yet, which also reads as falsy/absent).
    It earns its keep paired with
    ``test_auto_push_counts_ref_mismatch_warnings_onto_the_summary`` above
    (the POSITIVE control proving the fixture can produce a non-empty
    count) and stays as a regression pin once the coder's change lands."""
    responses, _requests = sorento_consumer
    company = _product_company(db)
    job = _job(db)
    row = _stage_product(db, company, job.id, source_ref="AED_SORENTO:SRT-02")

    responses.append({
        "summary": {"total": 1, "created": 1, "updated": 0, "failed": 0, "retryable": 0},
        "records": [{"source_ref": row.source_ref, "outcome": "created", "entity_id": "prod-2"}],
    })
    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, job_id=job.id)

    assert summary["pushed"] == 1
    assert not summary.get("warningCounts")


# ── AC-10-72: `codes` on product deletions ───────────────────────────────────


def test_codes_from_refs_derives_the_item_code_for_single_key_product_refs():
    from modules.autocount.sinks_sorento import codes_from_refs

    refs = ["AED_SORENTO:BRACD7455C", "AED_SORENTO:BRACD9999"]
    assert codes_from_refs(refs, key_fields=("ItemCode",)) == {
        "AED_SORENTO:BRACD7455C": "BRACD7455C",
        "AED_SORENTO:BRACD9999": "BRACD9999",
    }


def test_codes_from_refs_is_empty_for_a_multi_key_ref_negative():
    """AC-10-72's own "multi-key negative": a ref whose suffix carries a
    ``|`` (a multi-key task, e.g. item+location) has no single code and must
    never be guessed at."""
    from modules.autocount.sinks_sorento import codes_from_refs

    refs = ["AED_SORENTO:BRACD7455C|MBS"]
    assert codes_from_refs(refs, key_fields=("ItemCode",)) == {}


def test_codes_from_refs_is_empty_when_key_fields_is_not_exactly_item_code():
    from modules.autocount.sinks_sorento import codes_from_refs

    refs = ["AED_SORENTO:BRACD7455C"]
    assert codes_from_refs(refs, key_fields=("ItemCode", "Location")) == {}
    assert codes_from_refs(refs, key_fields=("AutoKey",)) == {}


def test_delete_batch_sends_codes_restricted_to_the_chunks_own_refs():
    calls: List[Dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        calls.append(body)
        return httpx.Response(
            200,
            json={
                "summary": {"total": 1, "deleted": 1, "deactivated": 0, "not_found": 0, "failed": 0, "retryable": 0},
                "records": [{"source_ref": "AED_SORENTO:A1", "outcome": "deleted"}],
            },
        )

    sink = sorento_sink_from_connection(
        {"baseUrl": "https://sorento.example.com"}, {"apiKey": "k"},
        entity_type=ENTITY_PRODUCT, company_code="SRT",
        transport=httpx.MockTransport(handler),
    )
    sink.delete_batch(
        ["AED_SORENTO:A1"], codes={"AED_SORENTO:A1": "A1", "AED_SORENTO:UNRELATED": "X"},
    )

    assert len(calls) == 1
    assert calls[0]["source_refs"] == ["AED_SORENTO:A1"]
    # Restricted to this call's own refs - "UNRELATED" must never leak in.
    assert calls[0]["codes"] == {"AED_SORENTO:A1": "A1"}


def test_delete_batch_omits_codes_entirely_when_not_given_control():
    """NOT RED TODAY - flagged, not silent: ``delete_batch`` sends no
    ``codes`` key today by construction (the kwarg does not exist), so this
    write-absence assertion is already true. Paired with
    ``test_delete_batch_sends_codes_restricted_to_the_chunks_own_refs``
    above (the positive control) and kept as the regression pin once the
    coder's change lands - a future refactor that starts sending ``codes``
    unconditionally would trip this one."""
    calls: List[Dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        calls.append(body)
        return httpx.Response(
            200,
            json={
                "summary": {"total": 1, "deleted": 1, "deactivated": 0, "not_found": 0, "failed": 0, "retryable": 0},
                "records": [{"source_ref": "AED_SORENTO:A1", "outcome": "deleted"}],
            },
        )

    sink = sorento_sink_from_connection(
        {"baseUrl": "https://sorento.example.com"}, {"apiKey": "k"},
        entity_type=ENTITY_PRODUCT, company_code="SRT",
        transport=httpx.MockTransport(handler),
    )
    sink.delete_batch(["AED_SORENTO:A1"])

    assert "codes" not in calls[0]


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_updated_with_ref_mismatch_warning_parses_as_delivered dies ONLY on
#   its LAST line (``result.warnings``) - everything above it already passes
#   today, which is the point: AC-10-70's parsing half needs no code change,
#   and a coder who reads only the top of this test and thinks it is already
#   green must still see the failing assertion.
# * test_auto_push_counts_ref_mismatch_warnings_onto_the_summary dies if the
#   coder counts warnings but keys the dict by something other than the
#   literal code string, or aggregates across ALL runs instead of resetting
#   per call.
# * test_codes_from_refs_is_empty_for_a_multi_key_ref_negative dies if the
#   guard only checks ``key_fields`` and forgets the ref-suffix ``|`` check -
#   a task COULD in principle be saved with ``keyFields == ["ItemCode"]`` and
#   still produce a composite ref if that ever changes upstream; this proves
#   the ref shape is checked independently.
# * test_delete_batch_sends_codes_restricted_to_the_chunks_own_refs dies if
#   the WHOLE caller-supplied map is sent regardless of chunk membership -
#   invisible on a single-chunk call, which is why the fixture deliberately
#   includes an "UNRELATED" ref outside this call's own ``source_refs``.
