"""AUTOCOUNT-LOAD-STRATEGY - our sync is never the reason AutoCount is slow
(``documentation/plans/sprint-5/autocount-load-strategy.md``, UAC
``autocount-load-strategy-acceptance-criteria.md``).

LS-1 stock balance page size 3000 (products stay at the connection's 1000),
LS-2 one AutoCount request at a time per server, page by page, a person's
call first, LS-3 longer pause while AutoCount answers slowly, LS-4 safety
stop after failures in a row, LS-5 the settings on the connection form.

The gate runs on a per-test fakeredis; the page walk rig is
``test_ss_stock_bal_soothe.py``'s fake wrapper. No real waits.
"""
from __future__ import annotations

import threading
import time
from typing import List

import fakeredis
import httpx
import pytest

from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.http_source import server_gate
from modules.autocount.http_source.client import HttpApiClient, HttpTransportError
from modules.autocount.http_source.server_gate import (
    PRIORITY_SYNC,
    PRIORITY_USER,
    ServerPolicy,
)
from modules.autocount.sources import Watermark
from tests.test_ss_stock_bal_soothe import (  # noqa: F401 - fixtures
    BALANCE_PATH,
    BASE_URL,
    ITEM_LOOKUP,
    Server,
    _company,
    _open_connection,
    _source,
    _stock_config,
)


@pytest.fixture
def gate(monkeypatch):
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    server_gate.set_client(fake)
    monkeypatch.setattr(server_gate, "POLL_SECONDS_SYNC", 0.005)
    monkeypatch.setattr(server_gate, "POLL_SECONDS_USER", 0.001)
    yield fake
    server_gate.set_client(False)


@pytest.fixture
def server(monkeypatch):
    """The soothe rig's fake wrapper, but keeping every keyword the source
    hands the client (policy, priority) so the gate is exercised."""
    import modules.autocount.http_source.source as source_module

    srv = Server()
    monkeypatch.setattr(
        source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(
            base_url, transport=httpx.Client(transport=httpx.MockTransport(srv.handler)),
            **{k: v for k, v in kw.items() if k != "transport"},
        ),
    )
    return srv


@pytest.fixture
def pauses(monkeypatch):
    import modules.autocount.http_source.gentle as gentle

    recorded: List[float] = []
    monkeypatch.setattr(
        gentle, "sleep_between_pages", lambda seconds, **_kw: recorded.append(seconds) or True,
    )
    return recorded


def _client(handler, **kw) -> HttpApiClient:
    return HttpApiClient(BASE_URL, transport=httpx.Client(transport=httpx.MockTransport(handler)), **kw)


def _ok(_request):
    return httpx.Response(200, json=[])


# ── LS-5 settings ──────────────────────────────────────────────────────────


def test_settings_defaults_for_a_connection_saved_before_this_lane():
    from modules.autocount.http_source.gentle import gentle_settings, server_policy

    s = gentle_settings({"baseUrl": BASE_URL, "auth": "none"})
    assert s.stock_page_size == 3000
    assert s.slow_page_seconds == 30.0
    p = server_policy({"baseUrl": BASE_URL, "auth": "none"})
    assert p == ServerPolicy(one_at_a_time=True, stop_after_failures=3, stop_minutes=10)


def test_settings_read_back_and_never_trust_junk():
    from modules.autocount.http_source.gentle import gentle_settings, server_policy

    s = gentle_settings({"stockPageSize": "2000", "slowPageSeconds": "0"})
    assert (s.stock_page_size, s.slow_page_seconds) == (2000, 0.0)
    junk = gentle_settings({"stockPageSize": "99999", "slowPageSeconds": "x"})
    assert (junk.stock_page_size, junk.slow_page_seconds) == (3000, 30.0)
    assert gentle_settings({"stockPageSize": "10"}).stock_page_size == 50
    p = server_policy({"oneRequestAtATime": "no", "stopAfterFailures": "0", "stopMinutes": "30"})
    assert p == ServerPolicy(one_at_a_time=False, stop_after_failures=0, stop_minutes=30)
    assert server_policy({"stopAfterFailures": "abc", "stopMinutes": "-4"}) == ServerPolicy()


