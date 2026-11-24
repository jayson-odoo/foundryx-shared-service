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
    assert res.outcome == "done" and CODE in res.warnings, (res.outcome, res.error_code)


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


# ---- the plan 55 service path: whole link (single PUT) and partial link (PUT 1 link + PUT 2 restore) ----------

from decimal import Decimal  # noqa: E402

from app.models import DEFAULT_TENANT_ID  # noqa: E402

LINKED = 12011

from tests.test_autocount_write_back_transfer_values import h as sv  # noqa: E402,F401
from tests.test_autocount_write_back_vendor_caps import db as _vcdb  # noqa: E402,F401


class _SvcDb:
    def __init__(self, ac, before_header, after_header):
        self.ac, self.b, self.a = ac, before_header, after_header

    def read(self, kind, doc):
        wrote = bool(self.ac.put_calls)
        return {"header": dict(self.a if wrote else self.b),
                "rows": {r["DtlKey"]: {"FurtherDescription": FD1} for r in doc["Details"]}}


def _link(sv, monkeypatch, before, after, qty):
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: _SvcDb(sv.ac, before, after))
    return sv.link_split(qty=Decimal(qty))


def test_partial_link_final_read_with_remark4_changed_warns(sv, monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="foundryx.autocount"):
        res = _link(sv, monkeypatch, {"Remark4": "L"}, {"Remark4": ""}, 10)
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert CODE in res.warnings
    assert any("Remark4" in r.getMessage() and "stored fields changed" in r.getMessage() for r in caplog.records)


def test_partial_link_with_nothing_changed_has_no_warning(sv, monkeypatch):
    res = _link(sv, monkeypatch, {"Remark4": "L"}, {"Remark4": "L"}, 10)
    assert res.outcome == "done" and CODE not in res.warnings


def test_single_put_relocate_hook_warns_and_stays_quiet(sv, monkeypatch):
    from modules.autocount.write_back.reader import AutoCountDocReader

    monkeypatch.setattr(AutoCountDocReader, "location_codes", lambda self: {"brw-am": "BRW-AM"})
    for after, expect in (({"Remark4": ""}, True), ({"Remark4": "L"}, False)):
        sv.ac.put_calls.clear()
        sv.ac.server_row(LINKED)["Location"] = "HQ"
        monkeypatch.setattr(WriteFrame, "_line_notes_source",
                            lambda self, company, a=after: _SvcDb(sv.ac, {"Remark4": "L"}, a))
        res = sv.service().relocate(tenant_id=DEFAULT_TENANT_ID, company_id=sv.company.id, po_doc_key=12008,
                                    po_dtl_key=LINKED, location="BRW-AM")
        assert res.outcome == "done", (res.outcome, res.error_code)
        assert (CODE in res.warnings) is expect
