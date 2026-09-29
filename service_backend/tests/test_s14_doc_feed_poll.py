"""sprint-5/14 S0 - poll + branch pull tests (AC-14-12, 13, 25..27, 40, 41, 72).

`run_poll`/`run_branch_pull` (`modules.autocount.doc_feed.runner`) do not
exist yet - the whole module fails to import (S0 red, D21).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
import pytest

from app.models.integration_activity import IntegrationActivity
from modules.autocount.doc_feed.runner import run_branch_pull, run_poll
from modules.autocount.models import AcDocFeed, AcDocFeedRun

from .s14_doc_feed_helpers import load_fixture, wired_company

NOW = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)


def _feed(db, company, ac_conn, *, feed_key: str = "delivery_orders", mode: str = "push") -> AcDocFeed:
    row = AcDocFeed(
        tenant_id=company.tenant_id, company_id=company.id, feed=feed_key,
        connection_id=ac_conn.id, book="db1", mode=mode, cursor_day=None,
    )
    db.add(row)
    db.flush()
    return row


def _latest_run(db, feed) -> AcDocFeedRun:
    return (
        db.query(AcDocFeedRun)
        .filter(AcDocFeedRun.feed_id == feed.id)
        .order_by(AcDocFeedRun.started_at.desc())
        .first()
    )


def _ok_sink(outcome="created") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        # S1 (review round 1) - the run-time contract gate probes through
        # this SAME `sink_transport`.
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders", "goods_receive_notes", "branches"]})
        payload = json.loads(request.content.decode("utf-8"))
        recs = payload.get("records") or []
        return httpx.Response(
            200,
            json={
                "dry_run": False, "summary": {"total": len(recs), outcome: len(recs)},
                "records": [
                    {"source_ref": r.get("source_ref") or f"db1:DO:{r.get('DocKey')}", "outcome": outcome, "entity_id": "x"}
                    for r in recs
                ],
            },
        )

    return httpx.MockTransport(handler)


# ── vendor error codes push nothing (AC-14-12) ──────────────────────────────


def test_a_paged_envelope_on_a_document_door_fails_with_vendor_paged(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    paged = load_fixture("do-vendor-day-paged-envelope.json")

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=paged)

    posted = []

    def sink(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        posted.append(1)
        return httpx.Response(200, json={})

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)),
        sink_transport=httpx.MockTransport(sink),
    )
    run = _latest_run(db, feed)
    assert run.outcome == "FAILED"
    assert run.error_code == "VENDOR_PAGED"
    assert not posted


def test_a_non_json_body_fails_with_vendor_not_json(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    run_poll(db, feed, dry_run=False, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=_ok_sink())
    run = _latest_run(db, feed)
    assert run.outcome == "FAILED"
    assert run.error_code == "VENDOR_NOT_JSON"


def test_a_5xx_after_the_retry_ladder_fails_with_vendor_http(session_factory, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "down"})

    run_poll(db, feed, dry_run=False, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=_ok_sink())
    run = _latest_run(db, feed)
    assert run.outcome == "FAILED"
    assert run.error_code == "VENDOR_HTTP"


def test_an_ssrf_blocked_base_url_fails_with_vendor_transport(session_factory, monkeypatch):
    from modules.autocount import http_client as http_client_module

    # S11 (review round 1) - the SSRF-blocked GET is retried through the
    # SAME transport-error ladder as any other transport failure (1s then
    # 4s), so this test would otherwise sleep ~5s for real.
    monkeypatch.setattr("time.sleep", lambda *_: None)
    db = session_factory()
    co, ac_conn, crm = wired_company(db)
    # Point the feed's own connection at a blocked target (a private IP
    # literal - the egress guard's ipaddress branch, no DNS involved).
    ac_conn.config_json = {**ac_conn.config_json, "baseUrl": "http://169.254.169.254/api/db1"}
    db.commit()
    feed = _feed(db, co, ac_conn)

    run_poll(db, feed, dry_run=False, now=NOW, vendor_transport=None, sink_transport=_ok_sink())
    run = _latest_run(db, feed)
    assert run.outcome == "FAILED"
    assert run.error_code == "VENDOR_TRANSPORT"


# ── 429 waited, 502 retried (AC-14-25) ──────────────────────────────────────


def test_a_429_with_retry_after_is_waited_out_then_succeeds(session_factory, monkeypatch):
    sleeps: List[float] = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)

    calls = {"n": 0}

    def sink(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={}, headers={"Retry-After": "2"})
        payload = json.loads(request.content.decode("utf-8"))
        recs = payload.get("records") or []
        return httpx.Response(200, json={"dry_run": False, "summary": {"total": 0}, "records": []})

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    run_poll(db, feed, dry_run=False, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=httpx.MockTransport(sink))
    run = _latest_run(db, feed)
    assert run.outcome == "SUCCESS"


def test_a_502_is_retried_per_chunk_then_succeeds(session_factory, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)

    calls = {"n": 0}

    def sink(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(502, json={"message": "bad gateway"})
        return httpx.Response(200, json={"dry_run": False, "summary": {}, "records": []})

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"DocKey": 1, "DocNo": "DO-1", "DocDate": "2026-09-29", "LastModified": "2026-09-29T09:00:00.000", "Details": []}],
        )

    run_poll(db, feed, dry_run=False, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=httpx.MockTransport(sink))
    run = _latest_run(db, feed)
    assert run.outcome == "SUCCESS"
    assert calls["n"] >= 2


# ── CONTRACT_GATE at run time (AC-14-26) ────────────────────────────────────


def test_a_contract_that_drops_below_2_7_after_mode_was_set_fails_the_run(session_factory, monkeypatch):
    from modules.autocount import sinks_sorento

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)

    monkeypatch.setattr(
        sinks_sorento.SorentoSink, "fetch_contract_detail",
        lambda self: sinks_sorento.SorentoContractInfo(version=2.6, entities=[]),
    )
    posted = []
    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))),
        sink_transport=httpx.MockTransport(lambda r: posted.append(1) or httpx.Response(200, json={})),
    )
    run = _latest_run(db, feed)
    assert run.outcome == "FAILED"
    assert run.error_code == "CONTRACT_GATE"
    assert not posted


# ── branch walk to echoed TotalPages, verdict matching (AC-14-40, 41) ───────


def test_branch_pull_walks_every_page_and_matches_verdicts_by_source_ref(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, feed_key="branches")
    page1 = load_fixture("branch-page-1.json")
    page2 = load_fixture("branch-page-2.json")
    crm_response = load_fixture("crm-ingest-branches-response.json")

    def vendor(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/db1/branchbypage"
        page = request.url.params.get("page")
        assert request.url.params.get("pageSize") == "1000"
        return httpx.Response(200, json=page1 if page == "1" else page2)

    posted_refs: List[str] = []

    def sink(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["branches"]})
        payload = json.loads(request.content.decode("utf-8"))
        for r in payload.get("records") or []:
            acc = r.get("AccNo") or ""
            posted_refs.append(f"db1:BR:{acc}:{r.get('BranchCode')}")
        return httpx.Response(200, json=crm_response)

    run_branch_pull(db, feed, dry_run=False, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=httpx.MockTransport(sink))

    # 3 of the 4 rows have a non-blank BranchCode (one page-2 row is blank -
    # skippedNoKey, D19/AC-14-41) - only those are ever posted.
    assert "db1:BR:300-R009:HQ" in posted_refs
    assert "db1:BR:300-R014:PJ" in posted_refs
    assert "db1:BR::HQ" in posted_refs
    assert len(posted_refs) == 3

    run = _latest_run(db, feed)
    assert run.outcome == "SUCCESS"
    assert run.summary_json.get("skippedNoKey", 0) >= 1


# ── activity: counters only, key masked (AC-14-72) ──────────────────────────


def test_activity_records_counters_only_and_never_the_api_key(session_factory):
    db = session_factory()
    co, ac_conn, crm_conn = wired_company(db)
    feed = _feed(db, co, ac_conn)

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))),
        sink_transport=_ok_sink(),
    )

    rows = (
        db.query(IntegrationActivity)
        .filter(IntegrationActivity.tenant_id == co.tenant_id, IntegrationActivity.source == "autocount")
        .all()
    )
    assert rows, "the doc-feed run must render in the Developer Logs console"
    blob = " ".join(
        str(r.request_summary_json) + str(r.response_summary_json) + str(r.error_message or "")
        for r in rows
    )
    from .s14_doc_feed_helpers import SORENTO_API_KEY

    assert SORENTO_API_KEY not in blob


# ═══ review round 2 ═════════════════════════════════════════════════════════


def _one_do(key: int = 1, **extra) -> Dict[str, Any]:
    return {
        "DocKey": key, "DocNo": f"DO-{key}", "DocDate": "2026-09-29",
        "LastModified": "2026-09-29T09:00:00.000", "Details": [], **extra,
    }


def test_ss1_poll_run_error_never_carries_the_crm_body_url_or_key(session_factory):
    from .s14_doc_feed_helpers import SORENTO_API_KEY

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)

    def sink(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        return httpx.Response(
            400, text=f"denied {SORENTO_API_KEY} at http://crm.example.test/api/v1/x " + "z" * 800,
        )

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[_one_do()]))),
        sink_transport=httpx.MockTransport(sink),
    )
    run = _latest_run(db, feed)
    assert run.outcome == "FAILED" and run.error_code == "SINK_ERROR"
    assert SORENTO_API_KEY not in run.error
    assert "http://" not in run.error
    assert len(run.error) < 400


def test_ss1_branch_run_error_never_carries_the_crm_body_url_or_key(session_factory):
    from .s14_doc_feed_helpers import SORENTO_API_KEY

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, feed_key="branches")
    page1 = load_fixture("branch-page-1.json")

    def sink(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["branches"]})
        return httpx.Response(400, text=f"denied {SORENTO_API_KEY} http://crm.example.test/x")

    run_branch_pull(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=page1))),
        sink_transport=httpx.MockTransport(sink),
    )
    run = _latest_run(db, feed)
    assert run.outcome == "FAILED"
    assert SORENTO_API_KEY not in run.error and "http://" not in run.error


def test_n3_branch_pull_counts_every_vendor_page_as_a_request(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, feed_key="branches")
    page1 = load_fixture("branch-page-1.json")
    page2 = load_fixture("branch-page-2.json")
    crm_response = load_fixture("crm-ingest-branches-response.json")

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page1 if request.url.params.get("page") == "1" else page2)

    def sink(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["branches"]})
        return httpx.Response(200, json=crm_response)

    run_branch_pull(db, feed, dry_run=False, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=httpx.MockTransport(sink))
    assert _latest_run(db, feed).requests == 2


def test_n3_a_blank_branch_outcome_lands_in_the_retryable_bucket(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, feed_key="branches")
    page = {"TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
            "Data": [{"BranchCode": "HQ", "AccNo": "300-R009", "BranchName": "HQ"}]}

    def sink(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["branches"]})
        # No verdict at all for the record -> a blank outcome.
        return httpx.Response(200, json={"dry_run": False, "summary": {}, "records": []})

    run_branch_pull(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=page))),
        sink_transport=httpx.MockTransport(sink),
    )
    summary = _latest_run(db, feed).summary_json
    assert "" not in summary
    assert summary["retryable"] == 1


def test_n7_an_oversize_record_is_stored_as_none_and_marked_failed_not_resendable(session_factory):
    from modules.autocount.models import AcDocFeedIssue

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    big = _one_do(7, Remarks="x" * (70 * 1024))

    def sink(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        return httpx.Response(
            200,
            json={"dry_run": False, "summary": {"retryable": 1},
                  "records": [{"source_ref": "db1:DO:7", "outcome": "retryable", "errors": {"x": "busy"}}]},
        )

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[big]))),
        sink_transport=httpx.MockTransport(sink),
    )
    issue = db.query(AcDocFeedIssue).filter(AcDocFeedIssue.doc_key == 7).one()
    assert issue.record_json is None
    assert issue.kind == "failed"  # never `retryable`: there is nothing to re-send
    assert "Too large" in issue.errors_json["record"]
    assert _latest_run(db, feed).summary_json["failed"] == 1
