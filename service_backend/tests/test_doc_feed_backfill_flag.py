"""DO-BACKFILL-SS - a doc-feed backfill run marks its ingest pushes ``backfill: true``.

The CRM ingest has a quiet mode behind the envelope flag ``"backfill": true``
(it skips the cancel relink and the embeddings). Only a push made by
``run_backfill`` may carry it: the incremental poll and the sweep's re-check
push are live traffic and must keep the full CRM side effects.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List

import httpx

from modules.autocount.doc_feed.runner import run_backfill, run_poll, run_sweep
from modules.autocount.models import AcDocFeed, AcDocFeedBackfill

from .s14_doc_feed_helpers import wired_company

NOW = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)
INGEST_PREFIX = "/api/v1/external/ingest/"


def _feed(db, company, ac_conn, *, feed_key: str = "delivery_orders") -> AcDocFeed:
    row = AcDocFeed(
        tenant_id=company.tenant_id, company_id=company.id, feed=feed_key,
        connection_id=ac_conn.id, book="db1", mode="push", cursor_day=date(2026, 9, 29),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _backfill(db, feed, *, dry_run: bool) -> AcDocFeedBackfill:
    day = date(2026, 9, 28)
    row = AcDocFeedBackfill(
        tenant_id=feed.tenant_id, company_id=feed.company_id, feed_id=feed.id, feed=feed.feed,
        book="db1", dry_run=dry_run, from_day=day, to_day=day, next_day=day,
        status="running", days_total=1, days_done=0, started_by="actor-1", started_at=NOW,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _vendor() -> httpx.Client:
    """Every vendor read (poll, sweep day, backfill day) returns one document
    (the same DocKey shape serves the DO and the GRN doors)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{
            "DocKey": 7, "DocNo": "DO-7", "DocDate": "2026-09-28T00:00:00",
            "LastModified": "2026-09-28T09:00:00.000", "Details": [],
        }])

    return httpx.Client(transport=httpx.MockTransport(handler))


def _capturing_sink(posts: List[Dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders", "goods_receive_notes"]})
        body = json.loads(request.content.decode("utf-8"))
        posts.append({"path": request.url.path, "params": dict(request.url.params), "body": body})
        recs = body.get("records") or []
        return httpx.Response(200, json={
            "dry_run": False, "summary": {"total": len(recs), "created": len(recs)},
            "records": [
                {"source_ref": r.get("source_ref"), "outcome": "created", "entity_id": "x"}
                for r in recs
            ],
        })

    return httpx.MockTransport(handler)


def _ingest_posts(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ingest = [p for p in posts if p["path"].startswith(INGEST_PREFIX)]
    # Control: the run really pushed (an empty push would pass the
    # absence assertions below for the wrong reason).
    assert ingest, posts
    return ingest


def test_a_backfill_push_carries_backfill_true(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, dry_run=False)
    posts: List[Dict[str, Any]] = []

    run_backfill(db, bf, now=NOW, vendor_transport=_vendor(), sink_transport=_capturing_sink(posts))

    for post in _ingest_posts(posts):
        assert post["body"]["backfill"] is True
        assert post["body"]["companyCode"]
        assert post["body"]["book"] == "db1"
        assert "dry_run" not in post["params"]


def test_a_dry_run_backfill_push_carries_backfill_true_and_dry_run(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, dry_run=True)
    posts: List[Dict[str, Any]] = []

    run_backfill(db, bf, now=NOW, vendor_transport=_vendor(), sink_transport=_capturing_sink(posts))

    for post in _ingest_posts(posts):
        assert post["body"]["backfill"] is True
        assert post["params"].get("dry_run") == "true"


def test_a_poll_push_does_not_carry_backfill(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    posts: List[Dict[str, Any]] = []

    run_poll(db, feed, dry_run=False, now=NOW, vendor_transport=_vendor(), sink_transport=_capturing_sink(posts))

    for post in _ingest_posts(posts):
        assert "backfill" not in post["body"]


def test_a_sweep_recheck_push_does_not_carry_backfill(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    posts: List[Dict[str, Any]] = []

    run_sweep(db, feed, dry_run=False, now=NOW, vendor_transport=_vendor(), sink_transport=_capturing_sink(posts))

    for post in _ingest_posts(posts):
        assert "backfill" not in post["body"]


def test_a_goods_receive_notes_backfill_push_does_not_carry_backfill(session_factory):
    """Audit #126: the CRM accepts `backfill` on delivery_orders ONLY and 422s
    it on any other entity, so a GRN backfill must leave the key out or every
    GRN backfill chunk fails."""
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, feed_key="goods_receive_notes")
    bf = _backfill(db, feed, dry_run=False)
    posts: List[Dict[str, Any]] = []

    run_backfill(db, bf, now=NOW, vendor_transport=_vendor(), sink_transport=_capturing_sink(posts))

    for post in _ingest_posts(posts):
        assert post["path"] == INGEST_PREFIX + "goods_receive_notes", post["path"]
        assert "backfill" not in post["body"]


def test_a_dry_run_goods_receive_notes_backfill_push_does_not_carry_backfill(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, feed_key="goods_receive_notes")
    bf = _backfill(db, feed, dry_run=True)
    posts: List[Dict[str, Any]] = []

    run_backfill(db, bf, now=NOW, vendor_transport=_vendor(), sink_transport=_capturing_sink(posts))

    for post in _ingest_posts(posts):
        assert post["path"] == INGEST_PREFIX + "goods_receive_notes", post["path"]
        assert post["params"].get("dry_run") == "true"
        assert "backfill" not in post["body"]
