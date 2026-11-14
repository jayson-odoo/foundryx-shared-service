"""Sprint-5/16 - AC-16-50: the vendor half of `doc_feed/runner.py::_resolve`
is extracted so the snapshot can reuse it WITHOUT the sink / contract gate,
while `_resolve`'s refusal codes and order stay exactly as the feed has them.

RED before the coder: `modules.autocount.doc_feed.runner.resolve_vendor`
does not exist (AttributeError). The `_resolve` regression tests below are
GREEN today and must stay green (they pin the unchanged behaviour).

ASSUMED NAMES:

* `modules.autocount.doc_feed.runner.resolve_vendor(db, feed_row, *,
  vendor_transport=None)` returns an object with `.company`, `.vendor_client`
  (an `HttpApiClient`), `.vendor` (a `DocFeedVendor`) and `.book`; it raises
  the same `RunRefusal` codes as `_resolve` for COMPANY_INACTIVE,
  NO_CONNECTION and BOOK_MISMATCH, and NEVER builds a sink or probes the
  contract.
* `_resolve` calls `resolve_vendor` first, then does the sink + contract
  gate (SINK_NOT_READY, CONTRACT_GATE), in that order.

Kill test: inline the vendor half back into `_resolve` (no
`resolve_vendor` call) and `test_ac_16_50_resolve_delegates_to_resolve_vendor`
fails; make `resolve_vendor` build the sink and
`test_ac_16_50_resolve_vendor_never_builds_a_sink_or_probes_the_contract`
fails.
"""
from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.doc_feed import runner as runner_module
from modules.autocount.doc_feed.runner import RunRefusal, _resolve
from modules.autocount.doc_feed.vendor import DocFeedVendor
from modules.autocount.http_source.client import HttpApiClient
from modules.autocount.models import AcDocFeed

from .s14_doc_feed_helpers import (
    BOOK,
    autocount_connection,
    company,
    load_fixture,
    other_tenant,
    sorento_connection,
    wired_company,
)
from .s16_do_pull_helpers import DO_DOOR, VendorStub, s16_isolation  # noqa: F401


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _feed(db, co, conn, *, book: str = BOOK, connection_id=None) -> AcDocFeed:
    row = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders",
        connection_id=connection_id if connection_id is not None else (conn.id if conn else None),
        book=book, mode="off", cursor_day=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _resolve_vendor():
    resolve_vendor = getattr(runner_module, "resolve_vendor", None)
    assert resolve_vendor is not None, "doc_feed.runner.resolve_vendor does not exist yet"
    return resolve_vendor


# ── resolve_vendor: the vendor half alone ────────────────────────────────────


def test_ac_16_50_resolve_vendor_returns_the_vendor_pieces_without_touching_the_sink(db):
    co = company(db)  # NO sink: logging impl, no Sorento connection, no company code
    conn = db.get(type(autocount_connection(db)), co.connection_id)
    feed = _feed(db, co, conn)
    recs = load_fixture("do-vendor-day.json")
    stub = VendorStub(lambda _day: recs)

    resolved = _resolve_vendor()(db, feed, vendor_transport=stub.client())

    assert resolved.company.id == co.id
    assert resolved.book == "db1"
    assert isinstance(resolved.vendor_client, HttpApiClient)
    assert isinstance(resolved.vendor, DocFeedVendor)
    assert resolved.vendor.day_by_doc_date("delivery_orders", date(2026, 9, 28)) == recs
    assert stub.paths == [DO_DOOR]
    assert stub.unrouted == []


def test_ac_16_50_resolve_vendor_never_builds_a_sink_or_probes_the_contract(db, monkeypatch):
    co, _ac_conn, _crm = wired_company(db)  # a fully wired sink that must stay untouched
    feed = _feed(db, co, _ac_conn)

    def boom(*_a, **_k):
        raise AssertionError("resolve_vendor must not build a sink")

    monkeypatch.setattr(runner_module, "sorento_sink_from_connection", boom)

    resolved = _resolve_vendor()(db, feed, vendor_transport=VendorStub().client())

    assert resolved.book == "db1"


