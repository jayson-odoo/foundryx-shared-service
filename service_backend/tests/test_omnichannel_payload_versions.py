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
        cls = getattr(schemas, shape)
        assert issubclass(cls, VersionedPayload), shape
        for key in keys:
            assert key in cls.model_fields, (shape, key)


# ── API responses: X-Fx-Api-Version ──────────────────────────────────────────
def test_header_1_is_byte_identical_to_no_header(client, session_factory, posted):
    assert_matches_snapshots(run_scenario(client, session_factory, posted, {HEADER: "1"}))


def test_header_2_adds_only_the_v2_key_and_keeps_rio_and_webhooks_identical(client, session_factory, posted):
    out = run_scenario(client, session_factory, posted, {HEADER: "2"})
    expected = {p.stem: p.read_bytes().decode("utf-8") for p in SNAPSHOT_DIR.glob("*.json")}
    assert sorted(out) == sorted(expected)
    for name, want in expected.items():
        if name.startswith("api.webhooks."):
            # The one V2-only key in S0, appended as the item's last key.
            want = want.replace('"updatedAt":"<ts>"}', '"updatedAt":"<ts>","payloadVersion":1}')
            assert '"payloadVersion":1' in want, name
        # Everything else, including every ?format=rio shape and every webhook
        # body (the endpoint is version 1), is byte-identical at version 2.
        assert out[name] == want, name


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


def test_v2_endpoint_gets_todays_body_when_no_key_is_gated_in_it(client, session_factory, posted):
    """S0 gates no key inside webhook bodies, so both endpoints get the same bytes."""
    hdr, channel_id = _key(client, session_factory)
    secrets = _two_endpoints(client, hdr, ("message.inbound", "contact.updated"))
    _process(session_factory, channel_id, _wa_payload(wamid="wamid.v-in-2", from_="60123450003"))
    calls = posted.drain(session_factory)
    by_url = {}
    for c in calls:
        by_url.setdefault(c["url"], []).append(c)
    assert len(by_url[HOOK_V1]) == len(by_url[HOOK_V2]) >= 1
    for a, b in zip(by_url[HOOK_V1], by_url[HOOK_V2]):
        assert a["content"] == b["content"]
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
