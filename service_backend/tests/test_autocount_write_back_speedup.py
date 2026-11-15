"""SS-AUTOCOUNT-SPEEDUP: cheaper AutoCount write-path calls, same answers.

AC-SPD-01 one pooled HTTP client per process for every write-back read and write;
AC-SPD-02 every call still logged; AC-SPD-03 the move reuses the replace read-back
(no second GET PO between the two PUTs); AC-SPD-04 the PO and SO first reads run in
parallel; AC-SPD-05 refusal / unknown paths unchanged; AC-SPD-06 the before/after table.
"""

from __future__ import annotations

import threading
import time
from datetime import date
from typing import Any, List

import httpx
import pytest

from modules.autocount import http_client
from modules.autocount.write_back.client import AutoCountWriteClient
from modules.autocount.write_back.reader import AutoCountDocReader
from tests.test_autocount_write_back_call_log import assert_one_row_per_call, logs
from tests.test_autocount_write_back_primitives import DB3
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

GET_PO = ("GET", "purchaseorderbydocno")
GET_SO = ("GET", "salesorderbydocno")
PUT_PO = ("PUT", "editpurchaseorderbydockey")
DELAY = 0.05  # fixed mocked latency per vendor call


@pytest.fixture
def world(h):
    return World(h)


def calls(h) -> List[tuple]:
    return [(c.method, c.leaf) for c in h.vendor.calls]


