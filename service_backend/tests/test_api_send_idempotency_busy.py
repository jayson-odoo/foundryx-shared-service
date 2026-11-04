"""RED tests (PR 203 round 2): a stored send keeps its Idempotency-Key
reservation, however the request ends afterwards.

``POST /api/v1/omnichannel/messages`` commits the QUEUED message row and then
runs more steps. An error after that commit (a 55P03 busy answer, a broker
error) must NOT release the reservation, or a same-key retry sends a second
message. An error BEFORE the row is committed still releases it.
"""
from __future__ import annotations

import os

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from tests.test_omnichannel_api_gateway import (
    _default_workspace_id,
    _mint,
    _seed_channel,
    _seed_open_contact,
)

URL = "/api/v1/omnichannel/messages"


class _Busy(Exception):
    pgcode = "55P03"
    sqlstate = "55P03"


def _busy():
    return OperationalError("UPDATE t SET v = 1", None, _Busy("lock timeout"))


def _setup(client, session_factory, phone):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id=f"pn-{phone[-6:]}")
    cid = _seed_open_contact(session_factory, ws, phone=phone, open_window=True)
    key = _mint(client, ws).json()["fullKey"]
    return {"Authorization": f"Bearer {key}", "Idempotency-Key": f"idem-{phone}"}, cid


def _messages(session_factory, contact_id):
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    try:
        rows = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact_id).all()
        return [r.id for r in rows]
    finally:
        db.close()


def _payload(phone):
    return {"to": phone, "type": "text", "text": {"body": "once"}}


def _no_raise_client(client):
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def _boom_after_commit(monkeypatch, exc_factory):
    from modules.omnichannel.services import message_service

    def boom(*args, **kwargs):
        raise exc_factory()

    monkeypatch.setattr(message_service, "run_send", boom)


@pytest.mark.parametrize(
    "exc_factory,status,code",
    [(_busy, 503, "busy_try_again"), (lambda: RuntimeError("broker down"), 500, None)],
    ids=["busy-503", "generic-500"],
)
def test_error_after_the_message_commit_keeps_the_reservation(
    client, session_factory, monkeypatch, exc_factory, status, code
):
    phone = "+60700800801" if status == 503 else "+60700800802"
    headers, cid = _setup(client, session_factory, phone)
    http = _no_raise_client(client)
    with monkeypatch.context() as m:
        _boom_after_commit(m, exc_factory)
        first = http.post(URL, json=_payload(phone), headers=headers)
    assert first.status_code == status, first.text
    if code:
        assert first.json()["error"]["code"] == code
    stored = _messages(session_factory, cid)
    assert len(stored) == 1, "the message row was committed before the error"

    retry = http.post(URL, json=_payload(phone), headers=headers)
    assert retry.status_code == 202, retry.text
    body = retry.json()
    assert body["idempotencyReplay"] is True
    assert body["id"] == stored[0]
    assert len(_messages(session_factory, cid)) == 1


def test_error_before_the_message_commit_still_releases_the_reservation(
    client, session_factory, monkeypatch
):
    phone = "+60700800803"
    headers, cid = _setup(client, session_factory, phone)
    http = _no_raise_client(client)
    from modules.omnichannel.services.public_gateway_service import PublicGatewayService

    real = PublicGatewayService._workspace_channel

    def busy_channel(self, *a, **k):
        raise _busy()

    with monkeypatch.context() as m:
        m.setattr(PublicGatewayService, "_workspace_channel", busy_channel)
        first = http.post(URL, json=_payload(phone), headers=headers)
    assert first.status_code == 503, first.text
    assert _messages(session_factory, cid) == []
    assert PublicGatewayService._workspace_channel is real

    retry = http.post(URL, json=_payload(phone), headers=headers)
    assert retry.status_code == 202, retry.text
    assert retry.json()["idempotencyReplay"] is False
    assert len(_messages(session_factory, cid)) == 1


def test_compose_backend_env_passes_the_api_lock_limits_through():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "docker-compose.yml")
    with open(path) as f:
        compose = yaml.safe_load(f)
    env = compose["x-backend-env"]
    for name in ("API_DB_LOCK_TIMEOUT_SECONDS", "API_DB_LONG_LOCK_TIMEOUT_SECONDS"):
        assert name in env, f"{name} must be passed through the backend env allow-list"


# ---- round 3: the stored id is recorded at commit, not after the refresh ----


def _fail_message_refresh(monkeypatch):
    """Every ``refresh`` of a message row raises (the post-commit refresh)."""
    from sqlalchemy.orm import Session

    from modules.omnichannel.models import ConversationMessage

    real = Session.refresh

    def refresh(self, instance, *a, **k):
        if isinstance(instance, ConversationMessage):
            raise RuntimeError("refresh failed after commit")
        return real(self, instance, *a, **k)

    monkeypatch.setattr(Session, "refresh", refresh)


def test_json_send_refresh_failure_after_commit_still_replays(client, session_factory, monkeypatch):
    phone = "+60700800811"
    headers, cid = _setup(client, session_factory, phone)
    http = _no_raise_client(client)
    with monkeypatch.context() as m:
        _fail_message_refresh(m)
        first = http.post(URL, json=_payload(phone), headers=headers)
    assert first.status_code == 500, first.text
    stored = _messages(session_factory, cid)
    assert len(stored) == 1
    retry = http.post(URL, json=_payload(phone), headers=headers)
    assert retry.status_code == 202, retry.text
    assert retry.json()["idempotencyReplay"] is True
    assert retry.json()["id"] == stored[0]
    assert len(_messages(session_factory, cid)) == 1


def test_multipart_send_refresh_failure_after_commit_still_replays(client, session_factory, monkeypatch):
    from tests.test_omnichannel_send_route_limits import _install, _multipart
    from tests.test_omnichannel_send_route_limits import _setup as _media_setup

    phone = "+60700800812"
    headers, cid, _ch = _media_setup(client, session_factory, phone=phone, token="tkn-live-r3")
    _install(monkeypatch)
    headers = {**headers, "Idempotency-Key": "idem-multipart-r3"}
    http = _no_raise_client(client)
    with monkeypatch.context() as m:
        _fail_message_refresh(m)
        first = http.post(URL, headers=headers, **_multipart(phone))
    assert first.status_code == 500, first.text
    stored = _messages(session_factory, cid)
    assert len(stored) == 1
    retry = http.post(URL, headers=headers, **_multipart(phone))
    assert retry.status_code == 202, retry.text
    assert retry.json()["idempotencyReplay"] is True
    assert retry.json()["id"] == stored[0]
    assert len(_messages(session_factory, cid)) == 1
