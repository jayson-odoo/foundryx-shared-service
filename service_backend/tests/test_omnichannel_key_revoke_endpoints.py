"""Plan 43 - a key's webhook endpoints when the key is revoked (AC-43-01..32,
backend only).

RED tests written before the implementation. Everything is asserted from the
outside: real HTTP routes, the real deferred-action path, real inbound and send
producers, the real `dispatch`, and rows read back from the database. Only
outbound HTTP is stubbed. Every test seeds its own workspace, channels, keys and
endpoints. Hosts and numbers are obvious fakes.

Controls (tests that pass today, kept so a red test cannot be red for the wrong
reason) say so in their name or docstring.
"""
import re
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import (
    Channel,
    ConversationMessage,
    WebhookDelivery,
    WebhookEndpoint,
    Workspace,
    WorkspaceApiKey,
)
from modules.omnichannel.services import idempotency
from modules.omnichannel.services import webhook_delivery as wd
from tests.test_omnichannel_api_gateway import _auth, _default_workspace_id, _mint
from tests.test_omnichannel_gateway_channels import _channel
from tests.test_omnichannel_one_webhook import _register_all
from tests.test_omnichannel_webhooks import _process, _wa_payload

BASE = "/api/v1/omnichannel"
STAFF = "/omnichannel"
HOOK = "https://hooks.example.com/k"
FOREIGN_TENANT = "other-tenant-id"
OLD = datetime(2020, 1, 1, tzinfo=timezone.utc)
_NO_BODY = object()


# ── fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


@pytest.fixture(autouse=True)
def _tmp_media(tmp_path):
    from app.config import settings
    from app.services.storage import set_storage

    prev = settings.media_root
    settings.media_root = str(tmp_path)
    set_storage(None)
    yield
    settings.media_root = prev
    set_storage(None)


class _Resp:
    def __init__(self, status_code=200):
        self.status_code = status_code


@pytest.fixture(autouse=True)
def _no_real_http(monkeypatch):
    monkeypatch.setattr(wd, "_post", lambda url, *, content, headers, timeout: _Resp(200))


# ── helpers ──────────────────────────────────────────────────────────────────
def _new_workspace(session_factory, name="Second"):
    db = session_factory()
    try:
        ws = Workspace(tenant_id=DEFAULT_TENANT_ID, name=name, is_default=False)
        db.add(ws)
        db.commit()
        return ws.id
    finally:
        db.close()


def _key(client, ws, name="Key"):
    """Mint through the staff route. Returns (key_id, public bearer headers)."""
    body = _mint(client, ws, name).json()
    return body["key"]["id"], {"Authorization": f"Bearer {body['fullKey']}"}


def _insert(
    session_factory,
    *,
    ws,
    created_by,
    tenant_id=DEFAULT_TENANT_ID,
    channel_id=None,
    status="ACTIVE",
    reason=None,
    disabled_at=None,
    failures=0,
    events=("message.inbound",),
    name="direct",
):
    db = session_factory()
    try:
        row = WebhookEndpoint(
            tenant_id=tenant_id,
            workspace_id=ws,
            channel_id=channel_id,
            name=name,
            url=HOOK,
            secret_encrypted="x",
            events_json=list(events),
            status=status,
            disabled_reason=reason,
            disabled_at=disabled_at,
            consecutive_failures=failures,
            created_by=created_by,
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _state(session_factory, endpoint_id):
    db = session_factory()
    try:
        r = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == endpoint_id).one()
        return {
            "status": r.status,
            "disabled_at": r.disabled_at,
            "reason": r.disabled_reason,
            "failures": r.consecutive_failures,
        }
    finally:
        db.close()


def _statuses(session_factory, ids):
    return {k: _state(session_factory, v)["status"] for k, v in ids.items()}


def _revoked(session_factory, key_id):
    db = session_factory()
    try:
        return db.query(WorkspaceApiKey).filter(WorkspaceApiKey.id == key_id).one().revoked_at is not None
    finally:
        db.close()


def _revoke(client, ws, key_id, body=_NO_BODY):
    url = f"{STAFF}/workspaces/{ws}/api-keys/{key_id}/revoke"
    if body is _NO_BODY:
        return client.post(url, headers=_auth(client))
    return client.post(url, headers=_auth(client), json=body)


def _deliveries(session_factory, endpoint_id=None):
    db = session_factory()
    try:
        q = db.query(WebhookDelivery)
        if endpoint_id:
            q = q.filter(WebhookDelivery.endpoint_id == endpoint_id)
        return [(r.id, r.event_id, r.status, r.error) for r in q.all()]
    finally:
        db.close()


def _inbound(session_factory, channel_id, phone_digits, wamid):
    return _process(session_factory, channel_id, _wa_payload(wamid=wamid, from_=phone_digits, text="hello"))


def _message_count(session_factory):
    db = session_factory()
    try:
        return db.query(ConversationMessage).count()
    finally:
        db.close()


