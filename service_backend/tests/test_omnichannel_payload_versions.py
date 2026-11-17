"""S0 payload versions: per-endpoint webhook ``payloadVersion`` and the
``X-Fx-Api-Version`` request header (services/payload_version.py).

Version 1 (no header, NULL endpoint version) is the frozen byte snapshot in
``test_omnichannel_payload_snapshots.py``; this file proves the opt-in side,
the validation, the fan-out per version and the migration.
"""
import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import WebhookDelivery, WebhookEndpoint
from modules.omnichannel.schemas import WebhookEndpointItem
from modules.omnichannel.services import payload_version as pv
from modules.omnichannel.services import webhook_delivery as wd
from modules.omnichannel.services.payload_version import VersionedPayload
from tests.test_omnichannel_api_gateway import _auth, _default_workspace_id, _mint, _seed_channel
from tests.test_omnichannel_payload_snapshots import (  # noqa: F401 - fixtures
    SNAPSHOT_DIR,
    _memory_idempotency,
    _tmp_media,
    assert_matches_snapshots,
    posted,
    run_scenario,
)
from tests.test_omnichannel_webhooks import _process, _wa_payload

BASE = "/api/v1/omnichannel"
HEADER = "X-Fx-Api-Version"
HOOK_V1 = "https://hooks.example.com/v1"
HOOK_V2 = "https://hooks.example.com/v2"
MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "modules/omnichannel/alembic/versions/0027_omni_payload_version.py"
)


# ── helpers ──────────────────────────────────────────────────────────────────
def _key(client, session_factory):
    ws = _default_workspace_id(session_factory)
    channel_id = _seed_channel(session_factory, ws)
    key = _mint(client, ws).json()["fullKey"]
    return {"Authorization": f"Bearer {key}"}, channel_id


def _create(client, hdr, url=HOOK_V1, events=("message.inbound",), **extra):
    return client.post(
        f"{BASE}/webhooks",
        json={"name": "w", "url": url, "events": list(events), **extra},
        headers=hdr,
    )


def _stored_version(session_factory, endpoint_id):
    db = session_factory()
    try:
        return db.query(WebhookEndpoint).filter(WebhookEndpoint.id == endpoint_id).one().payload_version
    finally:
        db.close()


def _assert_invalid_request(res):
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "invalid_request", res.text


# ── the seam ─────────────────────────────────────────────────────────────────
def test_versions_and_registry():
    assert (pv.V1, pv.V2, pv.LATEST) == (1, 2, 2)
    assert pv.GATED_KEYS["WebhookEndpointItem"] == {"payloadVersion": pv.V2}
    assert pv.visible("WebhookEndpointItem", "payloadVersion", pv.V2)
    assert not pv.visible("WebhookEndpointItem", "payloadVersion", pv.V1)
    assert pv.visible("WebhookEndpointItem", "name", pv.V1)
    assert pv.strip("WebhookEndpointItem", {"a": 1, "payloadVersion": 2, "b": 3}, pv.V1) == {"a": 1, "b": 3}
    assert pv.effective(None) == pv.V1 and pv.effective(2) == 2
    assert pv.current() == pv.V1
    with pv.serializing(pv.V2):
        assert pv.current() == pv.V2
    assert pv.current() == pv.V1


def test_every_registered_shape_is_versioned_and_has_its_keys():
    """A registry line without the base class (or the field) would silently
    leak or drop a key: every registered shape must be a VersionedPayload
    exposing each registered key."""
    from modules.omnichannel import schemas

    for shape, keys in pv.GATED_KEYS.items():
        if shape in pv.HAND_BUILT:
            assert not hasattr(schemas, shape), shape
            continue
        cls = getattr(schemas, shape)
        assert issubclass(cls, VersionedPayload), shape
        for key in keys:
            assert key in cls.model_fields, (shape, key)


# ── API responses: X-Fx-Api-Version ──────────────────────────────────────────
def test_header_1_is_byte_identical_to_no_header(client, session_factory, posted):
    assert_matches_snapshots(run_scenario(client, session_factory, posted, {HEADER: "1"}))


def _all_v2_keys():
    return {key for keys in pv.GATED_KEYS.values() for key in keys}


def _without_v2_keys(text):
    """A JSON body with every version 2 key removed, kept as ordered key/value
    pairs so key order is still compared."""
    gated = _all_v2_keys()
    return json.loads(text, object_pairs_hook=lambda pairs: [(k, v) for k, v in pairs if k not in gated])


# The versioned API responses of the snapshot scenario: version 2 adds keys to
# these and to nothing else.
V2_CHANGED_API = {
    "api.webhooks.create", "api.webhooks.list", "api.webhooks.update",
    "api.webhooks.disable", "api.webhooks.enable",
    "api.contacts.list", "api.contacts.get", "api.contacts.update", "api.contacts.messages",
    "api.contacts.message", "api.contacts.comment", "api.templates.list", "api.channels.list",
}


def test_header_2_adds_only_v2_keys_and_keeps_rio_and_webhooks_identical(client, session_factory, posted):
    out = run_scenario(client, session_factory, posted, {HEADER: "2"})
    expected = {p.stem: p.read_bytes().decode("utf-8") for p in SNAPSHOT_DIR.glob("*.json")}
    assert sorted(out) == sorted(expected)
    changed = set()
    for name, want in expected.items():
        if out[name] != want:
            changed.add(name)
            # Same keys, same order, same values once the version 2 keys are removed.
            assert _without_v2_keys(out[name]) == _without_v2_keys(want), name
    # Every ?format=rio shape and every webhook body (the endpoint is version 1)
    # is byte-identical at version 2.
    assert changed == V2_CHANGED_API, sorted(changed ^ V2_CHANGED_API)
    assert '"payloadVersion":1' in out["api.webhooks.list"]
    for name in ("api.contacts.list", "api.contacts.get", "api.contacts.update"):
        assert '"windowOpen":' in out[name] and '"windows":[' in out[name], name
    assert '"window":{' in out["api.contacts.messages"]
    assert '"sender":{"type":"API"' in out["api.contacts.messages"]
    assert '"sender":{"type":"SYSTEM"' in out["api.contacts.comment"]
    assert '"headerFormat":null,"headerVariableCount":0,"buttonVariableCount":0' in out["api.templates.list"]
    assert '"connectionState":"CONNECTED"' in out["api.channels.list"]


