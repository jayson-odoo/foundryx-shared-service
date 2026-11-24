"""Plan 73 fix round 4: the unread marker never leaks into a staged record or an answer document (the contract 57
document shape is unchanged), while the refusal for an unread database still works."""

from __future__ import annotations

import json

import pytest

from modules.autocount.models import AcStagedRecord
from modules.autocount.write_back import payloads as P
from modules.autocount.write_back.frame import WriteFrame
from tests.test_autocount_write_back_gateway import _hdr
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw, gw  # noqa: F401
from tests.test_autocount_write_back_gateway_read import KEYS, _get, _seed
from tests.test_autocount_write_back_operations import World, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

MARK = "_dbUnread"


class _ReadNone:
    def read(self, kind, doc):
        return None


class _KnownThenUnread:
    def __init__(self, h):
        self.h = h

    def read(self, kind, doc):
        if [c for c in self.h.vendor.calls if c.method == "PUT"]:
            return None
        return {"header": {}, "rows": {r["DtlKey"]: {"FurtherDescription": ""} for r in doc["Details"]}}


def test_public_doc_strips_the_marker_and_copies():
    doc = {"DocKey": 1, MARK: True, "Details": [{"DtlKey": 2}]}
    out = P.public_doc(doc)
    assert MARK not in out and out["Details"] == doc["Details"] and MARK in doc
    clean = {"DocKey": 1}
    assert P.public_doc(clean) is clean and P.public_doc(None) is None


def test_get_po_answers_no_marker_when_the_db_is_unread(client, gw, monkeypatch):
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: _ReadNone())
    _seed(gw, "PO")
    r = _get(client, gw, "purchase-orders", KEYS["PO"])
    assert r.status_code == 200, r.text
    assert MARK not in r.json()["document"] and MARK not in r.text


def test_staged_record_and_answer_carry_no_marker_when_the_readback_is_unread(h, monkeypatch):
    world = World(h)
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: _KnownThenUnread(h))
    res = h.edit("PO", 7001, line_changes=[{"DtlKey": world.p_free, "Qty": 3}])
    assert res.outcome == "done", (res.outcome, res.error_code)
    h.db.expire_all()
    staged = h.db.query(AcStagedRecord).filter(AcStagedRecord.entity_type == "purchase_order").all()
    assert staged and all(MARK not in json.dumps(s.raw_json, default=str) for s in staged)


def test_the_refusal_for_an_unread_db_still_works(h, monkeypatch):
    World(h)
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: _ReadNone())
    res = h.edit("PO", 7001, header_changes={"Ref": "N"})
    assert (res.outcome, res.error_code) == ("refused", "AUTOCOUNT_DB_UNREAD")
