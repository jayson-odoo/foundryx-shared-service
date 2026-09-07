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


# ── Review round 1, S8: cached + throttled (enumeration only) ───────────────
def test_frame_policy_is_cached_for_a_live_widget_key(client, session_factory):
    """The Next.js middleware calls this on EVERY panel request and each miss
    costs three DB queries. Second call inside the TTL is served from the
    cache - which is also why an origin edit can take up to 60s to reach the
    `frame-ancestors` header (accepted staleness, documented on the route)."""
    from modules.omnichannel.models import Channel

    widget_key, channel_id = _new_channel(client)
    assert client.get(FRAME_POLICY_URL.format(key=widget_key)).json()["allowedOrigins"] == [ORIGIN]

    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    cfg = dict(channel.widget_config_json or {})
    cfg["allowedOrigins"] = ["https://changed.example"]
    channel.widget_config_json = cfg
    db.commit()
    db.close()

    cached = client.get(FRAME_POLICY_URL.format(key=widget_key))
    assert cached.json()["allowedOrigins"] == [ORIGIN]

    from modules.omnichannel.services.webchat_visitor_service import reset_origins_cache

    reset_origins_cache()
    fresh = client.get(FRAME_POLICY_URL.format(key=widget_key))
    assert fresh.json()["allowedOrigins"] == ["https://changed.example"]


def test_frame_policy_spends_a_throttle_token_only_on_an_unresolved_key(
    client, session_factory
):
    """Legitimate traffic all arrives from the Next.js server's ONE IP, so
    counting it would let a busy deployment throttle its own panels off the
    air. Only a lookup that went to the database and resolved NOTHING - the
    shape of key enumeration - spends a token."""
    from app.models.auth_throttle import THROTTLE_SCOPE_WEBCHAT, AuthThrottle

    def _fails():
        db = session_factory()
        try:
            rows = (
                db.query(AuthThrottle)
                .filter(AuthThrottle.scope == THROTTLE_SCOPE_WEBCHAT)
                .all()
            )
            return sum(r.fail_count for r in rows)
        finally:
            db.close()

    widget_key, _ = _new_channel(client)
    before = _fails()
    for _ in range(3):
        client.get(FRAME_POLICY_URL.format(key=widget_key))
    assert _fails() == before

    client.get(FRAME_POLICY_URL.format(key="wk_enumeration_probe_0000000000"))
    assert _fails() == before + 1
