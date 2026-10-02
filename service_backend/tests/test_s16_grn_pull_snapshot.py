"""Sprint-5/16 follow-on - the public pull gateway's `goods_receive_notes`
snapshot (AC-16-70..86), the GRN mirror of the `delivery_orders` snapshot.
Contract of record: `documentation/plans/sprint-5/16-autocount-do-pull-snapshot-contract.md`
section 8.

Same scope keys, routes, header, limits and error ladder as DO; the only
differences are the entity, the vendor door (`/goodsreceivenotebydocdate`),
the stored `source_ref` (`{book}:GRN:{DocKey}`), the feed row that gates it
(`goods_receive_notes`), and the operator READ routes, which also need
`autocount.sync.read` for a GRN snapshot (supplier + cost data never widens
to `autocount.pull.read` alone - doc_lookup/registry.py's GRN rule).

Kill tests:
* AC-16-71: hardcode the build's vendor door to DO again and every GRN build
  fails (the stub routes only the GRN door).
* AC-16-72: hardcode `source_ref` to the DO feed and the `:GRN:` assertion fails.
* AC-16-73: gate on the DO feed row and the "only a DO feed" test 202s.
* AC-16-84: drop the `sync.read` check on the operator reads and the
  pull.read-only user sees GRN rows.
"""
from __future__ import annotations

from datetime import date

import pytest

from modules.autocount.models import AcDocFeed, AcPullAudit, AcPullSnapshot

from .s14_doc_feed_helpers import auth_headers, limited_user, load_fixture
from .s16_do_pull_helpers import (  # noqa: F401 - s16_isolation is an autouse fixture
    ENTITY_DO,
    ENTITY_GRN,
    GRN_DOOR,
    add_feed,
    build_env,
    day_ago,
    defer_jobs,
    get_header,
    get_rows,
    iso,
    post_build,
    s16_isolation,
    stored_rows,
    stored_snapshot,
)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def grn_records():
    """`grn-vendor-day.json`: raw GRNs with `Details` (DtlKey, ItemCode, Qty,
    Location, FromDocType/FromDocNo/FromDocDtlKey, OurPONo)."""
    return load_fixture("grn-vendor-day.json")


def _env(db, monkeypatch, **kwargs):
    return build_env(db, monkeypatch, feed=ENTITY_GRN, **kwargs)


def _one_day(day, extra=()):
    recs = grn_records()

    def day_fn(d):
        return [*reversed(recs), *extra] if d == day else []

    return day_fn


def _expected_order(records):
    return sorted(records, key=lambda r: (r["DocDate"], r["DocKey"]))


# ── AC-16-70: build envelope ─────────────────────────────────────────────────


