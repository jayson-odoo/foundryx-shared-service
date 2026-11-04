"""Plan 55 section 6a-2 (owner card 2): vendor capability gate, split link as two
writes, relocate, zero-qty emulation switch.

The fake wrapper mirrors db3: a NEW row linked with ``FromDocType "SO"`` is
forced to ``HQ`` and reads back ``FromDocType ""`` with the link in
``FromSODtlKey`` / ``FromSODocList`` and an empty ``DeliveryDate``; editing an
EXISTING row changes its location but never its link.
"""

from __future__ import annotations

import copy
import inspect
import json
from types import MappingProxyType
from decimal import Decimal
from typing import Any, Dict

import httpx
import pytest

from app.main import app
from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcStagedRecord, AcWriteAction
from modules.autocount.services.pull_key_service import PullKeyService
from modules.autocount.write_back import capabilities
from modules.autocount.write_back.deps import get_write_back_service
from modules.autocount.write_back.service import WriteBackService
from tests.test_autocount_write_back_service import (
    DB1,
    FakeAutoCount,
    Harness,
    _load,
)
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401,E402

PO_KEY = 12008
SO_KEY = 11988
EMPTY = "0001-01-01T00:00:00"
RELOCATE = "/api/v1/autocount/po-links/relocate"
LINK = "/api/v1/autocount/po-links"
UNLINK = "/api/v1/autocount/po-links/unlink"


class VendorFake(FakeAutoCount):
    """db3 reality. ``force_hq``: a new SO-linked row is forced to HQ.
    ``honor_existing_link``: an edited existing row also takes its link (the old
    behaviour, used when a capability flag is flipped on). ``put2_mode``: how
    every PUT after the first behaves: apply | vendor_error | timeout | ignore."""

    def __init__(self, db, session_factory):
        super().__init__(db, session_factory)
        self.force_hq = True
        self.honor_existing_link = False
        self.honor_unlink = False
        self.put2_mode = "apply"

    def _on_put(self, request: httpx.Request) -> httpx.Response:
        self.put_calls.append(request)
        self._check_txn("PUT")
        body = json.loads(request.content)
        self.put_bodies.append(body)
        other = self.session_factory()
        try:
            rows = (
                other.query(AcWriteAction)
                .filter(AcWriteAction.doc_key == body["DocKey"], AcWriteAction.outcome == "in_flight")
                .all()
            )
            self.in_flight_seen_at_put.append(len(rows))
        finally:
            other.close()
        mode = self.put_mode if len(self.put_calls) == 1 else self.put2_mode
        if mode == "timeout":
            raise httpx.ReadTimeout("slow")
        if mode == "vendor_error":
            return httpx.Response(400, json={"Message": "vendor says no"})
        if mode != "ignore":
            self._apply(body)
        return httpx.Response(200, json={"DocKey": body["DocKey"]})

    def _apply(self, body: Dict[str, Any]) -> None:
        doc = next(d for lst in self.docs.values() for d in lst if d["DocKey"] == body["DocKey"])
        for r in body["Details"]:
            linked_sent = r.get("FromDocType") == "SO"
            if r["DtlKey"] == 0:
                row = {**doc["Details"][0], **r, "DtlKey": self.next_dtl}
                self.next_dtl += 1
                row["FromSODtlKey"] = r["FromDocDtlKey"] if linked_sent else 0
                row["FromSODocList"] = r.get("FromDocNo", "") if linked_sent else ""
                row["FromDocType"], row["FromDocNo"], row["FromDocDtlKey"] = "", "", 0
                if linked_sent:
                    row["DeliveryDate"] = EMPTY
                    if self.force_hq:
                        row["Location"] = "HQ"
                doc["Details"].append(row)
            else:
                row = next(x for x in doc["Details"] if x["DtlKey"] == r["DtlKey"])
                row.update({k: v for k, v in r.items() if not k.startswith("From")})
                if self.honor_existing_link:
                    row["FromSODtlKey"] = r["FromDocDtlKey"] if linked_sent else 0
                    row["FromSODocList"] = r.get("FromDocNo", "") if linked_sent else ""
                elif self.honor_unlink and not linked_sent:
                    row["FromSODtlKey"], row["FromSODocList"] = 0, ""
        doc["LastModified"] = f"2026-11-05T09:00:{len(self.put_calls):02d}.00"

    def server_row(self, dtl_key: int) -> Dict[str, Any]:
        return next(r for r in self.docs["purchaseorderbydocdate"][0]["Details"] if r["DtlKey"] == dtl_key)

    def linked_row(self, so_dtl_key: int) -> Dict[str, Any]:
        return next(
            r for r in self.docs["purchaseorderbydocdate"][0]["Details"]
            if r.get("FromSODtlKey") == so_dtl_key and r["DtlKey"] not in (12011, 12013, 12015)
        )


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def h(db, session_factory):
    harness = Harness(db, session_factory)
    fake = VendorFake(db, session_factory)
    fake.serve("purchaseorderbydocdate", _load("po_202602_S0007.json"))
    fake.serve("salesorderbydocdate", _so_with_dates())
    harness.ac = fake
    return harness


