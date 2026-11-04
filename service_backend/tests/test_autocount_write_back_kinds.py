"""Plan 57 S1 red tests: doc kinds, capability table, DELETE verb (AC-57-01..05)."""

from __future__ import annotations

from types import MappingProxyType

import httpx
import pytest

from modules.autocount.write_back import capabilities
from modules.autocount.write_back.client import (
    AutoCountWriteClient,
    WriteResponse,
    WriteTransportError,
)
from modules.autocount.write_back.guard import WriteNotAllowed
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

DB3 = "https://ac.example.test/api/db3"

PATHS = {
    "QT": ("/NewQuotation", "/EditQuotationbydockey", "/quotationbydocdate"),
    "SO": ("/NewSalesOrder", "/EditSalesOrderbydockey", "/salesorderbydocdate"),
    "PO": ("/NewPurchaseOrder", "/EditPurchaseOrderbydockey", "/purchaseorderbydocdate"),
    "SPO": ("/NewPurchaseOrder", "/EditPurchaseOrderbydockey", "/purchaseorderbydocdate"),
}
PRIMITIVES = ("create_doc", "edit_doc", "add_line", "delete_line", "delete_doc", "cancel_doc")


def _doc_kinds():
    from modules.autocount.write_back import doc_kinds

    return doc_kinds


@pytest.mark.parametrize("name", sorted(PATHS))
def test_ac_57_01_kind_paths(name):
    dk = _doc_kinds()
    kind = dk.kind_of(name)
    assert dk.KINDS[name] == kind
    new, edit, by_date = PATHS[name]
    assert (kind.new_path, kind.edit_path, kind.by_date_path) == (new, edit, by_date)


@pytest.mark.parametrize(
    "name,field", [("QT", "DebtorCode"), ("SO", "DebtorCode"), ("PO", "CreditorCode"), ("SPO", "CreditorCode")]
)
def test_ac_57_01_party_field(name, field):
    assert _doc_kinds().kind_of(name).party_field == field


def test_ac_57_01_kind_table_is_exactly_four_and_frozen():
    dk = _doc_kinds()
    assert set(dk.KINDS) == {"QT", "SO", "PO", "SPO"}
    with pytest.raises(Exception):
        dk.kind_of("QT").new_path = "/x"  # frozen dataclass


@pytest.mark.parametrize("bad", ["XX", "", "qt", None, "DO"])
def test_ac_57_01_unknown_kind_is_value_error(bad):
    with pytest.raises(ValueError):
        _doc_kinds().kind_of(bad)


@pytest.mark.parametrize("name", sorted(PATHS))
def test_ac_57_16_one_delete_shape_per_kind(name):
    kind = _doc_kinds().kind_of(name)
    assert kind.delete_line.method == "DELETE"
    assert kind.delete_line.path.startswith("/Delete") and kind.delete_line.path.lower().endswith("bydtlkey")
    assert kind.delete_doc.method == "DELETE"
    assert kind.delete_doc.path.startswith("/Delete") and kind.delete_doc.path.lower().endswith("bydockey")
    assert kind.delete_line.path != kind.delete_doc.path


def test_ac_57_03_shipped_capability_table():
    on = {("QT", p) for p in ("create_doc", "edit_doc", "add_line")}
    on |= {("SO", p) for p in ("create_doc", "edit_doc", "add_line")}
    on |= {("PO", p) for p in ("create_doc", "edit_doc", "add_line")}
    on |= {("SPO", "edit_doc")}
    for kind in PATHS:
        for primitive in PRIMITIVES:
            assert capabilities.capable(kind, primitive) is ((kind, primitive) in on), (kind, primitive)


def test_ac_57_03_table_has_every_pair():
    assert set(capabilities.CAPABILITIES) == {(k, p) for k in PATHS for p in PRIMITIVES}


def test_ac_57_03_capable_reads_table_at_call_time(monkeypatch):
    assert capabilities.capable("QT", "cancel_doc") is False
    flipped = dict(capabilities.CAPABILITIES)
    flipped[("QT", "cancel_doc")] = True
    flipped[("QT", "create_doc")] = False
    monkeypatch.setattr(capabilities, "CAPABILITIES", MappingProxyType(flipped), raising=True)
    assert capabilities.capable("QT", "cancel_doc") is True
    assert capabilities.capable("QT", "create_doc") is False


def test_ac_57_03_unknown_pair_is_false_not_error():
    assert capabilities.capable("QT", "no_such_primitive") is False


def test_ac_57_13_and_q2_switches():
    assert capabilities.AUTO_DOCNO is True
    assert capabilities.PARTIAL_RECEIPT_SPLIT is True


# ---- client.delete ------------------------------------------------------------------


def _recording(calls, status=200, body=None):
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=body if body is not None else {"ok": True})

    return httpx.MockTransport(handler)


def _forbidden():
    def handler(request):
        raise AssertionError(f"network call made: {request.method} {request.url}")

    return httpx.MockTransport(handler)


def test_ac_57_01_delete_sends_delete_with_json_body():
    calls: list[httpx.Request] = []
    client = AutoCountWriteClient(DB3, transport=_recording(calls, 200, {"done": 1}))
    resp = client.delete("/DeleteQuotationDetailbydtlkey", {"DocKey": 5, "DtlKey": 7})
    assert isinstance(resp, WriteResponse) and resp.ok and resp.body == {"done": 1}
    assert len(calls) == 1
    assert calls[0].method == "DELETE"
    assert str(calls[0].url) == "https://ac.example.test/api/db3/DeleteQuotationDetailbydtlkey"
    import json

    assert json.loads(calls[0].read()) == {"DocKey": 5, "DtlKey": 7}


@pytest.mark.parametrize(
    "base",
    [
        "https://ac.example.test/api/db1",
        "https://ac.example.test/api/db2",
        "https://ac.example.test/api/db31",
        "https://ac.example.test/api/DB3",
        "https://ac.example.test/api/db3/../db1",
    ],
)
def test_ac_57_02_delete_refused_for_other_books_before_any_request(base):
    client = AutoCountWriteClient(DB3, transport=_forbidden())
    client.base_url = base  # swapped after construction: guard must re-run on the call
    with pytest.raises(WriteNotAllowed):
        client.delete("/DeleteQuotationbydockey", {"DocKey": 1})


def test_ac_57_02_delete_construct_on_db1_refused():
    with pytest.raises(WriteNotAllowed):
        AutoCountWriteClient("https://ac.example.test/api/db1", transport=_forbidden())


@pytest.mark.parametrize("path", ["Delete", "/a/../b", "/x?y=1", ""])
def test_ac_57_01_delete_bad_path_rejected_without_request(path):
    client = AutoCountWriteClient(DB3, transport=_forbidden())
    with pytest.raises(ValueError):
        client.delete(path, {})


def test_ac_57_05_delete_never_retries_on_timeout():
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("slow")

    client = AutoCountWriteClient(DB3, transport=httpx.MockTransport(handler))
    with pytest.raises(WriteTransportError) as ei:
        client.delete("/DeleteQuotationbydockey", {"DocKey": 1})
    assert ei.value.code == "WRITE_TIMEOUT"
    assert len(calls) == 1


def test_ac_57_05_post_put_still_never_retry():
    for method in ("post", "put"):
        calls: list[httpx.Request] = []

        def handler(request, calls=calls):
            calls.append(request)
            raise httpx.ReadTimeout("slow")

        client = AutoCountWriteClient(DB3, transport=httpx.MockTransport(handler))
        with pytest.raises(WriteTransportError):
            getattr(client, method)("/NewQuotation", {})
        assert len(calls) == 1