def test_connection_form_shows_the_new_fields_for_the_open_api_only():
    from modules.autocount.provider import AutoCountProvider

    fields = {f["key"]: f for f in AutoCountProvider().fields()}
    expected = {
        "stockPageSize": ("Stock balance page size", "3000"),
        "oneRequestAtATime": ("One request at a time per server", "yes"),
        "slowPageSeconds": ("Slow page (seconds)", "30"),
        "stopAfterFailures": ("Stop after failed requests in a row", "3"),
        "stopMinutes": ("Stop for (minutes)", "10"),
    }
    for key, (label, default) in expected.items():
        assert fields[key]["label"] == label
        assert fields[key]["defaultValue"] == default
        assert fields[key]["showWhen"] == {"field": "auth", "values": ["none"]}
    assert fields["stockPageSize"]["max"] == 3000
    assert fields["pageSize"]["max"] == 1000, "products stay at 1000 (owner 27 Nov)"


@pytest.mark.parametrize(
    "key,raw",
    [("stockPageSize", "3001"), ("stockPageSize", "49"), ("stockPageSize", "x"),
     ("slowPageSeconds", "-1"), ("slowPageSeconds", "301"),
     ("stopAfterFailures", "21"), ("stopAfterFailures", "1.5"),
     ("stopMinutes", "0"), ("stopMinutes", "121"),
     ("oneRequestAtATime", "maybe")],
)
def test_out_of_range_settings_are_refused_at_save(key, raw):
    from modules.autocount.provider import AutoCountProvider

    assert AutoCountProvider().validate_config({"baseUrl": "", "auth": "none", key: raw})


def test_in_range_settings_are_accepted():
    from modules.autocount.provider import AutoCountProvider

    assert AutoCountProvider().validate_config({
        "baseUrl": "", "auth": "none", "stockPageSize": "3000", "slowPageSeconds": "0",
        "stopAfterFailures": "0", "stopMinutes": "120", "oneRequestAtATime": "no",
    }) is None


# ── LS-1 page size ─────────────────────────────────────────────────────────


def test_stock_balance_walk_asks_for_3000_and_its_lookups_for_the_connection_size(
    session_factory, server, gate,
):
    db = session_factory()
    conn = _open_connection(db, pageSize="1000")
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn, lookups=[ITEM_LOOKUP])

    _source(db, company, config).fetch_changes(Watermark())

    sizes = {
        (r.url.path.rsplit("/", 1)[-1], r.url.params.get("pageSize")) for r in server.calls
    }
    assert ("itembatchbalqtybypage", "3000") in sizes
    assert ("itembypage", "1000") in sizes
    assert ("itembatchbalqtybypage", "1000") not in sizes


def test_owner_can_set_the_stock_page_size(session_factory, server, gate):
    db = session_factory()
    conn = _open_connection(db, stockPageSize="2000")
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn)

    _source(db, company, config).fetch_changes(Watermark())

    assert {r.url.params.get("pageSize") for r in server.calls} == {"2000"}


def test_product_walk_keeps_the_connection_page_size(session_factory, server, gate):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn, entity_type=ENTITY_PRODUCT)
    config.source_config = {**config.source_config, "path": "/itembypage", "keyFields": ["ItemCode"]}
    db.commit()

    _source(db, company, config).fetch_changes(Watermark())

    assert {r.url.params.get("pageSize") for r in server.calls} == {"1000"}


# ── LS-2 one request at a time per server ──────────────────────────────────