def _so_with_dates() -> Dict[str, Any]:
    return _load("so_SO389293.json")


def _split(h, **over):
    return h.link_split(**over)


def _no_http(h):
    assert h.ac.get_calls == [] and h.ac.put_calls == []


def _set_row_qty(h, dtl_key: int, qty: float) -> None:
    """Make PO row ``dtl_key`` a whole-row case: change it on the server and in staging."""
    h.ac.server_row(dtl_key)["Qty"] = qty
    staged = h.staged_po()
    raw = copy.deepcopy(staged.raw_json)
    for r in raw["_lines"]:
        if r["DtlKey"] == dtl_key:
            r["Qty"] = qty
    staged.raw_json = raw
    h.db.commit()


def _two_bodies(row: AcWriteAction):
    return row.request_json, row.response_json


# ---- 1. capability constants and the gate ------------------------------------------

def test_cap_constants_are_the_owner_rulings():
    assert capabilities.VENDOR_CAPABILITIES == {
        "link_new_row": True, "link_existing_row": False, "unlink": False, "spo_unlink": False,
    }
    assert capabilities.ZERO_QTY_EMULATION is False


@pytest.mark.parametrize("po_dtl_key,po_doc_key", [(12013, PO_KEY), (999, 777777)])
def test_cap_unlink_refused_before_any_request(h, po_dtl_key, po_doc_key):
    res = h.service().unlink(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=po_doc_key, po_dtl_key=po_dtl_key
    )
    assert res.outcome == "refused" and res.error_code == "VENDOR_UNSUPPORTED"
    _no_http(h)
    row = h.action(res)
    assert row.action == "unlink" and row.outcome == "refused" and row.error_code == "VENDOR_UNSUPPORTED"


@pytest.mark.parametrize("spo_doc_key,spo_dtl_key", [(46178924, 46179075), (1, 1)])
def test_cap_spo_unlink_refused_before_any_request(h, spo_doc_key, spo_dtl_key):
    res = h.service().spo_unlink(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, spo_doc_key=spo_doc_key, spo_dtl_key=spo_dtl_key
    )
    assert res.outcome == "refused" and res.error_code == "VENDOR_UNSUPPORTED"
    _no_http(h)


def test_cap_whole_row_link_refused_after_exactly_one_get_and_no_put(h):
    _set_row_qty(h, 12017, 10.0)
    res = _split(h, qty=Decimal(10))  # q == row qty
    assert res.outcome == "refused" and res.error_code == "VENDOR_UNSUPPORTED"
    assert len(h.ac.get_calls) == 1 and h.ac.put_calls == []
    assert h.action(res).error_code == "VENDOR_UNSUPPORTED"


def test_cap_q_above_row_qty_keeps_its_own_refusal(h):
    res = _split(h, qty=Decimal(51))
    assert res.outcome == "refused" and res.error_code == "QTY_ABOVE_FREE"
    assert h.ac.put_calls == []


def test_cap_flip_unlink_reenables_the_old_path(h, monkeypatch):
    monkeypatch.setattr(
        capabilities, "VENDOR_CAPABILITIES", MappingProxyType({**capabilities.VENDOR_CAPABILITIES, "unlink": True})
    )
    h.ac.honor_unlink = True
    res = h.service().unlink(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=PO_KEY, po_dtl_key=12013
    )
    assert res.outcome == "done", res.error_code
    assert h.ac.server_row(12013)["FromSODtlKey"] == 0