@pytest.mark.parametrize("value", ["3", "0", "-1", "abc", "v2", "1.0", "2 2", " ", "99999"])
def test_unknown_header_value_is_a_typed_422_everywhere(client, session_factory, value):
    hdr, _ = _key(client, session_factory)
    bad = {**hdr, HEADER: value}
    for method, path, kw in [
        ("GET", "/webhooks", {}),
        ("GET", "/contacts", {}),
        ("GET", "/contacts?format=rio", {}),
        ("GET", "/channels", {}),
        ("POST", "/messages", {"json": {"to": "+60123450009", "type": "text", "text": {"body": "x"}}}),
    ]:
        res = client.request(method, f"{BASE}{path}", headers=bad, **kw)
        _assert_invalid_request(res)
        assert HEADER in res.json()["error"]["message"]


def test_header_version_2_shows_payload_version_on_every_endpoint_route(client, session_factory):
    hdr, _ = _key(client, session_factory)
    v2 = {**hdr, HEADER: "2"}
    created = _create(client, v2, payloadVersion=2)
    assert created.status_code == 201, created.text
    assert created.json()["endpoint"]["payloadVersion"] == 2
    eid = created.json()["endpoint"]["id"]
    legacy = _create(client, v2, url=HOOK_V2)
    assert legacy.json()["endpoint"]["payloadVersion"] == 1  # NULL reads as version 1
    listed = client.get(f"{BASE}/webhooks", headers=v2).json()["data"]
    assert sorted(e["payloadVersion"] for e in listed) == [1, 2]
    assert client.patch(f"{BASE}/webhooks/{eid}", json={"name": "n"}, headers=v2).json()["payloadVersion"] == 2
    assert client.post(f"{BASE}/webhooks/{eid}/disable", headers=v2).json()["payloadVersion"] == 2
    assert client.post(f"{BASE}/webhooks/{eid}/enable", headers=v2).json()["payloadVersion"] == 2
    # Without the header the same endpoint answers with no payloadVersion key.
    plain = client.get(f"{BASE}/webhooks", headers=hdr).json()["data"]
    assert all("payloadVersion" not in e for e in plain)


# ── payloadVersion on the endpoint ───────────────────────────────────────────
def test_create_without_payload_version_stores_null(client, session_factory):
    hdr, _ = _key(client, session_factory)
    res = _create(client, hdr)
    assert res.status_code == 201
    assert "payloadVersion" not in res.json()["endpoint"]
    assert _stored_version(session_factory, res.json()["endpoint"]["id"]) is None


def test_create_with_payload_version_2_keeps_the_v1_response(client, session_factory):
    hdr, _ = _key(client, session_factory)
    res = _create(client, hdr, payloadVersion=2)
    assert res.status_code == 201
    assert "payloadVersion" not in res.json()["endpoint"]  # V1 caller: today's item
    assert _stored_version(session_factory, res.json()["endpoint"]["id"]) == 2


@pytest.mark.parametrize("value", [0, -1, 3, 99, "2", True, 2.5, [2], {"v": 2}])
def test_bad_payload_version_on_create_is_a_typed_422(client, session_factory, value):
    hdr, _ = _key(client, session_factory)
    _assert_invalid_request(_create(client, hdr, payloadVersion=value))
    assert client.get(f"{BASE}/webhooks", headers=hdr).json()["data"] == []


def test_update_sets_keeps_and_refuses_payload_version(client, session_factory):
    hdr, _ = _key(client, session_factory)
    eid = _create(client, hdr).json()["endpoint"]["id"]
    res = client.patch(f"{BASE}/webhooks/{eid}", json={"payloadVersion": 2}, headers=hdr)
    assert res.status_code == 200 and "payloadVersion" not in res.json()
    assert _stored_version(session_factory, eid) == 2
    # Omitted or null leaves it unchanged (same rule as name/url/events).
    client.patch(f"{BASE}/webhooks/{eid}", json={"name": "renamed"}, headers=hdr)
    client.patch(f"{BASE}/webhooks/{eid}", json={"payloadVersion": None}, headers=hdr)
    assert _stored_version(session_factory, eid) == 2
    _assert_invalid_request(client.patch(f"{BASE}/webhooks/{eid}", json={"payloadVersion": 7}, headers=hdr))
    _assert_invalid_request(client.patch(f"{BASE}/webhooks/{eid}", json={"payloadVersion": "1"}, headers=hdr))
    assert _stored_version(session_factory, eid) == 2
    client.patch(f"{BASE}/webhooks/{eid}", json={"payloadVersion": 1}, headers=hdr)
    assert _stored_version(session_factory, eid) == 1


def test_dashboard_routes_accept_payload_version_and_answer_as_before(client, session_factory):
    ws = _default_workspace_id(session_factory)
    channel_id = _seed_channel(session_factory, ws)
    staff = _auth(client)
    res = client.post(
        f"/omnichannel/channels/{channel_id}/webhooks",
        json={"name": "d", "url": HOOK_V1, "events": ["message.inbound"], "payloadVersion": 2},
        headers=staff,
    )
    assert res.status_code == 201, res.text
    eid = res.json()["endpoint"]["id"]
    assert "payloadVersion" not in res.json()["endpoint"]
    assert _stored_version(session_factory, eid) == 2
    listed = client.get(f"/omnichannel/channels/{channel_id}/webhooks", headers=staff).json()["data"]
    assert listed and all("payloadVersion" not in e for e in listed)
    assert "payloadVersion" not in client.patch(
        f"/omnichannel/webhooks/{eid}", json={"payloadVersion": 1}, headers=staff
    ).json()
    assert _stored_version(session_factory, eid) == 1
    bad = client.patch(f"/omnichannel/webhooks/{eid}", json={"payloadVersion": 5}, headers=staff)
    assert bad.status_code == 400  # the dashboard router's own error style
    assert _stored_version(session_factory, eid) == 1


# ── webhook fan-out: one body per endpoint version ───────────────────────────
class ProbeShape(VersionedPayload):
    """Test-only shape with one key gated to version 2."""

    kept: int
    added: int = 0


def _two_endpoints(client, hdr, events):
    v1 = _create(client, hdr, url=HOOK_V1, events=events).json()
    v2 = _create(client, hdr, url=HOOK_V2, events=events, payloadVersion=2).json()
    return {HOOK_V1: v1["signingSecret"], HOOK_V2: v2["signingSecret"]}


def _verify(call, secret):
    ts = call["headers"]["X-Fx-Timestamp"]
    assert call["headers"]["X-Fx-Signature"] == wd.sign_body(secret, ts, call["content"])