def test_two_clients_on_one_server_never_overlap(gate):
    """Two books on one wrapper (db1, db2): their requests take turns."""
    in_flight = {"now": 0, "max": 0}
    lock = threading.Lock()

    def slow(_request):
        with lock:
            in_flight["now"] += 1
            in_flight["max"] = max(in_flight["max"], in_flight["now"])
        time.sleep(0.01)
        with lock:
            in_flight["now"] -= 1
        return httpx.Response(200, json=[])

    a = HttpApiClient(
        "https://autocount-wrapper.example.com/api/db1",
        transport=httpx.Client(transport=httpx.MockTransport(slow)),
    )
    b = HttpApiClient(
        "https://autocount-wrapper.example.com/api/db2",
        transport=httpx.Client(transport=httpx.MockTransport(slow)),
    )

    def walk(client):
        for page in range(1, 6):
            client.get("/itembypage", {"page": page})

    threads = [threading.Thread(target=walk, args=(c,)) for c in (a, b, a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert in_flight["max"] == 1


def test_a_different_server_is_not_held_up(gate):
    gate.set(server_gate._keys(BASE_URL)["lock"], "someone-else", px=60_000)
    other = HttpApiClient(
        "https://other-wrapper.example.com/api/db9",
        transport=httpx.Client(transport=httpx.MockTransport(_ok)),
    )
    assert other.get("/location", {}).status_code == 200


def test_the_turn_is_handed_back_after_each_request_even_on_failure(gate):
    def boom(_request):
        raise httpx.ConnectError("down")

    client = _client(boom, server_policy=ServerPolicy(stop_after_failures=0))
    with pytest.raises(HttpTransportError):
        client.get("/itembypage", {"page": 1})
    assert gate.get(server_gate._keys(BASE_URL)["lock"]) is None
    _client(_ok).get("/location", {})
    assert gate.get(server_gate._keys(BASE_URL)["lock"]) is None


def test_switched_off_the_requests_do_not_wait(gate):
    gate.set(server_gate._keys(BASE_URL)["lock"], "someone-else", px=60_000)
    client = _client(_ok, server_policy=ServerPolicy(one_at_a_time=False))
    assert client.get("/location", {}).status_code == 200


def test_a_persons_call_goes_ahead_of_waiting_sync_pages(gate):
    """Owner 27 Nov: a person's call (Link PO, a lookup from a screen) waits
    at most for the one page already in flight; queued sync pages go after."""
    keys = server_gate._keys(BASE_URL)
    order: List[str] = []

    def record(name):
        def handler(_request):
            order.append(name)
            return httpx.Response(200, json=[])
        return handler

    gate.set(keys["lock"], "page-in-flight", px=60_000)
    sync = _client(record("sync"), priority=PRIORITY_SYNC)
    user = _client(record("user"), priority=PRIORITY_USER)
    t_sync = threading.Thread(target=lambda: sync.get("/itembatchbalqtybypage", {"page": 2}))
    t_sync.start()
    time.sleep(0.03)
    t_user = threading.Thread(target=lambda: user.get("/deliveryorderbydocdate", {}))
    t_user.start()
    time.sleep(0.03)
    gate.delete(keys["lock"])  # the page in flight ends
    t_user.join(2)
    t_sync.join(2)
    assert order == ["user", "sync"]


def test_a_crashed_holder_frees_the_server_by_itself(gate):
    keys = server_gate._keys(BASE_URL)
    gate.set(keys["lock"], "crashed", px=30)
    assert _client(_ok).get("/location", {}).status_code == 200


def test_without_redis_the_request_goes_ahead(monkeypatch):
    class Down:
        def __getattr__(self, _name):
            def fail(*_a, **_k):
                raise ConnectionError("redis down")
            return fail

    server_gate.set_client(Down())
    try:
        assert _client(_ok).get("/location", {}).status_code == 200
    finally:
        server_gate.set_client(False)


# ── LS-4 safety stop ───────────────────────────────────────────────────────


def _failing(status=503):
    return lambda _request: httpx.Response(status, json={})


def test_three_failures_in_a_row_stop_scheduled_calls(gate):
    policy = ServerPolicy(stop_after_failures=3, stop_minutes=10)
    bad = _client(_failing(), server_policy=policy)
    for _ in range(3):
        bad.get("/itembypage", {"page": 1})
    calls: List[int] = []
    good = _client(lambda r: calls.append(1) or httpx.Response(200, json=[]), server_policy=policy)
    with pytest.raises(HttpTransportError) as caught:
        good.get("/itembypage", {"page": 1})
    assert caught.value.stopped_until is not None
    assert "AutoCount is not answering well" in caught.value.message
    assert calls == [], "a stopped server gets no scheduled request"


def test_a_good_answer_resets_the_count(gate):
    policy = ServerPolicy(stop_after_failures=3)
    answers = iter([503, 503, 200, 503, 503, 200])
    client = _client(lambda r: httpx.Response(next(answers), json=[]), server_policy=policy)
    for _ in range(6):
        client.get("/itembypage", {"page": 1})
    assert server_gate.stopped_until(BASE_URL) is None


def test_four_hundreds_are_not_server_failures(gate):
    client = _client(_failing(404), server_policy=ServerPolicy(stop_after_failures=1))
    client.get("/nope", {})
    assert server_gate.stopped_until(BASE_URL) is None


def test_timeouts_count_as_failures(gate):
    def slow(_request):
        raise httpx.ReadTimeout("slow")

    client = _client(slow, server_policy=ServerPolicy(stop_after_failures=2))
    for _ in range(2):
        with pytest.raises(HttpTransportError):
            client.get("/itembypage", {"page": 1})
    assert server_gate.stopped_until(BASE_URL) is not None


def test_a_persons_call_is_never_refused_by_the_stop(gate):
    policy = ServerPolicy(stop_after_failures=1)
    _client(_failing(), server_policy=policy).get("/itembypage", {"page": 1})
    assert server_gate.stopped_until(BASE_URL) is not None
    user = _client(_ok, server_policy=policy, priority=PRIORITY_USER)
    assert user.get("/deliveryorderbydocdate", {}).status_code == 200
    assert server_gate.stopped_until(BASE_URL) is None, "its good answer resumes the sync"


def test_after_the_stop_one_test_call_decides(gate, monkeypatch):
    policy = ServerPolicy(stop_after_failures=1, stop_minutes=10)
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(server_gate, "_now", lambda: clock["t"])
    _client(_failing(), server_policy=policy).get("/itembypage", {"page": 1})
    clock["t"] += 10 * 60 + 1

    # The test call fails: stopped again for another 10 minutes.
    _client(_failing(), server_policy=policy).get("/itembypage", {"page": 1})
    assert server_gate.stopped_until(BASE_URL) is not None
    clock["t"] += 10 * 60 + 1

    # The next test call answers: everything resumes.
    _client(_ok, server_policy=policy).get("/itembypage", {"page": 1})
    assert server_gate.stopped_until(BASE_URL) is None
    assert _client(_ok, server_policy=policy).get("/itembypage", {"page": 2}).status_code == 200


def test_a_stopped_server_fails_the_run_once_with_a_plain_reason(session_factory, server, gate):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn)
    server_gate.record_result(BASE_URL, ok=False, policy=ServerPolicy(stop_after_failures=1))

    from modules.autocount.http_source.errors import HttpSourceError

    with pytest.raises(HttpSourceError) as caught:
        _source(db, company, config).fetch_changes(Watermark())
    assert caught.value.code == "server_stopped"
    assert "AutoCount is not answering well" in str(caught.value)
    assert server.calls == [], "no retry ladder against a stopped server"


def test_the_stop_is_off_when_set_to_zero(gate):
    policy = ServerPolicy(stop_after_failures=0)
    bad = _client(_failing(), server_policy=policy)
    for _ in range(10):
        bad.get("/itembypage", {"page": 1})
    assert server_gate.stopped_until(BASE_URL) is None


# ── LS-3 adaptive pause ────────────────────────────────────────────────────


def test_pause_grows_while_pages_are_slow_and_shrinks_back_to_the_floor():
    from modules.autocount.http_source.gentle import AdaptivePause

    p = AdaptivePause(floor_seconds=1.0, slow_seconds=30.0)
    assert p.seconds == 1.0
    assert p.after_page(40.0) == 5.0    # slow: at least 5 s
    assert p.after_page(45.0) == 10.0   # still slow: doubles
    assert p.after_page(20.0) == 10.0   # between: holds
    assert p.after_page(3.0) == 5.0     # fast: halves
    assert p.after_page(3.0) == 2.5
    assert p.after_page(3.0) == 1.25
    assert p.after_page(3.0) == 1.0     # never below the owner's floor


def test_pause_never_passes_90_seconds_and_zero_slow_switches_it_off():
    from modules.autocount.http_source.gentle import AdaptivePause

    p = AdaptivePause(floor_seconds=0.0, slow_seconds=30.0)
    for _ in range(20):
        p.after_page(100.0)
    assert p.seconds == 90.0
    off = AdaptivePause(floor_seconds=2.0, slow_seconds=0.0)
    assert off.after_page(500.0) == 2.0


def test_walk_pauses_longer_after_a_slow_page(session_factory, server, gate, pauses, monkeypatch):
    db = session_factory()
    conn = _open_connection(db, slowPageSeconds="30")
    company = _company(db, conn.id)
    config = _stock_config(db, company, conn)

    import modules.autocount.http_source.client as client_module

    latencies = iter([40.0, 1.0, 1.0])
    real = client_module.HttpApiClient.get

    def timed(self, path, params):
        response = real(self, path, params)
        self.last_latency_seconds = next(latencies)
        return response

    monkeypatch.setattr(client_module.HttpApiClient, "get", timed)
    source = _source(db, company, config)
    source.fetch_changes(Watermark())

    assert pauses == [5.0, 2.5], "slow page 1 -> 5 s; fast page 2 -> halved"
    assert source.source_pause_seconds == 0.0, "the owner's floor is what the run records"


# ── LS-6 document feeds ride the same queue, stop and pause ────────────────


@pytest.fixture
def _contract(monkeypatch):
    from modules.autocount import sinks_sorento

    monkeypatch.setattr(
        sinks_sorento.SorentoSink, "fetch_contract_detail",
        lambda self: sinks_sorento.SorentoContractInfo(
            version=2.7, entities=["delivery_orders", "goods_receive_notes"]
        ),
    )


def _doc_feed(session_factory, **conn_config):
    from datetime import date

    from modules.autocount.models import AcDocFeed
    from tests.s14_doc_feed_helpers import wired_company

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    ac_conn.config_json = {**ac_conn.config_json, **conn_config}
    db.commit()
    feed = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode="push", cursor_day=date(2026, 9, 29),
    )
    db.add(feed)
    db.commit()
    return db, feed