def test_cap_flip_spo_unlink_reenables_the_old_path(h, monkeypatch):
    monkeypatch.setattr(
        capabilities, "VENDOR_CAPABILITIES", MappingProxyType({**capabilities.VENDOR_CAPABILITIES, "spo_unlink": True})
    )
    h.ac.honor_unlink = True
    spo = _load("spo_db1_sample.json")
    spo["Details"][0].update(FromDocType="PO", FromDocDtlKey=12013)
    h._stage("shipping_order", spo)
    h.ac.serve("purchaseorderbydocdate", spo)
    dtl = spo["Details"][0]["DtlKey"]
    res = h.service().spo_unlink(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, spo_doc_key=spo["DocKey"], spo_dtl_key=dtl
    )
    assert res.outcome != "refused" or res.error_code != "VENDOR_UNSUPPORTED"
    assert len(h.ac.put_calls) == 1


def test_cap_flip_link_existing_row_reenables_the_whole_row_path(h, monkeypatch):
    monkeypatch.setattr(
        capabilities, "VENDOR_CAPABILITIES", MappingProxyType({**capabilities.VENDOR_CAPABILITIES, "link_existing_row": True})
    )
    h.ac.honor_existing_link = True
    _set_row_qty(h, 12017, 10.0)
    res = _split(h, qty=Decimal(10))
    assert res.outcome == "done", res.error_code
    assert len(h.ac.put_calls) == 1  # in place, same row, one write
    row = h.ac.server_row(12017)
    assert row["Location"] == "BRW-AM" and row["FromSODtlKey"] == 11989


# ---- 2. split link as two writes ----------------------------------------------------

def test_split_put1_is_the_split_body_then_put2_moves_the_new_row(h):
    from modules.autocount.write_back.payloads import build_link

    expected1 = build_link(
        copy.deepcopy(h.ac.docs["purchaseorderbydocdate"][0]), 12017,
        h.ac.docs["salesorderbydocdate"][0], 11989, Decimal(10),
    )
    res = _split(h)
    assert res.outcome == "done" and res.error_code is None
    assert len(h.ac.put_calls) == 2
    assert h.ac.put_bodies[0] == json.loads(json.dumps(expected1))
    new = h.ac.linked_row(11989)
    assert new["Location"] == "BRW-AM" and new["Qty"] == 10
    put2 = h.ac.put_bodies[1]
    assert put2["DocKey"] == PO_KEY
    assert [r["DtlKey"] for r in put2["Details"]] == [new["DtlKey"]]
    row2 = put2["Details"][0]
    assert row2["Location"] == "BRW-AM" and row2["Qty"] == 10
    assert (row2["FromDocType"], row2["FromDocNo"], row2["FromDocDtlKey"]) == ("", "", 0)  # as read
    assert "DeliveryDate" not in row2  # read back as 0001, omitted
    assert h.ac.server_row(12017)["Qty"] == 40 and h.ac.server_row(12017)["Location"] == "HQ"
    assert h.ac.violations == []


def test_split_action_row_records_both_bodies_and_responses(h):
    res = _split(h)
    row = h.action(res)
    assert isinstance(row.request_json, list) and len(row.request_json) == 2
    assert row.request_json == h.ac.put_bodies
    assert isinstance(row.response_json, list) and len(row.response_json) == 2
    assert row.outcome == "done" and row.error_code is None


def test_split_vendor_keeping_location_means_no_put2(h):
    h.ac.force_hq = False
    res = _split(h)
    assert res.outcome == "done" and res.error_code is None
    assert len(h.ac.put_calls) == 1
    body0 = h.ac.put_bodies[0]
    assert h.action(res).request_json in (body0, [body0])
    assert h.ac.linked_row(11989)["Location"] == "BRW-AM"


@pytest.mark.parametrize("mode", ["vendor_error", "timeout", "ignore"])
def test_split_put2_failure_is_done_with_location_not_moved(h, mode):
    h.ac.put2_mode = mode
    res = _split(h)
    assert res.outcome == "done" and res.error_code == "LOCATION_NOT_MOVED"
    assert len(h.ac.put_calls) == 2  # PUT2 sent once, never retried, link not undone
    new = h.ac.linked_row(11989)
    assert new["FromSODtlKey"] == 11989 and new["Location"] == "HQ"
    row = h.action(res)
    assert row.outcome == "done" and row.error_code == "LOCATION_NOT_MOVED"
    assert h.sink_calls == [] or len(h.sink_calls) <= 1


def test_split_put1_verify_ignores_the_new_rows_forced_location(h):
    res = _split(h)  # fake forced HQ on PUT1 read-back
    assert res.outcome == "done", res.error_code  # not "mismatch"


