"""Plan 73 round 6: after a PO / SPO write that landed, when both the pre-write document and the read-back came
from the AutoCount DB, a stored field the write did not intend to change but that differs is a warning
(STORED_FIELDS_CHANGED, names only); the outcome stays as it is."""

from __future__ import annotations

import logging

import pytest

from modules.autocount.write_back import payloads as P
from modules.autocount.write_back.frame import WriteFrame
from tests.test_autocount_write_back_line_notes import FD1, FD2
from tests.test_autocount_write_back_operations import World, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

CODE = "STORED_FIELDS_CHANGED"


class _Db:
    """The DB read before the first PUT answers ``before``; after it, ``after`` (None = unread)."""

    def __init__(self, h, before_header, after_header, before_fd=FD1, after_fd=FD1, after_unread=False):
        self.h, self.after_unread = h, after_unread
        self.b = (before_header, before_fd)
        self.a = (after_header, after_fd)

    def read(self, kind, doc):
        wrote = bool([c for c in self.h.vendor.calls if c.method == "PUT"])
        if wrote and self.after_unread:
            return None
        header, fd = self.a if wrote else self.b
        return {"header": dict(header), "rows": {r["DtlKey"]: {"FurtherDescription": fd} for r in doc["Details"]}}


def _run(h, monkeypatch, **kw):
    world = World(h)
    po = h.vendor.find("PO", 7001)
    po["Remark1"] = ""
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: _Db(h, **kw))
    return h.edit("PO", 7001, line_changes=[{"DtlKey": world.p_free, "Qty": 3}])


def test_remark4_mirrored_by_the_vendor_is_named(h, monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="foundryx.autocount"):
        res = _run(h, monkeypatch, before_header={"Remark4": "L"}, after_header={"Remark4": ""})
    assert res.outcome == "done", (res.outcome, res.error_code)  # the outcome stays as it is
    assert CODE in res.warnings
    line = [r.getMessage() for r in caplog.records if "stored fields changed" in r.getMessage()]
    assert line and "Remark4" in line[0] and "doc=7001" in line[0] and "L" not in line[0].split("fields=")[1].replace("Remark4", "")


def test_a_kept_rows_changed_fd_is_named(h, monkeypatch):
    res = _run(h, monkeypatch, before_header={}, after_header={}, before_fd=FD1, after_fd=FD2)
    assert res.outcome == "done" and CODE in res.warnings


def test_nothing_changed_is_no_warning(h, monkeypatch):
    res = _run(h, monkeypatch, before_header={"Remark4": "L"}, after_header={"Remark4": "L"})
    assert res.outcome == "done" and CODE not in res.warnings


def test_an_unread_readback_is_no_warning_and_no_crash(h, monkeypatch):
    res = _run(h, monkeypatch, before_header={"Remark4": "L"}, after_header={"Remark4": ""}, after_unread=True)
    assert CODE not in res.warnings and res.error_code != "INTERNAL_ERROR"


def test_an_intended_header_change_is_not_a_warning(h, monkeypatch):
    world = World(h)
    monkeypatch.setattr(WriteFrame, "_line_notes_source",
                        lambda self, company: _Db(h, {"Ref": "OLD"}, {"Ref": "NEW"}))
    res = h.edit("PO", 7001, header_changes={"Ref": "NEW"}, line_changes=[{"DtlKey": world.p_free, "Qty": 3}])
    assert CODE not in res.warnings


def test_an_operation_carries_the_warning_and_stays_done(h, monkeypatch):
    world = World(h)
    h.vendor.find("PO", 7001)["Remark1"] = ""
    monkeypatch.setattr(WriteFrame, "_line_notes_source",
                        lambda self, company: _Db(h, {"Remark4": "L"}, {"Remark4": ""}))
    res = h.run("link_row", world.params["link_row"])
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert CODE in res.warnings