def test_one_event_to_two_endpoints_gets_two_bodies_each_signed(client, session_factory, posted, monkeypatch):
    monkeypatch.setitem(pv.GATED_KEYS, "ProbeShape", {"added": pv.V2})
    hdr, channel_id = _key(client, session_factory)
    secrets = _two_endpoints(client, hdr, ("message.inbound",))
    db = session_factory()
    try:
        from modules.omnichannel.models import Channel

        channel = db.query(Channel).filter(Channel.id == channel_id).one()
        queued = wd.enqueue_event(
            db, channel, "message.inbound", "evt-probe",
            lambda: {"probe": ProbeShape(kept=1, added=2).model_dump(mode="json")},
        )
    finally:
        db.close()
    assert queued == 2
    calls = {c["url"]: c for c in posted.drain(session_factory)}
    v1, v2 = json.loads(calls[HOOK_V1]["content"]), json.loads(calls[HOOK_V2]["content"])
    assert v1["data"] == {"probe": {"kept": 1}}
    assert v2["data"] == {"probe": {"kept": 1, "added": 2}}
    assert v1["id"] == v2["id"] == "evt-probe"
    for url, secret in secrets.items():
        _verify(calls[url], secret)
    # Each body is signed over its own bytes, so the other secret fails.
    ts = calls[HOOK_V1]["headers"]["X-Fx-Timestamp"]
    assert calls[HOOK_V1]["headers"]["X-Fx-Signature"] != wd.sign_body(secrets[HOOK_V2], ts, calls[HOOK_V1]["content"])


def test_inbound_message_builds_each_endpoints_body_at_its_version(client, session_factory, posted, monkeypatch):
    """The real producer: message.inbound data is built per endpoint version."""
    hdr, channel_id = _key(client, session_factory)
    secrets = _two_endpoints(client, hdr, ("message.inbound",))
    real = wd.consumer_message_payload
    monkeypatch.setattr(
        wd, "consumer_message_payload",
        lambda item, row: {**real(item, row), "probeVersion": pv.current()},
    )
    _process(session_factory, channel_id, _wa_payload(wamid="wamid.v-in-1", from_="60123450002"))
    calls = {c["url"]: c for c in posted.drain(session_factory)}
    assert json.loads(calls[HOOK_V1]["content"])["data"]["message"]["probeVersion"] == 1
    assert json.loads(calls[HOOK_V2]["content"])["data"]["message"]["probeVersion"] == 2
    for url, secret in secrets.items():
        _verify(calls[url], secret)


def test_v2_endpoint_body_is_the_v1_body_plus_v2_keys(client, session_factory, posted):
    """Both endpoints get one body each; the version 2 body is the version 1
    body plus the version 2 keys (the window state on the contact object)."""
    hdr, channel_id = _key(client, session_factory)
    secrets = _two_endpoints(client, hdr, ("message.inbound", "contact.updated"))
    _process(session_factory, channel_id, _wa_payload(wamid="wamid.v-in-2", from_="60123450003"))
    calls = posted.drain(session_factory)
    by_url = {}
    for c in calls:
        by_url.setdefault(c["url"], []).append(c)
    assert len(by_url[HOOK_V1]) == len(by_url[HOOK_V2]) >= 1
    for a, b in zip(by_url[HOOK_V1], by_url[HOOK_V2]):
        assert _without_v2_keys(a["content"]) == _without_v2_keys(b["content"])
        contact_v1 = json.loads(a["content"])["data"]["contact"]
        contact_v2 = json.loads(b["content"])["data"]["contact"]
        assert "windows" not in contact_v1 and "windowOpen" not in contact_v1
        assert contact_v2["windowOpen"] is True and contact_v2["windowReason"] == "OPEN"
        _verify(a, secrets[HOOK_V1])
        _verify(b, secrets[HOOK_V2])
    db = session_factory()
    try:
        assert db.query(WebhookDelivery).count() == len(calls)
    finally:
        db.close()


def test_an_api_call_at_version_2_never_changes_webhook_bodies(client, session_factory, posted, monkeypatch):
    """A send made with the V2 header builds message.outbound for a V1 endpoint at V1."""
    from tests.test_omnichannel_api_gateway import _seed_open_contact

    hdr, _channel_id = _key(client, session_factory)
    _seed_open_contact(session_factory, _default_workspace_id(session_factory), phone="+60123450004")
    _create(client, hdr, events=("message.outbound",))
    seen = []
    real = wd.consumer_message_payload

    def _spy(item, row):
        seen.append(pv.current())
        return real(item, row)

    monkeypatch.setattr(wd, "consumer_message_payload", _spy)
    res = client.post(
        f"{BASE}/messages",
        json={"to": "+60123450004", "type": "text", "text": {"body": "x"}},
        headers={**hdr, HEADER: "2"},
    )
    assert res.status_code == 202, res.text
    assert seen == [pv.V1]


# ── WebhookEndpointItem dump rules ───────────────────────────────────────────
def test_item_dump_is_version_1_unless_serializing_a_higher_version():
    from datetime import datetime, timezone

    now = datetime(2026, 11, 18, tzinfo=timezone.utc)
    item = WebhookEndpointItem(
        id="e", tenantId=DEFAULT_TENANT_ID, workspaceId="w", name="n", url=HOOK_V1, events=[],
        status="ACTIVE", consecutiveFailures=0, createdAt=now, updatedAt=now, payloadVersion=2,
    )
    assert "payloadVersion" not in item.model_dump(mode="json")
    assert "payloadVersion" not in json.loads(item.model_dump_json())
    with pv.serializing(pv.V2):
        assert item.model_dump(mode="json")["payloadVersion"] == 2
        assert list(item.model_dump(mode="json"))[-1] == "payloadVersion"


