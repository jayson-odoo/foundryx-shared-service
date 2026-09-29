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
    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)),
        sink_transport=httpx.MockTransport(lambda r: posted.append(1) or httpx.Response(200, json={})),
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


def test_an_ssrf_blocked_base_url_fails_with_vendor_transport(session_factory):
    from modules.autocount import http_client as http_client_module

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
        assert request.url.path == "/branchbypage"
        page = request.url.params.get("page")
        assert request.url.params.get("pageSize") == "1000"
        return httpx.Response(200, json=page1 if page == "1" else page2)

    posted_refs: List[str] = []

    def sink(request: httpx.Request) -> httpx.Response:
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
