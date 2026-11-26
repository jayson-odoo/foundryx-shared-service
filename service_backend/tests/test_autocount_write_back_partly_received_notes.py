"""Plan 73 r9 review: the owner's note-only rule is the PO LINK's alone. A partly received unlink / relink adds its remainder
with the original's note as before; a partly received link adds a note-only line. A doc-batch row whose links span chunks puts
the original note + S/O note on its first new line OVERALL."""
from __future__ import annotations

from decimal import Decimal

import pytest

from modules.autocount.write_back import payloads as P
from tests.test_autocount_write_back_fd_from_get import FD_LINKED, PICT, fd, puts  # noqa: F401
from tests.test_autocount_write_back_operations import World, db, h  # noqa: F401
from tests.test_autocount_write_back_split_note_only import world  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


def _received(world, key):
    return lambda kind, doc, row: Decimal(1) if row["DtlKey"] == key else Decimal(0)


def _added(h, world):
    """Rows PUT with DtlKey 0 (the remainder / new line)."""
    return [r for c in puts(h) for r in c.body["Details"] if r["DtlKey"] == 0]


def test_partly_received_unlink_adds_the_remainder_with_the_original_fd(h, world):
    res = h.run("unlink_row", world.params["unlink_row"], receipt_reader=_received(world, world.p_linked))
    assert res.outcome == "done", (res.outcome, res.error_code)
    (added,) = _added(h, world)
    assert added["FurtherDescription"] == FD_LINKED


def test_partly_received_relink_new_row_is_original_fd_plus_note(h, world):
    res = h.run("relink_row", world.params["relink_row"], receipt_reader=_received(world, world.p_linked))
    assert res.outcome == "done", (res.outcome, res.error_code)
    (added,) = _added(h, world)
    assert added["FurtherDescription"].startswith(FD_LINKED[:-1])
    assert "S/O:" in added["FurtherDescription"][len(FD_LINKED) - 1:]


def test_partly_received_link_new_line_is_note_only(h, world):
    res = h.run("link_row", world.params["link_row"], receipt_reader=_received(world, world.p_free))
    assert res.outcome == "done", (res.outcome, res.error_code)
    (added,) = _added(h, world)
    assert added["FurtherDescription"].startswith(P._RTF_HEAD) and "S/O:" in added["FurtherDescription"]
    assert world.fd[:40] not in added["FurtherDescription"]


def test_doc_batch_row_spanning_chunks_puts_the_original_note_on_the_first_new_line_overall(h):
    from tests.test_autocount_write_back_doc_batch import OP, params
    from tests.test_autocount_write_back_link_batch import Rig

    rig = Rig(h)
    w = rig.w
    row = next(r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] == w.p_other)
    row["FurtherDescription"] = PICT
    for r in h.vendor.rows("PO", 7001):
        r.setdefault("FurtherDescription", "")
    # p_other (qty 4) takes both rows of SO 7006, 2 each: a fully taken row whose two links sit in two chunks
    res = h.run(OP, params([(w.p_other, 7006, rig.s6[0], 2), (w.p_other, 7006, rig.s6[1], 2)], max_lines_per_put=1),
                key="k-span")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    link_puts = [c for c in puts(h) if any(r["DtlKey"] == 0 for r in c.body["Details"])]
    assert len(link_puts) == 2
    first = next(r for r in link_puts[0].body["Details"] if r["DtlKey"] == 0)
    second = next(r for r in link_puts[1].body["Details"] if r["DtlKey"] == 0)
    assert first["FurtherDescription"].startswith(PICT[:-1]) and "S/O:" in first["FurtherDescription"][len(PICT) - 1:]
    assert PICT[:40] not in second["FurtherDescription"] and "S/O:" in second["FurtherDescription"]
