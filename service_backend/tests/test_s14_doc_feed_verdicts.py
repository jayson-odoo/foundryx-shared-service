"""sprint-5/14 S0 - owner test "verdicts" (AC-14-22..24, 56, T3).

`run_poll` writes the ledger/issue side-effects a live tick produces
(section 3.6 step 5); this file drives it against a stubbed vendor (one
record per tick) and a stubbed CRM answering a chosen verdict, then reads
`AcDocFeedLedger`/`AcDocFeedIssue` back directly - the DB rows are the
observable contract, independent of whatever `run_poll` itself returns.
Also pins `SorentoSink._result_for`'s `unchanged` change (D3) against an
EXISTING master entity as a control - that change is global, not doc-feed
scoped, and must not regress a master's own `unchanged` handling.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
import pytest

from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.doc_feed.runner import run_poll
from modules.autocount.models import AcDocFeed, AcDocFeedIssue, AcDocFeedLedger
from modules.autocount.sinks_sorento import SorentoSink

from .s14_doc_feed_helpers import wired_company

NOW = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)  # 18:00 MYT, 29 Sep
DOC_KEY = 700001


def _feed(db, company, ac_conn, *, mode: str = "push") -> AcDocFeed:
    feed = AcDocFeed(
        tenant_id=company.tenant_id, company_id=company.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode=mode, cursor_day=None,
    )
    db.add(feed)
    db.flush()
    return feed


def _record(doc_key=DOC_KEY, last_modified="2026-09-29T09:00:00.000"):
    return {
        "DocKey": doc_key, "DocNo": f"DO-{doc_key}", "DocDate": "2026-09-29T00:00:00",
        "LastModified": last_modified, "Details": [],
    }


def _vendor_transport(record: Optional[Dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/deliveryorderbyLastModified"
        return httpx.Response(200, json=[record] if record else [])

    return httpx.Client(transport=httpx.MockTransport(handler))


def _verdict_transport(outcome: str, *, errors: Optional[Dict] = None, warnings: Optional[List[str]] = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        recs = payload.get("records") or []
        body_records = []
        for r in recs:
            entry: Dict[str, Any] = {"source_ref": f"db1:DO:{r.get('DocKey')}", "outcome": outcome}
            if outcome in ("created", "updated", "unchanged"):
                entry["entity_id"] = "00000000-0000-0000-0000-000000000055"
            if errors:
                entry["errors"] = errors
            if warnings:
                entry["warnings"] = warnings
            body_records.append(entry)
        return httpx.Response(
            200, json={"dry_run": False, "summary": {"total": len(recs), outcome: len(recs)}, "records": body_records},
        )

    return httpx.MockTransport(handler)


def _ledger_row(db, company, feed_key="delivery_orders", doc_key=DOC_KEY) -> Optional[AcDocFeedLedger]:
    return (
        db.query(AcDocFeedLedger)
        .filter(
            AcDocFeedLedger.tenant_id == company.tenant_id,
            AcDocFeedLedger.company_id == company.id,
            AcDocFeedLedger.feed == feed_key,
            AcDocFeedLedger.book == "db1",
            AcDocFeedLedger.doc_key == doc_key,
        )
        .first()
    )


def _issue_row(db, company, feed_key="delivery_orders", doc_key=DOC_KEY) -> Optional[AcDocFeedIssue]:
    return (
        db.query(AcDocFeedIssue)
        .filter(
            AcDocFeedIssue.tenant_id == company.tenant_id,
            AcDocFeedIssue.company_id == company.id,
            AcDocFeedIssue.feed == feed_key,
            AcDocFeedIssue.book == "db1",
            AcDocFeedIssue.doc_key == doc_key,
        )
        .first()
    )


# ── unchanged delivered -> ledger row, no issue (AC-14-22) ──────────────────


def test_unchanged_is_delivered_writes_ledger_no_issue(session_factory):
    db = session_factory()
    company, ac_conn, _crm = wired_company(db)
    feed = _feed(db, company, ac_conn)

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_vendor_transport(_record()),
        sink_transport=_verdict_transport("unchanged"),
    )

    assert _ledger_row(db, company) is not None
    assert _ledger_row(db, company).vanished_at is None
    assert _issue_row(db, company) is None


def test_unchanged_is_delivered_master_control_on_an_existing_entity_type():
    """D3's `_OUTCOME_DELIVERED += "unchanged"` is a GLOBAL sink change - a
    master entity (customer) must ALSO now read `unchanged` as delivered,
    not fall through to the pre-plan-14 "unrecognised outcome" branch."""
    sink = SorentoSink(base_url="http://x", api_key="k", entity_type=ENTITY_CUSTOMER)
    result = sink._result_for("ref-1", {"outcome": "unchanged"})
    assert result.delivered is True
    assert result.outcome == "unchanged"


# ── stale_ignored counted, ledger not overwritten (AC-14-56) ────────────────


def test_stale_ignored_inserts_the_ledger_row_only_when_absent(session_factory):
    db = session_factory()
    company, ac_conn, _crm = wired_company(db)
    feed = _feed(db, company, ac_conn)

    # First tick: a plain `created` writes the real ledger values.
    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_vendor_transport(_record(last_modified="2026-09-29T09:00:00.000")),
        sink_transport=_verdict_transport("created"),
    )
    original = _ledger_row(db, company)
    assert original is not None
    original_source_modified_at = original.source_modified_at

    # Second tick, later, offers a STALE copy; the CRM answers unchanged +
    # stale_ignored. The stored ledger values must be UNTOUCHED.
    feed.cursor_day = None  # re-read today
    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_vendor_transport(_record(last_modified="2026-09-29T01:00:00.000")),
        sink_transport=_verdict_transport("unchanged", warnings=["stale_ignored"]),
    )
    db.refresh(original)
    assert original.source_modified_at == original_source_modified_at


# ── retryable: issue row, re-sent, superseded, cleared on delivery (AC-14-23) ─


def test_retryable_creates_an_issue_row_with_the_record_and_errors(session_factory):
    db = session_factory()
    company, ac_conn, _crm = wired_company(db)
    feed = _feed(db, company, ac_conn)

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_vendor_transport(_record()),
        sink_transport=_verdict_transport("retryable", errors={"Details.0.ItemCode": "unresolved"}),
    )

    issue = _issue_row(db, company)
    assert issue is not None
    assert issue.kind == "retryable"
    assert issue.errors_json == {"Details.0.ItemCode": "unresolved"}
    assert issue.record_json["DocKey"] == DOC_KEY


def test_retryable_is_re_sent_on_the_next_live_poll_outside_the_window(session_factory):
    db = session_factory()
    company, ac_conn, _crm = wired_company(db)
    feed = _feed(db, company, ac_conn)

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_vendor_transport(_record()),
        sink_transport=_verdict_transport("retryable", errors={"x": "y"}),
    )
    db.refresh(feed)

    sent_refs: List[str] = []

    def vendor_empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    def sink_capture(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        for r in payload.get("records") or []:
            sent_refs.append(f"db1:DO:{r.get('DocKey')}")
        return httpx.Response(
            200, json={"dry_run": False, "summary": {"total": 0}, "records": []},
        )

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor_empty)),
        sink_transport=httpx.MockTransport(sink_capture),
    )
    assert f"db1:DO:{DOC_KEY}" in sent_refs


def test_a_later_delivered_verdict_clears_the_retryable_issue_row(session_factory):
    db = session_factory()
    company, ac_conn, _crm = wired_company(db)
    feed = _feed(db, company, ac_conn)

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_vendor_transport(_record()),
        sink_transport=_verdict_transport("retryable", errors={"x": "y"}),
    )
    assert _issue_row(db, company) is not None

    def vendor_empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor_empty)),
        sink_transport=_verdict_transport("created"),
    )
    assert _issue_row(db, company) is None
    assert _ledger_row(db, company) is not None


# ── failed: issue row, never re-sent, cleared on delivery (AC-14-24) ────────


def test_failed_creates_an_issue_row_and_is_not_re_sent(session_factory):
    db = session_factory()
    company, ac_conn, _crm = wired_company(db)
    feed = _feed(db, company, ac_conn)

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_vendor_transport(_record()),
        sink_transport=_verdict_transport("failed", errors={"DocNo": "clash"}),
    )
    issue = _issue_row(db, company)
    assert issue is not None
    assert issue.kind == "failed"
    assert issue.errors_json == {"DocNo": "clash"}

    sent_refs: List[str] = []

    def vendor_empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    def sink_capture(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        for r in payload.get("records") or []:
            sent_refs.append(f"db1:DO:{r.get('DocKey')}")
        return httpx.Response(200, json={"dry_run": False, "summary": {}, "records": []})

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor_empty)),
        sink_transport=httpx.MockTransport(sink_capture),
    )
    assert sent_refs == []


# ── unknown/missing outcome -> retryable (AC-14-22) ─────────────────────────


def test_an_unrecognised_outcome_word_is_treated_as_retryable(session_factory):
    db = session_factory()
    company, ac_conn, _crm = wired_company(db)
    feed = _feed(db, company, ac_conn)

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_vendor_transport(_record()),
        sink_transport=_verdict_transport("some_future_outcome"),
    )
    issue = _issue_row(db, company)
    assert issue is not None
    assert issue.kind == "retryable"


def test_a_missing_verdict_is_treated_as_retryable(session_factory):
    db = session_factory()
    company, ac_conn, _crm = wired_company(db)
    feed = _feed(db, company, ac_conn)

    def sink_no_verdict(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"dry_run": False, "summary": {}, "records": []})

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_vendor_transport(_record()),
        sink_transport=httpx.MockTransport(sink_no_verdict),
    )
    issue = _issue_row(db, company)
    assert issue is not None
    assert issue.kind == "retryable"


# ── warning tally (AC-14-22) ─────────────────────────────────────────────────


def test_run_summary_tallies_warnings_by_code(session_factory):
    db = session_factory()
    company, ac_conn, _crm = wired_company(db)
    feed = _feed(db, company, ac_conn)

    from modules.autocount.models import AcDocFeedRun

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_vendor_transport(_record()),
        sink_transport=_verdict_transport("updated", warnings=["adopted_by_doc_no"]),
    )
    run = (
        db.query(AcDocFeedRun)
        .filter(AcDocFeedRun.feed_id == feed.id)
        .order_by(AcDocFeedRun.started_at.desc())
        .first()
    )
    assert run.summary_json["warnings"]["adopted_by_doc_no"] == 1