def test_ac_16_70_grn_range_build_answers_202_with_the_scope_echo(client, db, monkeypatch):
    env = _env(db, monkeypatch)
    from_day, to_day = day_ago(2), day_ago(1)

    response = post_build(
        client, env.key, entity=ENTITY_GRN, fromDay=iso(from_day), toDay=iso(to_day),
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert set(body) == {"snapshotId", "status", "entity", "companyCode", "fromDay", "toDay", "docNo"}
    assert body["entity"] == "goods_receive_notes"
    assert (body["fromDay"], body["toDay"], body["docNo"]) == (iso(from_day), iso(to_day), None)
    snap = stored_snapshot(db, body["snapshotId"])
    assert snap.entity_type == "goods_receive_notes"
    assert snap.requested_via == "gateway"


def test_ac_16_70_wire_entity_maps_to_the_internal_grn_feed_key():
    from modules.autocount.models import DOC_FEED_GOODS_RECEIVE_NOTES
    from modules.autocount.services.pull_gateway_service import ENTITY_WIRE_TO_INTERNAL

    assert ENTITY_WIRE_TO_INTERNAL["goods_receive_notes"] == DOC_FEED_GOODS_RECEIVE_NOTES


def test_ac_16_70_docno_alone_defaults_to_the_31_myt_days_ending_today(client, db, monkeypatch):
    env = _env(db, monkeypatch)

    body = post_build(client, env.key, entity=ENTITY_GRN, docNo="GRN-2609/0090").json()

    assert (body["fromDay"], body["toDay"]) == (iso(day_ago(30)), iso(day_ago(0)))
    assert body["docNo"] == "GRN-2609/0090"


@pytest.mark.parametrize(
    "scope",
    [
        {},
        {"toDay": "2026-09-01"},
        {"fromDay": "2026/09/01"},
        {"fromDay": "2022-12-31"},
        {"docNo": "   "},
    ],
)
def test_ac_16_70_the_do_scope_rules_apply_unchanged(client, db, monkeypatch, scope):
    env = _env(db, monkeypatch)

    response = post_build(client, env.key, entity=ENTITY_GRN, **scope)

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "INVALID_REQUEST"
    assert response.json()["entity"] == ENTITY_GRN
    assert env.stub.requests == []


# ── AC-16-71 / 72: the build job ─────────────────────────────────────────────


def test_ac_16_71_72_build_reads_the_grn_door_and_stores_raw_grns_verbatim(
    client, db, monkeypatch,
):
    day = day_ago(1)
    keyless = {"DocNo": "GRN-2609/0089", "Details": []}
    env = _env(db, monkeypatch, day_fn=_one_day(day, extra=[keyless]))

    snapshot_id = post_build(client, env.key, entity=ENTITY_GRN, fromDay=iso(day)).json()[
        "snapshotId"
    ]

    assert env.stub.paths == [GRN_DOOR], "one GET per day, the GRN by-DocDate door only"
    assert env.stub.unrouted == []
    rows = stored_rows(db, snapshot_id)
    expected = _expected_order(grn_records())
    assert [r.payload_json for r in rows] == expected
    assert [r.source_ref for r in rows] == [f"db1:GRN:{r['DocKey']}" for r in expected]
    first_lines = rows[0].payload_json["Details"]
    assert first_lines and {"DtlKey", "ItemCode", "Qty", "Location", "OurPONo"} <= set(
        first_lines[0]
    )

    header = get_header(client, env.key, snapshot_id).json()
    assert header["status"] == "ready"
    assert header["entity"] == "goods_receive_notes"
    assert header["book"] == "db1"
    assert header["contentHash"]
    assert header["complete"] is True
    assert header["recordCount"] == len(expected)
    assert header["daysRead"] == 1
    assert header["fetchedCount"] == len(expected) + 1
    assert header["lineCount"] == sum(len(r["Details"]) for r in expected)
    assert header["excludedCount"] == 1
    assert header["excludedRows"][0]["reason"] == "missing_doc_key"
    assert header["excludedRows"][0]["code"] == "GRN-2609/0089"

    page = get_rows(client, env.key, snapshot_id).json()
    assert page["rows"] == expected


def test_ac_16_72_a_too_large_grn_names_a_goods_received_note(client, db, monkeypatch):
    from modules.autocount.doc_feed import snapshot as snapshot_module

    monkeypatch.setattr(snapshot_module, "MAX_SNAPSHOT_DOCUMENT_BYTES", 10)
    day = day_ago(1)
    env = _env(db, monkeypatch, day_fn=_one_day(day))

    snapshot_id = post_build(client, env.key, entity=ENTITY_GRN, fromDay=iso(day)).json()[
        "snapshotId"
    ]

    header = get_header(client, env.key, snapshot_id).json()
    assert header["recordCount"] == 0
    reasons = {(r["reason"], r["source_ref"].split(":")[1], r["message"]) for r in header["excludedRows"]}
    assert reasons == {
        (
            "too_large", "GRN",
            "Goods received note exceeds 1 MB and cannot be stored in a snapshot.",
        )
    }


def test_ac_16_71_the_grn_build_never_moves_the_feed_watermark(client, db, monkeypatch):
    day = day_ago(1)
    env = _env(
        db, monkeypatch, day_fn=_one_day(day),
        feed_columns={"cursor_day": date(2026, 9, 1), "last_error": None},
    )
    db.refresh(env.feed)
    before = (env.feed.cursor_day, env.feed.last_poll_at, env.feed.last_poll_ok_at, env.feed.mode)

    post_build(client, env.key, entity=ENTITY_GRN, fromDay=iso(day))

    feed = db.get(AcDocFeed, env.feed.id)
    db.refresh(feed)
    assert (feed.cursor_day, feed.last_poll_at, feed.last_poll_ok_at, feed.mode) == before


def test_ac_16_71_over_10000_grns_fails_row_limit(client, db, monkeypatch):
    day = day_ago(1)
    many = [
        {"DocKey": i, "DocNo": f"GRN-{i}", "DocDate": "2026-09-28T00:00:00",
         "LastModified": "2026-09-28T10:00:00.000", "Details": []}
        for i in range(1, 10_002)
    ]
    env = _env(db, monkeypatch, day_fn=lambda d: many if d == day else [])

    snapshot_id = post_build(client, env.key, entity=ENTITY_GRN, fromDay=iso(day)).json()[
        "snapshotId"
    ]

    snap = stored_snapshot(db, snapshot_id)
    assert (snap.status, snap.error_code) == ("failed", "ROW_LIMIT")
    assert stored_rows(db, snapshot_id) == []


def test_ac_16_71_a_failing_vendor_day_fails_source_page_failed(client, db, monkeypatch):
    import httpx

    day = day_ago(1)
    env = _env(db, monkeypatch, day_fn=lambda d: httpx.Response(200, text="<html>"))

    snapshot_id = post_build(client, env.key, entity=ENTITY_GRN, fromDay=iso(day)).json()[
        "snapshotId"
    ]

    header = get_header(client, env.key, snapshot_id).json()
    assert header["status"] == "failed"
    assert header["error"]["code"] == "SOURCE_PAGE_FAILED"
    assert header["book"] == "db1"


# ── AC-16-73: gating ─────────────────────────────────────────────────────────


def test_ac_16_73_a_company_with_only_a_do_feed_is_pull_not_enabled_for_grn(
    client, db, monkeypatch,
):
    env = build_env(db, monkeypatch, feed=ENTITY_DO)

    response = post_build(client, env.key, entity=ENTITY_GRN, fromDay=iso(day_ago(1)))

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "PULL_NOT_ENABLED"
    assert response.json()["entity"] == ENTITY_GRN
    db.expire_all()
    assert db.query(AcPullSnapshot).count() == 0


@pytest.mark.parametrize("mode", ["off", "dry_run", "push"])
def test_ac_16_73_the_grn_feed_mode_never_gates_the_read(client, db, monkeypatch, mode):
    env = _env(db, monkeypatch, mode=mode)

    response = post_build(client, env.key, entity=ENTITY_GRN, fromDay=iso(day_ago(1)))

    assert response.status_code == 202, response.text


# ── AC-16-74: re-attach / in flight ──────────────────────────────────────────


def test_ac_16_74_same_scope_reattaches_and_different_scope_is_build_in_flight(
    client, db, monkeypatch,
):
    env = _env(db, monkeypatch)
    defer_jobs(monkeypatch)

    first = post_build(client, env.key, entity=ENTITY_GRN, fromDay=iso(day_ago(1)))
    again = post_build(client, env.key, entity=ENTITY_GRN, fromDay=iso(day_ago(1)))
    other = post_build(client, env.key, entity=ENTITY_GRN, fromDay=iso(day_ago(2)))

    assert first.status_code == again.status_code == 202
    assert again.json()["snapshotId"] == first.json()["snapshotId"]
    assert other.status_code == 409, other.text
    assert other.json()["code"] == "BUILD_IN_FLIGHT"
    assert other.json()["entity"] == ENTITY_GRN


def test_ac_16_74_a_do_build_in_flight_never_blocks_a_grn_build(client, db, monkeypatch):
    env = _env(db, monkeypatch)
    add_feed(db, env.company, env.conn, feed=ENTITY_DO)
    defer_jobs(monkeypatch)

    do = post_build(client, env.key, entity=ENTITY_DO, fromDay=iso(day_ago(1)))
    grn = post_build(client, env.key, entity=ENTITY_GRN, fromDay=iso(day_ago(2)))

    assert do.status_code == grn.status_code == 202
    assert do.json()["snapshotId"] != grn.json()["snapshotId"]


def test_ac_16_75_the_build_audit_row_carries_the_grn_entity(client, db, monkeypatch):
    env = _env(db, monkeypatch)

    snapshot_id = post_build(client, env.key, entity=ENTITY_GRN, fromDay=iso(day_ago(1))).json()[
        "snapshotId"
    ]

    db.expire_all()
    audit = db.query(AcPullAudit).filter(AcPullAudit.action == "build").one()
    assert (audit.entity_type, audit.snapshot_id) == ("goods_receive_notes", snapshot_id)


def test_ac_16_76_unknown_entity_lists_goods_receive_notes(client, db, monkeypatch):
    env = _env(db, monkeypatch)

    response = post_build(client, env.key, entity="widgets")

    assert response.json()["message"] == (
        "entity must be one of: delivery_orders, goods_receive_notes, products, stock_balances."
    )


# ── AC-16-80..84: operator routes ────────────────────────────────────────────


def _ready_grn(client, db, monkeypatch):
    day = day_ago(1)
    env = _env(db, monkeypatch, day_fn=_one_day(day))
    snapshot_id = post_build(client, env.key, entity=ENTITY_GRN, fromDay=iso(day)).json()[
        "snapshotId"
    ]
    return env, snapshot_id


def test_ac_16_80_operator_build_route_refuses_goods_receive_notes(client, db, monkeypatch):
    env = _env(db, monkeypatch)

    response = client.post(
        "/autocount/pull/snapshots",
        json={"companyId": env.company.id, "entityType": "goods_receive_notes"},
        headers=auth_headers(client),
    )

    assert response.status_code == 422, response.text
    assert env.stub.requests == []


def test_ac_16_82_operator_with_sync_read_lists_shows_and_pages_a_grn(client, db, monkeypatch):
    env, snapshot_id = _ready_grn(client, db, monkeypatch)
    headers = auth_headers(client)

    listing = client.get(
        "/autocount/pull/snapshots",
        params={"companyId": env.company.id, "entityType": "goods_receive_notes"},
        headers=headers,
    )
    assert listing.status_code == 200, listing.text
    assert [s["id"] for s in listing.json()["data"]] == [snapshot_id]
    assert client.get(f"/autocount/pull/snapshots/{snapshot_id}", headers=headers).status_code == 200
    rows = client.get(f"/autocount/pull/snapshots/{snapshot_id}/rows", headers=headers)
    assert rows.status_code == 200
    assert rows.json()["rows"] == _expected_order(grn_records())


def test_ac_16_84_pull_read_alone_never_sees_a_grn_snapshot(client, db, monkeypatch):
    env, snapshot_id = _ready_grn(client, db, monkeypatch)
    limited_user(db, ["autocount.pull.read"], email="s16-grn-pullonly@example.com")
    headers = auth_headers(client, "s16-grn-pullonly@example.com", "limited1234")

    listing = client.get(
        "/autocount/pull/snapshots", params={"companyId": env.company.id}, headers=headers,
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 0
    assert listing.json()["data"] == []
    filtered = client.get(
        "/autocount/pull/snapshots",
        params={"companyId": env.company.id, "entityType": "goods_receive_notes"},
        headers=headers,
    )
    assert filtered.status_code == 200
    assert filtered.json()["data"] == []

    unknown = client.get("/autocount/pull/snapshots/no-such-id", headers=headers)
    show = client.get(f"/autocount/pull/snapshots/{snapshot_id}", headers=headers)
    rows = client.get(f"/autocount/pull/snapshots/{snapshot_id}/rows", headers=headers)
    assert show.status_code == rows.status_code == unknown.status_code == 404
    assert show.json() == unknown.json(), "a hidden GRN reads exactly like an unknown id"


def test_ac_16_84_pull_read_plus_sync_read_sees_the_grn(client, db, monkeypatch):
    env, snapshot_id = _ready_grn(client, db, monkeypatch)
    limited_user(
        db, ["autocount.pull.read", "autocount.sync.read"], email="s16-grn-both@example.com",
    )
    headers = auth_headers(client, "s16-grn-both@example.com", "limited1234")

    rows = client.get(f"/autocount/pull/snapshots/{snapshot_id}/rows", headers=headers)

    assert rows.status_code == 200, rows.text
    assert len(rows.json()["rows"]) == len(grn_records())


def test_ac_16_84_pull_read_alone_still_sees_a_do_snapshot(client, db, monkeypatch):
    day = day_ago(1)
    env = build_env(db, monkeypatch, day_fn=lambda d: [], feed=ENTITY_DO)
    snapshot_id = post_build(client, env.key, fromDay=iso(day)).json()["snapshotId"]
    limited_user(db, ["autocount.pull.read"], email="s16-do-pullonly@example.com")
    headers = auth_headers(client, "s16-do-pullonly@example.com", "limited1234")

    show = client.get(f"/autocount/pull/snapshots/{snapshot_id}", headers=headers)

    assert show.status_code == 200, show.text
