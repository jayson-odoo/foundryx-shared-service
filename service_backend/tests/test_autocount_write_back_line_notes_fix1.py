"""Plan 73 fix round 1 (F1, F2, F4): the note splice, a refusal after a landed PUT, the recover path."""

from __future__ import annotations

import pytest

from modules.autocount.write_back import payloads as P

NOTE = "**ACME S/O: 389293 DD: 04/11/2026"
BODY = r"{\rtf1\ansi\deff0\pard\f0\fs20 Special\par{\pict\pngblip 8950}\par"


@pytest.mark.parametrize("tail", ["\r\n", "\x00", "  ", "\r\n\x00"])
def test_append_note_keeps_the_note_inside_the_group_and_the_trailing_bytes_after_it(tail):
    fd = BODY + "}" + tail
    out = P.append_note(fd, NOTE)
    assert out == BODY + "\\par " + NOTE + "}" + tail
    assert P.append_note(out, NOTE) == out  # idempotent


def test_append_note_a_plain_closing_brace_is_unchanged_behaviour():
    fd = BODY + "}"
    assert P.append_note(fd, NOTE) == BODY + "\\par " + NOTE + "}"


# ---- F2: a line-notes failure AFTER a PUT landed ends as a clean outcome, never INTERNAL_ERROR ---------

import json  # noqa: E402

import httpx  # noqa: E402

from modules.autocount.write_back.frame import WriteFrame  # noqa: E402
from tests.test_autocount_write_back_transfer_values import h  # noqa: E402,F401
from tests.test_autocount_write_back_vendor_caps import db  # noqa: E402,F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: E402,F401


class _KnownThenUnknown:
    """Known (empty) before the first PUT, unknown after it."""

    def __init__(self, ac):
        self.ac = ac

    def notes(self, kind, doc):
        if self.ac.put_calls:
            return None
        return {r.get("DtlKey"): "" for r in doc.get("Details") or []}


def _strip_fd_after_put(h):
    """The fake vendor read carries no FurtherDescription (like hapi) once a PUT landed."""
    ac, orig = h.ac, h.ac._on_get

    def on_get(request):
        resp = orig(request)
        if not ac.put_calls or resp.status_code != 200:
            return resp
        docs = json.loads(resp.content)
        for doc in docs if isinstance(docs, list) else [docs]:
            for r in doc.get("Details") or []:
                r.pop("FurtherDescription", None)
        return httpx.Response(200, json=docs)

    ac.read_transport = httpx.MockTransport(on_get)


def test_split_link_restore_uses_the_note_sent_in_put_1_when_the_readback_has_none(h, monkeypatch):
    _strip_fd_after_put(h)
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: _KnownThenUnknown(h.ac))
    res = h.link_split()
    assert res.error_code != "INTERNAL_ERROR" and res.outcome != "pending", (res.outcome, res.error_code)
    assert len(h.ac.put_calls) == 2  # the restore was built from the row PUT 1 sent
    assert "FurtherDescription" in h.ac.put_bodies[1]["Details"][0]


def test_split_link_restore_that_cannot_be_built_is_a_clean_mismatch(h, monkeypatch):
    def refuse(*a, **k):
        raise P.WriteRefusal(P.LINE_NOTES_UNKNOWN, P.LINE_NOTES_UNKNOWN_MESSAGE, plain=True)

    monkeypatch.setattr(P, "build_restore_transfer_row", refuse)
    res = h.link_split()
    assert (res.outcome, res.error_code) == ("mismatch", "ROW_VALUES_NOT_KEPT")
    assert len(h.ac.put_calls) == 1


# ---- F2 (operations): the same failure after a link PUT landed -------------------------------------

from tests.test_autocount_write_back_operations import OpHarness, World  # noqa: E402,F401
from tests.test_autocount_write_back_operations import h as op_h  # noqa: E402,F401


class _OpKnownThenUnknown:
    def __init__(self, vendor):
        self.vendor = vendor

    def notes(self, kind, doc):
        if self.vendor.writes():
            return None
        return {r.get("DtlKey"): "" for r in doc.get("Details") or []}


def _op_strip_fd_after_put(vendor):
    orig = vendor._handle

    def handle(request):
        resp = orig(request)
        if not vendor.writes() or resp.status_code != 200 or request.method != "GET":
            return resp
        docs = json.loads(resp.content)
        for doc in docs if isinstance(docs, list) else [docs]:
            for r in (doc.get("Details") or []) if isinstance(doc, dict) else []:
                r.pop("FurtherDescription", None)
        return httpx.Response(200, json=docs)

    vendor.transport = httpx.MockTransport(handle)


@pytest.mark.parametrize("op", ["link_row", "relink_row", "unlink_row", "spo_link_row", "spo_relink_row"])
def test_operation_restore_after_a_landed_put_never_ends_internal_error(op_h, monkeypatch, op):
    h = op_h
    world = World(h)
    if op not in world.params:
        pytest.skip(f"{op} has no World params")
    _op_strip_fd_after_put(h.vendor)
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: _OpKnownThenUnknown(h.vendor))
    res = h.run(op, world.params[op])
    assert res.error_code != "INTERNAL_ERROR", (res.outcome, res.error_code)
    assert res.outcome != "pending" or res.error_code != "INTERNAL_ERROR"
    print(op, res.outcome, res.error_code)


# ---- F4: a recover whose snapshot row has no Further Description (snapshot from before the deploy) -----

def test_recover_re_adds_the_row_and_logs_the_code_when_the_snapshot_has_no_fd(op_h, monkeypatch, caplog):
    from tests.test_autocount_write_back_operations import drop_new_row_once
    from modules.autocount.write_back.operations import OperationService

    h = op_h
    w = World(h)
    drop_new_row_once(h)
    real = OperationService._line_of

    def old_snapshot(self, snap, link, qty=None):
        snap["row"].pop(P.FURTHER_DESC, None)
        return real(self, snap, link, qty)

    monkeypatch.setattr(OperationService, "_line_of", old_snapshot)
    with caplog.at_level("WARNING", logger="foundryx.autocount"):
        res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "recovered"  # not stranded: the deleted row is back
    assert any(P.LINE_NOTES_UNKNOWN in r.getMessage() for r in caplog.records)
