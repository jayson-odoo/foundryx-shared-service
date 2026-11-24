"""Plan 73 fix round 2: a refused / timed-out PUT whose re-read has no line notes is still "unchanged" (G1);
the resume of a parked split carries the Further Description on its restore PUT (G2)."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from modules.autocount.write_back import payloads as P
from modules.autocount.write_back.frame import WriteFrame
from tests.test_autocount_write_back_po_link_stuck import (  # noqa: F401
    EDIT,
    SO_DAY,
    SUB,
    TIMEOUT_TEXT,
    _batch,
    _no_reread_wait,
    _parked_split,
    link_puts,
    puts,
    resume,
    split,
    tied,
    w,
)
from tests.test_autocount_write_back_operations import db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


class _UnknownAfterPut:
    """Line notes known (empty) until the first PUT call, unknown after it."""

    def __init__(self, vendor):
        self.vendor = vendor

    def read(self, kind, doc):
        if puts(self.vendor_h):
            return None
        return {"header": {}, "rows": {r.get("DtlKey"): {"FurtherDescription": ""} for r in doc.get("Details") or []}}


def _notes_vanish_after_put(h, monkeypatch):
    src = _UnknownAfterPut(h.vendor)
    src.vendor_h = h
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: src)
    orig = h.vendor._handle

    def handle(request):
        resp = orig(request)
        if request.method != "GET" or not puts(h) or resp.status_code != 200:
            return resp
        docs = json.loads(resp.content)
        for doc in docs if isinstance(docs, list) else [docs]:
            for r in (doc.get("Details") or []) if isinstance(doc, dict) else []:
                r.pop("FurtherDescription", None)
        return httpx.Response(200, json=docs)

    h.vendor.transport = httpx.MockTransport(handle)


def test_refusal_readback_missing_line_notes_is_still_unchanged(h, w, monkeypatch):
    original = h.vendor._route

    def route(method, leaf, call):
        if method == "PUT":
            return httpx.Response(500, json={"ExceptionMessage": "Not allowed.",
                                             "ExceptionType": "AutoCount.Invoicing.SomeBusinessException"})
        return original(method, leaf, call)

    h.vendor._route = route
    _notes_vanish_after_put(h, monkeypatch)
    res = _batch(h, w, "g1-ref")
    assert (res.outcome, res.error_code) == ("vendor_error", "VENDOR_REFUSED"), (res.outcome, res.error_code)


def test_timeout_readback_missing_line_notes_is_still_unchanged(h, w, monkeypatch):
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT)
    _notes_vanish_after_put(h, monkeypatch)
    res = _batch(h, w, "g1-to")
    assert (res.outcome, res.error_code) == ("vendor_error", "VENDOR_TIMEOUT"), (res.outcome, res.error_code)


# ---- G2: the resume of a parked split keeps the Further Description on its restore PUT ---------------

PICT = "89504e470d0a1a0a0000000d49484452"
FD = (r"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0\fswiss Arial;}}\viewkind4\uc1\pard\f0\fs20 Special finish\par"
      r"{\pict\pngblip\picw10\pich10 " + PICT + "}\\par\r\n}")


class _EchoFd:
    """The DB read of a vendor whose rows hold the stored FD: each row's own FurtherDescription, empty if none."""

    def read(self, kind, doc):
        return {"header": {}, "rows": {r.get("DtlKey"): {"FurtherDescription": r.get("FurtherDescription", "")}
                                       for r in doc.get("Details") or []}}


def _po_rows_carry_fd(h, monkeypatch):
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: _EchoFd())
    for r in h.vendor.rows("PO", 7001):
        r["FurtherDescription"] = FD


def _sent_note(h):
    (call,) = link_puts(h)
    new = next(r for r in call.body["Details"] if not r.get("DtlKey"))
    return new["FurtherDescription"]


def test_resume_split_restore_carries_further_description(h, w, monkeypatch):
    _po_rows_carry_fd(h, monkeypatch)
    res = _parked_split(h, w)
    sent_fd = _sent_note(h)
    assert sent_fd.startswith(FD[:-1]) and PICT in sent_fd and sent_fd != FD  # the S/O note is appended after the FD
    out = resume(h, res)
    assert (out.outcome, out.error_code) == ("done", None), (out.outcome, out.error_code, out.message)
    restore = puts(h)[-1].body["Details"]
    assert puts(h)[-1] is not link_puts(h)[0]
    (row,) = restore
    assert row["FurtherDescription"] == sent_fd and PICT in row["FurtherDescription"]
    assert row["FurtherDescription"].count(PICT) == 1


class _ReadNone:
    def read(self, kind, doc):
        return None


def test_resume_split_restore_notes_unknown_sends_no_put(h, w, monkeypatch):
    _po_rows_carry_fd(h, monkeypatch)
    res = _parked_split(h, w)
    for r in h.vendor.rows("PO", 7001):  # the notes can no longer be read
        r.pop("FurtherDescription", None)
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: _ReadNone())
    before = len(puts(h))
    out = resume(h, res)
    assert (out.outcome, out.error_code) == ("needs_attention", "RESTORE_NOT_LANDED"), (out.outcome, out.error_code)
    assert len(puts(h)) == before