def test_document_feed_reads_take_the_same_turn_and_policy(session_factory, gate, _contract):
    from modules.autocount.doc_feed.runner import resolve_vendor

    db, feed = _doc_feed(session_factory, oneRequestAtATime="no", stopAfterFailures="5")
    client = resolve_vendor(db, feed).vendor_client
    assert client.server_policy == ServerPolicy(one_at_a_time=False, stop_after_failures=5)
    assert client.priority == PRIORITY_SYNC


def test_a_stopped_server_fails_the_feed_poll_once_without_retries(
    session_factory, gate, _contract, monkeypatch,
):
    from datetime import datetime, timezone

    import modules.autocount.doc_feed.vendor as vendor_module
    from modules.autocount.doc_feed.runner import run_poll
    from tests.s14_doc_feed_helpers import VENDOR_BASE_URL

    sleeps: List[float] = []
    monkeypatch.setattr(vendor_module.time, "sleep", lambda s: sleeps.append(s))
    db, feed = _doc_feed(session_factory)
    server_gate.record_result(VENDOR_BASE_URL, ok=False, policy=ServerPolicy(stop_after_failures=1))
    calls: List[str] = []
    vendor = httpx.Client(transport=httpx.MockTransport(
        lambda r: calls.append(r.url.path) or httpx.Response(200, json=[]),
    ))

    run = run_poll(db, feed, dry_run=False, now=datetime(2026, 9, 29, 10, tzinfo=timezone.utc),
                   vendor_transport=vendor)

    assert calls == [] and sleeps == []
    assert run.error_code == "VENDOR_STOPPED"
    assert "AutoCount is not answering well" in (run.error or "")