# ---- 4. zero-qty emulation switch ----------------------------------------------------

def test_zero_qty_emulation_whole_row_link_is_edit_to_zero_plus_new_row_plus_move(h, monkeypatch):
    monkeypatch.setattr(capabilities, "ZERO_QTY_EMULATION", True)
    _set_row_qty(h, 12017, 10.0)
    res = _split(h, qty=Decimal(10))
    assert res.outcome == "done", res.error_code
    put1 = h.ac.put_bodies[0]
    by_key = {r["DtlKey"]: r for r in put1["Details"]}
    assert Decimal(str(by_key[12017]["Qty"])) == 0
    new_rows = [r for r in put1["Details"] if r["DtlKey"] == 0]
    assert len(new_rows) == 1
    assert Decimal(str(new_rows[0]["Qty"])) == 10
    assert (new_rows[0]["FromDocType"], new_rows[0]["FromDocNo"], new_rows[0]["FromDocDtlKey"]) == ("SO", "SO389293", 11989)
    assert len(h.ac.put_calls) == 2
    new = h.ac.linked_row(11989)
    assert new["Location"] == "BRW-AM" and new["Qty"] == 10
    assert h.ac.server_row(12017)["Qty"] == 0


# ---- 3. relocate ----------------------------------------------------------------------

def test_relocate_signature_takes_no_location():
    params = inspect.signature(WriteBackService.relocate).parameters
    assert list(params) == [
        "self", "tenant_id", "company_id", "po_doc_key", "po_dtl_key", "expected_last_modified", "key_id",
    ]


def _relocate(h, dtl_key: int, **over):
    args = dict(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=PO_KEY, po_dtl_key=dtl_key)
    args.update(over)
    return h.service().relocate(**args)


def _stranded_row(h) -> int:
    """A link whose location move failed (PUT2 ignored); returns the row's DtlKey."""
    h.ac.put2_mode = "ignore"
    assert _split(h).error_code == "LOCATION_NOT_MOVED"
    h.ac.put2_mode = "apply"
    h.ac.put_calls.clear()
    h.ac.put_bodies.clear()
    h.ac.get_calls.clear()
    return h.ac.linked_row(11989)["DtlKey"]


def test_relocate_moves_a_linked_row_to_the_so_location_only(h):
    dtl = _stranded_row(h)
    res = _relocate(h, dtl)
    assert res.outcome == "done" and res.error_code is None
    assert len(h.ac.put_calls) == 1
    body = h.ac.put_bodies[0]
    assert [r["DtlKey"] for r in body["Details"]] == [dtl]
    assert body["Details"][0]["Location"] == "BRW-AM"
    assert "DeliveryDate" not in body["Details"][0]
    row = h.ac.server_row(dtl)
    assert row["Location"] == "BRW-AM" and row["FromSODtlKey"] == 11989
    assert h.action(res).action == "relocate"


def test_relocate_location_comes_from_the_staged_so_row(h):
    dtl = _stranded_row(h)
    so = h.db.query(AcStagedRecord).filter(
        AcStagedRecord.entity_type == "sales_order", AcStagedRecord.company_id == h.company.id
    ).one()
    raw = copy.deepcopy(so.raw_json)
    for r in raw["_lines"]:
        if r["DtlKey"] == 11989:
            r["Location"] = "BRW-ZZ"
    so.raw_json = raw
    h.db.commit()
    _relocate(h, dtl)
    assert h.ac.put_bodies[0]["Details"][0]["Location"] == "BRW-ZZ"


def test_relocate_unlinked_row_is_refused_not_linked(h):
    res = _relocate(h, 12017)
    assert res.outcome == "refused" and res.error_code == "ROW_NOT_LINKED"
    assert h.ac.put_calls == []


def test_relocate_row_already_at_location_refused_with_no_put(h):
    assert _split(h).error_code is None  # link + move both landed
    dtl = h.ac.linked_row(11989)["DtlKey"]
    h.ac.put_calls.clear()
    res = _relocate(h, dtl)
    assert res.outcome == "refused" and res.error_code == "ROW_ALREADY_AT_LOCATION"
    assert h.ac.put_calls == []


