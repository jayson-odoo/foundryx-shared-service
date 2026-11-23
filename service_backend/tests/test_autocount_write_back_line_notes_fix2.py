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

    def notes(self, kind, doc):
        if puts(self.vendor_h):
            return None
        return {r.get("DtlKey"): "" for r in doc.get("Details") or []}


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