def test_document_feed_days_pause_longer_after_a_slow_day(session_factory, gate, _contract, monkeypatch):
    from datetime import date, datetime, timezone

    import modules.autocount.http_source.client as client_module
    import modules.autocount.http_source.gentle as gentle
    from modules.autocount.doc_feed.runner import run_sweep

    pauses: List[float] = []
    monkeypatch.setattr(gentle, "sleep_between_pages", lambda s, **_k: pauses.append(s) or True)
    latencies = iter([40.0] + [1.0] * 10)
    real = client_module.HttpApiClient.get

    def timed(self, path, params):
        response = real(self, path, params)
        self.last_latency_seconds = next(latencies)
        return response

    monkeypatch.setattr(client_module.HttpApiClient, "get", timed)
    db, feed = _doc_feed(session_factory)
    feed.window_config = {"recheckDays": 4}
    db.commit()
    vendor = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))

    run_sweep(db, feed, dry_run=True, now=datetime(2026, 9, 29, 10, tzinfo=timezone.utc),
              vendor_transport=vendor)

    assert pauses == [5.0, 2.5, 1.25], "slow day 1 -> 5 s, then halved back towards 0"
    assert date  # noqa: B018


# ── LS-2b a person's calls: writes, screen lookups, previews ───────────────


def _person_goes_first(gate, person_call):
    keys = server_gate._keys(BASE_URL)
    order: List[str] = []
    gate.set(keys["lock"], "page-in-flight", px=60_000)
    sync = _client(lambda r: order.append("sync") or httpx.Response(200, json=[]))
    t_sync = threading.Thread(target=lambda: sync.get("/itembatchbalqtybypage", {"page": 2}))
    t_sync.start()
    time.sleep(0.03)
    t_user = threading.Thread(target=lambda: person_call(order))
    t_user.start()
    time.sleep(0.03)
    assert order == [], "nothing overtakes the page in flight"
    gate.delete(keys["lock"])
    t_user.join(2)
    t_sync.join(2)
    return order


