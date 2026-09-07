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


# ── Review round 2, B4: NO throttle on this route at all ────────────────────
def test_frame_policy_records_no_throttle_rows_ever(client, session_factory):
    """Review round 1 (S8) put this route on the webchat IP throttle bucket,
    reasoning that only an unresolved lookup would spend a token. Review
    round 2 (B4) found the flaw: the route's ONLY caller is the Next.js
    middleware, so every legitimate request AND every attacker probe share
    ONE IP - an outsider enumerating widget keys could trip the shared
    counter and put every tenant's panel behind `frame-ancestors 'none'` at
    once. The throttle is removed from this route entirely; nothing it does,
    resolved or not, should ever write an `auth_throttle` row for the
    webchat scope."""
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
    assert _fails() == before


def test_frame_policy_601_unknown_key_probes_never_break_a_known_good_key(
    client, session_factory
):
    """The exact B4 scenario: an outsider hammering distinct unknown widget
    keys must never be able to force `frame-ancestors 'none'` onto a
    DIFFERENT, real tenant's panel. 601 distinct misses (one past the OLD
    600/5min IP throttle ceiling from S7) all return 200, and a known-good
    key served in between - and again after - still returns its own
    origins."""
    known_key, _ = _new_channel(client, allowed_origins=[ORIGIN])

    mid_probe = client.get(FRAME_POLICY_URL.format(key="wk_probe_mid_000000000000"))
    assert mid_probe.status_code == 200
    assert mid_probe.json()["allowedOrigins"] == []

    for i in range(601):
        res = client.get(FRAME_POLICY_URL.format(key=f"wk_enum_probe_{i:04d}_00000000"))
        assert res.status_code == 200
        assert res.json()["allowedOrigins"] == []

    good = client.get(FRAME_POLICY_URL.format(key=known_key))
    assert good.status_code == 200
    assert good.json()["allowedOrigins"] == [ORIGIN]


# ── Review round 2, S-new-1: bounded LRU + split TTL + cache-before-session ──
def test_origins_cache_enforces_a_hard_cap_with_lru_eviction(client, monkeypatch):
    """Unbounded, the cache was every distinct widget key ever probed -
    including keys that never resolved. A hard cap with oldest-evicted keeps
    memory bounded regardless of how many distinct keys a probe tries."""
    from modules.omnichannel.services import webchat_visitor_service as svc

    svc.reset_origins_cache()
    monkeypatch.setattr(svc, "_ORIGINS_CACHE_MAX_ENTRIES", 5)
    try:
        for i in range(6):
            client.get(FRAME_POLICY_URL.format(key=f"wk_cap_probe_{i}"))

        assert len(svc._origins_cache) == 5
        assert "wk_cap_probe_0" not in svc._origins_cache  # oldest, evicted
        assert "wk_cap_probe_5" in svc._origins_cache  # newest, kept
    finally:
        svc.reset_origins_cache()


def test_negative_cache_entry_expires_in_15_seconds_not_60(client, session_factory, monkeypatch):
    """An unresolved (enumeration-shaped) lookup gets a SHORTER TTL than a
    resolved one: 15s, not the 60s a real widget key's positive answer gets.
    A channel created after the first (negative) probe stays invisible while
    the negative entry is still warm, and becomes visible the moment it
    expires - proving the two TTLs are actually different, not just labelled
    differently."""
    from modules.omnichannel.models import Channel
    from modules.omnichannel.services import webchat_visitor_service as svc

    svc.reset_origins_cache()
    clock = {"t": 0.0}
    monkeypatch.setattr(svc, "_monotonic", lambda: clock["t"])
    widget_key = "wk_negative_ttl_probe_000000"
    try:
        db = session_factory()
        try:
            origins, unresolved = svc.resolve_frame_policy(db, widget_key)
            assert (origins, unresolved) == ([], True)
        finally:
            db.close()

        # The channel is minted AFTER the negative probe already cached it.
        _real_key, channel_id = _new_channel(client, allowed_origins=[ORIGIN])
        db = session_factory()
        try:
            channel = db.query(Channel).filter(Channel.id == channel_id).first()
            channel.widget_key = widget_key
            db.commit()
        finally:
            db.close()

        db = session_factory()
        try:
            clock["t"] = 10.0  # inside the 15s negative TTL - still cached-empty
            origins, unresolved = svc.resolve_frame_policy(db, widget_key)
            assert (origins, unresolved) == ([], True)

            clock["t"] = 16.0  # past the 15s negative TTL - re-queries, finds it
            origins, unresolved = svc.resolve_frame_policy(db, widget_key)
            assert (origins, unresolved) == ([ORIGIN], False)
        finally:
            db.close()
    finally:
        svc.reset_origins_cache()


def test_preflight_cache_hit_opens_no_db_session(client, session_factory):
    """`preflight_origin_allowed` runs on the ASGI middleware's hot path
    before routing. On a warm cache it must answer without ever constructing
    a `Session` - proven here by pointing the test session-factory seam at a
    spy that raises if it is ever called."""
    from modules.omnichannel.services import webchat_visitor_service as svc

    svc.reset_origins_cache()
    widget_key, _ = _new_channel(client, allowed_origins=[ORIGIN])
    db = session_factory()
    try:
        svc.resolve_frame_policy(db, widget_key)  # warms the cache
    finally:
        db.close()

    def _no_session_allowed():
        raise AssertionError("a cache hit must never open a DB session")

    svc.set_preflight_session_factory(_no_session_allowed)
    try:
        path = f"{svc.WEBCHAT_PUBLIC_PREFIX}{widget_key}/session"
        assert svc.preflight_origin_allowed(path, ORIGIN) is True
        assert svc.preflight_origin_allowed(path, "https://not-allowed.example") is False
    finally:
        svc.set_preflight_session_factory(None)
        svc.reset_origins_cache()
