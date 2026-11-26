"""Plan 73 r9 live fix (db3 25 Nov): AutoCount reads a NEW SO-linked row back with an EMPTY RTF note (it resets the row like
Location / UnitPrice / DeliveryDate). The restore PUT of that row must send exactly the Further Description PUT 1 SENT for it
(original + note for a whole link, autocount_rtf(note) for a split), never one rebuilt from the read-back."""
from __future__ import annotations

from decimal import Decimal

import pytest

from modules.autocount.write_back import payloads as P
from tests.test_autocount_write_back_fd_from_get import FD_LINKED, FD_OTHER, OLE, PICT, fd, puts  # noqa: F401
from tests.test_autocount_write_back_operations import World, db, h  # noqa: F401
from tests.test_autocount_write_back_split_note_only import world  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


def _new_key(h, world):
    return next(r["DtlKey"] for r in h.vendor.rows("PO", 7001) if r.get("FromSODtlKey") == world.so_a and r["DtlKey"] != world.p_linked)


def _assert_restore_equals_put1(h, world, *, expect):
    sent = puts(h)
    (new1,) = [r for r in sent[0].body["Details"] if r["DtlKey"] == 0]
    expect(new1["FurtherDescription"])
    restores = [r for c in sent[1:] for r in c.body["Details"]
                if r["DtlKey"] == _new_key(h, world) and "FurtherDescription" in r]
    assert restores, "no restore PUT carried the note"
    for r in restores:
        assert r["FurtherDescription"] == new1["FurtherDescription"]  # byte for byte what PUT 1 sent


def test_partial_link_restore_sends_exactly_the_put1_note_only_value(h, world):
    res = h.run("split_link", dict(po_doc_key=7001, po_dtl_key=world.p_free, so_doc_key=7002, so_dtl_key=world.so_a,
                                   qty=2), key="k-p")
    assert res.outcome == "done", (res.outcome, res.error_code)

    def expect(v):
        assert v.startswith(P._RTF_HEAD) and v.endswith(P._RTF_TAIL) and "S/O:" in v and world.fd[:40] not in v
    _assert_restore_equals_put1(h, world, expect=expect)


def test_whole_link_restore_sends_exactly_the_put1_original_plus_note(h, world):
    res = h.run("link_row", world.params["link_row"], key="k-w")
    assert res.outcome == "done", (res.outcome, res.error_code)
    _assert_restore_equals_put1(h, world, expect=lambda v: (
        v.startswith(world.fd[:-1]) and "S/O:" in v[len(world.fd) - 1:] and v.count(PICT) <= 1))
    # the stored row ends with the intended value, not the note-only rebuild
    stored = next(r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] == _new_key(h, world))
    assert stored["FurtherDescription"].startswith(world.fd[:-1])


def test_batch_link_restore_sends_exactly_the_put1_values(h, world):
    res = h.run("link_batch", dict(doc_key=7001, dtl_key=world.p_free, links=[
        dict(so_doc_key=7002, so_dtl_key=world.so_a, qty=2), dict(so_doc_key=7002, so_dtl_key=world.so_b, qty=2)]),
        key="k-b")
    assert res.outcome == "done", (res.outcome, res.error_code)
    first = puts(h)[0]
    sent_by_so = {r["FromDocDtlKey"]: r["FurtherDescription"] for r in first.body["Details"] if r["DtlKey"] == 0}
    for call in puts(h)[1:]:
        for r in call.body["Details"]:
            key = next((k for k in (world.so_a, world.so_b)
                        if any(x.get("FromSODtlKey") == k and x["DtlKey"] == r["DtlKey"] for x in h.vendor.rows("PO", 7001))), None)
            if key is not None and "FurtherDescription" in r:
                assert r["FurtherDescription"] == sent_by_so[key]
