"""sprint-5/14 S0 - owner test "integration" (T5, AC-14-E2 backend half).

One stubbed vendor + one stubbed CRM, `httpx.MockTransport` routers keyed by
path: a live poll -> ledger + issues + cursor; a 3-day live backfill ->
ledger; a sweep after the stub vendor "deletes" one DocKey -> exactly that
key posted with the window dates, `vanished_at` set. The final case drives
`POST /autocount/doc-feeds/{companyId}/delivery_orders/run` at the ROUTE
level through the `get_http_transport` FastAPI dependency override (the
`preview_job.py` precedent plan section 3.9 names), proving the real
Router -> Service -> runner dispatch, not just the service layer directly.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx
import pytest

from modules.autocount.doc_feed.runner import run_backfill, run_poll, run_sweep
from modules.autocount.models import AcDocFeed, AcDocFeedBackfill, AcDocFeedLedger, AcDocFeedIssue

from .s14_doc_feed_helpers import auth_headers, wired_company

NOW = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)
TODAY_MYT = date(2026, 9, 29)


class _Router:
    """A tiny per-path handler map for a two-sided stub (vendor door names
    are disjoint from the CRM's `/api/v1/...` paths, so one router can
    stand in for `get_http_transport`'s single override)."""

    def __init__(self):
        self.posted: List[Dict[str, Any]] = []
        self.ledger_keys: Dict[str, List[int]] = {}

    def vendor_day(self, path: str):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == path
            day = request.url.params.get("lastModified") or request.url.params.get("DocDate")
            keys = self.ledger_keys.get(day, [])
            return httpx.Response(
                200,
                json=[
                    {
                        "DocKey": k, "DocNo": f"DO-{k}",
                        "DocDate": f"{day[:4]}-{day[4:6]}-{day[6:]}T00:00:00",
                        "LastModified": f"{day[:4]}-{day[4:6]}-{day[6:]}T09:00:00.000",
                        "Details": [],
                    }
                    for k in keys
                ],
            )

        return handler

    def crm(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        if "deletions" in request.url.path:
            keys = payload.get("doc_keys") or []
            self.posted.append(payload)
            return httpx.Response(
                200,
                json={
                    "dry_run": "dry_run=true" in str(request.url),
                    "summary": {"deactivated": len(keys)},
                    "records": [{"source_ref": f"db1:DO:{k}", "outcome": "deactivated", "entity_id": "x"} for k in keys],
                },
            )
        records = payload.get("records") or []
        self.posted.append(payload)
        return httpx.Response(
            200,
            json={
                "dry_run": "dry_run=true" in str(request.url),
                "summary": {"total": len(records), "created": len(records)},
                "records": [
                    {"source_ref": f"db1:DO:{r.get('DocKey')}", "outcome": "created", "entity_id": "x"}
                    for r in records
                ],
            },
        )


def _feed(db, company, ac_conn) -> AcDocFeed:
    row = AcDocFeed(
        tenant_id=company.tenant_id, company_id=company.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode="push", cursor_day=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_a_live_poll_writes_ledger_issues_and_advances_the_cursor(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    router = _Router()
    router.ledger_keys = {"20260929": [900901]}

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(router.vendor_day("/deliveryorderbyLastModified"))),
        sink_transport=httpx.MockTransport(router.crm),
    )

    db.refresh(feed)
    assert feed.cursor_day == TODAY_MYT
    ledger = db.query(AcDocFeedLedger).filter(AcDocFeedLedger.company_id == co.id, AcDocFeedLedger.doc_key == 900901).first()
    assert ledger is not None
    assert ledger.vanished_at is None


def test_a_three_day_live_backfill_writes_ledger_rows(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    router = _Router()
    router.ledger_keys = {
        "20260927": [910001], "20260928": [910002], "20260929": [910003],
    }
    bf = AcDocFeedBackfill(
        tenant_id=co.tenant_id, company_id=co.id, feed_id=feed.id, feed="delivery_orders",
        book="db1", dry_run=False, from_day=date(2026, 9, 27), to_day=date(2026, 9, 29),
        next_day=date(2026, 9, 27), status="running", days_total=3, days_done=0,
        started_by="actor-1", started_at=NOW,
    )
    db.add(bf)
    db.commit()

    run_backfill(
        db, bf, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(router.vendor_day("/deliveryorderbydocdate"))),
        sink_transport=httpx.MockTransport(router.crm),
    )

    db.refresh(bf)
    assert bf.status == "done"
    for key in (910001, 910002, 910003):
        assert db.query(AcDocFeedLedger).filter(AcDocFeedLedger.company_id == co.id, AcDocFeedLedger.doc_key == key).first() is not None


def test_a_sweep_after_the_vendor_stops_returning_a_dockey_deactivates_only_it(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    window_from = TODAY_MYT - timedelta(days=44)
    db.add(
        AcDocFeedLedger(
            tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders", book="db1",
            doc_key=920001, doc_no="DO-920001", doc_date=window_from,
            last_outcome="created", pushed_at=NOW - timedelta(days=1),
        )
    )
    db.add(
        AcDocFeedLedger(
            tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders", book="db1",
            doc_key=920002, doc_no="DO-920002", doc_date=window_from,
            last_outcome="created", pushed_at=NOW - timedelta(days=1),
        )
    )
    db.commit()
    router = _Router()
    router.ledger_keys = {window_from.strftime("%Y%m%d"): [920002]}  # 920001 has "vanished"

    run_sweep(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(router.vendor_day("/deliveryorderbydocdate"))),
        sink_transport=httpx.MockTransport(router.crm),
    )

    assert len(router.posted) == 1
    assert router.posted[0]["doc_keys"] == [920001]
    assert router.posted[0]["doc_date_from"] == window_from.strftime("%Y-%m-%d")
    assert router.posted[0]["doc_date_to"] == TODAY_MYT.strftime("%Y-%m-%d")

    row = db.query(AcDocFeedLedger).filter(AcDocFeedLedger.company_id == co.id, AcDocFeedLedger.doc_key == 920001).one()
    assert row.vanished_at is not None
    row2 = db.query(AcDocFeedLedger).filter(AcDocFeedLedger.company_id == co.id, AcDocFeedLedger.doc_key == 920002).one()
    assert row2.vanished_at is None


def test_route_level_run_now_dispatches_through_get_http_transport(client, session_factory):
    """The `preview_job.py` precedent: `DocFeedService` threads the router's
    `get_http_transport` value through when eager
    (`CELERY_TASK_ALWAYS_EAGER=true` in pytest's own settings), so a plain
    route-level POST exercises Router -> Service -> runner end to end with
    no real network."""
    from modules.autocount.http_client import get_http_transport
    from app.main import app

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed_row = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode="dry_run", cursor_day=None,
    )
    db.add(feed_row)
    db.commit()

    router = _Router()
    stub_client = httpx.Client(transport=httpx.MockTransport(router.vendor_day("/deliveryorderbyLastModified")))
    app.dependency_overrides[get_http_transport] = lambda: stub_client
    try:
        headers = auth_headers(client)
        response = client.post(
            f"/autocount/doc-feeds/{co.id}/delivery_orders/run",
            json={"kind": "poll"}, headers=headers,
        )
        assert response.status_code == 202, response.text
    finally:
        app.dependency_overrides.pop(get_http_transport, None)