def slow_vendor(h, delay: float = DELAY) -> List[str]:
    """Every vendor call takes ``delay`` seconds; returns the thread names that served the calls."""
    inner = h.vendor.transport
    threads: List[str] = []

    class Slow(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            threads.append(threading.current_thread().name)
            time.sleep(delay)
            return inner.handle_request(request)

    h.vendor.transport = Slow()
    return threads


# ============================== AC-SPD-03 the duplicate read is gone ==========================

def test_spd_03_a_link_reads_the_po_once_between_the_two_puts(h, world):
    res = h.run("link_row", world.params["link_row"])
    assert res.outcome == "done", (res.error_code, res.warnings)
    seq = calls(h)
    first, second = [i for i, c in enumerate(seq) if c == PUT_PO]
    between = seq[first + 1:second]
    assert between == [GET_PO], seq  # the replace read-back IS the move's fresh read
    assert len(seq) == 7, seq


def test_spd_03_the_move_put_is_built_from_the_replace_read_back(h, world):
    res = h.run("link_row", world.params["link_row"])
    assert res.outcome == "done", res.error_code
    replace, move = h.vendor.writes()
    new_rows = [r for r in move.body["Details"] if r.get("DtlKey") not in {r2.get("DtlKey") for r2 in world.po["Details"]}]
    assert new_rows, move.body  # the move names the row the replace created
    assert res.replaced_lines and res.replaced_lines[0][1] in {r["DtlKey"] for r in move.body["Details"]}


def test_spd_03_the_live_reread_before_the_first_put_stays(h, world):
    h.run("link_row", world.params["link_row"])
    seq = calls(h)
    first_put = seq.index(PUT_PO)
    assert seq[first_put - 1] == GET_PO  # fresh read right before the first write
    assert seq[:first_put].count(GET_PO) == 2


def test_spd_03_relink_and_unlink_drop_the_duplicate_read_too(h, world):
    res = h.run("relink_row", world.params["relink_row"])
    assert res.outcome == "done", res.error_code
    seq = calls(h)
    puts = [i for i, c in enumerate(seq) if c == PUT_PO]
    for a, b in zip(puts, puts[1:]):
        assert seq[a + 1:b] == [GET_PO], seq


# ============================== AC-SPD-04 parallel first reads ================================

def test_spd_04_the_po_and_so_first_reads_run_at_the_same_time(h, world):
    threads = slow_vendor(h)
    started = time.monotonic()
    res = h.run("link_row", world.params["link_row"])
    took = time.monotonic() - started
    assert res.outcome == "done", res.error_code
    assert calls(h)[:2] in ([GET_PO, GET_SO], [GET_SO, GET_PO])
    assert len(set(threads[:2])) == 2  # served on two threads
    assert took < 7 * DELAY - DELAY / 2, took  # 7 calls, two of them overlapped: about 6 x delay


def test_spd_04_the_so_read_is_still_logged_once_with_its_own_rows(h, world):
    slow_vendor(h, 0.01)
    res = h.run("link_row", world.params["link_row"])
    assert res.outcome == "done", res.error_code
    assert_one_row_per_call(h)
    so_rows = [r for r in logs(h) if r.path.startswith("/SalesOrderbydocno")]
    assert len(so_rows) == 1
    assert so_rows[0].doc_type == "SO" and so_rows[0].doc_key == 7002 and so_rows[0].outcome == "ok"
    assert so_rows[0].operation_id == res.operation_id
    assert so_rows[0].duration_ms >= 10


def test_spd_04_a_failed_so_bydocno_falls_back_to_the_day_list_and_both_are_logged(h, world):
    h.vendor.fail_next("GET", "salesorderbydocno", status=500)
    res = h.run("link_row", world.params["link_row"])
    assert res.outcome == "done", res.error_code
    so_logs = [(r.path.split("?")[0], r.outcome) for r in logs(h) if r.path.startswith("/SalesOrder")]
    assert so_logs[0] == ("/SalesOrderbydocno", "http_error") and len(so_logs) == 2, so_logs
    assert_one_row_per_call(h)


def test_spd_04_an_unreadable_so_still_refuses_with_its_own_code(h, world):
    h.vendor.fail_next("GET", "salesorderbydocno", status=500)
    h.vendor.fail_next("GET", calls_day_leaf(h, world), status=500)
    res = h.run("link_row", world.params["link_row"])
    assert res.outcome == "refused" and res.error_code == "READ_FAILED", res.error_code
    assert not h.vendor.writes()
    assert_one_row_per_call(h)


def calls_day_leaf(h, world) -> str:
    from modules.autocount.write_back.doc_kinds import KINDS

    return KINDS["SO"].by_date_path.rsplit("/", 1)[-1].lower()


def test_spd_04_a_po_refusal_wins_over_the_so_read(h, world):
    params = dict(world.params["link_row"], dtl_key=world.p_linked)  # already linked
    res = h.run("link_row", params)
    assert res.outcome == "refused" and res.error_code == "ROW_ALREADY_LINKED"
    assert not h.vendor.writes()
    assert_one_row_per_call(h)


def test_spd_04_a_missing_so_date_is_refused_like_before(h, world):
    params = dict(world.params["link_row"], so_doc_key=9999)  # unknown SO: no date anywhere
    res = h.run("link_row", params)
    assert res.outcome == "refused" and res.error_code == "DOC_DATE_REQUIRED", res.error_code
    assert calls(h) == [GET_PO]


# ============================== AC-SPD-05 unknown outcome unchanged ===========================

def test_spd_05_a_timed_out_replace_is_still_pending_and_logged(h, world):
    h.vendor.timeout_next("PUT", "editpurchaseorderbydockey")
    res = h.run("link_row", world.params["link_row"])
    assert res.outcome == "pending_verification", res.outcome
    assert [c for c in calls(h) if c[0] == "PUT"] == [PUT_PO]
    assert_one_row_per_call(h)


def test_spd_05_a_failed_move_is_still_a_warning(h, world):
    h.vendor.fail_next("PUT", "editpurchaseorderbydockey", status=500, after=1)
    res = h.run("link_row", world.params["link_row"])
    assert res.outcome == "done" and "LOCATION_NOT_MOVED" in res.warnings, (res.outcome, res.warnings)
    assert_one_row_per_call(h)


# ============================== AC-SPD-01 one pooled client ===================================

@pytest.fixture
def pooled(monkeypatch, h):
    """The production path (no injected transport): count the clients built, see every request."""
    built: List[httpx.Client] = []
    seen: List[httpx.Request] = []
    inner = h.vendor.transport

    class Seen(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return inner.handle_request(request)

    def guarded(timeout: float) -> httpx.Client:
        client = httpx.Client(transport=Seen(), timeout=timeout, follow_redirects=False)
        built.append(client)
        return client

    monkeypatch.setattr(http_client, "autocount_guarded_client", guarded)
    http_client.reset_shared_autocount_client()
    yield built, seen
    http_client.reset_shared_autocount_client()


def _prod_factories(h):
    kwargs = h.factories()
    kwargs["client_factory"] = lambda base_url: AutoCountWriteClient(base_url)
    kwargs["reader_factory"] = lambda base_url: AutoCountDocReader(base_url)
    return kwargs


def test_spd_01_a_whole_link_uses_one_client_for_every_call(h, world, pooled):
    built, seen = pooled
    from modules.autocount.write_back.operations import OperationService

    from tests.test_autocount_write_back_operations import KEY_ID, ZERO
    from app.models import DEFAULT_TENANT_ID

    svc = OperationService(h.db, receipt_reader=ZERO, notifier=h.alerts.append, **_prod_factories(h))
    res = svc.run(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, key_id=KEY_ID,
                  idempotency_key="pool-1", op="link_row", params=world.params["link_row"])
    assert res.outcome == "done", res.error_code
    assert len(seen) == 7
    assert len(built) == 1 and not built[0].is_closed  # one pool, kept open for the next call
    assert_one_row_per_call(h)


def test_spd_01_reader_and_writer_share_the_client_and_keep_timeout_and_key(h, world, pooled):
    built, seen = pooled
    base = DB3
    reader = AutoCountDocReader(base, timeout=12.0)
    reader.set_auth_headers({"X-Api-Key": "k-test"})
    writer = AutoCountWriteClient(base, timeout=34.0)
    writer.set_auth_headers({"X-Api-Key": "k-test"})
    reader.get_by_doc_no("PO", "PO-7001")
    writer.put("/EditPurchaseOrderbydockey", {"DocKey": 7001, "Details": []})
    reader.get_by_doc_no("SO", "SO-7002")
    assert len(built) == 1
    assert [r.extensions["timeout"]["read"] for r in seen] == [12.0, 34.0, 12.0]
    assert all(r.headers.get("X-Api-Key") == "k-test" for r in seen)


def test_spd_01_a_refused_book_is_still_refused_before_anything_is_sent(h, pooled, monkeypatch):
    built, seen = pooled
    from modules.autocount.write_back import client as client_mod
    from modules.autocount.write_back.guard import WriteNotAllowed

    writer = AutoCountWriteClient(DB3)

    def refuse(url):
        raise WriteNotAllowed("db1")

    monkeypatch.setattr(client_mod, "assert_write_allowed", refuse)
    with pytest.raises(WriteNotAllowed):
        writer.put("/EditPurchaseOrderbydockey", {})
    assert not seen


def test_spd_01_a_new_process_gets_its_own_client(pooled, monkeypatch):
    built, _seen = pooled
    first = http_client.shared_autocount_client()
    assert http_client.shared_autocount_client() is first
    monkeypatch.setattr(http_client.os, "getpid", lambda: -1)  # a forked worker
    assert http_client.shared_autocount_client() is not first
    assert len(built) == 2


def test_spd_01_a_closed_client_is_replaced(pooled):
    built, _seen = pooled
    first = http_client.shared_autocount_client()
    first.close()
    assert http_client.shared_autocount_client() is not first


# ============================== AC-SPD-06 before / after ======================================

def test_spd_06_before_after_table(h, world, capsys):
    """Prints the measured row for the crew note: calls and wall time with a fixed delay."""
    slow_vendor(h)
    started = time.monotonic()
    res = h.run("link_row", world.params["link_row"])
    took = time.monotonic() - started
    assert res.outcome == "done"
    with capsys.disabled():
        print(f"\nSPEEDUP link_row: calls={len(calls(h))} wall={took * 1000:.0f}ms delay={DELAY * 1000:.0f}ms/call")
