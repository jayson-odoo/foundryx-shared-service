"""SS-AC-BLANK-MASTER-REF B4: a split link's new SO-transferred PO row keeps the
source row's unit price and delivery date, or the write fails loudly.

db3 (6 Nov, FXT-1106-PO1; 4 Nov FXT-1104d-1; test report 2026-11-04 P6/P10/C03):
the split PUT sends the new ``DtlKey 0`` row with ``UnitPrice 1.0`` and a
``DeliveryDate``, but AutoCount stores the transferred row with ``UnitPrice 0``,
an empty date and ``Location HQ``; the action answered ``done`` and the PO total
fell. The fake below mirrors that: a NEW SO-linked row is reset (HQ, price 0,
empty date); an EXISTING row's edit is applied (probe P4, location only proven
live; price/date to be proven by the AC-E2E-DB3 lane).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

import pytest

from modules.autocount.write_back import payloads as P
from modules.autocount.write_back.service import verify_readback
from tests.test_autocount_write_back_service import Harness, _load
from tests.test_autocount_write_back_vendor_caps import (  # noqa: F401
    EMPTY,
    VendorFake,
    _slow_readback_after_first_put,
    _so_with_dates,
    db,
)
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

SRC_PRICE = 100.0
SRC_DATE = "2026-03-15T00:00:00"


class TransferResetFake(VendorFake):
    """db3: a new SO-linked row also loses its price (``reset_price``); an edit of an
    existing row may ignore price/date (``honor_edit_values`` False)."""

    def __init__(self, db, session_factory):
        super().__init__(db, session_factory)
        self.reset_price = True
        self.honor_edit_values = True

    def _apply(self, body: Dict[str, Any]) -> None:
        doc = next(d for lst in self.docs.values() for d in lst if d["DocKey"] == body["DocKey"])
        before = {r["DtlKey"]: dict(r) for r in doc["Details"]}
        super()._apply(body)
        for r in body["Details"]:
            if r["DtlKey"] == 0 and r.get("FromDocType") == "SO" and self.reset_price:
                doc["Details"][-1]["UnitPrice"] = 0.0
            elif r["DtlKey"] and not self.honor_edit_values:
                row = next(x for x in doc["Details"] if x["DtlKey"] == r["DtlKey"])
                row["UnitPrice"] = before[r["DtlKey"]].get("UnitPrice")
                row["DeliveryDate"] = before[r["DtlKey"]].get("DeliveryDate")


@pytest.fixture
def h(db, session_factory):
    harness = Harness(db, session_factory)
    fake = TransferResetFake(db, session_factory)
    fake.serve("purchaseorderbydocdate", _load("po_202602_S0007.json"))
    fake.serve("salesorderbydocdate", _so_with_dates())
    harness.ac = fake
    return harness


def _new_row(h):
    return h.ac.linked_row(11989)


# ---- the happy path: the second write restores price and date --------------------------

def test_split_restores_price_and_date_on_the_new_row(h):
    res = h.link_split()
    assert res.outcome == "done" and res.error_code is None
    new = _new_row(h)
    assert new["Location"] == "BRW-AM"
    assert new["UnitPrice"] == SRC_PRICE
    assert new["DeliveryDate"] == SRC_DATE
    put2 = h.ac.put_bodies[1]["Details"][0]
    assert put2["UnitPrice"] == SRC_PRICE and put2["DeliveryDate"] == SRC_DATE
    assert put2["Location"] == "BRW-AM"
    assert h.ac.server_row(12017)["UnitPrice"] == SRC_PRICE  # the touched row kept its price


def test_location_kept_but_price_reset_still_sends_the_restore_write(h):
    h.ac.force_hq = False
    res = h.link_split()
    assert res.outcome == "done" and res.error_code is None
    assert len(h.ac.put_calls) == 2
    assert _new_row(h)["UnitPrice"] == SRC_PRICE


def test_no_restore_write_when_the_vendor_kept_everything(h):
    h.ac.force_hq = False
    h.ac.reset_price = False
    h.ac.server_row(12017)["DeliveryDate"] = EMPTY  # nothing to restore: no date sent
    res = h.link_split()
    assert res.outcome == "done" and res.error_code is None
    assert len(h.ac.put_calls) == 1


# ---- fails loudly: never "done" with a zero-priced transferred row -----------------------

@pytest.mark.parametrize("mode", ["vendor_error", "timeout", "ignore"])
def test_restore_write_failure_is_a_mismatch_not_done(h, mode):
    h.ac.put2_mode = mode
    res = h.link_split()
    assert res.outcome == "mismatch" and res.error_code == "ROW_VALUES_NOT_KEPT"
    assert len(h.ac.put_calls) == 2  # never retried, link not undone
    row = h.action(res)
    assert row.outcome == "mismatch" and row.error_code == "ROW_VALUES_NOT_KEPT"


def test_vendor_ignoring_price_on_the_restore_edit_is_a_mismatch(h):
    h.ac.honor_edit_values = False  # every edit of an existing row keeps its old price/date
    res = h.link_split()
    assert res.outcome == "mismatch" and res.error_code == "ROW_VALUES_NOT_KEPT"


def test_deadline_before_the_restore_write_is_a_mismatch(h, monkeypatch):
    from modules.autocount.write_back import service as service_mod

    monkeypatch.setattr(service_mod, "ACTION_DEADLINE_SECONDS", 0.2)
    _slow_readback_after_first_put(h)
    res = h.link_split()
    assert res.outcome == "mismatch" and res.error_code == "ROW_VALUES_NOT_KEPT"
    assert len(h.ac.put_calls) == 1


def test_only_location_not_moved_stays_done_with_the_warning(h):
    """Price/date not reset by the vendor, only the location: the old LOCATION_NOT_MOVED rule."""
    h.ac.reset_price = False
    h.ac.put2_mode = "vendor_error"
    h.ac.server_row(12017)["DeliveryDate"] = EMPTY
    res = h.link_split()
    assert res.outcome == "done" and res.error_code == "LOCATION_NOT_MOVED"


# ---- verify: touched rows compare price and date too ------------------------------------

def _po():
    return _load("po_202602_S0007.json")


def test_verify_readback_catches_a_touched_row_losing_its_price():
    before = _po()
    body = P.build_link(before, 12017, _so_with_dates(), 11989, Decimal(10))
    after = _po()
    row = next(r for r in after["Details"] if r["DtlKey"] == 12017)
    row["Qty"] = 40.0
    row["UnitPrice"] = 0.0
    after["Details"].append({**body["Details"][1], "DtlKey": 99999, "FromSODtlKey": 11989, "Location": "HQ"})
    assert verify_readback(before, after, body, ignore_new_row_location=True) is False
    row["UnitPrice"] = SRC_PRICE
    assert verify_readback(before, after, body, ignore_new_row_location=True) is True
    row["DeliveryDate"] = EMPTY
    assert verify_readback(before, after, body, ignore_new_row_location=True) is False


# ---- the pure helper ---------------------------------------------------------------------

def test_transfer_row_drift_names_only_what_differs():
    sent = {"Location": "BRW-AM", "UnitPrice": 100.0, "DeliveryDate": SRC_DATE}
    got = {"Location": "HQ", "UnitPrice": 0.0, "DeliveryDate": EMPTY}
    assert P.transfer_row_drift(sent, got) == sent
    assert P.transfer_row_drift(sent, dict(sent)) == {}
    assert P.transfer_row_drift({"UnitPrice": 100.0}, {"UnitPrice": 100, "DeliveryDate": EMPTY}) == {}
    # dates compare by day; an empty source date is never "restored"
    assert P.transfer_row_drift({"DeliveryDate": SRC_DATE}, {"DeliveryDate": "2026-03-15T00:00:00.000"}) == {}
    assert P.transfer_row_drift({"DeliveryDate": EMPTY}, {"DeliveryDate": ""}) == {}


def test_build_restore_row_sends_the_row_as_read_with_the_values():
    po = _po()
    row = next(r for r in po["Details"] if r["DtlKey"] == 12011)
    body = P.build_restore_transfer_row(po, 12011, {"Location": "BRW-AM", "UnitPrice": 5.0, "DeliveryDate": SRC_DATE})
    assert [r["DtlKey"] for r in body["Details"]] == [12011]
    sent = body["Details"][0]
    assert sent["Location"] == "BRW-AM" and sent["UnitPrice"] == 5.0 and sent["DeliveryDate"] == SRC_DATE
    assert sent["Qty"] == row["Qty"] and sent["ItemCode"] == row["ItemCode"]
    with pytest.raises(P.WriteRefusal):
        P.build_restore_transfer_row(po, 12011, {})
