"""A send the provider accepted without a usable message id stores NO id (NULL).

The provider id column is globally unique, so an empty string stored for one
accepted send would make the next one's commit fail. Black box over ``run_send``
with a fake adapter. Every test seeds its own channel / contact / rows.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import ConversationMessage
from modules.omnichannel.services.send_runner import run_send
from tests.test_omnichannel_meta_rate_limit_retry import _env, _live_creds  # noqa: F401
from tests.test_omnichannel_outbound_event import _deliveries, _rig


class FakeAdapter:
    def __init__(self, ids, on_send=None):
        self.ids = list(ids)
        self.on_send = on_send

    def send(self, *a, **k):
        if self.on_send:
            self.on_send()
        return {"external_message_id": self.ids.pop(0)}


def _use(monkeypatch, adapter):
    monkeypatch.setattr(
        "modules.omnichannel.services.send_runner.get_adapter", lambda *a, **k: adapter
    )


def _queue(session_factory, r, n):
    db = session_factory()
    try:
        rows = [
            ConversationMessage(
                tenant_id=DEFAULT_TENANT_ID, contact_id=r["cid"], channel_id=r["channel_id"],
                sender_type="AGENT", message_type="TEXT", body=f"m{i}", delivery_status="QUEUED",
            )
            for i in range(n)
        ]
        db.add_all(rows)
        db.commit()
        return [x.id for x in rows]
    finally:
        db.close()


def _state(session_factory, mid):
    db = session_factory()
    try:
        row = db.query(ConversationMessage).filter(ConversationMessage.id == mid).one()
        return row.delivery_status, row.external_message_id
    finally:
        db.close()


def _rig_rows(client, session_factory, phone, n):
    r = _rig(client, session_factory, phone, events=())
    _live_creds(session_factory, r["channel_id"])
    return _queue(session_factory, r, n)


def _run(session_factory, mid):
    db = session_factory()
    try:
        return run_send(db, mid)
    finally:
        db.close()


def test_two_sends_with_empty_provider_id_both_sent_with_null(client, session_factory, monkeypatch):
    ids = _rig_rows(client, session_factory, "60120000101", 2)
    _use(monkeypatch, FakeAdapter(["", ""]))
    for mid in ids:
        assert _run(session_factory, mid) == "SENT"
    for mid in ids:
        assert _state(session_factory, mid) == ("SENT", None)


def test_fallback_record_stores_null_for_empty_id(client, session_factory, monkeypatch):
    ids = _rig_rows(client, session_factory, "60120000102", 2)
    for mid in ids:
        db = session_factory()
        try:
            armed = {"on": False}
            _use(monkeypatch, FakeAdapter([""], on_send=lambda: armed.update(on=True)))
            real_commit = db.commit

            def commit():
                if armed["on"]:
                    armed["on"] = False
                    raise RuntimeError("forced commit failure")
                return real_commit()

            monkeypatch.setattr(db, "commit", commit)
            assert run_send(db, mid) == "SENT"
        finally:
            db.close()
    for mid in ids:
        assert _state(session_factory, mid) == ("SENT", None)


def test_real_id_stored_as_is_and_duplicate_real_id_still_unique(client, session_factory, monkeypatch):
    ids = _rig_rows(client, session_factory, "60120000103", 2)
    _use(monkeypatch, FakeAdapter(["wamid.X", "wamid.X"]))
    assert _run(session_factory, ids[0]) == "SENT"
    assert _state(session_factory, ids[0]) == ("SENT", "wamid.X")
    db = session_factory()
    try:
        db.query(ConversationMessage).filter(ConversationMessage.id == ids[1]).one().external_message_id = "wamid.X"
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_sent_record_fallback_stores_null_for_empty_id_directly(client, session_factory):
    from modules.omnichannel.services.send_runner import _record_sent_by_id

    ids = _rig_rows(client, session_factory, "60120000104", 2)
    for mid in ids:
        db = session_factory()
        try:
            db.query(ConversationMessage).filter(ConversationMessage.id == mid).one().delivery_status = "SENDING"
            db.commit()
            assert _record_sent_by_id(db, mid, "") == "SENT"
        finally:
            db.close()
    for mid in ids:
        assert _state(session_factory, mid) == ("SENT", None)


def test_sent_status_event_for_empty_id_carries_null_external_id(client, session_factory, monkeypatch):
    r = _rig(client, session_factory, "60120000105", events=("message.status",))
    _live_creds(session_factory, r["channel_id"])
    (mid,) = _queue(session_factory, r, 1)
    _use(monkeypatch, FakeAdapter([""]))
    assert _run(session_factory, mid) == "SENT"
    rows = [x for x in _deliveries(session_factory, "message.status") if x["payload"]["data"]["messageId"] == mid]
    assert [x["event_id"] for x in rows] == [f"{mid}:SENT"]
    data = rows[0]["payload"]["data"]
    assert "externalMessageId" in data and data["externalMessageId"] is None