# ── migration ────────────────────────────────────────────────────────────────
def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0027", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_adds_a_nullable_column_and_leaves_rows_untouched_up_and_down():
    mig = _load_migration()
    assert mig.revision == "0027_omni_payload_version" and len(mig.revision) <= 32
    assert mig.down_revision == "0026_omni_contact_erasures"
    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        conn.exec_driver_sql("ATTACH ':memory:' AS app_omnichannel")
        conn.exec_driver_sql(
            "CREATE TABLE app_omnichannel.webhook_endpoints ("
            "id VARCHAR PRIMARY KEY, tenant_id VARCHAR NOT NULL, workspace_id VARCHAR NOT NULL, "
            "channel_id VARCHAR, name VARCHAR NOT NULL, url VARCHAR NOT NULL, "
            "secret_encrypted TEXT NOT NULL, events_json JSON NOT NULL, status VARCHAR NOT NULL)"
        )
        conn.exec_driver_sql(
            "INSERT INTO app_omnichannel.webhook_endpoints VALUES "
            "('e1', 't', 'w', NULL, 'n', 'https://h.example.com', 's', '[\"message.inbound\"]', 'ACTIVE')"
        )
        before = conn.exec_driver_sql("SELECT * FROM app_omnichannel.webhook_endpoints").fetchall()

        def run(step):
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                step()

        def columns():
            return {c["name"]: c for c in sa.inspect(conn).get_columns("webhook_endpoints", schema="app_omnichannel")}

        run(mig.upgrade)
        cols = columns()
        assert "payload_version" in cols and cols["payload_version"]["nullable"] is True
        rows = conn.exec_driver_sql(
            "SELECT id, tenant_id, workspace_id, channel_id, name, url, secret_encrypted, events_json, "
            "status, payload_version FROM app_omnichannel.webhook_endpoints"
        ).fetchall()
        assert [tuple(r[:-1]) for r in rows] == [tuple(r) for r in before]
        assert rows[0][-1] is None  # existing endpoints stay on version 1
        run(mig.upgrade)  # idempotent
        run(mig.downgrade)
        assert "payload_version" not in columns()
        after = conn.exec_driver_sql("SELECT * FROM app_omnichannel.webhook_endpoints").fetchall()
        assert [tuple(r) for r in after] == [tuple(r) for r in before]


def test_migration_is_online_safe_on_postgres():
    text = MIGRATION.read_text()
    assert "ADD COLUMN IF NOT EXISTS payload_version INTEGER" in text
    assert "DEFAULT" not in text.upper().split("DEF UPGRADE")[1].split("DEF DOWNGRADE")[0]
    assert "UPDATE " not in text.upper()


# ── Track A S1: window state on ThreadItem (version 2 only) ──────────────────
def _hours(n):
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) + timedelta(hours=n)


def _set_identity_window(session_factory, channel_id, window_hours, human_agent_hours=None):
    from modules.omnichannel.models import ContactChannelIdentity

    db = session_factory()
    try:
        identity = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.channel_id == channel_id).one()
        identity.window_expires_at = _hours(window_hours)
        identity.human_agent_expires_at = _hours(human_agent_hours) if human_agent_hours is not None else None
        db.commit()
    finally:
        db.close()


def _contact(client, hdr, version="2"):
    data = client.get(f"{BASE}/contacts", headers={**hdr, HEADER: version}).json()["data"]
    assert len(data) == 1, data
    return data[0]


def test_two_numbers_inbound_on_a_leaves_b_closed(client, session_factory):
    ws = _default_workspace_id(session_factory)
    hdr, number_b = _key(client, session_factory)
    number_a = _seed_channel(session_factory, ws, phone_number_id="pn-number-a")
    # The customer once wrote to B (window long gone), then writes to A now.
    _process(session_factory, number_b, _wa_payload(wamid="wamid.two-b", from_="60123450021"))
    _set_identity_window(session_factory, number_b, -30)
    _process(session_factory, number_a, _wa_payload(wamid="wamid.two-a", from_="60123450021"))

    contact = _contact(client, hdr)
    assert contact["channelId"] == number_a
    assert (contact["windowOpen"], contact["allowedSendTypes"], contact["windowReason"]) == (True, ["ANY"], "OPEN")
    windows = {w["channelId"]: w for w in contact["windows"]}
    assert set(windows) == {number_a, number_b}
    assert windows[number_a]["windowOpen"] is True and windows[number_a]["allowedSendTypes"] == ["ANY"]
    assert windows[number_b]["windowOpen"] is False and windows[number_b]["allowedSendTypes"] == ["TEMPLATE"]
    assert windows[number_b]["channelType"] == "WHATSAPP"
    assert windows[number_b]["windowExpiresAt"].endswith("Z")
    # The contact-wide WhatsApp field is unchanged: it still reads open.
    assert contact["cswExpiresAt"] is not None

    # Version 1 (no header and header 1): none of the new keys.
    for version in (None, "1"):
        headers = hdr if version is None else {**hdr, HEADER: version}
        plain = client.get(f"{BASE}/contacts", headers=headers).json()["data"][0]
        for key in ("windowOpen", "allowedSendTypes", "windowReason", "windows"):
            assert key not in plain
        one = client.get(f"{BASE}/contacts/{contact['id']}", headers=headers).json()
        assert "windows" not in one
        history = client.get(f"{BASE}/contacts/{contact['id']}/messages", headers=headers).json()
        assert "window" not in history

    # Version 2 on the single read, the history and the dashboard (always version 1).
    one = client.get(f"{BASE}/contacts/{contact['id']}", headers={**hdr, HEADER: "2"}).json()
    assert one["windows"] == contact["windows"]
    history = client.get(f"{BASE}/contacts/{contact['id']}/messages", headers={**hdr, HEADER: "2"}).json()
    assert history["window"] == windows[number_a]
    rio = client.get(f"{BASE}/contacts/{contact['id']}?format=rio", headers={**hdr, HEADER: "2"}).json()
    assert "windows" not in rio and "windowOpen" not in json.dumps(rio)
    staff = client.get(f"/omnichannel/contacts/{contact['id']}", headers={**_auth(client), HEADER: "2"})
    assert staff.status_code == 200, staff.text
    assert staff.json()["id"] == contact["id"] and "windowOpen" not in staff.text and "windows" not in staff.text


def test_messenger_human_agent_window_is_nothing_sendable_for_an_api_key(client, session_factory):
    from tests.test_omnichannel_channels_messenger import _fb_channel, _messenger_payload

    ws = _default_workspace_id(session_factory)
    hdr = {"Authorization": f"Bearer {_mint(client, ws).json()['fullKey']}"}
    fb_id = _fb_channel(session_factory, external_account_id="pg-s1")
    _process(session_factory, fb_id, _messenger_payload(page_id="pg-s1", psid="psid-s1", mid="m.s1"))

    contact = _contact(client, hdr)
    assert (contact["windowOpen"], contact["allowedSendTypes"], contact["windowReason"]) == (True, ["ANY"], "OPEN")

    _set_identity_window(session_factory, fb_id, -1, human_agent_hours=100)
    contact = _contact(client, hdr)
    assert contact["channelType"] == "FACEBOOK"
    assert (contact["windowOpen"], contact["allowedSendTypes"], contact["windowReason"]) == (
        False, [], "HUMAN_AGENT_ONLY"
    )
    assert contact["windows"][0]["humanAgentExpiresAt"] is not None
    assert contact["cswExpiresAt"] is None  # WhatsApp-only field, unchanged

    _set_identity_window(session_factory, fb_id, -200, human_agent_hours=-1)
    contact = _contact(client, hdr)
    assert (contact["windowOpen"], contact["allowedSendTypes"], contact["windowReason"]) == (False, [], "CLOSED")


