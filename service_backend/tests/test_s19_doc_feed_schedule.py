"""sprint-5/19 - per-feed Document feed schedule (AC-19-01..09).

Red-first: the `schedule` wire field, `ac_doc_feed.schedule_config`, and the
beat honouring it do not exist yet. Same rules as the Entities ETL schedule
(`etl_service.py` floors + `next_run_times`), with the no-watermark floor.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.doc_feed.scheduler import sweep_doc_feeds
from modules.autocount.models import AcDocFeed

from .s14_doc_feed_helpers import auth_headers, limited_user, wired_company

NOW = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)
DEFAULT = {"incrementalMinutes": 60, "reconcileMode": "interval", "reconcileHours": 24, "reconcileAt": None}


@pytest.fixture(autouse=True)
def _open_contract_gate(monkeypatch):
    """The mode gate probes the Sorento contract; these tests are about the
    schedule, not the gate (AC-14-04), so the gate is held open."""
    from modules.autocount import sinks_sorento

    monkeypatch.setattr(
        sinks_sorento.SorentoSink, "fetch_contract_detail",
        lambda self: sinks_sorento.SorentoContractInfo(
            version=2.7, entities=["delivery_orders", "goods_receive_notes"]
        ),
    )


def _url(co, feed="delivery_orders"):
    return f"/autocount/doc-feeds/{co.id}/{feed}"


def _row(db, co, feed="delivery_orders") -> AcDocFeed:
    db.expire_all()
    return (
        db.query(AcDocFeed)
        .filter(AcDocFeed.tenant_id == DEFAULT_TENANT_ID, AcDocFeed.company_id == co.id, AcDocFeed.feed == feed)
        .one()
    )


def _item(client, co, headers, feed="delivery_orders"):
    body = client.get(f"/autocount/doc-feeds/{co.id}", headers=headers).json()
    return next(f for f in body["feeds"] if f["feed"] == feed)


def _armed(client, db, headers):
    co, ac_conn, _crm = wired_company(db)
    r = client.put(_url(co), json={"connectionId": ac_conn.id, "mode": "dry_run"}, headers=headers)
    assert r.status_code == 200, r.text
    return co, ac_conn


# ── Group A - defaults + wire ────────────────────────────────────────────────


def test_view_returns_default_schedule_for_unconfigured_feeds(client, session_factory):
    db = session_factory()
    co, _ac, _crm = wired_company(db)
    headers = auth_headers(client)
    for feed in ("delivery_orders", "goods_receive_notes"):
        item = _item(client, co, headers, feed)
        assert item["schedule"] == DEFAULT
        assert "nextPollAt" in item and "nextSweepAt" in item


def test_null_schedule_beat_keeps_todays_60min_and_24h(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode="push",
        next_poll_at=NOW - timedelta(minutes=1), next_sweep_at=NOW + timedelta(hours=5),
    )
    db.add(feed)
    db.commit()
    assert feed.schedule_config is None
    sweep_doc_feeds(db, now=NOW)
    db.refresh(feed)
    assert feed.next_poll_at == NOW + timedelta(minutes=60)


# ── Group B - edit + validation ──────────────────────────────────────────────


def test_put_schedule_is_stored_and_echoed(client, session_factory):
    db = session_factory()
    headers = auth_headers(client)
    co, ac_conn = _armed(client, db, headers)
    schedule = {"incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileHours": None, "reconcileAt": "02:00"}
    r = client.put(_url(co), json={"mode": "dry_run", "schedule": schedule}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["schedule"] == schedule
    assert _item(client, co, headers)["schedule"] == schedule
    assert _row(db, co).connection_id == ac_conn.id  # omitted connectionId kept


def test_put_without_schedule_keeps_the_stored_schedule(client, session_factory):
    db = session_factory()
    headers = auth_headers(client)
    co, _ = _armed(client, db, headers)
    schedule = {"incrementalMinutes": 30, "reconcileMode": "interval", "reconcileHours": 6, "reconcileAt": None}
    client.put(_url(co), json={"mode": "dry_run", "schedule": schedule}, headers=headers)
    r = client.put(_url(co), json={"mode": "push"}, headers=headers)
    assert r.status_code == 200, r.text
    assert _item(client, co, headers)["schedule"] == schedule


@pytest.mark.parametrize(
    "schedule,field",
    [
        ({"incrementalMinutes": 4, "reconcileMode": "interval", "reconcileHours": 24}, "incrementalMinutes"),
        ({"incrementalMinutes": None, "reconcileMode": "interval", "reconcileHours": 24}, "incrementalMinutes"),
        ({"incrementalMinutes": 60, "reconcileMode": "weekly", "reconcileHours": 24}, "reconcileMode"),
        ({"incrementalMinutes": 60, "reconcileMode": "interval", "reconcileHours": 0}, "reconcileHours"),
        ({"incrementalMinutes": 60, "reconcileMode": "interval", "reconcileHours": None}, "reconcileHours"),
        ({"incrementalMinutes": 60, "reconcileMode": "dailyAt", "reconcileAt": "25:00"}, "reconcileAt"),
        ({"incrementalMinutes": 60, "reconcileMode": "dailyAt", "reconcileAt": None}, "reconcileAt"),
    ],
)
def test_invalid_schedule_422s_and_changes_nothing(client, session_factory, schedule, field):
    db = session_factory()
    headers = auth_headers(client)
    co, _ = _armed(client, db, headers)
    before = _row(db, co)
    poll, sweep = before.next_poll_at, before.next_sweep_at
    r = client.put(_url(co), json={"mode": "push", "schedule": schedule}, headers=headers)
    assert r.status_code == 422, r.text
    assert field in r.json()["detail"]["fieldErrors"]
    after = _row(db, co)
    assert after.mode == "dry_run"
    assert after.schedule_config is None
    assert (after.next_poll_at, after.next_sweep_at) == (poll, sweep)


def test_floor_values_are_accepted(client, session_factory):
    db = session_factory()
    headers = auth_headers(client)
    co, _ = _armed(client, db, headers)
    schedule = {"incrementalMinutes": 5, "reconcileMode": "interval", "reconcileHours": 1, "reconcileAt": None}
    r = client.put(_url(co), json={"mode": "dry_run", "schedule": schedule}, headers=headers)
    assert r.status_code == 200, r.text


def test_put_schedule_403s_without_companies_manage(client, session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    limited_user(db, keys=["autocount.companies.read"])
    headers = auth_headers(client, email="s14-limited@example.com", password="limited1234")
    r = client.put(_url(co), json={"mode": "off", "schedule": DEFAULT}, headers=headers)
    assert r.status_code == 403


# ── beat honours the stored schedule (AC-19-06) ──────────────────────────────


def _due_feed(db, co, ac_conn, schedule, *, poll_due=True):
    feed = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode="push", schedule_config=schedule,
        next_poll_at=(NOW - timedelta(minutes=1)) if poll_due else NOW + timedelta(hours=1),
        next_sweep_at=NOW + timedelta(hours=5) if poll_due else NOW - timedelta(minutes=1),
    )
    db.add(feed)
    db.commit()
    return feed


def test_beat_rearms_poll_from_stored_minutes(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _due_feed(db, co, ac_conn, {"incrementalMinutes": 15, "reconcileMode": "interval", "reconcileHours": 24})
    sweep_doc_feeds(db, now=NOW)
    db.refresh(feed)
    assert feed.next_poll_at == NOW + timedelta(minutes=15)


def test_beat_rearms_sweep_interval_hours(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _due_feed(db, co, ac_conn, {"incrementalMinutes": 60, "reconcileMode": "interval", "reconcileHours": 6}, poll_due=False)
    sweep_doc_feeds(db, now=NOW)
    db.refresh(feed)
    assert feed.next_sweep_at == NOW + timedelta(hours=6)


def test_beat_rearms_sweep_daily_at_next_utc_time(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _due_feed(db, co, ac_conn, {"incrementalMinutes": 60, "reconcileMode": "dailyAt", "reconcileAt": "02:00"}, poll_due=False)
    sweep_doc_feeds(db, now=NOW)  # 10:00 UTC -> tomorrow 02:00 UTC
    db.refresh(feed)
    assert feed.next_sweep_at == datetime(2026, 9, 30, 2, 0, tzinfo=timezone.utc)


# ── Group C - re-arm on change ───────────────────────────────────────────────


def test_changing_poll_rearms_poll_only(client, session_factory):
    db = session_factory()
    headers = auth_headers(client)
    co, _ = _armed(client, db, headers)
    sweep_before = _row(db, co).next_sweep_at
    before = datetime.now(timezone.utc)
    r = client.put(_url(co), json={"mode": "dry_run", "schedule": {**DEFAULT, "incrementalMinutes": 15}}, headers=headers)
    after = datetime.now(timezone.utc)
    assert r.status_code == 200, r.text
    row = _row(db, co)
    assert before + timedelta(minutes=15) <= row.next_poll_at <= after + timedelta(minutes=15)
    assert row.next_sweep_at == sweep_before


def test_changing_sweep_rearms_sweep_only(client, session_factory):
    db = session_factory()
    headers = auth_headers(client)
    co, _ = _armed(client, db, headers)
    poll_before = _row(db, co).next_poll_at
    before = datetime.now(timezone.utc)
    r = client.put(_url(co), json={"mode": "dry_run", "schedule": {**DEFAULT, "reconcileHours": 3}}, headers=headers)
    after = datetime.now(timezone.utc)
    assert r.status_code == 200, r.text
    row = _row(db, co)
    assert before + timedelta(hours=3) <= row.next_sweep_at <= after + timedelta(hours=3)
    assert row.next_poll_at == poll_before


def test_saving_an_unchanged_schedule_rearms_nothing(client, session_factory):
    db = session_factory()
    headers = auth_headers(client)
    co, _ = _armed(client, db, headers)
    before = _row(db, co)
    poll, sweep = before.next_poll_at, before.next_sweep_at
    r = client.put(_url(co), json={"mode": "dry_run", "schedule": DEFAULT}, headers=headers)
    assert r.status_code == 200, r.text
    row = _row(db, co)
    assert (row.next_poll_at, row.next_sweep_at) == (poll, sweep)


def test_off_feed_stores_schedule_but_stays_unarmed_then_arms_from_it(client, session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    headers = auth_headers(client)
    schedule = {"incrementalMinutes": 60, "reconcileMode": "interval", "reconcileHours": 2, "reconcileAt": None}
    r = client.put(_url(co), json={"connectionId": ac_conn.id, "mode": "off", "schedule": schedule}, headers=headers)
    assert r.status_code == 200, r.text
    row = _row(db, co)
    assert row.next_poll_at is None and row.next_sweep_at is None
    assert row.schedule_config is not None

    before = datetime.now(timezone.utc)
    r = client.put(_url(co), json={"mode": "dry_run"}, headers=headers)
    after = datetime.now(timezone.utc)
    assert r.status_code == 200, r.text
    row = _row(db, co)
    assert before <= row.next_poll_at <= after
    assert before + timedelta(hours=2) <= row.next_sweep_at <= after + timedelta(hours=2)