@pytest.mark.parametrize("wire", ["inactive", "no_connection", "auth_not_none", "book_mismatch"])
def test_ac_16_50_resolve_vendor_refusals_use_the_feed_codes(db, wire):
    co = company(db)
    conn = db.get(type(autocount_connection(db)), co.connection_id)
    feed = _feed(db, co, conn)
    expected = {
        "inactive": "COMPANY_INACTIVE", "no_connection": "NO_CONNECTION",
        "auth_not_none": "NO_CONNECTION", "book_mismatch": "BOOK_MISMATCH",
    }[wire]
    if wire == "inactive":
        co.is_active = False
    elif wire == "no_connection":
        feed.connection_id = "conn-that-does-not-exist"
    elif wire == "auth_not_none":
        conn.config_json = {**conn.config_json, "auth": "basic"}
    else:
        feed.book = "db2"
    db.commit()

    with pytest.raises(RunRefusal) as excinfo:
        _resolve_vendor()(db, feed, vendor_transport=VendorStub().client())

    assert excinfo.value.code == expected


def test_ac_16_50_resolve_vendor_resolves_the_connection_within_the_feed_rows_tenant(db):
    """Tenant scope: a feed row whose stored connection id belongs to ANOTHER
    tenant is NO_CONNECTION, never resolved."""
    co = company(db)
    other = other_tenant(db)
    foreign_conn = autocount_connection(db, other)
    db.commit()
    feed = _feed(db, co, None, connection_id=foreign_conn.id)

    with pytest.raises(RunRefusal) as excinfo:
        _resolve_vendor()(db, feed, vendor_transport=VendorStub().client())

    assert excinfo.value.code == "NO_CONNECTION"


# ── _resolve: split, delegation and unchanged refusals ───────────────────────


def test_ac_16_50_resolve_delegates_to_resolve_vendor(db, monkeypatch):
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    real = _resolve_vendor()
    calls = []

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(runner_module, "resolve_vendor", spy)

    with pytest.raises(RunRefusal):
        # the sink half runs after the vendor half; the contract probe is
        # unrouted here so it refuses - the call count is what matters.
        _resolve(db, feed, vendor_transport=VendorStub().client(), sink_transport=httpx.MockTransport(
            lambda request: httpx.Response(500)
        ))

    assert calls == [1]


def test_ac_16_50_resolve_still_refuses_sink_not_ready_after_the_vendor_half_passed(db):
    co = company(db)  # vendor side fine, no sink at all
    conn = db.get(type(autocount_connection(db)), co.connection_id)
    feed = _feed(db, co, conn)

    with pytest.raises(RunRefusal) as excinfo:
        _resolve(db, feed, vendor_transport=VendorStub().client())

    assert excinfo.value.code == "SINK_NOT_READY"


@pytest.mark.parametrize(
    "case, expected",
    [
        ("inactive_and_everything_else_broken", "COMPANY_INACTIVE"),
        ("no_connection_and_no_sink", "NO_CONNECTION"),
        ("book_mismatch_and_no_sink", "BOOK_MISMATCH"),
        ("all_vendor_ok_no_sink", "SINK_NOT_READY"),
    ],
)
def test_ac_16_50_resolve_refusal_order_is_unchanged(db, case, expected):
    co = company(db)  # no sink in every case
    conn = db.get(type(autocount_connection(db)), co.connection_id)
    feed = _feed(db, co, conn)
    if case == "inactive_and_everything_else_broken":
        co.is_active = False
        feed.connection_id = "gone"
        feed.book = "db2"
    elif case == "no_connection_and_no_sink":
        feed.connection_id = "gone"
    elif case == "book_mismatch_and_no_sink":
        feed.book = "db2"
    db.commit()

    with pytest.raises(RunRefusal) as excinfo:
        _resolve(db, feed, vendor_transport=VendorStub().client())

    assert excinfo.value.code == expected


def test_ac_16_50_resolve_still_fails_closed_on_the_contract_gate(db):
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    old_contract = httpx.MockTransport(
        lambda request: httpx.Response(200, json=load_fixture("crm-contract-2.6-no-doc-feed.json"))
    )

    with pytest.raises(RunRefusal) as excinfo:
        _resolve(db, feed, vendor_transport=VendorStub().client(), sink_transport=old_contract)

    assert excinfo.value.code == "CONTRACT_GATE"


def test_ac_16_50_resolve_still_returns_the_sink_alongside_the_vendor_pieces(db):
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    contract = httpx.MockTransport(
        lambda request: httpx.Response(200, json=load_fixture("crm-contract-2.7.json"))
    )

    resolved = _resolve(db, feed, vendor_transport=VendorStub().client(), sink_transport=contract)

    assert resolved.company.id == co.id
    assert resolved.book == "db1"
    assert resolved.sink is not None
    assert isinstance(resolved.vendor, DocFeedVendor)
    assert isinstance(resolved.vendor_client, HttpApiClient)
    assert DEFAULT_TENANT_ID == co.tenant_id