def test_window_state_rules():
    from types import SimpleNamespace

    from modules.omnichannel.services.messaging_policy import window_state

    def ident(window, human=None):
        return SimpleNamespace(
            window_expires_at=_hours(window) if window is not None else None,
            human_agent_expires_at=_hours(human) if human is not None else None,
        )

    def triple(state):
        return state.window_open, list(state.allowed_send_types), state.reason

    # Web chat has no window at all.
    assert triple(window_state(None, "WEBCHAT", actor_is_human=False)) == (True, ["ANY"], "NO_WINDOW")
    assert triple(window_state(ident(None), "WEBCHAT", actor_is_human=False)) == (True, ["ANY"], "NO_WINDOW")
    # WhatsApp: per identity; no identity on that number = closed.
    assert triple(window_state(ident(5), "WHATSAPP", actor_is_human=False)) == (True, ["ANY"], "OPEN")
    assert triple(window_state(ident(-5), "WHATSAPP", actor_is_human=False)) == (False, ["TEMPLATE"], "CLOSED")
    assert triple(window_state(None, "WHATSAPP", actor_is_human=False)) == (False, ["TEMPLATE"], "CLOSED")
    # Instagram 7-day: a human may reply, automation may not.
    assert triple(window_state(ident(-1, 50), "INSTAGRAM", actor_is_human=True)) == (False, ["ANY"], "HUMAN_AGENT_ONLY")
    assert triple(window_state(ident(-1, 50), "INSTAGRAM", actor_is_human=False)) == (False, [], "HUMAN_AGENT_ONLY")
    assert triple(window_state(ident(-200, -1), "INSTAGRAM", actor_is_human=True)) == (False, [], "CLOSED")


def test_web_chat_thread_reads_no_window(client, session_factory):
    from modules.omnichannel.models import Channel, Contact, ContactChannelIdentity
    from modules.omnichannel.services import statuses
    from modules.omnichannel.services.conversation_service import ConversationService

    ws = _default_workspace_id(session_factory)
    db = session_factory()
    try:
        ch = Channel(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, channel_type="WEBCHAT", name="Site", is_active=True)
        c = Contact(
            tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, first_name="Visitor", priority="MEDIUM",
            status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "THREAD", "OPEN"),
        )
        db.add_all([ch, c])
        db.flush()
        db.add(ContactChannelIdentity(
            tenant_id=DEFAULT_TENANT_ID, contact_id=c.id, channel_id=ch.id, external_user_id="visitor-1",
        ))
        db.commit()
        item = ConversationService(db).thread_item(c)
        assert [w.model_dump() for w in item.windows] == [{
            "channelId": ch.id, "channelType": "WEBCHAT", "windowOpen": True,
            "windowExpiresAt": None, "humanAgentExpiresAt": None, "allowedSendTypes": ["ANY"],
        }]
    finally:
        db.close()


def test_v2_webhook_contact_carries_window_state_and_v1_does_not(client, session_factory, posted):
    hdr, channel_id = _key(client, session_factory)
    _two_endpoints(client, hdr, ("message.inbound",))
    _process(session_factory, channel_id, _wa_payload(wamid="wamid.s1-hook", from_="60123450031"))
    calls = {c["url"]: json.loads(c["content"]) for c in posted.drain(session_factory)}
    v1, v2 = calls[HOOK_V1]["data"]["contact"], calls[HOOK_V2]["data"]["contact"]
    assert "windows" not in v1 and "allowedSendTypes" not in v1
    assert v2["windows"][0]["channelId"] == channel_id
    assert v2["windows"][0]["allowedSendTypes"] == ["ANY"]
    assert v2["windowExpiresAt"] == v1["windowExpiresAt"]


# ── Track A S2: details on the public window refusals (version 2 only) ───────
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _closed_wa(client, session_factory, phone):
    from tests.test_omnichannel_api_gateway import _seed_open_contact

    hdr, channel_id = _key(client, session_factory)
    _seed_open_contact(session_factory, _default_workspace_id(session_factory), phone=phone, open_window=False)
    return hdr, channel_id


