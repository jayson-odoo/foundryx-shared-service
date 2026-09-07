"""Plan 34 (A7b) Slice S4 - `GET /public/omnichannel/webchat/{widgetKey}/
frame-policy`, the panel document's `Content-Security-Policy: frame-ancestors`
source (AC-WEB-47, D-A7B-11). Mirrors `test_omnichannel_embed.py`'s
`frame-policy` suite (plan-11H) exactly: unknown/dead widget key -> an empty
list, never a distinguishing status code (R7 - no enumeration signal), and a
read-only lookup (zero DB writes either way).
"""
from tests.test_omnichannel_channels_webchat import _auth, _connect

FRAME_POLICY_URL = "/public/omnichannel/webchat/{key}/frame-policy"
ORIGIN = "https://shop.acme.com"


def _new_channel(client, *, allowed_origins=None):
    h = _auth(client)
    body = _connect(client, h, allowed_origins=allowed_origins or [ORIGIN]).json()
    return body["widgetKey"], body["id"]


def test_frame_policy_returns_the_channels_allowed_origins(client):
    widget_key, _ = _new_channel(client, allowed_origins=[ORIGIN, "https://shop2.acme.com"])
    res = client.get(FRAME_POLICY_URL.format(key=widget_key))
    assert res.status_code == 200
    assert set(res.json()["allowedOrigins"]) == {ORIGIN, "https://shop2.acme.com"}


def test_frame_policy_unknown_widget_key_is_empty(client, session_factory):
    from modules.omnichannel.services.webchat_visitor_service import origins_for_frame_policy

    db = session_factory()
    try:
        assert origins_for_frame_policy(db, "does-not-exist") == []
    finally:
        db.close()


def test_frame_policy_unknown_widget_key_http_is_empty(client):
    res = client.get(FRAME_POLICY_URL.format(key="does-not-exist"))
    assert res.status_code == 200
    assert res.json()["allowedOrigins"] == []


def test_frame_policy_trashed_channel_is_empty(client, session_factory):
    from modules.omnichannel.models import Channel

    widget_key, channel_id = _new_channel(client)
    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    channel.is_trashed = True
    db.commit()
    db.close()

    res = client.get(FRAME_POLICY_URL.format(key=widget_key))
    assert res.status_code == 200
    assert res.json()["allowedOrigins"] == []


def test_frame_policy_inactive_channel_is_empty(client, session_factory):
    from modules.omnichannel.models import Channel

    widget_key, channel_id = _new_channel(client)
    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    channel.is_active = False
    db.commit()
    db.close()

    res = client.get(FRAME_POLICY_URL.format(key=widget_key))
    assert res.status_code == 200
    assert res.json()["allowedOrigins"] == []


def test_frame_policy_is_read_only(client, session_factory):
    """Zero DB writes either way (D-A7B-7-style hygiene) - a page view (or a
    middleware probe) never mutates the channel row."""
    from modules.omnichannel.models import Channel

    widget_key, channel_id = _new_channel(client)
    db = session_factory()
    before = db.query(Channel).filter(Channel.id == channel_id).first()
    before_config = dict(before.widget_config_json or {})
    db.close()

    for _ in range(3):
        client.get(FRAME_POLICY_URL.format(key=widget_key))

    db = session_factory()
    after = db.query(Channel).filter(Channel.id == channel_id).first()
    assert dict(after.widget_config_json or {}) == before_config
    db.close()
