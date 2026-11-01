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
    monkeypatch.setattr(wd.httpx, "post", lambda *a, **k: _Resp(200))


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


def test_ac_43_20_workspace_list_returns_all_channel_rows_with_no_live_channel(client, session_factory):
    r = _rig(client, session_factory)
    ws, ch, k = r["ws"], r["ch"], r["key"]
    sibling = _new_workspace(session_factory, "Sibling")
    ids = {
        "by_key": _insert(session_factory, ws=ws, created_by=_by(k)),
        "by_staff": _insert(session_factory, ws=ws, created_by="a-staff-user-id", name="staff row"),
        "paused": _insert(session_factory, ws=ws, created_by=_by(k), status="DISABLED", reason="r", disabled_at=OLD),
    }
    excluded = {
        "per_channel": _insert(session_factory, ws=ws, created_by=_by(k), channel_id=ch),
        "sibling_workspace": _insert(session_factory, ws=sibling, created_by=_by(k)),
        "other_tenant_same_workspace_id": _insert(session_factory, ws=ws, created_by=_by(k), tenant_id=FOREIGN_TENANT),
    }
    _disconnect_every_channel(session_factory, ws)

    res = client.get(f"{STAFF}/workspaces/{ws}/webhooks", headers=_auth(client))
    assert res.status_code == 200, res.text
    listed = {i["id"]: i for i in res.json()["data"]}
    assert set(listed) == set(ids.values()), {"listed": sorted(listed), "excluded": excluded}
    assert all(i["channelId"] is None for i in listed.values())
    assert listed[ids["by_key"]]["registeredByKeyName"] == "K"
    assert listed[ids["by_staff"]]["registeredByKeyName"] is None


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
    monkeypatch.setattr(wd.httpx, "post", lambda *a, **k: calls.append(a) or _Resp(200))
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
    monkeypatch.setattr(wd.httpx, "post", lambda *a, **k: calls.append(a) or _Resp(200))
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