def test_whatsapp_refusal_details_only_for_version_2(client, session_factory):
    from modules.omnichannel.services.messaging_policy import CSW_CLOSED_MESSAGE

    hdr, channel_id = _closed_wa(client, session_factory, "+60123450041")
    body = {"to": "+60123450041", "type": "text", "text": {"body": "hi"}}
    for headers in (hdr, {**hdr, HEADER: "1"}):
        res = client.post(f"{BASE}/messages", json=body, headers=headers)
        assert res.status_code == 409
        # Today's exact body for a version 1 caller.
        assert res.content == json.dumps(
            {"error": {"code": "csw_window_closed", "message": CSW_CLOSED_MESSAGE}},
            separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
    res = client.post(f"{BASE}/messages", json=body, headers={**hdr, HEADER: "2"})
    assert res.status_code == 409
    err = res.json()["error"]
    assert (err["code"], err["message"]) == ("csw_window_closed", CSW_CLOSED_MESSAGE)
    assert list(err) == ["code", "message", "details"]
    assert err["details"] == {
        "channelId": channel_id, "windowExpiresAt": None,
        "allowedSendTypes": ["TEMPLATE"], "reason": "csw_window_closed",
    }


def test_media_refusals_carry_details_for_version_2(client, session_factory):
    hdr, channel_id = _closed_wa(client, session_factory, "+60123450042")
    v2 = {**hdr, HEADER: "2"}
    # JSON media by URL: refused before any fetch.
    body = {"to": "+60123450042", "type": "image", "media": {"url": "https://media.example.com/a.png"}}
    plain = client.post(f"{BASE}/messages", json=body, headers=hdr)
    assert plain.status_code == 409 and "details" not in plain.json()["error"]
    res = client.post(f"{BASE}/messages", json=body, headers=v2)
    assert res.status_code == 409 and res.json()["error"]["code"] == plain.json()["error"]["code"]
    assert res.json()["error"]["message"] == plain.json()["error"]["message"]
    assert res.json()["error"]["details"]["channelId"] == channel_id
    # Multipart.
    payload = json.dumps({"to": "+60123450042", "type": "image"})
    files = {"file": ("a.png", PNG, "image/png")}
    plain = client.post(f"{BASE}/messages", headers=hdr, data={"payload": payload}, files=files)
    assert plain.status_code == 409 and "details" not in plain.json()["error"], plain.text
    res = client.post(f"{BASE}/messages", headers=v2, data={"payload": payload}, files=files)
    assert res.status_code == 409
    assert res.json()["error"]["details"]["allowedSendTypes"] == ["TEMPLATE"]


def test_messenger_automation_refusal_reason_for_version_2(client, session_factory):
    from tests.test_omnichannel_channels_messenger import _fb_channel, _messenger_payload

    ws = _default_workspace_id(session_factory)
    hdr = {"Authorization": f"Bearer {_mint(client, ws).json()['fullKey']}"}
    fb_id = _fb_channel(session_factory, external_account_id="pg-s2")
    _process(session_factory, fb_id, _messenger_payload(page_id="pg-s2", psid="psid-s2", mid="m.s2"))
    _set_identity_window(session_factory, fb_id, -1, human_agent_hours=100)
    body = {"to": "psid:psid-s2", "channelId": fb_id, "type": "text", "text": {"body": "hi"}}
    plain = client.post(f"{BASE}/messages", json=body, headers=hdr)
    assert plain.status_code == 409
    assert plain.json() == {"error": {"code": "messaging_window_closed", "message": plain.json()["error"]["message"]}}
    res = client.post(f"{BASE}/messages", json=body, headers={**hdr, HEADER: "2"})
    assert res.status_code == 409
    err = res.json()["error"]
    assert (err["code"], err["message"]) == ("messaging_window_closed", plain.json()["error"]["message"])
    assert err["details"]["reason"] == "automation_outside_window"
    assert err["details"]["allowedSendTypes"] == []
    assert err["details"]["channelId"] == fb_id and err["details"]["windowExpiresAt"].endswith("Z")


def test_other_refusals_and_the_dashboard_are_untouched_at_version_2(client, session_factory):
    from tests.test_omnichannel_api_gateway import _seed_open_contact

    hdr, _ = _key(client, session_factory)
    v2 = {**hdr, HEADER: "2"}
    bad = client.post(f"{BASE}/messages", json={"to": "+60123450043", "type": "text", "text": {"body": " "}}, headers=v2)
    assert bad.status_code == 422 and "details" not in bad.json()["error"]
    cid = _seed_open_contact(session_factory, _default_workspace_id(session_factory), phone="+60123450044", open_window=False)
    staff = client.post(
        f"/omnichannel/contacts/{cid}/messages",
        json={"messageType": "TEXT", "body": "hi"},
        headers={**_auth(client), HEADER: "2"},
    )
    assert staff.status_code == 422 and list(staff.json()) == ["detail"], staff.text
    assert isinstance(staff.json()["detail"], str)


# ── Track A S3: sender attribution (stored always, returned at version 2) ────
SENDER = {"externalId": "ecohub:user-42", "displayName": "  Aisyah Lim  ", "avatarUrl": "https://cdn.example.com/a.png"}
STORED = {"externalId": "ecohub:user-42", "displayName": "Aisyah Lim", "avatarUrl": "https://cdn.example.com/a.png"}


class _SpyAdapter:
    """Replaces the provider adapter at the send_runner boundary; records every send."""

    def __init__(self):
        self.calls = []

    def upload_media(self, *a, **k):
        return "media-fake"

    def send(self, *a, **k):
        self.calls.append((a, k))
        return {"external_message_id": f"wamid.s3-{len(self.calls)}"}


@pytest.fixture
def spy(monkeypatch):
    adapter = _SpyAdapter()
    monkeypatch.setattr("modules.omnichannel.services.send_runner.get_adapter", lambda *a, **k: adapter)
    return adapter


def _open_contact(client, session_factory, phone):
    from tests.test_omnichannel_api_gateway import _seed_open_contact

    hdr, channel_id = _key(client, session_factory)
    cid = _seed_open_contact(session_factory, _default_workspace_id(session_factory), phone=phone, open_window=True)
    return hdr, channel_id, cid


def _row(session_factory, message_id):
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    try:
        m = db.query(ConversationMessage).filter(ConversationMessage.id == message_id).one()
        return {"sender_id": m.sender_id, "ext": m.sender_external_agent_id, "meta": dict(m.metadata_json or {}), "body": m.body}
    finally:
        db.close()


def test_sender_is_stored_and_returned_only_at_version_2(client, session_factory, posted, spy):
    hdr, channel_id, cid = _open_contact(client, session_factory, "+60123450051")
    _two_endpoints(client, hdr, ("message.outbound",))
    res = client.post(
        f"{BASE}/messages",
        json={"to": "+60123450051", "type": "text", "text": {"body": "Your quote is ready"}, "sender": SENDER},
        headers=hdr,
    )
    assert res.status_code == 202, res.text
    mid = res.json()["id"]
    row = _row(session_factory, mid)
    assert row["meta"]["senderAttribution"] == STORED
    assert row["sender_id"].startswith("apikey:") and row["ext"] is None

    one_v1 = client.get(f"{BASE}/contacts/{cid}/messages/{mid}", headers=hdr).json()
    one_v2 = client.get(f"{BASE}/contacts/{cid}/messages/{mid}", headers={**hdr, HEADER: "2"}).json()
    assert "sender" not in one_v1
    assert one_v2["sender"] == {"type": "API", **STORED, "userId": None}
    # D5: the existing sender fields are the same at both versions.
    for key in ("senderType", "senderId", "senderName", "senderAvatarUrl", "senderExternalAgentId"):
        assert one_v1[key] == one_v2[key], key
    assert one_v1["senderName"] is None and one_v1["senderType"] == "AGENT"
    history = client.get(f"{BASE}/contacts/{cid}/messages", headers={**hdr, HEADER: "2"}).json()["data"]
    assert next(m for m in history if m["id"] == mid)["sender"]["displayName"] == "Aisyah Lim"
    rio = client.get(f"{BASE}/contacts/{cid}/messages/{mid}?format=rio", headers={**hdr, HEADER: "2"}).text
    assert "Aisyah" not in rio

    calls = {c["url"]: json.loads(c["content"]) for c in posted.drain(session_factory)}
    out_v1, out_v2 = calls[HOOK_V1]["data"], calls[HOOK_V2]["data"]
    assert "sender" not in out_v1["message"]
    assert out_v2["message"]["sender"]["externalId"] == "ecohub:user-42"
    assert out_v1["source"] == out_v2["source"] == "api"
    assert out_v1["message"]["senderName"] is None


def test_customer_text_is_byte_identical_with_or_without_sender(client, session_factory, spy):
    hdr, _, _ = _open_contact(client, session_factory, "+60123450052")
    text = "Hello éè \U0001f600  spaced\nline two"
    for extra in ({}, {"sender": SENDER}):
        res = client.post(
            f"{BASE}/messages", json={"to": "+60123450052", "type": "text", "text": {"body": text}, **extra}, headers=hdr,
        )
        assert res.status_code == 202, res.text
    assert len(spy.calls) == 2
    assert spy.calls[0] == spy.calls[1]
    assert spy.calls[0][1]["text"] == spy.calls[1][1]["text"] == text
    assert "Aisyah" not in repr(spy.calls[1]) and "ecohub:user-42" not in repr(spy.calls[1])


def test_sender_on_multipart_and_structured_sends(client, session_factory, spy):
    hdr, _, cid = _open_contact(client, session_factory, "+60123450053")
    payload = json.dumps({"to": "+60123450053", "type": "image", "media": {"caption": "photo"}, "sender": SENDER})
    res = client.post(f"{BASE}/messages", headers=hdr, data={"payload": payload}, files={"file": ("a.png", PNG, "image/png")})
    assert res.status_code == 202, res.text
    assert _row(session_factory, res.json()["id"])["meta"]["senderAttribution"] == STORED
    res = client.post(
        f"{BASE}/messages",
        json={"to": "+60123450053", "type": "location", "location": {"lat": 3.1, "lng": 101.6}, "sender": SENDER},
        headers=hdr,
    )
    assert res.status_code == 202, res.text
    assert _row(session_factory, res.json()["id"])["meta"]["senderAttribution"] == STORED
    # Without sender: nothing stored, version 2 shows a bare API sender.
    res = client.post(f"{BASE}/messages", json={"to": "+60123450053", "type": "text", "text": {"body": "x"}}, headers=hdr)
    mid = res.json()["id"]
    assert "senderAttribution" not in _row(session_factory, mid)["meta"]
    one = client.get(f"{BASE}/contacts/{cid}/messages/{mid}", headers={**hdr, HEADER: "2"}).json()
    assert one["sender"] == {"type": "API", "externalId": None, "displayName": None, "avatarUrl": None, "userId": None}


@pytest.mark.parametrize("sender", [
    {"displayName": "A"},
    {"externalId": "x", "displayName": "   "},
    {"externalId": "bad id", "displayName": "A"},
    {"externalId": "x" * 129, "displayName": "A"},
    {"externalId": "x", "displayName": "A" * 121},
    {"externalId": "x", "displayName": "A", "avatarUrl": "http://cdn.example.com/a.png"},
    {"externalId": "x", "displayName": "A", "avatarUrl": "https://" + "a" * 2050},
    "Aisyah",
])
def test_invalid_sender_is_a_typed_422_and_nothing_is_sent(client, session_factory, spy, sender):
    hdr, _, _ = _open_contact(client, session_factory, "+60123450054")
    res = client.post(
        f"{BASE}/messages", json={"to": "+60123450054", "type": "text", "text": {"body": "x"}, "sender": sender}, headers=hdr,
    )
    _assert_invalid_request(res)
    payload = json.dumps({"to": "+60123450054", "type": "image", "sender": sender})
    res = client.post(f"{BASE}/messages", headers=hdr, data={"payload": payload}, files={"file": ("a.png", PNG, "image/png")})
    _assert_invalid_request(res)
    assert spy.calls == []


def test_sender_types_for_customer_note_workflow_and_agent():
    from types import SimpleNamespace

    from modules.omnichannel.services.conversation_service import _message_sender

    def msg(sender_type, sender_id=None, ext=None):
        return SimpleNamespace(sender_type=sender_type, sender_id=sender_id, sender_external_agent_id=ext)

    assert _message_sender(msg("CONTACT"), {}, None, None).type == "CUSTOMER"
    assert _message_sender(msg("SYSTEM", "u1"), {}, None, None).type == "SYSTEM"
    assert _message_sender(msg("AGENT"), {}, None, None).type == "WORKFLOW"
    assert _message_sender(msg("AGENT", "u1"), {"broadcast": {"id": "b"}}, None, None).type == "BROADCAST"
    native = _message_sender(msg("AGENT", "u1"), {}, None, "Staff One")
    assert (native.type, native.userId, native.displayName) == ("AGENT", "u1", "Staff One")
    embed = _message_sender(msg("AGENT", None, "ext-1"), {}, SimpleNamespace(name="Embed Agent", avatar_url=None), None)
    assert (embed.type, embed.displayName, embed.userId) == ("AGENT", "Embed Agent", None)


# ── Track A S4: template header/button fields ────────────────────────────────
RICH_COMPONENTS = [
    {"type": "HEADER", "format": "TEXT", "text": "Order {{1}}"},
    {"type": "BODY", "text": "Hi {{1}}, your quote {{2}} is ready"},
    {"type": "BUTTONS", "buttons": [{"type": "URL", "text": "Open", "url": "https://shop.example.com/q/{{1}}"}]},
]


def _rich_template(session_factory, channel_id, name="quote_ready", components=RICH_COMPONENTS):
    from modules.omnichannel.models import WhatsappTemplate

    db = session_factory()
    try:
        t = WhatsappTemplate(
            tenant_id=DEFAULT_TENANT_ID, channel_id=channel_id, name=name, language="en",
            status="APPROVED", category="UTILITY", components_json=components,
        )
        db.add(t)
        db.commit()
        return t.id
    finally:
        db.close()


def test_template_list_shape_fields_only_at_version_2(client, session_factory):
    hdr, channel_id = _key(client, session_factory)
    _rich_template(session_factory, channel_id)
    _rich_template(session_factory, channel_id, name="image_promo", components=[
        {"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "Sale"},
    ])
    v1 = client.get(f"{BASE}/templates", headers=hdr).json()["data"]
    assert all("headerFormat" not in t and "buttonVariableCount" not in t for t in v1)
    v2 = {t["name"]: t for t in client.get(f"{BASE}/templates", headers={**hdr, HEADER: "2"}).json()["data"]}
    q = v2["quote_ready"]
    assert (q["variableCount"], q["headerFormat"], q["headerVariableCount"], q["buttonVariableCount"]) == (2, "TEXT", 1, 1)
    img = v2["image_promo"]
    assert (img["headerFormat"], img["headerVariableCount"], img["buttonVariableCount"]) == ("IMAGE", 0, 0)


def test_template_send_with_header_and_button_variables(client, session_factory, spy):
    hdr, channel_id, _ = _open_contact(client, session_factory, "+60123450061")
    tid = _rich_template(session_factory, channel_id)
    base = {"to": "+60123450061", "type": "template"}
    # Without them the send is refused exactly as before (Meta needs every parameter).
    res = client.post(f"{BASE}/messages", json={**base, "template": {"id": tid, "variables": ["Sam", "Q-1"]}}, headers=hdr)
    assert res.status_code == 422, res.text
    assert spy.calls == []
    res = client.post(
        f"{BASE}/messages",
        json={**base, "template": {"id": tid, "variables": ["Sam", "Q-1"], "headerVariables": ["#88"], "buttonVariables": ["Q-1"]}},
        headers=hdr,
    )
    assert res.status_code == 202, res.text
    sent = repr(spy.calls)
    assert "#88" in sent and "Q-1" in sent and "Sam" in sent


# ── Track A S9: channel connectionState + opt-in channel.updated ─────────────
def _channel_row(session_factory, channel_id):
    from modules.omnichannel.models import Channel

    db = session_factory()
    try:
        return db.query(Channel).filter(Channel.id == channel_id).one()
    finally:
        db.close()


def _channels(client, hdr, version=None):
    headers = hdr if version is None else {**hdr, HEADER: version}
    return {c["id"]: c for c in client.get(f"{BASE}/channels", headers=headers).json()["data"]}


def test_connection_state_only_at_version_2_and_status_values_unchanged(client, session_factory):
    from modules.omnichannel.services import statuses

    hdr, channel_id = _key(client, session_factory)
    assert "connectionState" not in _channels(client, hdr)[channel_id]
    assert "connectionState" not in _channels(client, hdr, "1")[channel_id]
    assert _channels(client, hdr, "2")[channel_id]["connectionState"] == "CONNECTED"

    def set_row(**kw):
        from modules.omnichannel.models import Channel

        db = session_factory()
        try:
            c = db.query(Channel).filter(Channel.id == channel_id).one()
            for k, v in kw.items():
                if k == "status":
                    c.status_id = statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", v)
                else:
                    setattr(c, k, v)
            db.commit()
        finally:
            db.close()

    set_row(is_active=False, status="INACTIVE")
    item = _channels(client, hdr, "2")[channel_id]
    assert (item["status"], item["connectionState"]) == ("INACTIVE", "PAUSED")
    set_row(is_active=True, status="ERROR")
    item = _channels(client, hdr, "2")[channel_id]
    assert (item["status"], item["connectionState"]) == ("ERROR", "NEEDS_RECONNECT")


def _hook(client, hdr, url, events, version=None):
    extra = {"payloadVersion": version} if version else {}
    return _create(client, hdr, url=url, events=events, **extra).json()


def test_channel_updated_reaches_only_endpoints_that_list_it(client, session_factory, posted):
    hdr, channel_id = _key(client, session_factory)
    # An existing-style endpoint subscribed to every pre-S9 event type.
    from tests.test_omnichannel_payload_snapshots import V1_EVENT_TYPES

    _hook(client, hdr, "https://hooks.example.com/legacy", list(V1_EVENT_TYPES))
    _hook(client, hdr, HOOK_V1, ["channel.updated"])
    _hook(client, hdr, HOOK_V2, ["channel.updated"], version=2)
    staff = _auth(client)
    res = client.patch(f"/omnichannel/channels/{channel_id}", json={"isActive": False}, headers=staff)
    assert res.status_code == 200, res.text
    calls = list(posted.drain(session_factory))
    by_url = {c["url"]: c for c in calls}
    assert "https://hooks.example.com/legacy" not in by_url
    assert {c["headers"]["X-Fx-Event-Type"] for c in calls} == {"channel.updated"}
    v1 = json.loads(by_url[HOOK_V1]["content"])
    v2 = json.loads(by_url[HOOK_V2]["content"])
    assert v1["data"]["channel"]["id"] == channel_id and v1["data"]["channel"]["isActive"] is False
    assert "connectionState" not in v1["data"]["channel"]
    assert v2["data"]["channel"]["connectionState"] == "PAUSED"
    assert v2["data"]["channel"]["status"] == "INACTIVE"

    # Resume, then disconnect: one event each.
    client.patch(f"/omnichannel/channels/{channel_id}", json={"isActive": True}, headers=staff)
    client.patch(f"/omnichannel/channels/{channel_id}", json={"name": "renamed"}, headers=staff)  # no state change
    states = [json.loads(c["content"])["data"]["channel"]["connectionState"]
              for c in posted.drain(session_factory)[len(calls):] if c["url"] == HOOK_V2]
    assert states == ["CONNECTED"]


def test_channel_updated_on_disconnect_and_token_health(client, session_factory, posted, monkeypatch):
    from modules.omnichannel.services import token_health
    from modules.omnichannel.services.channel_service import ChannelService

    hdr, channel_id = _key(client, session_factory)
    _hook(client, hdr, HOOK_V2, ["channel.updated"], version=2)

    class _Dead:
        verdict = "dead"

        def check_token(self, *a, **k):
            return self.verdict

    adapter = _Dead()
    monkeypatch.setattr(token_health, "get_adapter", lambda *a, **k: adapter)
    monkeypatch.setattr(token_health, "_checkable", lambda c: {"access_token": "t"})
    monkeypatch.setattr(token_health, "_notify_dead", lambda db, c: None)
    db = session_factory()
    try:
        assert token_health.check_channel_token(db, channel_id) == "dead"
        assert token_health.check_channel_token(db, channel_id) == "dead"  # no change, no event
        adapter.verdict = "ok"
        assert token_health.check_channel_token(db, channel_id) == "ok"
        ChannelService(db).disconnect([channel_id], DEFAULT_TENANT_ID)
    finally:
        db.close()
    states = [json.loads(c["content"])["data"]["channel"]["connectionState"] for c in posted.drain(session_factory)]
    assert states == ["NEEDS_RECONNECT", "CONNECTED", "DISCONNECTED"]