def test_a_write_waits_only_for_the_page_in_flight_and_goes_before_sync(gate, monkeypatch):
    import modules.autocount.write_back.client as write_client
    from modules.autocount.write_back.client import AutoCountWriteClient

    # The write-book guard is its own suite's concern (test_autocount_plan63_gate.py).
    monkeypatch.setattr(write_client, "assert_write_allowed", lambda _url: "db3")

    def write(order):
        client = AutoCountWriteClient(
            BASE_URL,
            transport=httpx.MockTransport(lambda r: order.append("write") or httpx.Response(200, json={})),
        )
        client.post("/SalesOrder", {"DocNo": "X"})

    assert _person_goes_first(gate, write) == ["write", "sync"]


def test_a_document_read_from_a_screen_goes_before_sync(gate):
    from modules.autocount.write_back.reader import AutoCountDocReader

    def read(order):
        reader = AutoCountDocReader(
            BASE_URL,
            transport=httpx.MockTransport(lambda r: order.append("read") or httpx.Response(200, json=[])),
        )
        reader.fetch_records("/SalesOrder", {"DocNo": "X"})

    assert _person_goes_first(gate, read) == ["read", "sync"]


def test_doc_finder_and_preview_reads_are_a_persons_calls(session_factory, gate, _contract, monkeypatch):
    import modules.autocount.http_source.preview as preview_module

    seen: List[str] = []
    real = HttpApiClient.__init__

    def spy(self, *a, **kw):
        real(self, *a, **kw)
        seen.append(kw.get("priority", PRIORITY_SYNC))

    monkeypatch.setattr(HttpApiClient, "__init__", spy)
    try:
        preview_module.run_http_preview(
            BASE_URL, "/location",
            transport=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))),
        )
    except Exception:  # noqa: BLE001 - only the client's priority matters here
        pass
    assert seen and seen[0] == PRIORITY_USER

    from modules.autocount.doc_lookup import job as lookup_job

    assert lookup_job.READ_PRIORITY == PRIORITY_USER