@contextmanager
def _statements(session_factory):
    """Collect every SQL statement the engine runs inside the block."""
    db = session_factory()
    engine = db.get_bind()
    db.close()
    seen = []

    def _on(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", _on)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _on)


def _reads_table(statements, table):
    pat = re.compile(rf"\bFROM\s+(?:\w+\.)?{table}\b", re.IGNORECASE)
    return [s for s in statements if pat.search(s)]


def _foreign_tenant_workspace(session_factory):
    """A second real tenant with the module installed. Returns its workspace id."""
    from app.models import Tenant
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    db = session_factory()
    try:
        TenantService(db).provision(
            name="Beta",
            slug="beta-key-revoke",
            admin_name="Bea",
            admin_email="admin@beta-key-revoke.example.com",
            admin_password="pw12345678",
        )
        tenant = db.query(Tenant).filter(Tenant.slug == "beta-key-revoke").first()
        AppStoreService(db).install(tenant.id, "omnichannel")
        ws = (
            db.query(Workspace)
            .filter(Workspace.tenant_id == tenant.id, Workspace.is_default.is_(True))
            .first()
        )
        return tenant.id, ws.id
    finally:
        db.close()


def _foreign_key(session_factory, *, tenant_id, ws, name="Foreign key"):
    db = session_factory()
    try:
        row = WorkspaceApiKey(
            tenant_id=tenant_id,
            workspace_id=ws,
            name=name,
            key_prefix="zzzzzzzz",
            key_hash="0" * 64,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _deferred_revoke(client, session_factory, key_id, payload=_NO_BODY, *, lapse=True):
    """Park `api_keys.revoke` through the real route, then (when `lapse`) let the
    undo window close and commit it the way the sweep does. Returns
    (action id, final status)."""
    from app.deferred_actions.service import PendingActionService
    from app.models.pending_action import PendingAction

    body = {"actionKey": "api_keys.revoke", "entityType": "api_key", "entityId": key_id}
    if payload is not _NO_BODY:
        body["payload"] = payload
    res = client.post("/api/v1/pending-actions", json=body, headers=_auth(client))
    assert res.status_code == 202, res.text
    action_id = res.json()["id"]
    if not lapse:
        return action_id, "pending"
    db = session_factory()
    try:
        row = db.get(PendingAction, action_id)
        row.commit_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        done = PendingActionService(db).commit_one(row)
        return action_id, done.status
    finally:
        db.close()


def _rig(client, session_factory, *, ws=None):
    """A workspace with one live channel and one key. Returns a dict."""
    ws = ws or _default_workspace_id(session_factory)
    ch = _channel(session_factory, ws, name=f"wa-{ws[:6]}", age_rank=1)
    key_id, hdr = _key(client, ws, "K")
    return {"ws": ws, "ch": ch, "key": key_id, "hdr": hdr}


def _by(key_id):
    return f"apikey:{key_id}"


def _staff_list_channel(client, channel_id):
    res = client.get(f"{STAFF}/channels/{channel_id}/webhooks", headers=_auth(client))
    assert res.status_code == 200, res.text
    return res.json()["data"]


# ═════════════════════════════════════════════════════════════════════════════
# AC-43-01 - key list carries the count of ACTIVE endpoints the key made
# ═════════════════════════════════════════════════════════════════════════════
def _key_list(client, ws):
    res = client.get(f"{STAFF}/workspaces/{ws}/api-keys", headers=_auth(client))
    assert res.status_code == 200, res.text
    return {k["id"]: k for k in res.json()["data"]}


def test_ac_43_01_count_is_active_endpoints_the_key_made(client, session_factory):
    r = _rig(client, session_factory)
    ws, ch, a = r["ws"], r["ch"], r["key"]
    b, _ = _key(client, ws, "B")
    c, _ = _key(client, ws, "C")
    sibling = _new_workspace(session_factory, "Sibling")
    _, foreign_ws = _foreign_tenant_workspace(session_factory)
    foreign_tenant = FOREIGN_TENANT

    _insert(session_factory, ws=ws, created_by=_by(a))  # counts: all-channels ACTIVE
    _insert(session_factory, ws=ws, created_by=_by(a), channel_id=ch)  # counts: older per-channel row
    _insert(session_factory, ws=ws, created_by=_by(a), status="DISABLED", reason="Disabled by user.", disabled_at=OLD)
    _insert(session_factory, ws=ws, created_by=_by(a), status="AUTO_DISABLED", reason="auto", disabled_at=OLD)
    _insert(session_factory, ws=ws, created_by=_by(b))  # another key's row
    _insert(session_factory, ws=ws, created_by="a-staff-user-id")  # staff row
    _insert(session_factory, ws=ws, created_by=None)  # row with no creator
    _insert(session_factory, ws=sibling, created_by=_by(a))  # same text, sibling workspace
    _insert(session_factory, ws=ws, created_by=_by(a), tenant_id=foreign_tenant)  # same text, other tenant

    items = _key_list(client, ws)
    observed = {k: items[k].get("webhookEndpointCount") for k in (a, b, c)}
    assert observed == {a: 2, b: 1, c: 0}, observed


def test_ac_43_01_count_does_not_add_a_query_per_key(client, session_factory):
    r = _rig(client, session_factory)
    ws = r["ws"]
    _insert(session_factory, ws=ws, created_by=_by(r["key"]))
    headers = _auth(client)

    def run():
        with _statements(session_factory) as seen:
            res = client.get(f"{STAFF}/workspaces/{ws}/api-keys", headers=headers)
        assert res.status_code == 200, res.text
        return len(seen), res.json()["data"]

    few_statements, few_items = run()
    for i in range(5):
        extra, _ = _key(client, ws, f"extra-{i}")
        _insert(session_factory, ws=ws, created_by=_by(extra))
    many_statements, many_items = run()

    observed = {
        "grew": many_statements - few_statements,
        "has_count": all("webhookEndpointCount" in k for k in many_items),
        "items": len(many_items),
    }
    assert observed == {"grew": 0, "has_count": True, "items": 6}, observed


# ═════════════════════════════════════════════════════════════════════════════
# AC-43-02 - revoke with pauseEndpoints true
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_43_02_revoke_pauses_only_this_keys_active_endpoints(client, session_factory):
    r = _rig(client, session_factory)
    ws, ch, k = r["ws"], r["ch"], r["key"]
    other, _ = _key(client, ws, "Other")
    ids = {
        "mine_all": _insert(session_factory, ws=ws, created_by=_by(k)),
        "mine_old_channel": _insert(session_factory, ws=ws, created_by=_by(k), channel_id=ch),
        "other_key": _insert(session_factory, ws=ws, created_by=_by(other)),
        "staff": _insert(session_factory, ws=ws, created_by="a-staff-user-id"),
        "paused": _insert(
            session_factory, ws=ws, created_by=_by(k), status="DISABLED", reason="Disabled by user.", disabled_at=OLD
        ),
        "auto": _insert(
            session_factory,
            ws=ws,
            created_by=_by(k),
            status="AUTO_DISABLED",
            reason="Auto-disabled after 10 failed deliveries.",
            disabled_at=OLD,
            failures=10,
        ),
    }
    untouched = {n: _state(session_factory, ids[n]) for n in ("other_key", "staff", "paused", "auto")}

    res = _revoke(client, ws, k, {"pauseEndpoints": True})
    assert res.status_code == 200 and res.json()["status"] == "REVOKED", res.text  # control: the key is revoked

    assert {n: _state(session_factory, ids[n]) for n in untouched} == untouched
    for name in ("mine_all", "mine_old_channel"):
        s = _state(session_factory, ids[name])
        assert s["status"] == "DISABLED", (name, s)
        assert s["disabled_at"] is not None, (name, s)
        assert "revoked" in (s["reason"] or "").lower(), (name, s)


def test_ac_43_02_pause_and_revoke_are_one_commit(client, session_factory, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from modules.omnichannel.services.webhook_service import WebhookService

    r = _rig(client, session_factory)
    ws, k = r["ws"], r["key"]
    ep = _insert(session_factory, ws=ws, created_by=_by(k))

    def boom(self, *args, **kwargs):
        raise RuntimeError("pause step failed")

    # raising=False: the method does not exist yet, so the test fails on the
    # assertions below (the key is revoked), not on the patch.
    monkeypatch.setattr(WebhookService, "pause_for_key", boom, raising=False)
    quiet = TestClient(app, raise_server_exceptions=False)  # keeps the dependency override set by `client`
    res = quiet.post(
        f"{STAFF}/workspaces/{ws}/api-keys/{k}/revoke", headers=_auth(client), json={"pauseEndpoints": True}
    )

    observed = {
        "revoked": _revoked(session_factory, k),
        "endpoint": _state(session_factory, ep)["status"],
        "key_still_signs_in": client.get(f"{BASE}/channels", headers=r["hdr"]).status_code,
        "answered_ok": res.status_code == 200,
    }
    assert observed == {"revoked": False, "endpoint": "ACTIVE", "key_still_signs_in": 200, "answered_ok": False}, observed


# ═════════════════════════════════════════════════════════════════════════════
# AC-43-03 - pauseEndpoints false
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_43_03_revoke_without_pausing_changes_no_endpoint(client, session_factory):
    """Passes today: revoke never touches an endpoint. Kept as the control for 02."""
    r = _rig(client, session_factory)
    ws, k = r["ws"], r["key"]
    ids = {
        "a": _insert(session_factory, ws=ws, created_by=_by(k)),
        "b": _insert(session_factory, ws=ws, created_by=_by(k), channel_id=r["ch"]),
    }
    before = {n: _state(session_factory, i) for n, i in ids.items()}
    res = _revoke(client, ws, k, {"pauseEndpoints": False})
    assert res.status_code == 200 and res.json()["status"] == "REVOKED", res.text
    assert _revoked(session_factory, k) is True
    assert {n: _state(session_factory, i) for n, i in ids.items()} == before


# ═════════════════════════════════════════════════════════════════════════════
# AC-43-04 - default is to pause; a non-boolean counts as true
# ═════════════════════════════════════════════════════════════════════════════
ROUTE_BODIES = {
    "no_body": _NO_BODY,
    "empty_object": {},
    "null": {"pauseEndpoints": None},
    "string_false": {"pauseEndpoints": "false"},
    "zero": {"pauseEndpoints": 0},
    "empty_string": {"pauseEndpoints": ""},
}


@pytest.mark.parametrize("name", list(ROUTE_BODIES))
def test_ac_43_04_route_pauses_unless_the_value_is_boolean_false(client, session_factory, name):
    r = _rig(client, session_factory)
    ws, k = r["ws"], r["key"]
    ep = _insert(session_factory, ws=ws, created_by=_by(k))
    res = _revoke(client, ws, k, ROUTE_BODIES[name])
    observed = {
        "status": res.status_code,
        "revoked": _revoked(session_factory, k),
        "endpoint": _state(session_factory, ep)["status"],
    }
    assert observed == {"status": 200, "revoked": True, "endpoint": "DISABLED"}, (name, observed, res.text)


DEFERRED_PAYLOADS = {
    "no_payload": _NO_BODY,
    "empty_payload": {},
    "null": {"pauseEndpoints": None},
    "string_false": {"pauseEndpoints": "false"},
    "zero": {"pauseEndpoints": 0},
    "true": {"pauseEndpoints": True},
}


@pytest.mark.parametrize("name", list(DEFERRED_PAYLOADS))
def test_ac_43_04_deferred_action_pauses_unless_the_value_is_boolean_false(client, session_factory, name):
    r = _rig(client, session_factory)
    ws, k = r["ws"], r["key"]
    ep = _insert(session_factory, ws=ws, created_by=_by(k))
    _, done = _deferred_revoke(client, session_factory, k, DEFERRED_PAYLOADS[name])
    observed = {"done": done, "revoked": _revoked(session_factory, k), "endpoint": _state(session_factory, ep)["status"]}
    assert observed == {"done": "committed", "revoked": True, "endpoint": "DISABLED"}, (name, observed)


# ═════════════════════════════════════════════════════════════════════════════
# AC-43-05 - the deferred action: false, cancel, repeat
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_43_05_deferred_false_revokes_and_changes_no_endpoint(client, session_factory):
    """Passes today (control for the pause cases above)."""
    r = _rig(client, session_factory)
    ws, k = r["ws"], r["key"]
    ep = _insert(session_factory, ws=ws, created_by=_by(k))
    before = _state(session_factory, ep)
    _, done = _deferred_revoke(client, session_factory, k, {"pauseEndpoints": False})
    assert done == "committed"
    assert _revoked(session_factory, k) is True
    assert _state(session_factory, ep) == before


def test_ac_43_05_cancel_in_the_window_changes_neither_key_nor_endpoints(client, session_factory):
    """Passes today (nothing runs before the window closes). Control."""
    r = _rig(client, session_factory)
    ws, k = r["ws"], r["key"]
    ep = _insert(session_factory, ws=ws, created_by=_by(k))
    before = _state(session_factory, ep)
    action_id, _ = _deferred_revoke(client, session_factory, k, {"pauseEndpoints": True}, lapse=False)
    cancel = client.post(f"/api/v1/pending-actions/{action_id}/cancel", headers=_auth(client))
    assert cancel.status_code == 200 and cancel.json()["status"] == "cancelled", cancel.text
    assert _revoked(session_factory, k) is False
    assert _state(session_factory, ep) == before


def test_ac_43_05_revoking_twice_by_route_pauses_nothing_further(client, session_factory):
    r = _rig(client, session_factory)
    ws, k = r["ws"], r["key"]
    ep = _insert(session_factory, ws=ws, created_by=_by(k))
    first = _revoke(client, ws, k, {"pauseEndpoints": True})
    assert first.status_code == 200, first.text
    after_first = _state(session_factory, ep)["status"]
    revoked_at = first.json()["revokedAt"]

    # a staff user resumes the endpoint between the two revokes
    resumed = client.post(f"{STAFF}/webhooks/{ep}/enable", headers=_auth(client))
    assert resumed.status_code == 200, resumed.text
    second = _revoke(client, ws, k, {"pauseEndpoints": True})
    observed = {
        "second_status": second.status_code,
        "after_second": _state(session_factory, ep)["status"],
        "revoked_at_unchanged": second.json().get("revokedAt") == revoked_at,
        "after_first": after_first,
    }
    assert observed == {
        "second_status": 200,
        "after_second": "ACTIVE",
        "revoked_at_unchanged": True,
        "after_first": "DISABLED",
    }, observed


def test_ac_43_05_revoking_twice_by_deferred_action_pauses_nothing_further(client, session_factory):
    r = _rig(client, session_factory)
    ws, k = r["ws"], r["key"]
    ep = _insert(session_factory, ws=ws, created_by=_by(k))
    _, first = _deferred_revoke(client, session_factory, k, {"pauseEndpoints": True})
    after_first = _state(session_factory, ep)["status"]
    resumed = client.post(f"{STAFF}/webhooks/{ep}/enable", headers=_auth(client))
    assert resumed.status_code == 200, resumed.text
    _, second = _deferred_revoke(client, session_factory, k, {"pauseEndpoints": True})
    observed = {
        "first": first,
        "second": second,
        "after_first": after_first,
        "after_second": _state(session_factory, ep)["status"],
    }
    assert observed == {"first": "committed", "second": "committed", "after_first": "DISABLED", "after_second": "ACTIVE"}, observed


# ═════════════════════════════════════════════════════════════════════════════
# AC-43-06 - found by tenant, workspace and exact apikey:<id>
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_43_06_lookalike_rows_are_not_paused(client, session_factory):
    r = _rig(client, session_factory)
    ws, k = r["ws"], r["key"]
    same_name, _ = _key(client, ws, "K")  # a second key with the same name
    sibling = _new_workspace(session_factory, "Sibling")
    _, foreign_ws = _foreign_tenant_workspace(session_factory)
    ids = {
        "mine": _insert(session_factory, ws=ws, created_by=_by(k)),
        "same_name_key": _insert(session_factory, ws=ws, created_by=_by(same_name)),
        "foreign_tenant_same_text": _insert(session_factory, ws=ws, created_by=_by(k), tenant_id=FOREIGN_TENANT),
        "foreign_real_tenant_same_text": _insert(
            session_factory, ws=foreign_ws, created_by=_by(k), tenant_id=_foreign_tenant_id(session_factory, foreign_ws)
        ),
        "sibling_workspace_same_text": _insert(session_factory, ws=sibling, created_by=_by(k)),
        "longer_id": _insert(session_factory, ws=ws, created_by=_by(k) + "-2"),
        "shorter_id": _insert(session_factory, ws=ws, created_by=_by(k)[:-1]),
    }
    res = _revoke(client, ws, k, {"pauseEndpoints": True})
    assert res.status_code == 200, res.text
    observed = _statuses(session_factory, ids)
    assert observed == {
        "mine": "DISABLED",  # control: the revoke reached its own row
        "same_name_key": "ACTIVE",
        "foreign_tenant_same_text": "ACTIVE",
        "foreign_real_tenant_same_text": "ACTIVE",
        "sibling_workspace_same_text": "ACTIVE",
        "longer_id": "ACTIVE",
        "shorter_id": "ACTIVE",
    }, observed


def _foreign_tenant_id(session_factory, workspace_id):
    db = session_factory()
    try:
        return db.query(Workspace).filter(Workspace.id == workspace_id).one().tenant_id
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# AC-43-07 - a paused endpoint gets nothing, a new key resumes it
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_43_07_paused_endpoint_gets_no_event_and_a_new_key_resumes_it(client, session_factory):
    ws = _default_workspace_id(session_factory)
    ch = _channel(session_factory, ws, name="wa-resume", age_rank=1)
    old_id, old_hdr = _key(client, ws, "old")
    _new_id, new_hdr = _key(client, ws, "new")
    ep, _ = _register_all(client, old_hdr, ["message.inbound"], expect_null=True)

    assert _inbound(session_factory, ch, "60111700001", "wamid.43-07-a")["messages"] == 1
    assert len(_deliveries(session_factory, ep)) == 1  # control: an active endpoint is fed

    assert _revoke(client, ws, old_id, {"pauseEndpoints": True}).status_code == 200
    assert _inbound(session_factory, ch, "60111700002", "wamid.43-07-b")["messages"] == 1
    during = len(_deliveries(session_factory, ep))

    resumed = client.post(f"{BASE}/webhooks/{ep}/enable", headers=new_hdr)
    assert resumed.status_code == 200, resumed.text
    item = resumed.json()
    assert _inbound(session_factory, ch, "60111700003", "wamid.43-07-c")["messages"] == 1
    observed = {
        "while_paused": during,
        "resumed_status": item["status"],
        "reason_cleared": item["disabledReason"] is None and item["disabledAt"] is None,
        "after_resume": len(_deliveries(session_factory, ep)),
    }
    assert observed == {"while_paused": 1, "resumed_status": "ACTIVE", "reason_cleared": True, "after_resume": 2}, observed


# ═════════════════════════════════════════════════════════════════════════════
# AC-43-10 / 11 - who made it
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_43_10_staff_channel_list_names_the_key(client, session_factory):
    r = _rig(client, session_factory)
    ws, ch, k = r["ws"], r["ch"], r["key"]
    revoked_id, _ = _key(client, ws, "Retired key")
    sibling = _new_workspace(session_factory, "Sibling")
    sibling_key = _foreign_key(session_factory, tenant_id=DEFAULT_TENANT_ID, ws=sibling, name="Sibling key")
    foreign_key = _foreign_key(session_factory, tenant_id=FOREIGN_TENANT, ws=sibling, name="Foreign key")
    ids = {
        "live_key": _insert(session_factory, ws=ws, created_by=_by(k)),
        "revoked_key": _insert(session_factory, ws=ws, created_by=_by(revoked_id), channel_id=ch),
        "staff": _insert(session_factory, ws=ws, created_by="a-staff-user-id"),
        "no_creator": _insert(session_factory, ws=ws, created_by=None),
        "key_gone": _insert(session_factory, ws=ws, created_by="apikey:no-such-key"),
        "key_of_sibling_workspace": _insert(session_factory, ws=ws, created_by=_by(sibling_key)),
        "key_of_other_tenant": _insert(session_factory, ws=ws, created_by=_by(foreign_key)),
    }
    assert _revoke(client, ws, revoked_id, {"pauseEndpoints": False}).status_code == 200

    items = {i["id"]: i for i in _staff_list_channel(client, ch)}
    assert all("registeredByKeyName" in i for i in items.values()), items
    observed = {n: items[i].get("registeredByKeyName") for n, i in ids.items()}
    assert observed == {
        "live_key": "K",
        "revoked_key": "Retired key",
        "staff": None,
        "no_creator": None,
        "key_gone": None,
        "key_of_sibling_workspace": None,
        "key_of_other_tenant": None,
    }, observed


def test_ac_43_10_public_endpoint_item_has_no_such_field(client, session_factory):
    """Passes today. Control: the public item stays as it is."""
    r = _rig(client, session_factory)
    _insert(session_factory, ws=r["ws"], created_by=_by(r["key"]))
    res = client.get(f"{BASE}/webhooks", headers=r["hdr"])
    assert res.status_code == 200, res.text
    items = res.json()["data"]
    assert items, "the key's row is listed"  # control: something to inspect
    assert all("registeredByKeyName" not in i for i in items)
    made = _register_all(client, r["hdr"], ["message.inbound"])  # the create response too
    created = client.get(f"{BASE}/webhooks", headers=r["hdr"]).json()["data"]
    assert made and all("registeredByKeyName" not in i for i in created)


def test_ac_43_11_staff_channel_list_does_not_query_per_row(client, session_factory):
    r = _rig(client, session_factory)
    ws, ch = r["ws"], r["ch"]
    _insert(session_factory, ws=ws, created_by=_by(r["key"]))
    headers = _auth(client)

    def run():
        with _statements(session_factory) as seen:
            res = client.get(f"{STAFF}/channels/{ch}/webhooks", headers=headers)
        assert res.status_code == 200, res.text
        return len(seen), res.json()["data"]

    few_statements, _ = run()
    for i in range(5):
        extra, _ = _key(client, ws, f"extra-{i}")
        _insert(session_factory, ws=ws, created_by=_by(extra))
        _insert(session_factory, ws=ws, created_by="a-staff-user-id", channel_id=ch)
    many_statements, many = run()

    named = [i.get("registeredByKeyName") for i in many]
    observed = {"grew": many_statements - few_statements, "rows": len(many), "named": sum(1 for n in named if n)}
    assert observed == {"grew": 0, "rows": 11, "named": 6}, observed


def test_ac_43_11_workspace_list_does_not_query_per_row(client, session_factory):
    r = _rig(client, session_factory)
    ws = r["ws"]
    _insert(session_factory, ws=ws, created_by=_by(r["key"]))
    headers = _auth(client)

    def run():
        with _statements(session_factory) as seen:
            res = client.get(f"{STAFF}/workspaces/{ws}/webhooks", headers=headers)
        assert res.status_code == 200, res.text
        return len(seen), res.json()["data"]

    few_statements, _ = run()
    for i in range(5):
        extra, _ = _key(client, ws, f"extra-{i}")
        _insert(session_factory, ws=ws, created_by=_by(extra))
    many_statements, many = run()
    observed = {"grew": many_statements - few_statements, "rows": len(many), "named": sum(1 for i in many if i.get("registeredByKeyName"))}
    assert observed == {"grew": 0, "rows": 6, "named": 6}, observed


# ═════════════════════════════════════════════════════════════════════════════
# AC-43-20 / 21 - workspace-level staff list
# ═════════════════════════════════════════════════════════════════════════════
def _disconnect_every_channel(session_factory, ws):
    db = session_factory()
    try:
        for ch in db.query(Channel).filter(Channel.workspace_id == ws).all():
            ch.is_trashed = True
            ch.is_active = False
        db.commit()
    finally:
        db.close()


def test_ac_43_20_workspace_list_returns_per_channel_and_all_channel_rows_with_no_live_channel(client, session_factory):
    r = _rig(client, session_factory)
    ws, ch, k = r["ws"], r["ch"], r["key"]
    sibling = _new_workspace(session_factory, "Sibling")
    ids = {
        "by_key": _insert(session_factory, ws=ws, created_by=_by(k)),
        "by_staff": _insert(session_factory, ws=ws, created_by="a-staff-user-id", name="staff row"),
        "paused": _insert(session_factory, ws=ws, created_by=_by(k), status="DISABLED", reason="r", disabled_at=OLD),
    }
    per_channel = _insert(session_factory, ws=ws, created_by=_by(k), channel_id=ch, name="per channel")
    ids["per_channel"] = per_channel
    excluded = {
        "sibling_workspace": _insert(session_factory, ws=sibling, created_by=_by(k)),
        "other_tenant_same_workspace_id": _insert(session_factory, ws=ws, created_by=_by(k), tenant_id=FOREIGN_TENANT),
    }
    _disconnect_every_channel(session_factory, ws)

    res = client.get(f"{STAFF}/workspaces/{ws}/webhooks", headers=_auth(client))
    assert res.status_code == 200, res.text
    listed = {i["id"]: i for i in res.json()["data"]}
    assert set(listed) == set(ids.values()), {"listed": sorted(listed), "excluded": excluded}
    assert listed[per_channel]["channelId"] == ch
    assert all(i["channelId"] is None for i in listed.values() if i["id"] != per_channel)
    assert listed[ids["by_key"]]["registeredByKeyName"] == "K"
    assert listed[ids["by_staff"]]["registeredByKeyName"] is None


def test_ac_43_20_a_per_channel_row_on_a_disconnected_channel_is_listed_and_can_be_paused(client, session_factory):
    r = _rig(client, session_factory)
    ws, ch = r["ws"], r["ch"]
    ep = _insert(session_factory, ws=ws, created_by=_by(r["key"]), channel_id=ch, name="on a gone channel")
    _disconnect_every_channel(session_factory, ws)
    h = _auth(client)

    listed = client.get(f"{STAFF}/workspaces/{ws}/webhooks", headers=h)
    assert listed.status_code == 200, listed.text
    assert [i["id"] for i in listed.json()["data"]] == [ep]
    paused = client.post(f"{STAFF}/webhooks/{ep}/disable", headers=h)
    assert paused.status_code == 200 and paused.json()["status"] == "DISABLED", paused.text
    assert _state(session_factory, ep)["status"] == "DISABLED"


def test_ac_43_20_another_tenants_workspace_is_404_and_the_permission_is_read(client, session_factory):
    r = _rig(client, session_factory)
    ws = r["ws"]
    _tenant, foreign_ws = _foreign_tenant_workspace(session_factory)
    from tests.test_omnichannel_inbox_views import _limited_role_auth

    own = client.get(f"{STAFF}/workspaces/{ws}/webhooks", headers=_auth(client))
    assert own.status_code == 200, own.text  # control: the route exists for an own workspace
    foreign = client.get(f"{STAFF}/workspaces/{foreign_ws}/webhooks", headers=_auth(client))
    assert foreign.status_code == 404, foreign.text

    no_perm, _ = _limited_role_auth(
        client, session_factory, keys=["conversations.read"], email="wh-noperm-43@example.com"
    )
    denied = client.get(f"{STAFF}/workspaces/{ws}/webhooks", headers=no_perm)
    assert denied.status_code == 403, denied.text
    reader, _ = _limited_role_auth(client, session_factory, keys=["webhooks.read"], email="wh-reader-43@example.com")
    allowed = client.get(f"{STAFF}/workspaces/{ws}/webhooks", headers=reader)
    assert allowed.status_code == 200, allowed.text


def test_ac_43_21_control_staff_actions_work_with_no_live_channel(client, session_factory):
    """Passes today: the per-id staff routes are tenant scoped, not channel scoped.
    Kept so a regression in them shows up next to the new list."""
    r = _rig(client, session_factory)
    ws = r["ws"]
    ep = _insert(session_factory, ws=ws, created_by=_by(r["key"]))
    _disconnect_every_channel(session_factory, ws)
    h = _auth(client)

    patched = client.patch(f"{STAFF}/webhooks/{ep}", headers=h, json={"name": "renamed"})
    assert patched.status_code == 200 and patched.json()["name"] == "renamed", patched.text
    rotated = client.post(f"{STAFF}/webhooks/{ep}/rotate", headers=h)
    assert rotated.status_code == 200 and rotated.json()["signingSecret"], rotated.text
    paused = client.post(f"{STAFF}/webhooks/{ep}/disable", headers=h)
    assert paused.status_code == 200 and paused.json()["status"] == "DISABLED", paused.text
    resumed = client.post(f"{STAFF}/webhooks/{ep}/enable", headers=h)
    assert resumed.status_code == 200 and resumed.json()["status"] == "ACTIVE", resumed.text
    log = client.get(f"{STAFF}/webhooks/{ep}/deliveries", headers=h)
    assert log.status_code == 200 and log.json()["data"] == [], log.text
    gone = client.delete(f"{STAFF}/webhooks/{ep}", headers=h)
    assert gone.status_code == 204, gone.text


def test_ac_43_21_rows_found_on_the_workspace_list_can_be_managed_there(client, session_factory):
    r = _rig(client, session_factory)
    ws = r["ws"]
    _insert(session_factory, ws=ws, created_by=_by(r["key"]))
    _disconnect_every_channel(session_factory, ws)
    h = _auth(client)

    listed = client.get(f"{STAFF}/workspaces/{ws}/webhooks", headers=h)
    assert listed.status_code == 200, listed.text
    row = listed.json()["data"][0]
    ep = row["id"]
    assert client.post(f"{STAFF}/webhooks/{ep}/disable", headers=h).json()["status"] == "DISABLED"
    again = client.get(f"{STAFF}/workspaces/{ws}/webhooks", headers=h).json()["data"]
    assert [(i["id"], i["status"]) for i in again] == [(ep, "DISABLED")]  # paused rows stay listed
    assert client.patch(f"{STAFF}/webhooks/{ep}", headers=h, json={"name": "edited"}).status_code == 200
    assert client.delete(f"{STAFF}/webhooks/{ep}", headers=h).status_code == 204
    assert client.get(f"{STAFF}/workspaces/{ws}/webhooks", headers=h).json()["data"] == []


# ═════════════════════════════════════════════════════════════════════════════
# AC-43-30 / 31 / 32 - delivery follows the workspace and tenant state
# ═════════════════════════════════════════════════════════════════════════════
def _suspend_tenant(sf):
    from app.services.tenant_service import TenantService

    db = sf()
    try:
        TenantService(db).suspend(DEFAULT_TENANT_ID)
    finally:
        db.close()

    def restore():
        d = sf()
        try:
            TenantService(d).reactivate(DEFAULT_TENANT_ID)
        finally:
            d.close()

    return restore


def _deactivate_module(sf):
    from app.services.app_store_service import AppStoreService

    db = sf()
    try:
        AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
    finally:
        db.close()

    def restore():
        d = sf()
        try:
            AppStoreService(d).reactivate(DEFAULT_TENANT_ID, "omnichannel")
        finally:
            d.close()

    return restore


def _trash_workspace_of(ws):
    def enter(sf):
        from modules.omnichannel.services.workspace_service import WorkspaceService

        db = sf()
        try:
            WorkspaceService(db).trash([ws], DEFAULT_TENANT_ID)
        finally:
            db.close()

        def restore():
            d = sf()
            try:
                WorkspaceService(d).restore([ws], DEFAULT_TENANT_ID)
            finally:
                d.close()

        return restore

    return enter


STATES = ["tenant_suspended", "module_inactive", "workspace_trashed"]


def _enter_state(name, sf, ws):
    if name == "tenant_suspended":
        return _suspend_tenant(sf)
    if name == "module_inactive":
        return _deactivate_module(sf)
    return _trash_workspace_of(ws)(sf)


def _off_rig(client, session_factory, events=("message.inbound", "message.outbound", "contact.updated")):
    """A non-default workspace (so it can be trashed) with a channel, a key and
    one all-channels endpoint."""
    ws = _new_workspace(session_factory, "Delivery")
    ch = _channel(session_factory, ws, name="wa-off", age_rank=1)
    key_id, hdr = _key(client, ws, "K")
    ep, _ = _register_all(client, hdr, list(events), expect_null=True)
    return {"ws": ws, "ch": ch, "key": key_id, "hdr": hdr, "ep": ep}


def _workspace_event(session_factory, ws, event_id):
    db = session_factory()
    try:
        return wd.enqueue_workspace_event(
            db, DEFAULT_TENANT_ID, ws, "contact.updated", event_id, {"contact": {"id": "c-43"}}
        )
    finally:
        db.close()


@pytest.mark.parametrize("state", STATES)
def test_ac_43_30_no_event_is_queued_while_the_workspace_is_off(client, session_factory, state):
    r = _off_rig(client, session_factory)
    restore = _enter_state(state, session_factory, r["ws"])
    try:
        # The inbound pipeline itself may refuse in some states (module inactive
        # stores nothing); the channel event is therefore also fed straight to the
        # real producer, so the assertion never rests on the pipeline alone.
        _inbound(session_factory, r["ch"], "60111800001", f"wamid.43-30-{state}")
        db = session_factory()
        try:
            channel = db.query(Channel).filter(Channel.id == r["ch"]).one()
            direct_queued = wd.enqueue_event(
                db, channel, "message.inbound", f"evt-direct-{state}", {"message": {"id": "m-43"}}
            )
        finally:
            db.close()
        queued_for_workspace = _workspace_event(session_factory, r["ws"], f"evt-43-30-{state}")
        observed = {
            "channel_event_rows": _deliveries(session_factory, r["ep"]),
            "direct_channel_event_queued": direct_queued,
            "workspace_event_queued": queued_for_workspace,
        }
    finally:
        restore()
    assert observed == {
        "channel_event_rows": [],
        "direct_channel_event_queued": 0,
        "workspace_event_queued": 0,
    }, observed


def test_ac_43_30_control_normal_state_queues_both_events(client, session_factory):
    """Passes today. Control for the three states above."""
    r = _off_rig(client, session_factory)
    _inbound(session_factory, r["ch"], "60111800002", "wamid.43-30-control")
    assert _workspace_event(session_factory, r["ws"], "evt-43-30-control") == 1
    kinds = sorted(ev for (_i, ev, _s, _e) in _deliveries(session_factory, r["ep"]))
    assert kinds == sorted(["wamid.43-30-control", "evt-43-30-control"])


def test_ac_43_30_the_state_is_checked_only_when_an_endpoint_subscribes(client, session_factory):
    ws = _new_workspace(session_factory, "Quiet")
    ch = _channel(session_factory, ws, name="wa-quiet", age_rank=1)
    key_id, hdr = _key(client, ws, "K")

    db = session_factory()
    try:
        with _statements(session_factory) as seen:
            queued = wd.enqueue_workspace_event(db, DEFAULT_TENANT_ID, ws, "contact.updated", "evt-quiet", {"contact": {}})
        no_subscriber = {
            "queued": queued,
            "tenant_reads": len(_reads_table(seen, "tenants")),
            "workspace_reads": len(_reads_table(seen, "workspaces")),
        }
    finally:
        db.close()
    # control half, passes today: nothing is read beyond the endpoint lookup
    assert no_subscriber == {"queued": 0, "tenant_reads": 0, "workspace_reads": 0}, no_subscriber

    _register_all(client, hdr, ["contact.updated"], expect_null=True)
    db = session_factory()
    try:
        with _statements(session_factory) as seen:
            queued = wd.enqueue_workspace_event(db, DEFAULT_TENANT_ID, ws, "contact.updated", "evt-sub", {"contact": {}})
        with_subscriber = {"queued": queued, "tenant_reads": len(_reads_table(seen, "tenants"))}
    finally:
        db.close()
    assert with_subscriber["queued"] == 1, with_subscriber
    assert with_subscriber["tenant_reads"] >= 1, with_subscriber  # the state check ran, once an endpoint subscribed
    assert key_id and ch


@pytest.mark.parametrize("state", STATES)
def test_ac_43_31_queued_delivery_is_not_sent_while_the_workspace_is_off(client, session_factory, monkeypatch, state):
    r = _off_rig(client, session_factory)
    _inbound(session_factory, r["ch"], "60111800011", f"wamid.43-31-a-{state}")
    _inbound(session_factory, r["ch"], "60111800012", f"wamid.43-31-b-{state}")
    queued = [d[0] for d in _deliveries(session_factory, r["ep"])]
    assert len(queued) == 2  # control: both rows were queued while the workspace was on

    db = session_factory()
    try:
        ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == r["ep"]).one()
        ep.consecutive_failures = 3
        db.commit()
    finally:
        db.close()

    calls = []
    monkeypatch.setattr(
        wd, "_post", lambda url, *, content, headers, timeout: calls.append(url) or _Resp(200)
    )
    monkeypatch.setattr(wd, "assert_deliverable", lambda url: None)
    restore = _enter_state(state, session_factory, r["ws"])
    try:
        db = session_factory()
        try:
            for delivery_id in queued:
                wd.dispatch(db, delivery_id)
        finally:
            db.close()
    finally:
        restore()

    rows = _deliveries(session_factory, r["ep"])
    errors = {e for (_i, _ev, _s, e) in rows}
    observed = {
        "http_calls": len(calls),
        "statuses": sorted(s for (_i, _ev, s, _e) in rows),
        "one_fixed_text": len(errors) == 1 and None not in errors and "" not in errors,
        "no_transport_detail": not any(("Consumer returned" in (e or "") or "Delivery failed" in (e or "")) for e in errors),
        "endpoint": _state(session_factory, r["ep"]),
    }
    endpoint = observed.pop("endpoint")
    assert observed == {
        "http_calls": 0,
        "statuses": ["FAILED", "FAILED"],
        "one_fixed_text": True,
        "no_transport_detail": True,
    }, observed
    assert endpoint["failures"] == 3 and endpoint["status"] == "ACTIVE", endpoint


def test_ac_43_31_control_normal_state_dispatch_sends(client, session_factory, monkeypatch):
    """Passes today. Control: the same rig sends while the workspace is on."""
    r = _off_rig(client, session_factory)
    _inbound(session_factory, r["ch"], "60111800013", "wamid.43-31-control")
    (delivery_id, *_rest) = _deliveries(session_factory, r["ep"])[0]
    calls = []
    monkeypatch.setattr(
        wd, "_post", lambda url, *, content, headers, timeout: calls.append(url) or _Resp(200)
    )
    monkeypatch.setattr(wd, "assert_deliverable", lambda url: None)
    db = session_factory()
    try:
        assert wd.dispatch(db, delivery_id) == "success"
    finally:
        db.close()
    assert len(calls) == 1
    assert [s for (_i, _e, s, _x) in _deliveries(session_factory, r["ep"])] == ["SUCCESS"]


def test_ac_43_32_a_failing_state_check_never_reaches_inbound_or_send(client, session_factory, monkeypatch):
    """The check is patched on `webhook_delivery`, the module `_fan_out` lives in
    and the seam the plan names ("`gateway_key_enabled` in `_fan_out`"). If the
    move to the service layer changes where the code reads it, the patch target
    moves with it; the `calls` assertion fails (not the patch) until it does."""
    ws = _default_workspace_id(session_factory)
    ch = _channel(session_factory, ws, name="wa-boom", age_rank=1)
    _key_id, hdr = _key(client, ws, "K")
    _register_all(client, hdr, ["message.inbound", "message.outbound"], expect_null=True)
    contact = _seed_contact(session_factory, ws, "+60111800021")

    calls = []

    def boom(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("state check exploded")

    monkeypatch.setattr(wd, "gateway_key_enabled", boom, raising=False)

    messages_before = _message_count(session_factory)
    out = _inbound(session_factory, ch, "60111800022", "wamid.43-32")
    sent = client.post(
        f"{BASE}/messages",
        json={"to": "+60111800021", "type": "text", "text": {"body": "hi"}, "channelId": ch},
        headers=hdr,
    )
    observed = {
        "inbound_messages": out["messages"],
        "inbound_stored": _message_count(session_factory) - messages_before >= 1,
        "send_status": sent.status_code,
        "state_check_ran_inside_fan_out": len(calls) >= 1,
    }
    assert observed == {
        "inbound_messages": 1,
        "inbound_stored": True,
        "send_status": 202,
        "state_check_ran_inside_fan_out": True,
    }, (observed, sent.text)
    assert contact


def _seed_contact(session_factory, ws, phone):
    from tests.test_omnichannel_api_gateway import _seed_open_contact

    return _seed_open_contact(session_factory, ws, phone=phone, open_window=True)


def test_ac_43_11_key_name_is_not_read_from_another_tenant(client, session_factory):
    """A key row of ANOTHER tenant that carries this workspace's id text must not
    name a row of this tenant, even though its workspace text matches."""
    r = _rig(client, session_factory)
    ws, ch = r["ws"], r["ch"]
    other_tenant_key = _foreign_key(session_factory, tenant_id=FOREIGN_TENANT, ws=ws, name="Other tenant key")
    own = _insert(session_factory, ws=ws, created_by=_by(r["key"]))
    named = _insert(session_factory, ws=ws, created_by=_by(other_tenant_key), channel_id=ch)

    items = {i["id"]: i for i in _staff_list_channel(client, ch)}
    observed = {
        "own_key": items[own].get("registeredByKeyName"),
        "other_tenant_key": items[named].get("registeredByKeyName"),
    }
    assert observed == {"own_key": "K", "other_tenant_key": None}, observed


# ═════════════════════════════════════════════════════════════════════════════
# AC-43-08 - a key write under way when the key is revoked
#
# The overlap itself (two database sessions interleaving on row locks) is only
# visible on Postgres; the lead proves it there. The suite runs on sqlite, which
# ignores row locks, so these tests pin what sqlite can show: the answer when the
# key is already revoked at the re-read, the order of the steps, and the lock
# requests made on the key row.
# ═════════════════════════════════════════════════════════════════════════════
NEW_HOOK = "https://hooks.example.com/changed"


def _revoke_on_another_session(session_factory, ws, key_id):
    from modules.omnichannel.services.api_key_service import ApiKeyService

    other = session_factory()
    try:
        ApiKeyService(other).revoke(key_id, DEFAULT_TENANT_ID, ws)
    finally:
        other.close()


def _revoke_during_url_check(monkeypatch, session_factory, ws, key_id, events=None):
    """The URL validator in webhook_service revokes the key (on another session)
    while it runs, then returns the URL unchanged."""
    from modules.omnichannel.services import webhook_service as ws_mod

    real = ws_mod.validate_callback_url

    def slow_check(url, **kw):
        if events is not None:
            events.append("url")
        clean = real(url, **kw)
        _revoke_on_another_session(session_factory, ws, key_id)
        return clean

    monkeypatch.setattr(ws_mod, "validate_callback_url", slow_check)


def _endpoint_count(session_factory, ws):
    db = session_factory()
    try:
        return db.query(WebhookEndpoint).filter(WebhookEndpoint.workspace_id == ws).count()
    finally:
        db.close()


def _url_of(session_factory, endpoint_id):
    db = session_factory()
    try:
        return db.query(WebhookEndpoint).filter(WebhookEndpoint.id == endpoint_id).one().url
    finally:
        db.close()


def test_ac_43_08_register_answers_401_when_the_key_is_revoked_during_the_url_check(
    client, session_factory, monkeypatch
):
    r = _rig(client, session_factory)
    _revoke_during_url_check(monkeypatch, session_factory, r["ws"], r["key"])

    res = client.post(
        f"{BASE}/webhooks", headers=r["hdr"], json={"name": "n", "url": NEW_HOOK, "events": ["message.inbound"]}
    )

    assert _revoked(session_factory, r["key"]) is True  # control: the revoke ran
    assert res.status_code == 401, res.text
    assert "signingSecret" not in res.text
    assert _endpoint_count(session_factory, r["ws"]) == 0


def test_ac_43_08_patch_answers_401_when_the_key_is_revoked_during_the_url_check(
    client, session_factory, monkeypatch
):
    r = _rig(client, session_factory)
    ep = _insert(session_factory, ws=r["ws"], created_by=_by(r["key"]))
    _revoke_during_url_check(monkeypatch, session_factory, r["ws"], r["key"])

    res = client.patch(f"{BASE}/webhooks/{ep}", headers=r["hdr"], json={"url": NEW_HOOK})

    assert _revoked(session_factory, r["key"]) is True  # control: the revoke ran
    assert res.status_code == 401, res.text
    assert _url_of(session_factory, ep) == HOOK


@pytest.fixture
def lock_spy(monkeypatch):
    """Record every `Query.with_for_update` call as (entity name, kwargs, position
    in a shared event list) and pass it through unchanged."""
    from sqlalchemy.orm import Query

    events = []
    real = Query.with_for_update

    def spy(self, **kw):
        entity = self.column_descriptions[0]["entity"]
        events.append(("lock", getattr(entity, "__name__", str(entity)), dict(kw)))
        return real(self, **kw)

    monkeypatch.setattr(Query, "with_for_update", spy)
    return events


def _key_locks(events):
    return [(i, e) for i, e in enumerate(events) if e[0] == "lock" and e[1] == "WorkspaceApiKey"]


def _write_call(name, client, r, ep):
    h = r["hdr"]
    if name == "register":
        return client.post(f"{BASE}/webhooks", headers=h, json={"name": "n", "url": NEW_HOOK, "events": ["message.inbound"]})
    if name == "patch":
        return client.patch(f"{BASE}/webhooks/{ep}", headers=h, json={"url": NEW_HOOK})
    if name == "rotate":
        return client.post(f"{BASE}/webhooks/{ep}/rotate", headers=h)
    return client.post(f"{BASE}/webhooks/{ep}/enable", headers=h)


@pytest.mark.parametrize("name", ["register", "patch", "rotate", "enable"])
def test_ac_43_08_each_key_write_rereads_the_key_row_under_a_key_row_lock(
    client, session_factory, monkeypatch, lock_spy, name
):
    r = _rig(client, session_factory)
    ep = _insert(session_factory, ws=r["ws"], created_by=_by(r["key"]), status="DISABLED", reason="x", disabled_at=OLD)
    from modules.omnichannel.services import webhook_service as ws_mod

    real = ws_mod.validate_callback_url

    def recording_check(url, **kw):
        lock_spy.append(("url",))
        return real(url, **kw)

    monkeypatch.setattr(ws_mod, "validate_callback_url", recording_check)

    res = _write_call(name, client, r, ep)

    assert res.status_code in (200, 201), res.text  # control: a live key still writes
    locks = _key_locks(lock_spy)
    assert locks, "no lock was taken on the key row"
    assert all(e[2].get("key_share") is True for _i, e in locks), locks
    urls = [i for i, e in enumerate(lock_spy) if e[0] == "url"]
    if name in ("register", "patch"):
        assert urls, "the URL check did not run"
        assert min(i for i, _e in locks) > max(urls), {"events": lock_spy}  # re-read after the URL check


def test_ac_43_08_revoke_locks_the_key_row_before_it_updates_it(client, session_factory, lock_spy):
    r = _rig(client, session_factory)
    key_id = r["key"]

    def on_sql(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE") and "workspace_api_keys" in statement:
            lock_spy.append(("update_key",))

    db = session_factory()
    engine = db.get_bind()
    db.close()
    event.listen(engine, "before_cursor_execute", on_sql)
    try:
        res = _revoke(client, r["ws"], key_id)
    finally:
        event.remove(engine, "before_cursor_execute", on_sql)

    assert res.status_code == 200, res.text
    update_at = [i for i, e in enumerate(lock_spy) if e[0] == "update_key"]
    assert update_at, "the key row was never updated"  # control: the update ran
    locks = _key_locks(lock_spy)
    assert locks, "revoke took no lock on the key row"
    assert locks[0][0] < update_at[0], lock_spy
    assert not locks[0][1][2].get("key_share"), locks[0]  # the revoke takes the plain row lock, not the lighter key-row lock the key writes take


@pytest.mark.parametrize("name", ["register", "patch", "rotate", "enable"])
def test_ac_43_08_a_key_revoked_after_the_first_check_answers_401_and_changes_nothing(
    client, session_factory, monkeypatch, name
):
    """The key passes the auth dependency, then is revoked on another session
    before the service runs (the seam is the first service-side call of each
    route). The re-read of the key row must then refuse the write."""
    from modules.omnichannel.routers import api_v1

    r = _rig(client, session_factory)
    ep = _insert(session_factory, ws=r["ws"], created_by=_by(r["key"]), status="DISABLED", reason="x", disabled_at=OLD)
    before = _state(session_factory, ep)

    if name == "register":
        from modules.omnichannel.services.webhook_service import WebhookService

        real = WebhookService.require_active_channel

        def seam(self, *a, **k):
            _revoke_on_another_session(session_factory, r["ws"], r["key"])
            return real(self, *a, **k)

        monkeypatch.setattr(WebhookService, "require_active_channel", seam)
    else:
        real_own = api_v1._own_endpoint

        def seam(db, api_ws, endpoint_id):
            _revoke_on_another_session(session_factory, r["ws"], r["key"])
            return real_own(db, api_ws, endpoint_id)

        monkeypatch.setattr(api_v1, "_own_endpoint", seam)

    res = _write_call(name, client, r, ep)

    assert _revoked(session_factory, r["key"]) is True  # control: the revoke ran
    assert res.status_code == 401, res.text
    assert "signingSecret" not in res.text
    after = _state(session_factory, ep)
    if name == "enable":
        assert after["status"] == "DISABLED" == before["status"]
    assert _url_of(session_factory, ep) == HOOK
    if name == "register":
        assert _endpoint_count(session_factory, r["ws"]) == 1  # only the seeded row


def test_ac_43_08_control_staff_writes_need_no_key_and_work_after_a_revoke(client, session_factory):
    """Passes today and must keep passing: the staff routes for the same writes are
    not tied to a key."""
    r = _rig(client, session_factory)
    ep = _insert(session_factory, ws=r["ws"], created_by=_by(r["key"]), status="DISABLED", reason="x", disabled_at=OLD)
    assert _revoke(client, r["ws"], r["key"]).status_code == 200
    h = _auth(client)

    patched = client.patch(f"{STAFF}/webhooks/{ep}", headers=h, json={"url": NEW_HOOK})
    assert patched.status_code == 200, patched.text
    rotated = client.post(f"{STAFF}/webhooks/{ep}/rotate", headers=h)
    assert rotated.status_code == 200 and rotated.json()["signingSecret"], rotated.text
    enabled = client.post(f"{STAFF}/webhooks/{ep}/enable", headers=h)
    assert enabled.status_code == 200 and enabled.json()["status"] == "ACTIVE", enabled.text


# ═════════════════════════════════════════════════════════════════════════════
# AC-43-09 - the key that last changed a row owns it
# ═════════════════════════════════════════════════════════════════════════════
def _created_by(session_factory, endpoint_id):
    db = session_factory()
    try:
        return db.query(WebhookEndpoint).filter(WebhookEndpoint.id == endpoint_id).one().created_by
    finally:
        db.close()


def _register_as(client, hdr, name="by key"):
    res = client.post(
        f"{BASE}/webhooks", headers=hdr, json={"name": name, "url": HOOK, "events": ["message.inbound"]}
    )
    assert res.status_code == 201, res.text
    return res.json()["endpoint"]["id"]


def _key_write(client, hdr, action, ep):
    if action == "patch":
        return client.patch(f"{BASE}/webhooks/{ep}", headers=hdr, json={"name": "renamed by key"})
    return client.post(f"{BASE}/webhooks/{ep}/{action}", headers=hdr)


def _counts(client, ws, *key_ids):
    items = _key_list(client, ws)
    return [items[k].get("webhookEndpointCount") for k in key_ids]


def _list_owner_name(client, ws, ep):
    res = client.get(f"{STAFF}/workspaces/{ws}/webhooks", headers=_auth(client))
    assert res.status_code == 200, res.text
    return {i["id"]: i for i in res.json()["data"]}[ep].get("registeredByKeyName")


@pytest.mark.parametrize("action", ["patch", "rotate", "enable"])
def test_ac_43_09_a_second_key_changing_a_row_takes_it_over(client, session_factory, action):
    r = _rig(client, session_factory)
    ws, k1 = r["ws"], r["key"]
    k2, hdr2 = _key(client, ws, "Second key")
    ep = _register_as(client, r["hdr"])
    assert _created_by(session_factory, ep) == _by(k1)  # control: register records the key
    if action == "enable":  # enabling an ACTIVE row changes nothing, so the key pauses it first
        assert client.post(f"{BASE}/webhooks/{ep}/disable", headers=r["hdr"]).status_code == 200
        assert _counts(client, ws, k1, k2) == [0, 0]  # control
    else:
        assert _counts(client, ws, k1, k2) == [1, 0]  # control

    res = _key_write(client, hdr2, action, ep)

    assert res.status_code == 200, res.text  # control: the write itself works
    assert _created_by(session_factory, ep) == _by(k2)
    assert _counts(client, ws, k1, k2) == [0, 1]
    assert _list_owner_name(client, ws, ep) == "Second key"
    assert _revoke(client, ws, k2).status_code == 200
    assert _state(session_factory, ep)["status"] == "DISABLED"


def test_ac_43_09_resuming_a_row_after_its_old_key_was_revoked_without_pausing_gives_it_to_the_new_key(
    client, session_factory
):
    r = _rig(client, session_factory)
    ws, k1 = r["ws"], r["key"]
    k2, hdr2 = _key(client, ws, "Second key")
    ep = _register_as(client, r["hdr"])
    assert _revoke(client, ws, k1, {"pauseEndpoints": False}).status_code == 200
    assert _state(session_factory, ep)["status"] == "ACTIVE"  # control: left running
    assert client.post(f"{BASE}/webhooks/{ep}/disable", headers=hdr2).status_code == 200  # a key's own pause

    res = client.post(f"{BASE}/webhooks/{ep}/enable", headers=hdr2)

    assert res.status_code == 200, res.text
    assert _counts(client, ws, k2) == [1]
    assert _revoke(client, ws, k2).status_code == 200
    assert _state(session_factory, ep)["status"] == "DISABLED"


def test_ac_43_09_a_key_patching_a_staff_made_row_owns_it(client, session_factory):
    r = _rig(client, session_factory)
    ws, k = r["ws"], r["key"]
    ep = _insert(session_factory, ws=ws, created_by="a-staff-user-id", name="staff row")
    assert _list_owner_name(client, ws, ep) is None  # control

    res = _key_write(client, r["hdr"], "patch", ep)

    assert res.status_code == 200, res.text
    assert _created_by(session_factory, ep) == _by(k)
    assert _list_owner_name(client, ws, ep) == "K"
    assert _revoke(client, ws, k).status_code == 200
    assert _state(session_factory, ep)["status"] == "DISABLED"


def test_ac_43_09_a_keys_disable_leaves_the_owner_alone(client, session_factory):
    r = _rig(client, session_factory)
    ws, k1 = r["ws"], r["key"]
    k2, hdr2 = _key(client, ws, "Second key")
    ep = _register_as(client, r["hdr"])

    res = client.post(f"{BASE}/webhooks/{ep}/disable", headers=hdr2)

    assert res.status_code == 200 and res.json()["status"] == "DISABLED", res.text  # control
    assert _created_by(session_factory, ep) == _by(k1)


def test_ac_43_09_a_keys_delete_removes_the_row_and_moves_no_other_row(client, session_factory):
    r = _rig(client, session_factory)
    ws, k1 = r["ws"], r["key"]
    k2, hdr2 = _key(client, ws, "Second key")
    gone = _register_as(client, r["hdr"], "gone")
    kept = _register_as(client, r["hdr"], "kept")

    assert client.delete(f"{BASE}/webhooks/{gone}", headers=hdr2).status_code == 204  # control
    assert _created_by(session_factory, kept) == _by(k1)
    assert _counts(client, ws, k1, k2) == [1, 0]


@pytest.mark.parametrize("owner", ["key", "staff"])
@pytest.mark.parametrize("action", ["patch", "rotate", "disable", "enable"])
def test_ac_43_09_control_staff_actions_leave_the_owner_as_it_was(client, session_factory, owner, action):
    """Passes today and must keep passing."""
    r = _rig(client, session_factory)
    ws = r["ws"]
    created_by = _by(r["key"]) if owner == "key" else "a-staff-user-id"
    ep = _insert(session_factory, ws=ws, created_by=created_by)
    h = _auth(client)

    if action == "patch":
        res = client.patch(f"{STAFF}/webhooks/{ep}", headers=h, json={"name": "renamed by staff"})
    else:
        res = client.post(f"{STAFF}/webhooks/{ep}/{action}", headers=h)

    assert res.status_code == 200, res.text
    assert _created_by(session_factory, ep) == created_by


def test_ac_43_09_control_a_refused_key_write_moves_nothing(client, session_factory):
    """A bad URL on PATCH is 422 and the row stays with its first key. Passes
    today; it guards the change that moves ownership."""
    r = _rig(client, session_factory)
    ws, k1 = r["ws"], r["key"]
    k2, hdr2 = _key(client, ws, "Second key")
    ep = _register_as(client, r["hdr"])

    res = client.patch(f"{BASE}/webhooks/{ep}", headers=hdr2, json={"url": "not a url"})

    assert res.status_code == 422, res.text
    assert _created_by(session_factory, ep) == _by(k1)
    assert _counts(client, ws, k1, k2) == [1, 0]


def test_ac_43_09_control_registering_records_the_registering_key(client, session_factory):
    r = _rig(client, session_factory)
    ep = _register_as(client, r["hdr"])
    assert _created_by(session_factory, ep) == _by(r["key"])


# ═════════════════════════════════════════════════════════════════════════════
# AC-43-50 - the guide and the engineering doc state what revoking a key does
# ═════════════════════════════════════════════════════════════════════════════
_REPO = Path(__file__).resolve().parents[2]
_GUIDE = _REPO / "documentation/omnichannel/consumer-integration-guide.md"
_ENG = _REPO / "documentation/engineering/omnichannel-service.md"


def _doc_section(text, start, end):
    i = text.index(start)
    j = text.index(end, i + len(start))
    return " ".join(text[i:j].split()).lower()


def _first_changelog_row():
    """The changelog row for this change, found by its words among the rows."""
    lines = _GUIDE.read_text().splitlines()[:40]
    rows = [
        ln for ln in lines
        if ln.startswith("> |") and "| Date |" not in ln and not ln.startswith("> |--")
    ]
    mine = [
        ln for ln in rows
        if "disabledReason" in ln or "revoked key" in ln.lower() or "key is revoked" in ln.lower()
    ]
    return mine[0] if mine else rows[0]


def test_ac_43_50_guide_first_changelog_row_is_for_the_revoke_change():
    row = _first_changelog_row()
    assert "disabledReason" in row or "revoked key" in row.lower() or "key is revoked" in row.lower(), row
    assert "/channels" not in row, "keep this row apart from the GET /channels row"


def test_ac_43_50_guide_section_7_says_what_staff_may_do_with_a_revoked_keys_endpoints():
    sec = _doc_section(_GUIDE.read_text(), "## 7. Receiving events", "## 8. ")
    assert any("revoked" in x and "pause" in x and "staff" in x for x in sec.split(". ")), (
        "section 7 must say staff may pause a revoked key's endpoints"
    )
    assert any("disabledreason" in x and "revoked" in x for x in sec.split(". ")), (
        "section 7 must say disabledReason says the key was revoked"
    )
    assert "post /webhooks/{id}/enable" in sec and "resume" in sec
    assert any("recogni" in x and "resume" in x for x in sec.split(". ")), (
        "section 7 must say to resume only endpoints you recognise"
    )


def test_ac_43_50_guide_section_7_says_the_key_that_last_changed_an_endpoint_owns_it():
    sec = _doc_section(_GUIDE.read_text(), "## 7. Receiving events", "## 8. ")
    assert any(
        "last" in x and "changed" in x and ("owns" in x or "owner" in x) for x in sec.split(". ")
    ), "section 7 must say the key that last changed an endpoint owns it"


def test_ac_43_50_guide_at_least_once_statement_covers_a_workspace_or_tenant_that_is_off():
    sec = _doc_section(_GUIDE.read_text(), "### Delivery guarantees", "### Registering")
    parts = [x for x in sec.split(". ") if "workspace" in x and "tenant" in x]
    assert parts, "the delivery guarantees must name a workspace or tenant that is off"
    flat = " ".join(parts)
    assert "no event is queued" in flat or "not queued" in flat or "nothing is queued" in flat, flat
    assert "failed" in sec and "retr" in sec
    assert "not sent later" in sec or "not sent afterwards" in sec or "never sent later" in sec, sec


def test_ac_43_50_guide_says_a_write_refused_because_the_key_was_revoked_is_401():
    sec = _doc_section(_GUIDE.read_text(), "## 7. Receiving events", "## 8. ")
    assert any("revoked" in x and "401" in x and ("write" in x or "register" in x or "change" in x)
               for x in sec.split(". ")), "section 7 must say a refused write from a revoked key is 401"


def test_ac_43_50_engineering_doc_mentions_the_key_row_lock_and_the_ownership_rule():
    text = " ".join(_ENG.read_text().split()).lower()
    assert "_hold_live_key" in text or "key row lock" in text or "lock on the key row" in text
    assert any("last" in x and "changed" in x and ("owns" in x or "owner" in x or "created_by" in x)
               for x in text.split(". ")), "the engineering doc must state the ownership rule"


def test_ac_43_09_a_write_that_lands_last_owns_the_row(client, session_factory, monkeypatch):
    """K1 owns the row and PATCHes it. While K1's URL check runs, K2 PATCHes the
    same row; K1's write is the last to land, so K1 owns the row afterwards."""
    from modules.omnichannel.services import webhook_service as ws_mod

    r = _rig(client, session_factory)
    ws, k1 = r["ws"], r["key"]
    k2, hdr2 = _key(client, ws, "Second key")
    ep = _register_as(client, r["hdr"])
    real = ws_mod.validate_callback_url
    inner = {"done": False}

    def check_with_other_write(url, **kw):
        clean = real(url, **kw)
        if not inner["done"]:
            inner["done"] = True
            res = client.patch(
                f"{BASE}/webhooks/{ep}", headers=hdr2, json={"name": "second key name", "url": "https://hooks.example.com/second"}
            )
            assert res.status_code == 200, res.text  # control: the other write landed
        return clean

    monkeypatch.setattr(ws_mod, "validate_callback_url", check_with_other_write)

    res = client.patch(f"{BASE}/webhooks/{ep}", headers=r["hdr"], json={"url": NEW_HOOK})

    assert res.status_code == 200, res.text
    assert inner["done"] is True
    assert _url_of(session_factory, ep) == NEW_HOOK
    assert _created_by(session_factory, ep) == _by(k1)
    assert _revoke(client, ws, k1).status_code == 200
    assert _state(session_factory, ep)["status"] == "DISABLED"


def test_ac_43_09_an_empty_patch_by_another_key_moves_nothing(client, session_factory):
    r = _rig(client, session_factory)
    ws, k1 = r["ws"], r["key"]
    k2, hdr2 = _key(client, ws, "Second key")
    ep = _register_as(client, r["hdr"])

    res = client.patch(f"{BASE}/webhooks/{ep}", headers=hdr2, json={})

    assert res.status_code == 200, res.text
    assert _created_by(session_factory, ep) == _by(k1)
    assert _counts(client, ws, k1, k2) == [1, 0]
    real_change = client.patch(f"{BASE}/webhooks/{ep}", headers=hdr2, json={"name": "a real change"})
    assert real_change.status_code == 200, real_change.text  # control: a real change still moves it
    assert _created_by(session_factory, ep) == _by(k2)


def test_ac_43_09_enabling_an_active_row_by_another_key_moves_nothing(client, session_factory):
    r = _rig(client, session_factory)
    ws, k1 = r["ws"], r["key"]
    k2, hdr2 = _key(client, ws, "Second key")
    ep = _register_as(client, r["hdr"])
    assert _state(session_factory, ep)["status"] == "ACTIVE"  # control

    res = client.post(f"{BASE}/webhooks/{ep}/enable", headers=hdr2)

    assert res.status_code == 200, res.text
    assert _created_by(session_factory, ep) == _by(k1)
    assert _counts(client, ws, k1, k2) == [1, 0]
    assert client.post(f"{BASE}/webhooks/{ep}/disable", headers=hdr2).status_code == 200  # a key's own pause
    resumed = client.post(f"{BASE}/webhooks/{ep}/enable", headers=hdr2)
    assert resumed.status_code == 200, resumed.text  # control: a real change still moves it
    assert _created_by(session_factory, ep) == _by(k2)


# ═════════════════════════════════════════════════════════════════════════════
# AC-43-12 - a pause set by staff holds against keys
# ═════════════════════════════════════════════════════════════════════════════
STAFF_REASON = "Disabled by user."


def _row_snapshot(session_factory, endpoint_id):
    db = session_factory()
    try:
        r = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == endpoint_id).one()
        return {
            "status": r.status,
            "url": r.url,
            "name": r.name,
            "secret": r.secret_encrypted,
            "reason": r.disabled_reason,
            "created_by": r.created_by,
        }
    finally:
        db.close()


def _staff_paused_row(client, r):
    ep = _register_as(client, r["hdr"])
    res = client.post(f"{STAFF}/webhooks/{ep}/disable", headers=_auth(client))
    assert res.status_code == 200 and res.json()["status"] == "DISABLED", res.text
    return ep


@pytest.mark.parametrize("action", ["patch", "rotate", "enable"])
def test_ac_43_12_a_key_write_on_a_row_staff_paused_answers_409_and_changes_nothing(
    client, session_factory, action
):
    r = _rig(client, session_factory)
    k2, hdr2 = _key(client, r["ws"], "Second key")
    ep = _staff_paused_row(client, r)
    before = _row_snapshot(session_factory, ep)
    assert before["reason"] == STAFF_REASON and before["status"] == "DISABLED"  # control

    if action == "patch":
        res = client.patch(f"{BASE}/webhooks/{ep}", headers=hdr2, json={"url": NEW_HOOK, "name": "other"})
    else:
        res = client.post(f"{BASE}/webhooks/{ep}/{action}", headers=hdr2)

    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "endpoint_paused_by_staff", res.text
    assert "signingSecret" not in res.text
    assert _row_snapshot(session_factory, ep) == before


def test_ac_43_12_after_staff_resume_a_key_write_works_again(client, session_factory):
    r = _rig(client, session_factory)
    k2, hdr2 = _key(client, r["ws"], "Second key")
    ep = _staff_paused_row(client, r)
    assert client.post(f"{BASE}/webhooks/{ep}/enable", headers=hdr2).status_code == 409  # control

    resumed = client.post(f"{STAFF}/webhooks/{ep}/enable", headers=_auth(client))
    assert resumed.status_code == 200 and resumed.json()["status"] == "ACTIVE", resumed.text

    patched = client.patch(f"{BASE}/webhooks/{ep}", headers=hdr2, json={"name": "after resume"})
    assert patched.status_code == 200, patched.text
    assert _row_snapshot(session_factory, ep)["status"] == "ACTIVE"


def test_ac_43_12_control_a_row_paused_by_a_revoke_is_resumed_by_another_live_key(client, session_factory):
    """Passes today (AC-43-07 behaviour) and must keep passing."""
    r = _rig(client, session_factory)
    k2, hdr2 = _key(client, r["ws"], "Second key")
    ep = _register_as(client, r["hdr"])
    assert _revoke(client, r["ws"], r["key"]).status_code == 200
    assert _state(session_factory, ep)["status"] == "DISABLED"

    res = client.post(f"{BASE}/webhooks/{ep}/enable", headers=hdr2)

    assert res.status_code == 200 and res.json()["status"] == "ACTIVE", res.text


def test_ac_43_12_a_keys_own_disable_stores_a_reason_other_than_the_staff_one_and_keys_can_resume_it(
    client, session_factory
):
    r = _rig(client, session_factory)
    k2, hdr2 = _key(client, r["ws"], "Second key")
    ep = _register_as(client, r["hdr"])

    paused = client.post(f"{BASE}/webhooks/{ep}/disable", headers=r["hdr"])
    assert paused.status_code == 200 and paused.json()["status"] == "DISABLED", paused.text  # control

    reason = _row_snapshot(session_factory, ep)["reason"]
    assert reason and reason != STAFF_REASON, reason
    resumed = client.post(f"{BASE}/webhooks/{ep}/enable", headers=hdr2)
    assert resumed.status_code == 200 and resumed.json()["status"] == "ACTIVE", resumed.text


def test_ac_43_12_control_a_key_patch_on_a_row_paused_by_a_key_or_a_revoke_works_and_stays_paused(
    client, session_factory
):
    """Pins today's answer: PATCH is not a resume."""
    r = _rig(client, session_factory)
    k2, hdr2 = _key(client, r["ws"], "Second key")
    own = _register_as(client, r["hdr"], "paused by its key")
    assert client.post(f"{BASE}/webhooks/{own}/disable", headers=r["hdr"]).status_code == 200
    by_revoke = _register_as(client, hdr2, "paused by a revoke")
    assert _revoke(client, r["ws"], k2).status_code == 200
    k3, hdr3 = _key(client, r["ws"], "Third key")

    for ep in (own, by_revoke):
        res = client.patch(f"{BASE}/webhooks/{ep}", headers=r["hdr"] if ep == own else hdr3, json={"name": f"renamed {ep[:4]}"})
        assert res.status_code == 200, res.text
        assert _state(session_factory, ep)["status"] == "DISABLED"


def test_ac_43_12_a_keys_disable_cannot_turn_a_staff_pause_into_its_own(client, session_factory):
    r = _rig(client, session_factory)
    k2, hdr2 = _key(client, r["ws"], "Second key")
    ep = _staff_paused_row(client, r)
    before = _row_snapshot(session_factory, ep)
    assert before["reason"] == STAFF_REASON  # control

    res = client.post(f"{BASE}/webhooks/{ep}/disable", headers=hdr2)

    assert res.status_code == 200 and res.json()["status"] == "DISABLED", res.text  # pinned: the row comes back as it was
    assert _row_snapshot(session_factory, ep) == before
    assert _row_snapshot(session_factory, ep)["reason"] == STAFF_REASON
    enabled = client.post(f"{BASE}/webhooks/{ep}/enable", headers=hdr2)
    assert enabled.status_code == 409, enabled.text
    assert enabled.json()["error"]["code"] == "endpoint_paused_by_staff"


# ═════════════════════════════════════════════════════════════════════════════
# Final review round: a staff pause under way, a revoke under way on disable, a
# row deleted under way, and requests that change nothing
# ═════════════════════════════════════════════════════════════════════════════
def _staff_pause_in_another_session(session_factory, endpoint_id):
    from modules.omnichannel.services.webhook_service import WebhookService

    other = session_factory()
    try:
        WebhookService(other).set_status(DEFAULT_TENANT_ID, endpoint_id, False)
    finally:
        other.close()


@pytest.mark.parametrize("action", ["patch", "rotate", "enable"])
def test_ac_43_12_a_staff_pause_during_a_key_write_answers_409_and_changes_nothing(
    client, session_factory, monkeypatch, action
):
    from modules.omnichannel.services import webhook_service as ws_mod

    r = _rig(client, session_factory)
    k2, hdr2 = _key(client, r["ws"], "Second key")
    ep = _register_as(client, r["hdr"])
    if action == "enable":
        assert client.post(f"{BASE}/webhooks/{ep}/disable", headers=r["hdr"]).status_code == 200
    start = _row_snapshot(session_factory, ep)
    fired = {"n": 0}

    def pause_once():
        if not fired["n"]:
            fired["n"] += 1
            _staff_pause_in_another_session(session_factory, ep)

    if action == "patch":
        real = ws_mod.validate_callback_url

        def slow_check(url, **kw):
            clean = real(url, **kw)
            pause_once()
            return clean

        monkeypatch.setattr(ws_mod, "validate_callback_url", slow_check)
    else:
        real_hold = ws_mod.WebhookService._hold_live_key

        def hold_after_pause(self, *a, **k):
            pause_once()
            return real_hold(self, *a, **k)

        monkeypatch.setattr(ws_mod.WebhookService, "_hold_live_key", hold_after_pause)

    if action == "patch":
        res = client.patch(f"{BASE}/webhooks/{ep}", headers=hdr2, json={"url": NEW_HOOK, "name": "other"})
    else:
        res = client.post(f"{BASE}/webhooks/{ep}/{action}", headers=hdr2)

    assert fired["n"] == 1  # control: staff paused during the request
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "endpoint_paused_by_staff", res.text
    assert "signingSecret" not in res.text
    after = _row_snapshot(session_factory, ep)
    assert after["status"] == "DISABLED" and after["reason"] == STAFF_REASON
    assert {k: after[k] for k in ("url", "name", "secret", "created_by")} == {
        k: start[k] for k in ("url", "name", "secret", "created_by")
    }


@pytest.mark.parametrize("action", ["patch", "rotate", "enable", "disable"])
def test_ac_43_12_each_key_write_rereads_the_endpoint_row_under_a_lock_after_the_key_row(
    client, session_factory, lock_spy, action
):
    r = _rig(client, session_factory)
    ep = _register_as(client, r["hdr"])
    if action == "enable":
        assert client.post(f"{BASE}/webhooks/{ep}/disable", headers=r["hdr"]).status_code == 200
    lock_spy.clear()

    if action == "patch":
        res = client.patch(f"{BASE}/webhooks/{ep}", headers=r["hdr"], json={"name": "renamed"})
    else:
        res = client.post(f"{BASE}/webhooks/{ep}/{action}", headers=r["hdr"])

    assert res.status_code == 200, res.text  # control: a live key still writes
    key_at = [i for i, e in enumerate(lock_spy) if e[0] == "lock" and e[1] == "WorkspaceApiKey"]
    row_at = [
        i for i, e in enumerate(lock_spy)
        if e[0] == "lock" and e[1] == "WebhookEndpoint" and e[2].get("key_share") is True
    ]
    assert key_at, "no lock on the key row"
    assert row_at, "the endpoint row was not re-read under a lock"
    assert min(row_at) > min(key_at), lock_spy


def test_ac_43_12_a_keys_delete_of_a_staff_paused_row_answers_409_and_keeps_row_and_log(client, session_factory):
    r = _rig(client, session_factory)
    k2, hdr2 = _key(client, r["ws"], "Second key")
    ep = _staff_paused_row(client, r)
    db = session_factory()
    try:
        db.add(
            WebhookDelivery(
                tenant_id=DEFAULT_TENANT_ID, endpoint_id=ep, event_id="evt-keep", event_type="message.inbound",
                payload_json={"id": "evt-keep"}, status="FAILED",
            )
        )
        db.commit()
    finally:
        db.close()
    before = _row_snapshot(session_factory, ep)

    res = client.delete(f"{BASE}/webhooks/{ep}", headers=hdr2)

    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "endpoint_paused_by_staff", res.text
    assert _row_snapshot(session_factory, ep) == before
    assert [d[1] for d in _deliveries(session_factory, ep)] == ["evt-keep"]


def _failing_endpoint(client, session_factory, r):
    """A key-owned row at one failure short of the threshold, with a delivery on
    its last attempt. Returns (endpoint id, delivery id)."""
    ep = _insert(session_factory, ws=r["ws"], created_by=_by(r["key"]), failures=9)
    from modules.omnichannel.services.webhook_service import encrypt_secret

    db = session_factory()
    try:
        db.query(WebhookEndpoint).filter(WebhookEndpoint.id == ep).update(
            {WebhookEndpoint.secret_encrypted: encrypt_secret("whsec_test")}
        )
        d = WebhookDelivery(
            tenant_id=DEFAULT_TENANT_ID, endpoint_id=ep, event_id="evt-last", event_type="message.inbound",
            payload_json={"id": "evt-last"}, status="PENDING", attempt_count=wd.MAX_ATTEMPTS - 1,
        )
        db.add(d)
        db.commit()
        return ep, d.id
    finally:
        db.close()


def _dispatch_failing(session_factory, delivery_id, monkeypatch, *, on_post=None):
    import httpx

    reached = []

    def failing_post(url, *, content, headers, timeout):
        reached.append(url)
        if on_post:
            on_post()
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(wd, "_post", failing_post)
    monkeypatch.setattr(wd, "assert_deliverable", lambda url: None)
    db = session_factory()
    try:
        outcome = wd.dispatch(db, delivery_id)
    finally:
        db.close()
    assert reached, "the stubbed send was reached"
    return outcome


def test_ac_43_12_control_the_last_failing_attempt_auto_disables_at_the_threshold(
    client, session_factory, monkeypatch
):
    r = _rig(client, session_factory)
    ep, d = _failing_endpoint(client, session_factory, r)

    assert _dispatch_failing(session_factory, d, monkeypatch) == "dead"

    assert _state(session_factory, ep)["status"] == "AUTO_DISABLED"


def test_ac_43_12_the_last_failing_attempt_does_not_turn_a_staff_pause_into_an_auto_disable(
    client, session_factory, monkeypatch
):
    r = _rig(client, session_factory)
    k2, hdr2 = _key(client, r["ws"], "Second key")
    ep, d = _failing_endpoint(client, session_factory, r)

    _dispatch_failing(
        session_factory, d, monkeypatch, on_post=lambda: _staff_pause_in_another_session(session_factory, ep)
    )

    state = _state(session_factory, ep)
    assert state["status"] == "DISABLED" and state["reason"] == STAFF_REASON, state
    res = client.post(f"{BASE}/webhooks/{ep}/enable", headers=hdr2)
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "endpoint_paused_by_staff"


def test_ac_43_08_a_key_disable_with_the_key_revoked_under_way_answers_401_and_changes_nothing(
    client, session_factory, monkeypatch
):
    from modules.omnichannel.routers import api_v1

    r = _rig(client, session_factory)
    real_own = api_v1._own_endpoint

    def seam(db, api_ws, endpoint_id):
        _revoke_on_another_session(session_factory, r["ws"], r["key"])
        return real_own(db, api_ws, endpoint_id)

    monkeypatch.setattr(api_v1, "_own_endpoint", seam)
    # A staff-made row, so that the revoke itself leaves it alone.
    other = _insert(session_factory, ws=r["ws"], created_by="a-staff-user-id")
    before = _row_snapshot(session_factory, other)

    res = client.post(f"{BASE}/webhooks/{other}/disable", headers=r["hdr"])

    assert _revoked(session_factory, r["key"]) is True  # control: the revoke ran
    assert res.status_code == 401, res.text
    assert _row_snapshot(session_factory, other) == before


def test_ac_43_08_a_row_deleted_during_the_url_check_answers_404_in_the_gateway_envelope(
    client, session_factory, monkeypatch
):
    from fastapi.testclient import TestClient

    from app.main import app
    from modules.omnichannel.services import webhook_service as ws_mod
    from modules.omnichannel.services.webhook_service import WebhookService

    r = _rig(client, session_factory)
    ep = _register_as(client, r["hdr"])
    real = ws_mod.validate_callback_url

    def check_then_delete(url, **kw):
        clean = real(url, **kw)
        other = session_factory()
        try:
            WebhookService(other).delete(DEFAULT_TENANT_ID, ep)
        finally:
            other.close()
        return clean

    monkeypatch.setattr(ws_mod, "validate_callback_url", check_then_delete)

    with TestClient(app, raise_server_exceptions=False) as quiet:
        res = quiet.patch(f"{BASE}/webhooks/{ep}", headers=r["hdr"], json={"url": NEW_HOOK})

    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "not_found", res.text


def test_ac_43_09_enabling_an_active_row_with_failures_changes_nothing(client, session_factory):
    r = _rig(client, session_factory)
    ws, k1 = r["ws"], r["key"]
    k2, hdr2 = _key(client, ws, "Second key")
    ep = _insert(session_factory, ws=ws, created_by=_by(k1), failures=3)

    res = client.post(f"{BASE}/webhooks/{ep}/enable", headers=hdr2)

    assert res.status_code == 200, res.text
    assert _state(session_factory, ep)["failures"] == 3
    assert _created_by(session_factory, ep) == _by(k1)


@pytest.mark.parametrize(
    "body",
    [
        {"name": "  direct  "},
        {"url": f"  {HOOK}  "},
        {"url": HOOK},
        {"events": ["message.inbound", "message.inbound", "message.outbound"]},
        {"events": ["message.outbound", "message.inbound"]},
    ],
    ids=["padded_name", "padded_url", "same_url", "duplicate_events", "events_in_another_order"],
)
def test_ac_43_09_a_patch_with_the_same_values_moves_nothing(client, session_factory, body):
    r = _rig(client, session_factory)
    ws, k1 = r["ws"], r["key"]
    k2, hdr2 = _key(client, ws, "Second key")
    ep = _insert(session_factory, ws=ws, created_by=_by(k1), events=("message.inbound", "message.outbound"))
    before = _row_snapshot(session_factory, ep)

    res = client.patch(f"{BASE}/webhooks/{ep}", headers=hdr2, json=body)

    assert res.status_code == 200, res.text
    assert _created_by(session_factory, ep) == _by(k1)
    assert _row_snapshot(session_factory, ep) == before


def test_ac_43_12_a_staff_status_change_reads_the_row_under_a_lock(client, session_factory, lock_spy):
    r = _rig(client, session_factory)
    ep = _insert(session_factory, ws=r["ws"], created_by=_by(r["key"]))
    h = _auth(client)
    db = session_factory()
    engine = db.get_bind()
    db.close()

    def on_sql(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE") and "webhook_endpoints" in statement:
            lock_spy.append(("update_row",))

    event.listen(engine, "before_cursor_execute", on_sql)
    try:
        for step in ("disable", "enable"):  # a pause, then a resume
            lock_spy.clear()
            res = client.post(f"{STAFF}/webhooks/{ep}/{step}", headers=h)
            assert res.status_code == 200, res.text  # control: the staff change works
            locks = [
                i for i, e in enumerate(lock_spy)
                if e[0] == "lock" and e[1] == "WebhookEndpoint" and e[2].get("key_share") is True
            ]
            updates = [i for i, e in enumerate(lock_spy) if e[0] == "update_row"]
            assert updates, (step, "the row was never updated")  # control
            assert locks, (step, "the endpoint row was read without a lock")
            assert min(locks) < min(updates), (step, lock_spy)
    finally:
        event.remove(engine, "before_cursor_execute", on_sql)


def test_ac_43_12_a_staff_pause_always_writes_the_status(client, session_factory, monkeypatch):
    """The row is read as DISABLED with a key's reason; before the pause commits,
    another session enables it. The staff pause must still end DISABLED with the
    staff reason. The wrapper hooks the first read `set_status` makes (today
    `_get`); if that read moves, hook the new first read instead."""
    from sqlalchemy import update

    from modules.omnichannel.services.webhook_service import KEY_DISABLED_REASON, WebhookService

    r = _rig(client, session_factory)
    ep = _insert(
        session_factory, ws=r["ws"], created_by=_by(r["key"]), status="DISABLED",
        reason=KEY_DISABLED_REASON, disabled_at=OLD,
    )
    real_get = WebhookService._get
    fired = {"n": 0}

    def get_then_enable_elsewhere(self, tenant_id, endpoint_id):
        row = real_get(self, tenant_id, endpoint_id)
        if not fired["n"]:
            fired["n"] += 1
            other = session_factory()
            try:
                other.execute(
                    update(WebhookEndpoint)
                    .where(WebhookEndpoint.id == endpoint_id)
                    .values(status="ACTIVE", disabled_reason=None, disabled_at=None)
                )
                other.commit()
            finally:
                other.close()
        return row

    monkeypatch.setattr(WebhookService, "_get", get_then_enable_elsewhere)
    db = session_factory()
    try:
        WebhookService(db).set_status(DEFAULT_TENANT_ID, ep, False)
    finally:
        db.close()

    assert fired["n"] == 1  # control: the other session enabled the row during the read
    state = _state(session_factory, ep)
    assert state["status"] == "DISABLED" and state["reason"] == STAFF_REASON, state
