"""Lane SS-UNLINK-STRIP-SO-NOTE (RED first): an unlink that REPLACES the linked row with a new free row drops the S/O note.

Owner 26 Nov: when a PO unlink has no merge target and replaces the linked row with a new free row copied from it
(``_replace_run``), the new free row must NOT keep the S/O note Link PO added to the linked row; it keeps the rest of the
linked row's Further Description as is (byte for byte, pictures included). Only the exact note text the link wrote
(``so_link_note`` of the linked SO row, appended by ``append_note``) is removed; anything else stays. The merge path
and the source / pool rows are unchanged (their own tests).
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from modules.autocount.write_back import payloads as P
from modules.autocount.write_back.frame import WriteFrame
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

PICT = (r"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0\fswiss Arial;}}\viewkind4\uc1\pard\f0\fs20 Special finish\par"
        r"{\pict\pngblip\picw10\pich10 89504e470d0a1a0a0000000d49484452}\par" + "\r\n}")
NOTE = "**Acme {Trading}/Ref 9 S/O: 7002 DD: 01/12/2026"


# ---- the shared strip: the exact inverse of append_note -----------------------------------------------

@pytest.mark.parametrize("fd", [PICT, "", None, "Plain words", r"{\rtf1\ansi\pard x\par}"])
def test_strip_note_undoes_append_note(fd):
    linked = P.append_note(fd, NOTE)
    got = P.strip_note(linked, NOTE)
    if isinstance(fd, str) and fd.strip() and not fd.lstrip().startswith("{\\rtf"):
        assert got == P.autocount_rtf(fd)  # plain text came back in AutoCount's wrapper: the text, no note
    else:
        assert got == (fd or "")  # RTF byte for byte (pictures included); empty stays empty


def test_strip_note_leaves_an_fd_without_that_note_unchanged():
    assert P.strip_note(PICT, NOTE) == PICT
    other = P.append_note(PICT, "**Acme S/O: 9999")
    assert P.strip_note(other, NOTE) == other  # another link's note is not this one
    assert P.strip_note(None, NOTE) is None


def test_strip_note_only_removes_the_last_paragraph_never_a_note_text_in_the_middle():
    middle = P.append_note(P.append_note(PICT, NOTE), "Hand written after")
    assert P.strip_note(middle, NOTE) == middle


def test_strip_note_tolerates_autocount_trailing_padding():
    linked = P.append_note(PICT, NOTE) + "\x00"
    assert P.strip_note(linked, NOTE) == PICT + "\x00"


# ---- the unlink replace path -------------------------------------------------------------------------

@pytest.fixture
def world(h, monkeypatch):
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: None)  # legacy: FD from the GET
    h.delete_on()
    return World(h)


def _so_note(world) -> str:
    so_row = next(r for r in world.so["Details"] if r["DtlKey"] == world.so_a)
    return P.so_link_note(world.so, so_row)


def _set_fds(h, world, linked_fd: str) -> None:
    for r in h.vendor.rows("PO", 7001):
        r["FurtherDescription"] = linked_fd if r["DtlKey"] == world.p_linked else PICT


def puts(h) -> List[Any]:
    return [c for c in h.vendor.writes() if c.method == "PUT"]


def new_rows(call) -> List[Dict[str, Any]]:
    return [r for r in call.body["Details"] if r["DtlKey"] == 0]


def test_unlink_replace_new_free_row_drops_the_so_note_and_keeps_the_rest_byte_for_byte(h, world):
    _set_fds(h, world, P.append_note(PICT, _so_note(world)))
    res = h.run("unlink_row", world.params["unlink_row"], key="k-strip")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    (new,) = new_rows(puts(h)[0])
    assert not new.get("FromDocDtlKey")
    assert new["FurtherDescription"] == PICT  # the linked row's FD minus the S/O note, picture blob included
    for call in puts(h)[1:]:  # a later move PUT never puts the note back
        for r in call.body["Details"]:
            assert "S/O:" not in (r.get("FurtherDescription") or "")


def test_unlink_replace_of_a_note_only_row_leaves_an_empty_fd(h, world):
    _set_fds(h, world, P.autocount_rtf(_so_note(world)))  # the row had no FD of its own before the link
    res = h.run("unlink_row", world.params["unlink_row"], key="k-only")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    (new,) = new_rows(puts(h)[0])
    assert new["FurtherDescription"] == ""


def test_unlink_replace_keeps_an_fd_whose_last_paragraph_is_not_this_links_note(h, world):
    other = P.append_note(PICT, "**Someone else S/O: 1234")
    _set_fds(h, world, other)
    res = h.run("unlink_row", world.params["unlink_row"], key="k-other")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    (new,) = new_rows(puts(h)[0])
    assert new["FurtherDescription"] == other


def test_unlink_replace_without_a_staged_so_keeps_the_fd_as_is(h, world):
    from modules.autocount.models import AcStagedRecord

    linked = P.append_note(PICT, _so_note(world))
    _set_fds(h, world, linked)
    h.db.query(AcStagedRecord).filter(AcStagedRecord.entity_type == "sales_order").delete()
    h.db.commit()
    res = h.run("unlink_row", world.params["unlink_row"], key="k-nostage")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    (new,) = new_rows(puts(h)[0])
    assert new["FurtherDescription"] == linked  # unknown note text: nothing guessed, nothing removed
