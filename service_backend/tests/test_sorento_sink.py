"""SorentoSink - hop 2's real consumer (AC-14-15..18, 14-20/21, 14-24).

These pin the CONTRACT the live push already proved end-to-end, so a refactor
cannot silently break what the vendor round-trip verified: the projection to
Sorento's field set, X-API-Key auth, per-record outcome semantics, 429 honour,
and the dry-run shape.

The HTTP boundary is faked with ``httpx.MockTransport`` - the sink builds its own
``httpx.Client`` per call, and the transport is injected, so no socket opens.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import pytest

from modules.autocount.canonical.masters import CanonicalCustomer, CanonicalSupplier
from modules.autocount.sinks_sorento import (
    SORENTO_MAX_BATCH,
    SorentoRateLimited,
    SorentoSink,
    SorentoSinkError,
)


def _supplier(ref: str = "AED_VSOFT:1", code: str = "400-J001") -> CanonicalSupplier:
    return CanonicalSupplier(
        source_ref=ref, source_doc_no=code, code=code, name="JAPAN",
        email=None, is_active=True,
    )


def _customer(ref: str = "AED_VSOFT:3", code: str = "300-O002") -> CanonicalCustomer:
    return CanonicalCustomer(
        source_ref=ref, source_doc_no=code, code=code, name="OW PIN BOON",
        email=None, phone_number=None, credit_limit=None, tax_id="TIN1", is_active=True,
    )


class _Recorder:
    """Captures the request and serves a scripted response, so a test can assert
    on exactly what crossed the wire."""

    def __init__(self, responder) -> None:
        self.requests: List[httpx.Request] = []
        self._responder = responder

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self._responder(request)
        return httpx.MockTransport(handle)


def _ok_records(request: httpx.Request, outcome: str = "created") -> httpx.Response:
    body = json.loads(request.content)
    records = [
        {"source_ref": r["source_ref"], "outcome": outcome,
         "entity_id": f"id-{r['source_ref']}"}
        for r in body["records"]
    ]
    summary = {"total": len(records), "created": len(records) if outcome == "created" else 0,
               "updated": len(records) if outcome == "updated" else 0, "failed": 0, "retryable": 0}
    return httpx.Response(200, json={"summary": summary, "records": records})


# ── projection (AC-14-13/14) ─────────────────────────────────────────────────


def test_only_sink_fields_cross_the_wire():
    """Provenance and local-only fields (source_system, entity_type, extras,
    last_modified) must never reach Sorento - its models forbid extras, so an
    unknown key is a per-record rejection."""
    rec = _Recorder(_ok_records)
    sink = SorentoSink(base_url="http://x", api_key="sk_test",
                       entity_type="supplier", transport=rec.transport())
    sink.write_batch([_supplier()], request_id="t")

    sent = json.loads(rec.requests[0].content)["records"][0]
    assert set(sent) == {"source_ref", "source_doc_no", "code", "name", "email", "is_active"}
    assert "source_system" not in sent
    assert "entity_type" not in sent
    assert "last_modified" not in sent


def test_customer_projection_carries_its_extra_fields():
    rec = _Recorder(_ok_records)
    sink = SorentoSink(base_url="http://x", api_key="sk_test",
                       entity_type="customer", transport=rec.transport())
    sink.write_batch([_customer()], request_id="t")

    sent = json.loads(rec.requests[0].content)["records"][0]
    assert {"phone_number", "credit_limit", "tax_id"} <= set(sent)


# ── auth (AC-14-15) ──────────────────────────────────────────────────────────


def test_auth_is_x_api_key_never_bearer():
    rec = _Recorder(_ok_records)
    sink = SorentoSink(base_url="http://x", api_key="sk_secret",
                       entity_type="supplier", transport=rec.transport())
    sink.write_batch([_supplier()], request_id="t")

    headers = rec.requests[0].headers
    assert headers["X-API-Key"] == "sk_secret"
    assert "authorization" not in {k.lower() for k in headers}


def test_entity_path_maps_to_the_plural_route():
    for entity, segment in (("supplier", "suppliers"), ("customer", "customers")):
        rec = _Recorder(_ok_records)
        sink = SorentoSink(base_url="http://x", api_key="k",
                           entity_type=entity, transport=rec.transport())
        rec_or_cust = _supplier() if entity == "supplier" else _customer()
        sink.write_batch([rec_or_cust], request_id="t")
        assert rec.requests[0].url.path == f"/api/v1/external/ingest/{segment}"


def test_unknown_entity_is_refused_at_construction():
    with pytest.raises(SorentoSinkError):
        SorentoSink(base_url="http://x", api_key="k", entity_type="widget")


# ── per-record outcomes (AC-14-16) ───────────────────────────────────────────


@pytest.mark.parametrize("outcome, delivered", [("created", True), ("updated", True)])
def test_created_and_updated_are_delivered(outcome, delivered):
    rec = _Recorder(lambda r: _ok_records(r, outcome))
    sink = SorentoSink(base_url="http://x", api_key="k",
                       entity_type="supplier", transport=rec.transport())
    [result] = sink.write_batch([_supplier()], request_id="t")
    assert result.delivered is delivered
    assert result.ok is True
    assert result.external_id == "id-AED_VSOFT:1"


def test_failed_record_is_not_delivered_and_names_the_error():
    def responder(request):
        ref = json.loads(request.content)["records"][0]["source_ref"]
        return httpx.Response(200, json={
            "summary": {"total": 1, "created": 0, "updated": 0, "failed": 1, "retryable": 0},
            "records": [{"source_ref": ref, "outcome": "failed", "entity_id": None,
                         "errors": {"name": "Field required"}}]})
    rec = _Recorder(responder)
    sink = SorentoSink(base_url="http://x", api_key="k",
                       entity_type="supplier", transport=rec.transport())
    [result] = sink.write_batch([_supplier()], request_id="t")
    assert result.delivered is False
    assert result.ok is False
    assert "Field required" in result.message


def test_retryable_is_a_loud_failure_not_a_silent_requeue():
    """AC-14-24: retryable cannot occur for masters. If Sorento ever reports it,
    it is a defect signal, surfaced as a non-delivered failure - never quietly
    accepted."""
    def responder(request):
        ref = json.loads(request.content)["records"][0]["source_ref"]
        return httpx.Response(200, json={
            "summary": {"total": 1, "created": 0, "updated": 0, "failed": 0, "retryable": 1},
            "records": [{"source_ref": ref, "outcome": "retryable", "entity_id": None}]})
    rec = _Recorder(responder)
    sink = SorentoSink(base_url="http://x", api_key="k",
                       entity_type="supplier", transport=rec.transport())
    [result] = sink.write_batch([_supplier()], request_id="t")
    assert result.delivered is False
    assert "retryable" in result.message.lower()


def test_a_missing_verdict_is_never_treated_as_success():
    """Sorento omitted this record from its response - an anomaly, not a pass."""
    responder = lambda r: httpx.Response(200, json={"summary": {}, "records": []})
    rec = _Recorder(responder)
    sink = SorentoSink(base_url="http://x", api_key="k",
                       entity_type="supplier", transport=rec.transport())
    [result] = sink.write_batch([_supplier()], request_id="t")
    assert result.delivered is False
    assert "no verdict" in result.message.lower()


# ── 429 (AC-14-17) ───────────────────────────────────────────────────────────


def test_429_waits_the_retry_after_then_succeeds(monkeypatch):
    slept: List[float] = []
    monkeypatch.setattr("modules.autocount.sinks_sorento.time.sleep", slept.append)
    calls = {"n": 0}

    def responder(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, json={"code": "rate_limited"})
        return _ok_records(request)

    rec = _Recorder(responder)
    sink = SorentoSink(base_url="http://x", api_key="k",
                       entity_type="supplier", transport=rec.transport())
    [result] = sink.write_batch([_supplier()], request_id="t")
    assert result.delivered is True
    assert slept == [7]


def test_429_beyond_the_wait_budget_raises(monkeypatch):
    monkeypatch.setattr("modules.autocount.sinks_sorento.time.sleep", lambda *_: None)
    responder = lambda r: httpx.Response(429, headers={"Retry-After": "3"}, json={})
    rec = _Recorder(responder)
    sink = SorentoSink(base_url="http://x", api_key="k", entity_type="supplier",
                       transport=rec.transport(), max_rate_limit_waits=2)
    with pytest.raises(SorentoRateLimited) as exc:
        sink.write_batch([_supplier()], request_id="t")
    assert exc.value.retry_after == 3


def test_non_200_non_429_is_a_batch_level_error():
    responder = lambda r: httpx.Response(500, json={"message": "Internal server error"})
    rec = _Recorder(responder)
    sink = SorentoSink(base_url="http://x", api_key="k",
                       entity_type="supplier", transport=rec.transport())
    with pytest.raises(SorentoSinkError) as exc:
        sink.write_batch([_supplier()], request_id="t")
    assert "500" in str(exc.value)


# ── dry run (AC-14-20/21) ────────────────────────────────────────────────────


def test_dry_run_parses_summary_and_diffs():
    def responder(request):
        assert request.url.params.get("dry_run") == "true"
        return httpx.Response(200, json={
            "dry_run": True,
            "summary": {"total": 1, "created": 0, "updated": 1, "failed": 0, "retryable": 0},
            "records": [{"source_ref": "AED_VSOFT:3", "outcome": "updated",
                         "entity_id": "cust-1",
                         "diff": {"payment_terms_days": {"current": 30, "incoming": None}}}]})
    rec = _Recorder(responder)
    sink = SorentoSink(base_url="http://x", api_key="k",
                       entity_type="customer", transport=rec.transport())
    result = sink.dry_run([_customer()])
    assert result.summary["updated"] == 1
    [pred] = result.predictions
    assert pred.outcome == "updated"
    assert pred.changes_live_data is True
    assert result.would_change == [pred]
    assert pred.diff["payment_terms_days"]["current"] == 30


def test_dry_run_of_nothing_makes_no_call():
    rec = _Recorder(_ok_records)
    sink = SorentoSink(base_url="http://x", api_key="k",
                       entity_type="supplier", transport=rec.transport())
    result = sink.dry_run([])
    assert result.summary["total"] == 0
    assert rec.requests == []


# ── batching (AC-14-16, chunk ≤ MAX_BATCH) ───────────────────────────────────


def test_write_batch_chunks_at_the_vendor_ceiling():
    rec = _Recorder(_ok_records)
    sink = SorentoSink(base_url="http://x", api_key="k",
                       entity_type="supplier", transport=rec.transport())
    n = SORENTO_MAX_BATCH + 5
    records = [_supplier(ref=f"AED_VSOFT:{i}", code=f"C{i}") for i in range(n)]
    results = sink.write_batch(records, request_id="t")
    assert len(results) == n
    assert all(r.delivered for r in results)
    # Two HTTP calls: 1000 then 5.
    assert len(rec.requests) == 2
    assert len(json.loads(rec.requests[0].content)["records"]) == SORENTO_MAX_BATCH
    assert len(json.loads(rec.requests[1].content)["records"]) == 5
