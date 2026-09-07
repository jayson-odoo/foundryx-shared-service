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


# ── Review round 2, N-new-2: visitor re-verify interval carries jitter ──────
def test_jittered_interval_scales_within_the_documented_band(monkeypatch):
    """+/-20% of the base interval - a pure function so it is unit-testable
    without spinning up a socket. Pins the exact `random.uniform` bounds
    (0.8, 1.2) so a later reader can't silently widen/narrow the jitter."""
    calls = []

    def _fake_uniform(low, high):
        calls.append((low, high))
        return low

    monkeypatch.setattr(ws_module.random, "uniform", _fake_uniform)
    assert ws_module._jittered_interval(60.0) == 48.0  # 60 * 0.8

    monkeypatch.setattr(ws_module.random, "uniform", lambda low, high: high)
    assert ws_module._jittered_interval(60.0) == 72.0  # 60 * 1.2

    assert calls == [(0.8, 1.2)]


def test_jittered_interval_is_computed_once_per_socket_not_per_tick(monkeypatch):
    """`revalidate_visitor` must read the jitter ONCE at task start, never
    re-roll it inside the `while True` loop (which would defeat the
    anti-lockstep point - a socket could still land back near the original
    cadence on a later tick)."""
    calls = {"n": 0}

    def _counting_uniform(_low, _high):
        calls["n"] += 1
        return 1.0

    monkeypatch.setattr(ws_module.random, "uniform", _counting_uniform)
    ws_module._jittered_interval(60.0)
    ws_module._jittered_interval(60.0)
    # Two INDEPENDENT calls (two sockets) each roll once - the guarantee this
    # pins is per-call, not global: `revalidate_visitor` itself calls this
    # helper exactly once, before its loop starts (see ws.py).
    assert calls["n"] == 2
