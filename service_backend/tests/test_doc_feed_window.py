"""DOC-FEED-WINDOW - per-feed poll basis / poll lookback / re-check window,
and the content re-check folded into the deletion sweep.

The poll used to be hard-wired to ``byLastModified`` for yesterday..today and
the sweep to a 45-day deletions-only pass. A line edit in AutoCount may not
bump the header ``LastModified`` (unverified), so the sweep now also re-pushes
every document in its DocDate window whose content digest (header + lines)
differs from what the ledger last saw delivered.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx
import pytest

from modules.autocount.doc_feed.records import content_digest
from modules.autocount.doc_feed.runner import run_poll, run_sweep
from modules.autocount.doc_feed.window import (
    DEFAULT_DOC_FEED_WINDOW,
    resolve_window,
    validate_doc_feed_window,
)
from modules.autocount.models import AcDocFeed, AcDocFeedLedger, AcDocFeedRun

from .s14_doc_feed_helpers import auth_headers, wired_company

NOW = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)  # MYT today = 2026-09-29
TODAY = date(2026, 9, 29)


@pytest.fixture(autouse=True)
def _open_contract_gate(monkeypatch):
    from modules.autocount import sinks_sorento

    monkeypatch.setattr(
        sinks_sorento.SorentoSink, "fetch_contract_detail",
        lambda self: sinks_sorento.SorentoContractInfo(
            version=2.7, entities=["delivery_orders", "goods_receive_notes"]
        ),
    )


# ── helpers ──────────────────────────────────────────────────────────────────


def _feed(db, co, ac_conn, *, window=None, cursor_day=TODAY) -> AcDocFeed:
    row = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode="push", cursor_day=cursor_day,
        window_config=window,
    )
    db.add(row)
    db.commit()
    return row


def _doc(key: int, day: date, *, qty: float = 1.0, modified: str = "09:00:00.000") -> Dict[str, Any]:
    iso = day.isoformat()
    return {
        "DocKey": key, "DocNo": f"DO-{key}", "DocDate": f"{iso}T00:00:00",
        "LastModified": f"{iso}T{modified}",
        "Details": [{"DocKey": key, "DtlKey": key * 10, "ItemCode": "A", "Qty": qty}],
    }


class Vendor:
    """Answers both document doors; records every (path, day) asked."""

    def __init__(self, by_doc_date: Dict[date, List[Dict[str, Any]]] = None,
                 by_last_modified: Dict[date, List[Dict[str, Any]]] = None):
        self.by_doc_date = by_doc_date or {}
        self.by_last_modified = by_last_modified or {}
        self.calls: List[tuple] = []

    def client(self) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/deliveryorderbydocdate"):
                raw = request.url.params.get("DocDate")
                day = date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
                self.calls.append(("doc_date", day))
                return httpx.Response(200, json=self.by_doc_date.get(day, []))
            if path.endswith("/deliveryorderbyLastModified"):
                raw = request.url.params.get("lastModified")
                day = date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
                self.calls.append(("last_modified", day))
                return httpx.Response(200, json=self.by_last_modified.get(day, []))
            raise AssertionError(f"unrouted vendor path {path}")

        return httpx.Client(transport=httpx.MockTransport(handler))


class Crm:
    """Ingest answers ``outcome`` for every record; deletions answer
    ``deactivated``. Records which DocKeys each endpoint saw."""

    def __init__(self, outcome: str = "updated", warnings=None):
        self.outcome = outcome
        self.warnings = warnings or []
        self.ingested: List[int] = []
        self.deleted: List[int] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/external/contract":
                return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
            payload = json.loads(request.content.decode("utf-8"))
            if "doc_keys" in payload:
                keys = list(payload["doc_keys"])
                self.deleted.extend(keys)
                return httpx.Response(200, json={
                    "dry_run": False, "summary": {"deactivated": len(keys)},
                    "records": [{"source_ref": f"db1:DO:{k}", "outcome": "deactivated"} for k in keys],
                })
            recs = payload.get("records") or []
            self.ingested.extend(int(r["DocKey"]) for r in recs)
            return httpx.Response(200, json={
                "dry_run": False, "summary": {self.outcome: len(recs)},
                "records": [
                    {"source_ref": r.get("source_ref") or f"db1:DO:{r.get('DocKey')}",
                     "outcome": self.outcome, "warnings": self.warnings, "entity_id": "x"}
                    for r in recs
                ],
            })

        return httpx.MockTransport(handler)


def _ledger(db, feed, doc: Dict[str, Any], *, digest=None) -> None:
    db.add(AcDocFeedLedger(
        tenant_id=feed.tenant_id, company_id=feed.company_id, feed=feed.feed, book="db1",
        doc_key=doc["DocKey"], doc_no=doc["DocNo"], doc_date=date.fromisoformat(doc["DocDate"][:10]),
        last_outcome="created", pushed_at=NOW - timedelta(days=1), content_digest=digest,
    ))
    db.commit()


def _ledger_row(db, feed, key) -> AcDocFeedLedger:
    db.expire_all()
    return db.query(AcDocFeedLedger).filter(
        AcDocFeedLedger.feed == feed.feed, AcDocFeedLedger.doc_key == key,
        AcDocFeedLedger.company_id == feed.company_id,
    ).one()


# ── window settings (unit) ────────────────────────────────────────────────────


def test_null_window_resolves_to_todays_behaviour():
    assert resolve_window(None) == {
        "pollBasis": "last_modified", "pollLookbackDays": 1, "recheckDays": 45,
    }
    assert DEFAULT_DOC_FEED_WINDOW == resolve_window(None)


def test_a_partial_stored_window_fills_the_rest_from_defaults():
    assert resolve_window({"recheckDays": 90}) == {
        "pollBasis": "last_modified", "pollLookbackDays": 1, "recheckDays": 90,
    }


@pytest.mark.parametrize("raw, field", [
    ({"pollBasis": "created", "pollLookbackDays": 1, "recheckDays": 45}, "pollBasis"),
    ({"pollBasis": "doc_date", "pollLookbackDays": -1, "recheckDays": 45}, "pollLookbackDays"),
    ({"pollBasis": "doc_date", "pollLookbackDays": 31, "recheckDays": 45}, "pollLookbackDays"),
    ({"pollBasis": "doc_date", "pollLookbackDays": 1, "recheckDays": 0}, "recheckDays"),
    ({"pollBasis": "doc_date", "pollLookbackDays": 1, "recheckDays": 181}, "recheckDays"),
    ({"pollBasis": "doc_date", "pollLookbackDays": True, "recheckDays": 45}, "pollLookbackDays"),
    ({"pollBasis": "doc_date", "pollLookbackDays": 1, "recheckDays": "abc"}, "recheckDays"),
])
def test_out_of_range_window_values_are_named(raw, field):
    _clean, errors = validate_doc_feed_window(raw)
    assert field in errors


def test_bounds_are_accepted():
    clean, errors = validate_doc_feed_window(
        {"pollBasis": "doc_date", "pollLookbackDays": 0, "recheckDays": 180}
    )
    assert errors == {}
    assert clean == {"pollBasis": "doc_date", "pollLookbackDays": 0, "recheckDays": 180}


# ── content digest ───────────────────────────────────────────────────────────


def test_digest_changes_on_a_line_edit_with_the_same_last_modified():
    before = _doc(1, TODAY, qty=1)
    after = _doc(1, TODAY, qty=2)
    assert before["LastModified"] == after["LastModified"]
    assert content_digest(before) != content_digest(after)


def test_digest_ignores_key_order():
    doc = _doc(1, TODAY)
    reordered = dict(reversed(list(doc.items())))
    assert content_digest(doc) == content_digest(reordered)
    assert len(content_digest(doc)) == 64


# ── API ──────────────────────────────────────────────────────────────────────


def _url(co):
    return f"/autocount/doc-feeds/{co.id}/delivery_orders"


def _item(client, co, headers):
    body = client.get(f"/autocount/doc-feeds/{co.id}", headers=headers).json()
    return next(f for f in body["feeds"] if f["feed"] == "delivery_orders")


def test_view_returns_the_default_window(client, session_factory):
    db = session_factory()
    co, _ac, _crm = wired_company(db)
    headers = auth_headers(client)
    assert _item(client, co, headers)["window"] == {
        "pollBasis": "last_modified", "pollLookbackDays": 1, "recheckDays": 45,
    }


def test_put_window_is_stored_and_echoed_and_omitting_it_keeps_it(client, session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    headers = auth_headers(client)
    window = {"pollBasis": "doc_date", "pollLookbackDays": 3, "recheckDays": 150}
    r = client.put(_url(co), json={"connectionId": ac_conn.id, "mode": "dry_run", "window": window}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["window"] == window
    r = client.put(_url(co), json={"mode": "dry_run"}, headers=headers)
    assert r.status_code == 200, r.text
    assert _item(client, co, headers)["window"] == window


def test_invalid_window_422s_and_changes_nothing(client, session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    headers = auth_headers(client)
    bad = {"pollBasis": "doc_date", "pollLookbackDays": 1, "recheckDays": 999}
    r = client.put(_url(co), json={"connectionId": ac_conn.id, "mode": "dry_run", "window": bad}, headers=headers)
    assert r.status_code == 422, r.text
    assert "recheckDays" in r.json()["detail"]["fieldErrors"]
    item = _item(client, co, headers)
    assert item["mode"] == "off"
    assert item["window"]["recheckDays"] == 45


def test_changing_recheck_days_does_not_rearm_anything(client, session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    headers = auth_headers(client)
    assert client.put(_url(co), json={"connectionId": ac_conn.id, "mode": "dry_run"}, headers=headers).status_code == 200
    before = _item(client, co, headers)
    r = client.put(_url(co), json={
        "mode": "dry_run", "window": {"pollBasis": "last_modified", "pollLookbackDays": 1, "recheckDays": 90},
    }, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["nextPollAt"] == before["nextPollAt"]
    assert r.json()["nextSweepAt"] == before["nextSweepAt"]


# ── poll basis + lookback ────────────────────────────────────────────────────


def test_default_poll_reads_last_modified_yesterday_to_today(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    vendor = Vendor()
    run_poll(db, feed, dry_run=False, now=NOW, vendor_transport=vendor.client(), sink_transport=Crm().transport())
    assert vendor.calls == [("last_modified", TODAY - timedelta(days=1)), ("last_modified", TODAY)]


def test_poll_lookback_widens_the_window(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, window={"pollLookbackDays": 3})
    vendor = Vendor()
    run = run_poll(db, feed, dry_run=False, now=NOW, vendor_transport=vendor.client(), sink_transport=Crm().transport())
    assert [d for _p, d in vendor.calls] == [TODAY - timedelta(days=n) for n in (3, 2, 1, 0)]
    assert (run.day_from, run.day_to) == (TODAY - timedelta(days=3), TODAY)


def test_poll_lookback_zero_reads_today_only(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, window={"pollLookbackDays": 0})
    vendor = Vendor()
    run_poll(db, feed, dry_run=False, now=NOW, vendor_transport=vendor.client(), sink_transport=Crm().transport())
    assert vendor.calls == [("last_modified", TODAY)]


def test_an_older_cursor_still_wins_over_the_lookback(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, window={"pollLookbackDays": 1}, cursor_day=TODAY - timedelta(days=4))
    vendor = Vendor()
    run_poll(db, feed, dry_run=False, now=NOW, vendor_transport=vendor.client(), sink_transport=Crm().transport())
    assert vendor.calls[0] == ("last_modified", TODAY - timedelta(days=4))
    assert len(vendor.calls) == 5


def test_doc_date_basis_reads_the_doc_date_door_and_pushes(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, window={"pollBasis": "doc_date"})
    doc = _doc(501, TODAY)
    vendor = Vendor(by_doc_date={TODAY: [doc]})
    crm = Crm(outcome="created")
    run = run_poll(db, feed, dry_run=False, now=NOW, vendor_transport=vendor.client(), sink_transport=crm.transport())
    assert {p for p, _d in vendor.calls} == {"doc_date"}
    assert crm.ingested == [501]
    assert run.outcome == "SUCCESS"


def test_a_delivered_poll_stores_the_content_digest(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    doc = _doc(601, TODAY)
    vendor = Vendor(by_last_modified={TODAY: [doc]})
    run_poll(db, feed, dry_run=False, now=NOW, vendor_transport=vendor.client(), sink_transport=Crm("created").transport())
    assert _ledger_row(db, feed, 601).content_digest == content_digest(doc)


def test_a_dry_run_poll_writes_no_digest(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    vendor = Vendor(by_last_modified={TODAY: [_doc(602, TODAY)]})
    run_poll(db, feed, dry_run=True, now=NOW, vendor_transport=vendor.client(), sink_transport=Crm("created").transport())
    db.expire_all()
    assert db.query(AcDocFeedLedger).filter(AcDocFeedLedger.doc_key == 602).first() is None


# ── re-check (folded into the sweep) ─────────────────────────────────────────


def test_recheck_reads_the_configured_number_of_doc_date_days(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, window={"recheckDays": 10})
    vendor = Vendor()
    run = run_sweep(db, feed, dry_run=False, now=NOW, vendor_transport=vendor.client(), sink_transport=Crm().transport())
    assert [d for _p, d in vendor.calls] == [TODAY - timedelta(days=n) for n in range(9, -1, -1)]
    assert (run.day_from, run.day_to) == (TODAY - timedelta(days=9), TODAY)


def test_recheck_pushes_a_line_edit_the_last_modified_did_not_reveal(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    old_day = TODAY - timedelta(days=20)
    before = _doc(701, old_day, qty=1)
    after = _doc(701, old_day, qty=5)  # same header LastModified
    _ledger(db, feed, before, digest=content_digest(before))
    vendor = Vendor(by_doc_date={old_day: [after]})
    crm = Crm(outcome="updated")
    run = run_sweep(db, feed, dry_run=False, now=NOW, vendor_transport=vendor.client(), sink_transport=crm.transport())
    assert run.outcome == "SUCCESS", run.error
    assert crm.ingested == [701]
    assert crm.deleted == []
    assert run.summary_json["rechecked"] == 1
    assert run.summary_json["changed"] == 1
    assert run.summary_json["updated"] == 1
    assert _ledger_row(db, feed, 701).content_digest == content_digest(after)


def test_recheck_skips_a_document_whose_digest_is_unchanged(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    doc = _doc(702, TODAY - timedelta(days=3))
    _ledger(db, feed, doc, digest=content_digest(doc))
    crm = Crm()
    run = run_sweep(db, feed, dry_run=False, now=NOW,
                    vendor_transport=Vendor(by_doc_date={TODAY - timedelta(days=3): [doc]}).client(),
                    sink_transport=crm.transport())
    assert crm.ingested == []
    assert run.summary_json["rechecked"] == 1
    assert run.summary_json["changed"] == 0


def test_recheck_pushes_a_ledger_row_with_no_digest_yet_and_records_it(session_factory):
    """Q3 - after deploy every ledger row is NULL: pushed once (the CRM
    answers `unchanged`), then the digest is the baseline."""
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    doc = _doc(703, TODAY - timedelta(days=2))
    _ledger(db, feed, doc, digest=None)
    crm = Crm(outcome="unchanged")
    run_sweep(db, feed, dry_run=False, now=NOW,
              vendor_transport=Vendor(by_doc_date={TODAY - timedelta(days=2): [doc]}).client(),
              sink_transport=crm.transport())
    assert crm.ingested == [703]
    assert _ledger_row(db, feed, 703).content_digest == content_digest(doc)


def test_recheck_pushes_a_document_the_ledger_never_saw(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    doc = _doc(704, TODAY)
    crm = Crm(outcome="created")
    run = run_sweep(db, feed, dry_run=False, now=NOW,
                    vendor_transport=Vendor(by_doc_date={TODAY: [doc]}).client(),
                    sink_transport=crm.transport())
    assert crm.ingested == [704]
    assert run.summary_json["created"] == 1


def test_recheck_still_runs_the_deletion_step(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    kept = _doc(705, TODAY - timedelta(days=1))
    gone = _doc(706, TODAY - timedelta(days=1))
    _ledger(db, feed, kept, digest=content_digest(kept))
    _ledger(db, feed, gone, digest=content_digest(gone))
    crm = Crm()
    run = run_sweep(db, feed, dry_run=False, now=NOW,
                    vendor_transport=Vendor(by_doc_date={TODAY - timedelta(days=1): [kept]}).client(),
                    sink_transport=crm.transport())
    assert crm.ingested == []
    assert crm.deleted == [706]
    assert run.summary_json["deactivated"] == 1
    assert _ledger_row(db, feed, 706).vanished_at is not None


def test_a_dry_run_recheck_pushes_as_dry_run_and_writes_no_digest(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    old_day = TODAY - timedelta(days=5)
    before, after = _doc(707, old_day, qty=1), _doc(707, old_day, qty=9)
    _ledger(db, feed, before, digest=content_digest(before))
    crm = Crm()
    run_sweep(db, feed, dry_run=True, now=NOW,
              vendor_transport=Vendor(by_doc_date={old_day: [after]}).client(),
              sink_transport=crm.transport())
    assert crm.ingested == [707]
    assert _ledger_row(db, feed, 707).content_digest == content_digest(before)


def test_a_recheck_push_failure_fails_the_run_before_any_deletion(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    day = TODAY - timedelta(days=1)
    changed = _doc(708, day, qty=3)
    gone = _doc(709, day)
    _ledger(db, feed, _doc(708, day, qty=1), digest=content_digest(_doc(708, day, qty=1)))
    _ledger(db, feed, gone, digest=content_digest(gone))
    deleted: List[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        payload = json.loads(request.content.decode("utf-8"))
        if "doc_keys" in payload:
            deleted.extend(payload["doc_keys"])
            return httpx.Response(200, json={"summary": {}, "records": []})
        return httpx.Response(400, json={"detail": "bad"})

    run = run_sweep(db, feed, dry_run=False, now=NOW,
                    vendor_transport=Vendor(by_doc_date={day: [changed]}).client(),
                    sink_transport=httpx.MockTransport(handler))
    assert run.outcome == "FAILED"
    assert run.error_code == "SINK_ERROR"
    assert deleted == []


def test_recheck_is_tenant_and_company_scoped(session_factory):
    """Another company's ledger row with the same DocKey is never read as
    this feed's baseline."""
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    doc = _doc(710, TODAY)
    db.add(AcDocFeedLedger(
        tenant_id=feed.tenant_id, company_id="another-company", feed=feed.feed, book="db1",
        doc_key=710, doc_date=TODAY, last_outcome="created", content_digest=content_digest(doc),
    ))
    db.commit()
    crm = Crm(outcome="created")
    run_sweep(db, feed, dry_run=False, now=NOW,
              vendor_transport=Vendor(by_doc_date={TODAY: [doc]}).client(),
              sink_transport=crm.transport())
    assert crm.ingested == [710]


def test_run_rows_keep_the_sweep_kind(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    run_sweep(db, feed, dry_run=False, now=NOW, vendor_transport=Vendor().client(), sink_transport=Crm().transport())
    db.expire_all()
    assert db.query(AcDocFeedRun).filter(AcDocFeedRun.feed_id == feed.id).one().kind == "sweep"
