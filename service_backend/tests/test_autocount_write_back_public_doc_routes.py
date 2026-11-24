"""Plan 73: the internal legacy / unread markers never reach an answer ``document`` or a stored action row."""
from __future__ import annotations

import json

import pytest

from modules.autocount.models import AcWriteAction
from modules.autocount.write_back.frame import WriteFrame
from tests.test_autocount_write_back_po_link_detail import LINK, _whole, far, gw  # noqa: F401
from tests.test_autocount_write_back_operations import World, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

MARKS = ("_dbLegacy", "_dbUnread")


class _Echo:
    def read(self, kind, doc):
        return {"header": {}, "rows": {r["DtlKey"]: {"FurtherDescription": r.get("FurtherDescription", "")}
                                       for r in doc.get("Details") or []}}


def _no_marker(text: str) -> None:
    assert not any(m in text for m in MARKS), text[:200]


@pytest.mark.parametrize("mode", ["legacy", "db"])
def test_po_links_answer_and_stored_rows_carry_no_marker(client, gw, far, monkeypatch, mode):
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: None if mode == "legacy" else _Echo())
    r = client.post(LINK, json=_whole(far), headers=gw.hdr())
    assert r.status_code == 200, r.text
    _no_marker(json.dumps(r.json()["document"]))
    gw.db.expire_all()
    for action in gw.db.query(AcWriteAction).all():
        _no_marker(json.dumps([action.before_json, action.after_json], default=str))
