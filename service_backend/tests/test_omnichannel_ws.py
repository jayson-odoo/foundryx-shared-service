"""WebSocket realtime tests - plan 05 Phase B-5.

Auth-on-connect (bad token / missing perm → 4403 close), and the pub/sub
relay: a realtime.publish on the workspace room reaches a connected socket.
Sync publisher + async WS consumer share one fakeredis FakeServer.
"""
import json

import fakeredis
import fakeredis.aioredis
import pytest
from starlette.websockets import WebSocketDisconnect

from modules.omnichannel.routers import ws as ws_module
from modules.omnichannel.services import realtime
from tests.test_omnichannel_conversations import _seed_thread, _token


@pytest.fixture(autouse=True)
def _shared_fake_redis(session_factory):
    server = fakeredis.FakeServer()
    realtime.set_client(fakeredis.FakeRedis(server=server, decode_responses=True))
    ws_module.set_async_redis(
        fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    )
    ws_module.set_session_factory(session_factory)
    yield
    realtime.set_client(None)
    ws_module.set_async_redis(None)
    ws_module.set_session_factory(ws_module.SessionLocal)


def _default_ws_id(session_factory):
    from modules.omnichannel.models import Workspace

    db = session_factory()
    wid = db.query(Workspace).filter(Workspace.is_default.is_(True)).first().id
    db.close()
    return wid


def test_ws_rejects_bad_token(client, session_factory):
    wid = _default_ws_id(session_factory)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/omnichannel/ws?workspaceId={wid}&token=garbage"):
            pass
    assert exc.value.code == 4403


def test_ws_rejects_unknown_workspace(client, session_factory):
    token = _token(client)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/omnichannel/ws?workspaceId=nope&token={token}"):
            pass
    assert exc.value.code == 4403


def test_ws_relays_published_events(client, session_factory):
    # Admin holds workspaces.manage → member check bypassed by design.
    _seed_thread(session_factory, messages=[{}])
    wid = _default_ws_id(session_factory)
    token = _token(client)

    with client.websocket_connect(f"/omnichannel/ws?workspaceId={wid}&token={token}") as sock:
        realtime.publish(wid, {"type": "message.status", "messageId": "m1"})
        event = json.loads(sock.receive_text())
        assert event == {"type": "message.status", "messageId": "m1"}
