"""sprint-5/14 S0 - clock + record-shape unit tests (AC-14-10, T1 groundwork).

No DB, no network: pure functions from `modules.autocount.doc_feed.clock`
(MYT day math) and `modules.autocount.doc_feed.records` (DocKey/source_ref/
dedupe/sort/DocDate parsing), plus the vendor path constants plan section 1
pins as literal strings in `modules.autocount.doc_feed.constants`. These
modules do not exist yet (S0) - an ImportError here IS the expected red
(D21): the coder builds `doc_feed/{clock,records,constants}.py` to make it
pass, module names/behaviour drawn from plan section 3.3/3.6 and the plan's
own decision log (D6 MYT fixed UTC+8, D8 one copy per DocKey/greatest
LastModified/push oldest-first, D18 numbers stay JSON numbers).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from modules.autocount.doc_feed import constants as doc_feed_constants
from modules.autocount.doc_feed.clock import MYT, myt_date, yyyymmdd
from modules.autocount.doc_feed.records import (
    dedupe_latest,
    doc_date,
    doc_key,
    push_order,
    source_ref,
    vendor_modified_at,
)


# ── vendor path constants (AC-14-10) ─────────────────────────────────────────


def test_vendor_path_constants_match_the_plan_exactly():
    """Plan section 1's table, quoted exactly - casing differs per door and
    must never drift (a query-string change here is a live-vendor outage)."""
    assert doc_feed_constants.DO_BY_LAST_MODIFIED_PATH == "/deliveryorderbyLastModified"
    assert doc_feed_constants.DO_BY_DOC_DATE_PATH == "/deliveryorderbydocdate"
    assert doc_feed_constants.GRN_BY_LAST_MODIFIED_PATH == "/goodsreceivenotebyLastModified"
    assert doc_feed_constants.GRN_BY_DOC_DATE_PATH == "/goodsreceivenotebydocdate"
    # plan 14 section 11 (D28): the branchbypage path left the doc feed (it is
    # now `presets.HTTP_PRESETS["branch"].path`).
    assert not hasattr(doc_feed_constants, "BRANCH_BY_PAGE_PATH")


def test_feed_keys_are_the_two_left_after_branches_became_an_entity():
    assert doc_feed_constants.FEED_DELIVERY_ORDERS == "delivery_orders"
    assert doc_feed_constants.FEED_GOODS_RECEIVE_NOTES == "goods_receive_notes"
    assert not hasattr(doc_feed_constants, "FEED_BRANCHES")
    assert doc_feed_constants.ALL_FEEDS == ("delivery_orders", "goods_receive_notes")


# ── MYT clock (D6, AC-14-11/30/31) ───────────────────────────────────────────


def test_myt_is_a_fixed_utc_plus_8_offset_no_dst():
    now = datetime(2026, 1, 15, 0, 0, 0, tzinfo=MYT)
    assert now.utcoffset().total_seconds() == 8 * 3600
    # A July timestamp (northern-hemisphere DST season elsewhere) must carry
    # the IDENTICAL offset - Malaysia observes no DST.
    july = datetime(2026, 7, 15, 0, 0, 0, tzinfo=MYT)
    assert july.utcoffset().total_seconds() == 8 * 3600


def test_myt_date_at_15_59_utc_is_still_the_earlier_myt_day():
    # 15:59 UTC + 8h = 23:59 MYT - still the SAME MYT calendar day as 15:59 UTC.
    aware = datetime(2026, 9, 29, 15, 59, 0, tzinfo=timezone.utc)
    assert myt_date(aware) == date(2026, 9, 29)


def test_myt_date_at_16_00_utc_rolls_to_the_next_myt_day():
    # 16:00 UTC + 8h = 00:00 MYT the NEXT calendar day (AC-14-11's own example:
    # 2026-09-29T16:30:00Z = 00:30 MYT on 30 Sep).
    aware = datetime(2026, 9, 29, 16, 30, 0, tzinfo=timezone.utc)
    assert myt_date(aware) == date(2026, 9, 30)


def test_yyyymmdd_formats_a_date_with_no_separators():
    assert yyyymmdd(date(2026, 9, 5)) == "20260905"
    assert yyyymmdd(date(2026, 12, 31)) == "20261231"


# ── doc_key (D19) ────────────────────────────────────────────────────────────


def test_doc_key_accepts_an_integer():
    assert doc_key({"DocKey": 55120}) == 55120


def test_doc_key_accepts_an_integer_string():
    assert doc_key({"DocKey": "55120"}) == 55120


def test_doc_key_is_none_when_missing():
    assert doc_key({"DocNo": "DO-1"}) is None


def test_doc_key_is_none_for_a_non_integer_string():
    assert doc_key({"DocKey": "ABC"}) is None


def test_doc_key_is_none_for_a_bool():
    # isinstance(True, int) is True in Python - a stray boolean must never be
    # accepted as a DocKey (the record would then be "sent" under DocKey 1).
    assert doc_key({"DocKey": True}) is None


def test_doc_key_is_none_for_a_blank_string():
    assert doc_key({"DocKey": ""}) is None


# ── dedupe_latest + push_order (D8) ──────────────────────────────────────────


def _rec(doc_key_value, last_modified):
    return {"DocKey": doc_key_value, "DocNo": f"DO-{doc_key_value}", "LastModified": last_modified}


def test_dedupe_latest_keeps_one_record_per_dockey_the_greatest_last_modified():
    older = _rec(55120, "2026-09-28T09:00:00.000")
    newer = _rec(55120, "2026-09-28T15:37:53.367")
    other = _rec(55121, "2026-09-28T08:45:19.220")

    deduped = dedupe_latest([older, newer, other])

    by_key = {doc_key(r): r for r in deduped}
    assert set(by_key) == {55120, 55121}
    assert by_key[55120]["LastModified"] == newer["LastModified"]


def test_dedupe_latest_string_sort_is_lexical_on_the_one_fixed_iso_format():
    # The vendor's own fixed-format ISO string sorts lexically identically to
    # chronological order (plan 08 D7) - dedupe never needs to PARSE the
    # timestamp to compare two copies of the same DocKey.
    early = _rec(1, "2026-09-28T08:00:00.000")
    late = _rec(1, "2026-09-28T23:59:59.999")
    assert dedupe_latest([late, early])[0]["LastModified"] == late["LastModified"]
    assert dedupe_latest([early, late])[0]["LastModified"] == late["LastModified"]


def test_push_order_is_last_modified_ascending():
    a = _rec(1, "2026-09-28T08:00:00.000")
    b = _rec(2, "2026-09-28T23:59:59.999")
    c = _rec(3, "2026-09-28T15:00:00.000")
    ordered = push_order([b, a, c])
    assert [doc_key(r) for r in ordered] == [1, 3, 2]


# ── source_ref (13.3 / C2) ────────────────────────────────────────────────────


def test_source_ref_delivery_order():
    assert source_ref("delivery_orders", "db1", {"DocKey": 55120}) == "db1:DO:55120"


def test_source_ref_goods_receive_note():
    assert source_ref("goods_receive_notes", "db1", {"DocKey": 77140}) == "db1:GRN:77140"


def test_source_ref_rejects_a_branches_feed_key_now():
    """AC-14-46 - the doc feed's `source_ref` no longer knows a `branches`
    feed (branch identity is the mapping engine's, see test_autocount_branch)."""
    with pytest.raises(ValueError):
        source_ref("branches", "db1", {"BranchCode": "HQ", "AccNo": "300-R009"})


# ── doc_date parsing (D19's "sent anyway, unparseable = None") ──────────────


def test_doc_date_parses_iso_date():
    assert doc_date({"DocDate": "2026-09-28"}) == date(2026, 9, 28)


def test_doc_date_parses_iso_datetime():
    assert doc_date({"DocDate": "2026-09-28T00:00:00"}) == date(2026, 9, 28)


def test_doc_date_parses_yyyymmdd():
    assert doc_date({"DocDate": "20260928"}) == date(2026, 9, 28)


def test_doc_date_is_none_for_unparseable_but_the_record_still_belongs():
    assert doc_date({"DocDate": "not-a-date"}) is None
    assert doc_date({}) is None


# ── vendor_modified_at (naive MYT -> aware UTC) ─────────────────────────────


def test_vendor_modified_at_converts_naive_myt_to_aware_utc():
    # The live-inspected sample format (issue #1354): a full naive MYT
    # timestamp, `2026-07-27T15:37:53.367`.
    record = {"LastModified": "2026-07-27T15:37:53.367"}
    converted = vendor_modified_at(record)
    assert converted.tzinfo is not None
    assert converted.astimezone(timezone.utc) == datetime(
        2026, 7, 27, 7, 37, 53, 367000, tzinfo=timezone.utc
    )


def test_vendor_modified_at_is_none_when_absent():
    assert vendor_modified_at({}) is None
