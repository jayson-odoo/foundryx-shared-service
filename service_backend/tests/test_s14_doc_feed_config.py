"""sprint-5/14 S0 - config + gate router tests (AC-14-01..06).

Router `routers/doc_feeds.py` (manifest prefix `/autocount/doc-feeds`, plan
section 3.2) does not exist yet - every request below 404s until S2 wires
it, which IS the expected red for a not-yet-mounted router (D21). Body
shape assertions stick to what the plan's own prose states literally
(`feeds` is inferred as a list of `DocFeedItem`, each carrying its own
`feed` key - the plan never gives the exact envelope name, so this is the
coder's contract to confirm/adjust, not a private name).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import DEFAULT_TENANT_ID

from .s14_doc_feed_helpers import (
    auth_headers,
    autocount_connection,
    company,
    limited_user,
    other_tenant,
    sorento_connection,
    wired_company,
)


def _feed_item(body, feed="delivery_orders"):
    feeds = body.get("feeds")
    assert feeds is not None, f"no 'feeds' key in view response: {body}"
    match = [f for f in feeds if f.get("feed") == feed]
    assert len(match) == 1, f"expected exactly one '{feed}' item, got {match}"
    return match[0]


# ── AC-14-01 - defaults + cross-tenant 404 ──────────────────────────────────


def test_unconfigured_company_answers_two_feeds_off_with_zero_counts(client, session_factory):
    db = session_factory()
    co = company(db)
    headers = auth_headers(client)

    response = client.get(f"/autocount/doc-feeds/{co.id}", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    # AC-14-46 (plan 14 section 11, D28) - branches left the doc feed: exactly
    # two feeds, never a third row.
    assert [f["feed"] for f in body["feeds"]] == ["delivery_orders", "goods_receive_notes"]
    for feed in ("delivery_orders", "goods_receive_notes"):
        item = _feed_item(body, feed)
        assert item["mode"] == "off"
        assert item.get("connectionId") in (None, "")
        assert item.get("cursorDay") in (None, "")
        assert item.get("retryableCount", 0) == 0
        assert item.get("failedCount", 0) == 0


def test_view_of_a_cross_tenant_company_404s(client, session_factory):
    db = session_factory()
    tenant_b = other_tenant(db)
    co = company(db, tenant_id=tenant_b)
    headers = auth_headers(client)  # a default-tenant admin

    response = client.get(f"/autocount/doc-feeds/{co.id}", headers=headers)
    assert response.status_code == 404


# ── AC-14-02 - eligible connections ─────────────────────────────────────────


def test_eligible_connections_only_lists_open_autocount_db1_segment_connections(client, session_factory):
    """Coder note (deviation from the S0 red test, minimal + intent-preserving):
    `company(db)` with no `ac_connection` kwarg SILENTLY mints its OWN
    default `db1`, auth=none vendor connection (`s14_doc_feed_helpers.
    company`'s own docstring: "an `autocount` open API connection (vendor
    reads)") - a SECOND eligible connection the original test never
    accounted for, so its single-item equality assertion below would fail
    against ANY correct implementation, not just an incorrect one. Passing
    the manually-built `eligible` connection AS the company's own
    `ac_connection` (the exact `wired_company` pattern two tests up)
    suppresses that implicit second mint - the test's INTENT (exactly one
    eligible connection survives the auth/segment/tenant filters) is
    unchanged."""
    db = session_factory()
    eligible = autocount_connection(db, base_url="https://hapi.sorento.cc.cd/api/db1", auth="none")
    co = company(db, ac_connection=eligible)
    autocount_connection(db, base_url="https://hapi.sorento.cc.cd/api/db2", auth="basic", name="basic-auth")
    autocount_connection(db, base_url="https://hapi.sorento.cc.cd/api/not a valid segment!!", auth="none", name="bad-segment")
    tenant_b = other_tenant(db)
    autocount_connection(db, tenant_id=tenant_b, base_url="https://hapi.sorento.cc.cd/api/db1", auth="none", name="other-tenant")
    db.commit()

    headers = auth_headers(client)
    response = client.get(f"/autocount/doc-feeds/{co.id}", headers=headers)
    assert response.status_code == 200, response.text
    eligible_out = response.json()["eligibleConnections"]
    assert [c["id"] for c in eligible_out] == [eligible.id]
    assert eligible_out[0]["book"] == "db1"


# ── AC-14-03 - PUT connection + derived book ────────────────────────────────


def test_put_sets_connection_and_derives_book(client, session_factory):
    db = session_factory()
    co = company(db)
    conn = autocount_connection(db, base_url="https://hapi.sorento.cc.cd/api/db1", auth="none")
    db.commit()
    headers = auth_headers(client)

    response = client.put(
        f"/autocount/doc-feeds/{co.id}/delivery_orders",
        json={"connectionId": conn.id, "mode": "off"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["book"] == "db1"
    assert body["connectionId"] == conn.id


@pytest.mark.parametrize("bad_connection_id", ["does-not-exist"])
def test_put_with_an_unknown_connection_id_422s_and_stores_nothing(client, session_factory, bad_connection_id):
    """Coder note (deviation from the S0 red test, minimal + intent-preserving):
    the ORIGINAL parametrize also carried a bare `None` case that sent NO
    `connectionId` key at all (not even a JSON `null`) alongside `mode:
    "off"`, and still expected a 422 naming `connectionId` - directly
    contradicting `test_mode_off_is_always_accepted_with_no_connection`
    right below (an EXPLICIT `"connectionId": None` with `mode: "off"` is
    200, per AC-14-04 "mode: off is always accepted") and AC-14-03 itself
    (only a "basic-auth, ineligible, unknown or other-tenant" id 422s - an
    ABSENT id is never one of those). The test's own NAME is "unknown
    connection id", which only the `"does-not-exist"` case actually
    exercises; the `None` case tested a different, contradicted claim
    ("missing key"), so it is dropped rather than reconciled with a
    provably-wrong sibling assertion."""
    db = session_factory()
    co = company(db)
    headers = auth_headers(client)

    payload = {"mode": "off", "connectionId": bad_connection_id}
    response = client.put(f"/autocount/doc-feeds/{co.id}/delivery_orders", json=payload, headers=headers)
    assert response.status_code == 422, response.text
    assert "connectionId" in response.json()["detail"]["fieldErrors"]


def test_put_with_a_basic_auth_connection_422s_field_error(client, session_factory):
    db = session_factory()
    co = company(db)
    basic_conn = autocount_connection(db, base_url="https://hapi.sorento.cc.cd/api/db1", auth="basic")
    db.commit()
    headers = auth_headers(client)

    response = client.put(
        f"/autocount/doc-feeds/{co.id}/delivery_orders",
        json={"connectionId": basic_conn.id, "mode": "off"},
        headers=headers,
    )
    assert response.status_code == 422, response.text


def test_put_with_another_tenants_connection_id_422s(client, session_factory):
    db = session_factory()
    co = company(db)
    tenant_b = other_tenant(db)
    other_conn = autocount_connection(db, tenant_id=tenant_b)
    db.commit()
    headers = auth_headers(client)

    response = client.put(
        f"/autocount/doc-feeds/{co.id}/delivery_orders",
        json={"connectionId": other_conn.id, "mode": "off"},
        headers=headers,
    )
    assert response.status_code == 422, response.text


# ── AC-14-04 - mode gate ────────────────────────────────────────────────────


def test_mode_off_is_always_accepted_with_no_connection(client, session_factory):
    db = session_factory()
    co = company(db)
    headers = auth_headers(client)
    response = client.put(
        f"/autocount/doc-feeds/{co.id}/delivery_orders", json={"connectionId": None, "mode": "off"}, headers=headers,
    )
    assert response.status_code == 200, response.text


def test_push_mode_422s_when_the_company_has_no_sorento_sink(client, session_factory):
    db = session_factory()
    co = company(db)  # sink_impl stays "logging" - no consumer connection.
    conn = autocount_connection(db)
    db.commit()
    headers = auth_headers(client)

    response = client.put(
        f"/autocount/doc-feeds/{co.id}/delivery_orders",
        json={"connectionId": conn.id, "mode": "push"},
        headers=headers,
    )
    assert response.status_code == 422, response.text
    assert "mode" in response.json()["detail"]["fieldErrors"]


def test_push_mode_422s_when_the_sorento_company_code_is_blank(client, session_factory, monkeypatch):
    db = session_factory()
    ac_conn = autocount_connection(db)
    crm_conn = sorento_connection(db)
    co = company(db, sink_connection=crm_conn, sorento_company_code="", ac_connection=ac_conn)
    db.commit()
    headers = auth_headers(client)

    response = client.put(
        f"/autocount/doc-feeds/{co.id}/delivery_orders",
        json={"connectionId": ac_conn.id, "mode": "push"},
        headers=headers,
    )
    assert response.status_code == 422, response.text


def test_push_mode_422s_when_the_crm_contract_is_below_2_7(client, session_factory, monkeypatch):
    from modules.autocount import sinks_sorento

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)

    monkeypatch.setattr(
        sinks_sorento.SorentoSink, "fetch_contract_detail",
        lambda self: sinks_sorento.SorentoContractInfo(version=2.6, entities=[]),
    )
    headers = auth_headers(client)
    response = client.put(
        f"/autocount/doc-feeds/{co.id}/delivery_orders",
        json={"connectionId": ac_conn.id, "mode": "push"},
        headers=headers,
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert "mode" in body["detail"]["fieldErrors"]


def test_push_mode_422s_when_the_crm_contract_omits_the_entity_name(client, session_factory, monkeypatch):
    from modules.autocount import sinks_sorento

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)

    monkeypatch.setattr(
        sinks_sorento.SorentoSink, "fetch_contract_detail",
        lambda self: sinks_sorento.SorentoContractInfo(version=2.7, entities=["branches"]),
    )
    headers = auth_headers(client)
    response = client.put(
        f"/autocount/doc-feeds/{co.id}/delivery_orders",
        json={"connectionId": ac_conn.id, "mode": "push"},
        headers=headers,
    )
    assert response.status_code == 422, response.text


def test_push_mode_422s_when_the_crm_is_unreachable(client, session_factory, monkeypatch):
    from modules.autocount import sinks_sorento

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)

    monkeypatch.setattr(sinks_sorento.SorentoSink, "fetch_contract_detail", lambda self: None)
    headers = auth_headers(client)
    response = client.put(
        f"/autocount/doc-feeds/{co.id}/delivery_orders",
        json={"connectionId": ac_conn.id, "mode": "push"},
        headers=headers,
    )
    assert response.status_code == 422, response.text


def test_view_carries_contract_gate_while_shut_and_null_when_open(client, session_factory, monkeypatch):
    from modules.autocount import sinks_sorento

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    monkeypatch.setattr(
        sinks_sorento.SorentoSink, "fetch_contract_detail",
        lambda self: sinks_sorento.SorentoContractInfo(version=2.6, entities=[]),
    )
    headers = auth_headers(client)
    body = client.get(f"/autocount/doc-feeds/{co.id}", headers=headers).json()
    item = _feed_item(body, "delivery_orders")
    assert item["contractGate"]["requiredVersion"] == 2.7
    assert item["contractGate"]["version"] == 2.6

    monkeypatch.setattr(
        sinks_sorento.SorentoSink, "fetch_contract_detail",
        lambda self: sinks_sorento.SorentoContractInfo(
            version=2.7, entities=["delivery_orders", "goods_receive_notes", "branches"]
        ),
    )
    body = client.get(f"/autocount/doc-feeds/{co.id}", headers=headers).json()
    item = _feed_item(body, "delivery_orders")
    assert item["contractGate"] is None


# ── AC-14-05 - permissions ───────────────────────────────────────────────────


def test_view_403s_without_companies_read(client, session_factory):
    db = session_factory()
    co = company(db)
    limited_user(db, keys=["autocount.companies.manage"])
    headers = auth_headers(client, email="s14-limited@example.com", password="limited1234")

    response = client.get(f"/autocount/doc-feeds/{co.id}", headers=headers)
    assert response.status_code == 403


def test_put_403s_without_companies_manage(client, session_factory):
    db = session_factory()
    co = company(db)
    limited_user(db, keys=["autocount.companies.read"])
    headers = auth_headers(client, email="s14-limited@example.com", password="limited1234")

    response = client.put(
        f"/autocount/doc-feeds/{co.id}/delivery_orders", json={"connectionId": None, "mode": "off"}, headers=headers,
    )
    assert response.status_code == 403


def test_run_now_403s_without_sync_run(client, session_factory):
    db = session_factory()
    co = company(db)
    limited_user(db, keys=["autocount.companies.read"])
    headers = auth_headers(client, email="s14-limited@example.com", password="limited1234")

    response = client.post(
        f"/autocount/doc-feeds/{co.id}/delivery_orders/run", json={"kind": "poll"}, headers=headers,
    )
    assert response.status_code == 403


def test_runs_list_403s_without_sync_read(client, session_factory):
    db = session_factory()
    co = company(db)
    limited_user(db, keys=["autocount.companies.read"])
    headers = auth_headers(client, email="s14-limited@example.com", password="limited1234")

    response = client.get(f"/autocount/doc-feeds/{co.id}/runs", headers=headers)
    assert response.status_code == 403


# ── AC-14-06 - arming and disarming ─────────────────────────────────────────


def test_switching_off_to_dry_run_arms_next_poll_now_and_next_sweep_plus_24h(client, session_factory, monkeypatch):
    """Coder note (deviation from the S0 red test, minimal + intent-preserving):
    the ORIGINAL test never monkeypatched `fetch_contract_detail`, so the mode
    gate's own real network probe (advisory only against `crm.example.test`,
    unreachable under this file's autouse network-block fixture) would 422 the
    PUT before the arming assertions this test exists to make ever ran - the
    test's own INTENT is the arm/disarm mechanic (AC-14-06), not the gate
    (AC-14-04), so an open-gate monkeypatch (the exact pattern
    `test_view_carries_contract_gate_while_shut_and_null_when_open` already
    uses two tests down) is the minimal fix."""
    from modules.autocount import sinks_sorento
    from modules.autocount.models import AcDocFeed

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    monkeypatch.setattr(
        sinks_sorento.SorentoSink, "fetch_contract_detail",
        lambda self: sinks_sorento.SorentoContractInfo(
            version=2.7, entities=["delivery_orders", "goods_receive_notes", "branches"]
        ),
    )
    headers = auth_headers(client)

    before = datetime.now(timezone.utc)
    response = client.put(
        f"/autocount/doc-feeds/{co.id}/delivery_orders",
        json={"connectionId": ac_conn.id, "mode": "dry_run"},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    row = (
        db.query(AcDocFeed)
        .filter(AcDocFeed.tenant_id == DEFAULT_TENANT_ID, AcDocFeed.company_id == co.id, AcDocFeed.feed == "delivery_orders")
        .one()
    )
    assert row.next_poll_at is not None and row.next_poll_at >= before
    assert row.next_sweep_at is not None
    assert (row.next_sweep_at - row.next_poll_at).total_seconds() >= 23 * 3600


def test_switching_to_off_clears_both_schedule_columns(client, session_factory):
    from modules.autocount.models import AcDocFeed

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    headers = auth_headers(client)
    client.put(
        f"/autocount/doc-feeds/{co.id}/delivery_orders",
        json={"connectionId": ac_conn.id, "mode": "dry_run"}, headers=headers,
    )
    client.put(
        f"/autocount/doc-feeds/{co.id}/delivery_orders",
        json={"connectionId": ac_conn.id, "mode": "off"}, headers=headers,
    )
    row = (
        db.query(AcDocFeed)
        .filter(AcDocFeed.tenant_id == DEFAULT_TENANT_ID, AcDocFeed.company_id == co.id, AcDocFeed.feed == "delivery_orders")
        .one()
    )
    assert row.next_poll_at is None
    assert row.next_sweep_at is None


# ── stock gate unchanged (D4 refactor regression) ───────────────────────────


def test_stock_push_gate_error_is_unchanged_by_the_contract_refusal_refactor(session_factory):
    from modules.autocount.services.company_service import CompanyService

    db = session_factory()
    co = company(db)  # logging sink, no Sorento connection - the refusal case.
    result = CompanyService(db).stock_push_gate_error(DEFAULT_TENANT_ID, co)
    assert result is not None
    assert result["requiredVersion"] == 2.5


# ═══ review round 2 (N4) ═══════════════════════════════════════════════════


def test_n4_an_explicit_null_connection_clears_the_stored_connection(client, session_factory):
    db = session_factory()
    co = company(db)
    conn = autocount_connection(db, base_url="https://hapi.sorento.cc.cd/api/db1", auth="none")
    db.commit()
    headers = auth_headers(client)
    url = f"/autocount/doc-feeds/{co.id}/delivery_orders"

    assert client.put(url, json={"connectionId": conn.id, "mode": "off"}, headers=headers).status_code == 200
    cleared = client.put(url, json={"connectionId": None, "mode": "off"}, headers=headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["connectionId"] is None
    assert cleared.json()["book"] is None

    view = client.get(f"/autocount/doc-feeds/{co.id}", headers=headers).json()
    item = next(f for f in view["feeds"] if f["feed"] == "delivery_orders")
    assert item["connectionId"] is None  # survives a reload


def test_n4_an_omitted_connection_key_keeps_the_stored_connection(client, session_factory):
    db = session_factory()
    co = company(db)
    conn = autocount_connection(db, base_url="https://hapi.sorento.cc.cd/api/db1", auth="none")
    db.commit()
    headers = auth_headers(client)
    url = f"/autocount/doc-feeds/{co.id}/delivery_orders"

    client.put(url, json={"connectionId": conn.id, "mode": "off"}, headers=headers)
    kept = client.put(url, json={"mode": "off"}, headers=headers)
    assert kept.status_code == 200, kept.text
    assert kept.json()["connectionId"] == conn.id


def test_n4_clearing_the_connection_while_arming_a_mode_422s(client, session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    headers = auth_headers(client)
    url = f"/autocount/doc-feeds/{co.id}/delivery_orders"

    client.put(url, json={"connectionId": ac_conn.id, "mode": "off"}, headers=headers)
    response = client.put(url, json={"connectionId": None, "mode": "push"}, headers=headers)
    assert response.status_code == 422, response.text
    assert "connectionId" in response.json()["detail"]["fieldErrors"]
