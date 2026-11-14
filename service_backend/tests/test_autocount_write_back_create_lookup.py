"""Plan 62: the create resend lookup (``OperationService.find_created_doc``), driven for real through the
gateway route with the fake vendor stamping ``CreatedTimeStamp`` / ``LastModified`` (MYT, no zone, ms).

A first POST that may have landed (answer lost) is looked up on the next resend of the same key:
found -> done (locked, no second POST); none -> released (one POST); several -> needs attention.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any, List

import pytest

from app.main import app  # noqa: F401
from modules.autocount.models import AcApiCallLog, AcWriteOperation
from tests.test_autocount_write_back_call_log import assert_one_row_per_call
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw, code, create_body
from tests.test_autocount_write_back_operations import OpHarness, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

URL = f"{PREFIX}/documents/purchase-orders"
MYT = timezone(timedelta(hours=8))


@pytest.fixture
def gw(h, db):
    h.vendor.stamp_created = True
    h.delete_on()
    return Gw(h, db)


def posts(h) -> List[Any]:
    return [c for c in h.vendor.writes() if c.method == "POST"]


def lookups(h) -> List[Any]:
    return [c for c in h.vendor.gets() if c.leaf == "purchaseorderbylastmodified"]


def body(docno=None, **header) -> dict:
    out = create_body("PO")
    out["header"].update(header)
    if docno:
        out["header"]["docNo"] = docno
    return out


def first_attempt_landed(client, h, gw, key, b):
    h.vendor.apply_then_500_next("POST", "NewPurchaseOrder")
    r = client.post(URL, json=b, headers=gw.hdr(key))
    assert r.status_code == 502 and r.json()["outcome"] == "vendor_error", r.text
    assert len(posts(h)) == 1 and len(h.vendor.docs["PO"]) == 1


def shift(doc, seconds=0, to=None):
    stamp = to or (datetime.now(MYT).replace(tzinfo=None) + timedelta(seconds=seconds)).isoformat(timespec="milliseconds")
    doc["CreatedTimeStamp"] = doc["LastModified"] = stamp


# ============================== <<New>> body ====================================================

def test_new_number_first_post_landed_resend_finds_the_one_document_and_posts_no_more(client, h, gw):
    first_attempt_landed(client, h, gw, "cl-1", body())
    landed = h.vendor.docs["PO"][0]
    r = client.post(URL, json=body(), headers=gw.hdr("cl-1"))
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert r.json()["docNo"] == landed["DocNo"]
    assert len(posts(h)) == 1  # no second POST
    assert lookups(h), "the day list was never read"
    again = client.post(URL, json=body(), headers=gw.hdr("cl-1"))  # locked now
    assert again.json()["outcome"] == "done" and len(posts(h)) == 1


@pytest.mark.parametrize("mode", ["fail", "timeout"])
def test_new_number_nothing_created_posts_once_more(client, h, gw, mode):
    getattr(h.vendor, f"{mode}_next")("POST", "NewPurchaseOrder")
    r1 = client.post(URL, json=body(), headers=gw.hdr("cl-2"))
    assert r1.json()["outcome"] in ("vendor_error", "pending_verification")
    assert h.vendor.docs["PO"] == []
    r2 = client.post(URL, json=body(), headers=gw.hdr("cl-2"))
    assert r2.status_code == 200 and r2.json()["outcome"] == "done", r2.text
    assert len(posts(h)) == 2 and len(h.vendor.docs["PO"]) == 1


def test_new_number_two_identical_documents_in_the_window_need_attention_with_no_post(client, h, gw):
    first_attempt_landed(client, h, gw, "cl-3", body())
    twin = copy.deepcopy(h.vendor.docs["PO"][0])
    twin.update(DocKey=twin["DocKey"] + 1000, DocNo="PO-TWIN")
    h.vendor.docs["PO"].append(twin)
    r = client.post(URL, json=body(), headers=gw.hdr("cl-3"))
    assert r.json()["outcome"] == "needs_attention" and code(r) == "CREATE_AMBIGUOUS", r.text
    assert len(posts(h)) == 1
    again = client.post(URL, json=body(), headers=gw.hdr("cl-3"))  # locked for a person
    assert again.json()["outcome"] == "needs_attention" and len(posts(h)) == 1


def _not_a_match(client, h, gw, key, mutate):
    first_attempt_landed(client, h, gw, key, body())
    mutate(h.vendor.docs["PO"][0])
    r = client.post(URL, json=body(), headers=gw.hdr(key))
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert len(posts(h)) == 2  # the look-alike was not ours: one fresh POST
    assert len(h.vendor.docs["PO"]) == 2


def test_a_matching_document_created_thirty_minutes_earlier_is_not_ours(client, h, gw):
    _not_a_match(client, h, gw, "cl-4a", lambda d: shift(d, seconds=-1800))


def test_a_matching_document_created_thirty_minutes_later_is_not_ours(client, h, gw):
    _not_a_match(client, h, gw, "cl-4b", lambda d: shift(d, seconds=1800))


@pytest.mark.parametrize("seconds", [-480, 480], ids=["clock_behind", "clock_ahead"])
def test_a_document_eight_minutes_off_the_attempt_is_ours_clock_skew_is_tolerated(client, h, gw, seconds):
    first_attempt_landed(client, h, gw, f"cl-skew{seconds}", body())
    shift(h.vendor.docs["PO"][0], seconds=seconds)  # the AutoCount server's clock is not ours
    r = client.post(URL, json=body(), headers=gw.hdr(f"cl-skew{seconds}"))
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert len(posts(h)) == 1  # found, so no second POST


def test_a_document_for_another_party_is_not_ours(client, h, gw):
    _not_a_match(client, h, gw, "cl-4c", lambda d: d.update(CreditorCode="OTHER-PARTY"))


def test_a_document_with_different_lines_is_not_ours(client, h, gw):
    _not_a_match(client, h, gw, "cl-4d", lambda d: d["Details"][0].update(Qty=9))


def test_a_window_straddling_midnight_reads_both_day_lists(client, h, gw, db):
    first_attempt_landed(client, h, gw, "cl-5", body())
    shift(h.vendor.docs["PO"][0], to="2026-11-11T00:00:02.000")  # created just after MYT midnight
    op = db.query(AcWriteOperation).filter_by(op="create_doc:PO").one()
    op.snapshot_json = dict(op.snapshot_json, start="2026-11-10T23:59:50+08:00", end="2026-11-11T00:00:05+08:00")
    db.commit()
    r = client.post(URL, json=body(), headers=gw.hdr("cl-5"))
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert len(posts(h)) == 1
    days = sorted(c.query["lastModified"] for c in lookups(h))
    assert days[:2] == ["20261110", "20261111"], days  # both sides of the midnight (later days may follow, up to today)


def test_every_lookup_get_is_in_the_api_call_log(client, h, gw):
    first_attempt_landed(client, h, gw, "cl-6", body())
    client.post(URL, json=body(), headers=gw.hdr("cl-6"))
    assert lookups(h)
    assert_one_row_per_call(h)
    rows = h.db.query(AcApiCallLog).filter(AcApiCallLog.method == "GET").all()
    assert len(rows) == len(h.vendor.gets())


# ============================== numbered body ===================================================

def test_numbered_body_found_with_matching_party_and_lines_is_done_by_the_doc_no_door(client, h, gw):
    b = body(docno="PO-NUM-1")
    first_attempt_landed(client, h, gw, "cl-7", b)
    r = client.post(URL, json=b, headers=gw.hdr("cl-7"))
    assert r.status_code == 200 and r.json()["outcome"] == "done" and r.json()["docNo"] == "PO-NUM-1", r.text
    assert len(posts(h)) == 1
    assert [c for c in h.vendor.gets() if c.leaf == "purchaseorderbydocno"]
    assert lookups(h) == []  # a numbered body never reads the day list


def test_numbered_body_found_with_different_lines_is_not_ours_and_the_create_runs_again(client, h, gw):
    b = body(docno="PO-NUM-2")
    first_attempt_landed(client, h, gw, "cl-8", b)
    h.vendor.docs["PO"][0]["Details"][0]["Qty"] = 9  # someone else's document with that number
    client.post(URL, json=b, headers=gw.hdr("cl-8"))
    assert len(posts(h)) == 2  # not ours -> released -> one more POST (AutoCount then answers for the number)