def test_relocate_stale_busy_and_db3_guard(h):
    dtl = _stranded_row(h)
    stale = _relocate(h, dtl, expected_last_modified="2020-01-01T00:00:00.00")
    assert stale.outcome == "refused" and stale.error_code == "DOC_STALE"
    assert h.ac.put_calls == []
    h.db.add(AcWriteAction(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, action="link", doc_type="PO",
        doc_key=PO_KEY, dtl_key=1, outcome="in_flight", request_json={},
    ))
    h.db.commit()
    busy = _relocate(h, dtl)
    assert busy.outcome == "refused" and busy.error_code == "DOC_BUSY"
    h.db.query(AcWriteAction).filter(AcWriteAction.outcome == "in_flight").delete()
    h.db.commit()
    db1 = h._connection(DB1, DEFAULT_TENANT_ID)
    h.company.write_connection_id = db1.id
    h.db.commit()
    h.ac.get_calls.clear()
    blocked = _relocate(h, dtl)
    assert blocked.outcome == "refused" and blocked.error_code == "WRITE_NOT_ALLOWED"
    assert h.ac.get_calls == [] and h.ac.put_calls == []


# ---- gateway: VENDOR_UNSUPPORTED 409, LOCATION_NOT_MOVED 200, relocate route ----------

def _gateway(client, h, scopes=("write_back",)):
    h.company.sorento_company_code = "SRT"
    h.db.commit()
    row, plain = PullKeyService(h.db).issue(DEFAULT_TENANT_ID, name="caps", company_ids=[h.company.id])
    row.scopes = list(scopes)
    h.db.commit()
    app.dependency_overrides[get_write_back_service] = lambda: h.service()
    return {"X-API-Key": plain}


def test_gateway_unlink_is_409_vendor_unsupported(client, h):
    hdr = _gateway(client, h)
    r = client.post(UNLINK, json={"companyCode": "SRT", "poDocKey": PO_KEY, "poDtlKey": 12013}, headers=hdr)
    assert r.status_code == 409, r.text
    assert r.json()["errorCode"] == "VENDOR_UNSUPPORTED" and r.json()["outcome"] == "refused"
    _no_http(h)


def test_gateway_whole_row_link_is_409_vendor_unsupported(client, h):
    hdr = _gateway(client, h)
    _set_row_qty(h, 12017, 10.0)
    body = {"companyCode": "SRT", "poDocKey": PO_KEY, "poDtlKey": 12017, "soDocKey": SO_KEY, "soDtlKey": 11989, "qty": 10}
    r = client.post(LINK, json=body, headers=hdr)
    assert r.status_code == 409 and r.json()["errorCode"] == "VENDOR_UNSUPPORTED"
    assert h.ac.put_calls == []


def test_gateway_location_not_moved_answers_200_with_the_code(client, h):
    hdr = _gateway(client, h)
    h.ac.put2_mode = "ignore"
    body = {"companyCode": "SRT", "poDocKey": PO_KEY, "poDtlKey": 12017, "soDocKey": SO_KEY, "soDtlKey": 11989, "qty": 10}
    r = client.post(LINK, json=body, headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "done" and r.json()["errorCode"] == "LOCATION_NOT_MOVED"
    assert h.ac.linked_row(11989)["FromSODtlKey"] == 11989  # link not undone


def test_gateway_relocate_done_200_and_already_at_location_409(client, h):
    hdr = _gateway(client, h)
    dtl = _stranded_row(h)
    body = {"companyCode": "SRT", "poDocKey": PO_KEY, "poDtlKey": dtl}
    ok = client.post(RELOCATE, json=body, headers=hdr)
    assert ok.status_code == 200, ok.text
    assert ok.json()["outcome"] == "done"
    again = client.post(RELOCATE, json=body, headers=hdr)
    assert again.status_code == 409 and again.json()["errorCode"] == "ROW_ALREADY_AT_LOCATION"


def test_gateway_relocate_needs_the_write_back_scope(client, h):
    hdr = _gateway(client, h, scopes=("pull",))
    r = client.post(RELOCATE, json={"companyCode": "SRT", "poDocKey": PO_KEY, "poDtlKey": 12017}, headers=hdr)
    assert r.status_code == 403 and "SCOPE_REQUIRED" in r.text
    _no_http(h)


@pytest.mark.parametrize("body", [
    {"companyCode": "SRT", "poDtlKey": 1},
    {"companyCode": "SRT", "poDocKey": "x", "poDtlKey": 1},
    {"poDocKey": 1, "poDtlKey": 1},
])
def test_gateway_relocate_validation_is_422(client, h, body):
    hdr = _gateway(client, h)
    assert client.post(RELOCATE, json=body, headers=hdr).status_code == 422
    _no_http(h)
