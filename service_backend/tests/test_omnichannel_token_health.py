"""Plan 42 - WhatsApp token health (AC-42-01 .. AC-42-16). RED tests, written
before any implementation exists.

Seams (the contract names the coder matches):
- ``WhatsAppCloudAdapter.check_token(credentials, phone_number_id)`` -> "ok" | "dead" | "unknown"
- ``WhatsAppCloudAdapter.subscribe_app_checked(credentials, waba_id)`` -> bool
- ``WhatsAppCloudAdapter.token_expiry(token)`` -> datetime | None
- ``modules.omnichannel.services.token_health.run_channel_token_checks(db)`` / ``check_channel_token(db, id)``
- ``POST /omnichannel/channels/{id}/replace-token`` with ``{"accessToken": ...}``

Every test seeds its own chain. Symbols are imported inside the test bodies so
one missing symbol never fails collection. All tokens and numbers are fakes.
"""
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL

TOKEN_OLD = "tok-old-under-test-1"
TOKEN_NEW = "tok-under-test-1"
PN = "pn-th-1"
DIGITS = "0042"
DISPLAY = f"+60 11-111 {DIGITS}"


# ── plumbing ─────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """No test here may reach a real host. MockTransport (used by AC-42-01)
    is a different class, so it is unaffected."""

    def boom(self, *a, **k):
        raise AssertionError("a real network call was attempted")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", boom)


def _resolve(value, *args):
    if isinstance(value, BaseException):
        raise value
    if callable(value):
        return value(*args)
    return value


_UNSET = object()


class _Stub:
    def __init__(self):
        self.check = "ok"
        self.subscribe = True
        self.expiry = None
        self.scopes = None
        self.app_id = None
        self.details = _UNSET
        self.check_calls = []
        self.subscribe_calls = []
        self.expiry_calls = []


def _stub(monkeypatch, **kw):
    """Stub the three named adapter methods on the WhatsApp adapter class."""
    from modules.omnichannel.adapters.whatsapp_cloud import WhatsAppCloudAdapter

    st = _Stub()
    for k, v in kw.items():
        setattr(st, k, v)

    def check_token(self, credentials, phone_number_id):
        st.check_calls.append((dict(credentials), phone_number_id))
        return _resolve(st.check, credentials, phone_number_id)

    def subscribe_app_checked(self, credentials, waba_id):
        st.subscribe_calls.append((dict(credentials), waba_id))
        return _resolve(st.subscribe, credentials, waba_id)

    def token_details(self, token):
        st.expiry_calls.append(token)
        if st.details is not _UNSET:
            return _resolve(st.details, token)
        return {"expires_at": _resolve(st.expiry, token), "scopes": st.scopes, "app_id": st.app_id}

    monkeypatch.setattr(WhatsAppCloudAdapter, "check_token", check_token, raising=False)
    monkeypatch.setattr(WhatsAppCloudAdapter, "subscribe_app_checked", subscribe_app_checked, raising=False)
    monkeypatch.setattr(WhatsAppCloudAdapter, "token_details", token_details, raising=False)
    return st


def _spy_email(monkeypatch, *, raises=None):
    from app.services.email_service import OutboxEmailService

    calls = []

    def enqueue_raw(self, db, tenant_id, to_email, subject, html_body, text_body, *a, **k):
        calls.append(
            SimpleNamespace(
                tenant_id=tenant_id, to=to_email, subject=subject, html=html_body, text=text_body
            )
        )
        if raises is not None:
            raise raises
        return SimpleNamespace(id="spy")

    monkeypatch.setattr(OutboxEmailService, "enqueue_raw", enqueue_raw)
    return calls


def _auth(client, **kw):
    from tests.test_omnichannel import _auth as a

    return a(client, **kw)


def _ws_for(db, tenant_id):
    from modules.omnichannel.models import Workspace

    ws = (
        db.query(Workspace)
        .filter(Workspace.tenant_id == tenant_id)
        .order_by(Workspace.is_default.desc())
        .first()
    )
    assert ws is not None, "fixture: tenant has no workspace"
    return ws.id


def _wa_channel(
    session_factory,
    *,
    name="Support Line",
    status_key="ACTIVE",
    active=True,
    trashed=False,
    tenant_id=DEFAULT_TENANT_ID,
    channel_type="WHATSAPP",
    creds=None,
    pn=PN,
    waba="waba-th-1",
):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses

    db = session_factory()
    try:
        statuses.ensure_statuses(db, tenant_id)
        wa = channel_type == "WHATSAPP"
        ch = Channel(
            tenant_id=tenant_id,
            workspace_id=_ws_for(db, tenant_id),
            channel_type=channel_type,
            name=name,
            credentials_json=encrypt_credentials(
                creds if creds is not None else {"access_token": TOKEN_OLD, "extra_key": "keep-me"}
            ),
            waba_id=waba if wa else None,
            phone_number_id=pn if wa else None,
            external_account_id=f"ext-{pn}" if channel_type == "FACEBOOK" else None,
            widget_key=f"wk-{pn}" if channel_type == "WEBCHAT" else None,
            display_phone_number=DISPLAY if wa else None,
            is_active=active,
            is_trashed=trashed,
            status_id=statuses.status_id_for(db, tenant_id, "CHANNEL", status_key),
        )
        db.add(ch)
        db.commit()
        return ch.id
    finally:
        db.close()


def _read(session_factory, channel_id):
    """(status_key, is_active, raw credentials_json, decrypted creds)."""
    from modules.omnichannel.models import Channel
    from modules.omnichannel.security import decrypt_credentials
    from modules.omnichannel.services import statuses

    db = session_factory()
    try:
        ch = db.query(Channel).filter(Channel.id == channel_id).first()
        key = statuses.id_to_key_map(db, ch.tenant_id).get(ch.status_id)
        return key, ch.is_active, ch.credentials_json, decrypt_credentials(ch.credentials_json)
    finally:
        db.close()


def _run_check(session_factory, channel_id):
    from modules.omnichannel.services import token_health

    db = session_factory()
    try:
        return token_health.check_channel_token(db, channel_id)
    finally:
        db.close()


def _provision_tenant(session_factory, slug, *, module=True):
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    db = session_factory()
    try:
        t = TenantService(db).provision(
            name=f"Tenant {slug}", slug=slug, admin_email=f"admin-{slug}@example.com",
            admin_password="Password123!", admin_name="Admin",
        )
        db.flush()
        if module:
            AppStoreService(db).install(t.id, "omnichannel")
        db.commit()
        return t.id
    finally:
        db.close()


def _user(session_factory, email, perm_keys, *, tenant_id=DEFAULT_TENANT_ID, status="ACTIVE", trashed=False):
    from sqlalchemy.sql import func

    from app.models import Permission, Role, User
    from app.security import hash_password

    db = session_factory()
    try:
        role = Role(tenant_id=tenant_id, name=f"role-{email}", description="t", is_system=False)
        role.permissions = db.query(Permission).filter(Permission.key.in_(perm_keys)).all()
        assert len(role.permissions) == len(perm_keys), "fixture: unknown permission key"
        db.add(role)
        db.flush()
        u = User(
            tenant_id=tenant_id, email=email, password=hash_password("Passw0rd!x"), name=email,
            status=status, email_verified_at=func.now(), is_trashed=trashed,
        )
        u.roles = [role]
        db.add(u)
        db.commit()
    finally:
        db.close()


def _activity_dump(session_factory):
    from app.models.integration_activity import IntegrationActivity

    db = session_factory()
    try:
        return json.dumps(
            [{k: str(v) for k, v in r.__dict__.items() if not k.startswith("_")} for r in db.query(IntegrationActivity).all()]
        )
    finally:
        db.close()


# ── AC-42-01 classifier table (check_token against a faked Graph response) ──
def _graph_adapter(monkeypatch, handler, *, app_configured=True):
    from app.config import settings
    from modules.omnichannel.adapters.whatsapp_cloud import WhatsAppCloudAdapter

    monkeypatch.setattr(settings, "meta_app_id", "test-app-id" if app_configured else "")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret" if app_configured else "")
    return WhatsAppCloudAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))


def _err(code, status=400):
    return lambda request: httpx.Response(status, json={"error": {"message": "m", "code": code}})


CLASSIFIER = [
    ("code 190", _err(190, 401), "dead"),
    ("200", lambda r: httpx.Response(200, json={"id": PN}), "ok"),
    ("http 500", lambda r: httpx.Response(500, json={"error": {"message": "x"}}), "unknown"),
    ("http 503 non-json body", lambda r: httpx.Response(503, text="gateway"), "unknown"),
    ("code 4 rate limit", _err(4), "unknown"),
    ("code 80007 rate limit", _err(80007), "unknown"),
    ("code 130429 rate limit", _err(130429), "unknown"),
    ("code 10 permission", _err(10), "unknown"),
    ("code 200 permission", _err(200), "unknown"),
]


@pytest.mark.parametrize("label,handler,expected", CLASSIFIER, ids=[c[0] for c in CLASSIFIER])
def test_ac_42_01_check_token_classifies_graph_answers(monkeypatch, label, handler, expected):
    adapter = _graph_adapter(monkeypatch, handler)
    assert adapter.check_token({"access_token": TOKEN_OLD}, PN) == expected


def test_ac_42_01_transport_error_is_unknown(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("no route", request=request)

    adapter = _graph_adapter(monkeypatch, handler)
    assert adapter.check_token({"access_token": TOKEN_OLD}, PN) == "unknown"


def test_ac_42_01_check_reads_the_number_with_the_given_token(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"id": PN})

    adapter = _graph_adapter(monkeypatch, handler)
    assert adapter.check_token({"access_token": TOKEN_NEW}, PN) == "ok"
    assert PN in seen["url"]
    assert TOKEN_NEW in seen["auth"] or TOKEN_NEW in seen["url"]


# ── AC-42-02 scan ────────────────────────────────────────────────────────────
def test_ac_42_02_scan_queues_exactly_the_expected_channels(session_factory, monkeypatch):
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    live = _wa_channel(session_factory, name="live", pn="pn-s-live")
    paused = _wa_channel(session_factory, name="paused", pn="pn-s-paused", status_key="INACTIVE", active=False)
    errored = _wa_channel(session_factory, name="errored", pn="pn-s-err", status_key="ERROR")
    trashed = _wa_channel(session_factory, name="trashed", pn="pn-s-trash", trashed=True)
    webchat = _wa_channel(session_factory, name="web", channel_type="WEBCHAT", pn="pn-s-web")
    facebook = _wa_channel(session_factory, name="fb", channel_type="FACEBOOK", pn="pn-s-fb")
    dev = _wa_channel(session_factory, name="dev", pn="pn-s-dev", creds={"dev": True})

    off_tenant = _provision_tenant(session_factory, "th-modoff")
    off = _wa_channel(session_factory, name="modoff", pn="pn-s-off", tenant_id=off_tenant)
    sus_tenant = _provision_tenant(session_factory, "th-susp")
    sus = _wa_channel(session_factory, name="susp", pn="pn-s-sus", tenant_id=sus_tenant)
    ok_tenant = _provision_tenant(session_factory, "th-other-ok")
    other_ok = _wa_channel(session_factory, name="otherok", pn="pn-s-ok", tenant_id=ok_tenant)

    db = session_factory()
    AppStoreService(db).deactivate(off_tenant, "omnichannel")
    TenantService(db).suspend(sus_tenant)
    db.close()

    from modules.omnichannel.services import token_health  # after the fixtures: a missing module fails here

    queued = []
    monkeypatch.setattr(token_health, "enqueue_channel_token_check", lambda cid: queued.append(cid), raising=False)
    st = _stub(monkeypatch)

    db = session_factory()
    try:
        count = token_health.run_channel_token_checks(db)
    finally:
        db.close()

    expected = {live, paused, errored, other_ok}
    excluded = {trashed, webchat, facebook, dev, off, sus}
    assert expected.isdisjoint(excluded)
    assert set(queued) == expected
    assert len(queued) == len(expected), "one check per channel, no duplicates"
    assert count == len(expected)
    assert st.check_calls == [], "the scan itself makes no Meta call"


def test_ac_42_02_beat_schedule_runs_the_scan_every_six_hours():
    from app.workflow_engine.worker import celery_app

    entries = [e for e in celery_app.conf.beat_schedule.values() if "token" in str(e.get("task", ""))]
    assert entries, "beat_schedule has no token-health entry"
    from celery.schedules import crontab

    # a fixed-interval float restarts its clock on every deploy; a crontab does not
    assert entries[0]["schedule"] == crontab(minute=0, hour="*/6")


# ── AC-42-03 dead -> ERROR, is_active untouched, inbound and send still work ─
def _inbound(session_factory, channel_id, wamid):
    from modules.omnichannel.services.inbound_service import InboundService

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "waba-th-1", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": PN, "display_phone_number": "60111110042"},
            "contacts": [{"wa_id": "60100000001", "profile": {"name": "Sam"}}],
            "messages": [{"id": wamid, "from": "60100000001", "timestamp": "1717550000",
                          "type": "text", "text": {"body": "hello"}}],
        }}]}],
    }
    db = session_factory()
    try:
        return InboundService(db).process_payload(channel_id, payload)
    finally:
        db.close()


def test_ac_42_03_dead_sets_error_and_keeps_is_active(session_factory, monkeypatch):
    _stub(monkeypatch, check="dead")
    _spy_email(monkeypatch)
    cid = _wa_channel(session_factory)
    assert _read(session_factory, cid)[:2] == ("ACTIVE", True)  # control
    _run_check(session_factory, cid)
    key, active, _, _ = _read(session_factory, cid)
    assert key == "ERROR"
    assert active is True


def test_ac_42_03_inbound_still_lands_after_dead(session_factory, monkeypatch):
    _stub(monkeypatch, check="dead")
    _spy_email(monkeypatch)
    cid = _wa_channel(session_factory)
    before = _inbound(session_factory, cid, "wamid.th-before")
    assert before["messages"] == 1  # control: this setup does land inbound
    _run_check(session_factory, cid)
    assert _read(session_factory, cid)[0] == "ERROR"
    after = _inbound(session_factory, cid, "wamid.th-after")
    assert after["messages"] == 1


def test_ac_42_03_send_still_calls_the_adapter_after_dead(client, session_factory, monkeypatch):
    from modules.omnichannel.adapters.whatsapp_cloud import WhatsAppCloudAdapter
    from tests.test_omnichannel_api_gateway import _default_workspace_id, _seed_open_contact
    from tests.test_omnichannel_gateway_channels import _hdr, _post_without_channel_id

    sent = []

    def fake_send(self, credentials, phone_number_id, to, **kw):
        sent.append(phone_number_id)
        return {"external_message_id": f"wamid.th-{len(sent)}"}

    monkeypatch.setattr(WhatsAppCloudAdapter, "send", fake_send)
    _stub(monkeypatch, check="dead")
    _spy_email(monkeypatch)
    cid = _wa_channel(session_factory)
    ws = _default_workspace_id(session_factory)
    _seed_open_contact(session_factory, ws, phone="+601234567890", open_window=True)
    hdr = _hdr(client, ws)

    first = _post_without_channel_id(client, hdr, "+601234567890")
    assert first.status_code == 202, first.text
    assert sent == [PN]  # control: a healthy channel reaches the adapter

    _run_check(session_factory, cid)
    assert _read(session_factory, cid)[0] == "ERROR"
    second = _post_without_channel_id(client, hdr, "+601234567890")
    assert second.status_code == 202, second.text
    assert sent == [PN, PN]


# ── AC-42-04 ok clears ERROR per is_active; ok on ACTIVE writes nothing ─────
@pytest.mark.parametrize(
    "start_key,active,expected_key",
    [("ERROR", True, "ACTIVE"), ("ERROR", False, "INACTIVE")],
)
def test_ac_42_04_ok_clears_error_per_is_active(session_factory, monkeypatch, start_key, active, expected_key):
    _stub(monkeypatch, check="ok")
    cid = _wa_channel(session_factory, status_key=start_key, active=active)
    _run_check(session_factory, cid)
    key, is_active, _, _ = _read(session_factory, cid)
    assert key == expected_key
    assert is_active is active


def test_ac_42_04_ok_on_a_normal_channel_writes_nothing(session_factory, monkeypatch):
    from modules.omnichannel.models import Channel

    st = _stub(monkeypatch, check="ok")
    cid = _wa_channel(session_factory)
    db = session_factory()
    before = db.query(Channel).filter(Channel.id == cid).first().updated_at
    db.close()
    _run_check(session_factory, cid)
    assert st.check_calls, "control: the check really ran"
    db = session_factory()
    ch = db.query(Channel).filter(Channel.id == cid).first()
    assert ch.updated_at == before
    db.close()
    assert _read(session_factory, cid)[:2] == ("ACTIVE", True)


# ── AC-42-05 unknown changes nothing and mails nobody ───────────────────────
@pytest.mark.parametrize("start_key", ["ACTIVE", "ERROR"])
def test_ac_42_05_unknown_changes_nothing_and_sends_no_email(session_factory, monkeypatch, start_key):
    st = _stub(monkeypatch, check="unknown")
    calls = _spy_email(monkeypatch)
    cid = _wa_channel(session_factory, status_key=start_key)
    _, _, raw_before, _ = _read(session_factory, cid)
    _run_check(session_factory, cid)
    key, active, raw_after, _ = _read(session_factory, cid)
    assert st.check_calls, "control: the check really ran"
    assert (key, active, raw_after) == (start_key, True, raw_before)
    assert calls == []


# ── AC-42-06 notification ────────────────────────────────────────────────────
def _setup_recipients(session_factory):
    _user(session_factory, "mgr2@example.com", ["channels.manage"])
    _user(session_factory, "reader@example.com", ["channels.read"])
    _user(session_factory, "trashed-mgr@example.com", ["channels.manage"], trashed=True)
    _user(session_factory, "inactive-mgr@example.com", ["channels.manage"], status="INACTIVE")
    other = _provision_tenant(session_factory, "th-mail-other")
    return other


def test_ac_42_06_one_email_to_each_eligible_user_only(session_factory, monkeypatch):
    _stub(monkeypatch, check="dead")
    calls = _spy_email(monkeypatch)
    other = _setup_recipients(session_factory)
    cid = _wa_channel(session_factory)
    _run_check(session_factory, cid)
    assert _read(session_factory, cid)[0] == "ERROR"
    recipients = sorted(c.to for c in calls)
    assert recipients == sorted([ACTIVE_EMAIL, "mgr2@example.com"])
    assert {c.tenant_id for c in calls} == {DEFAULT_TENANT_ID}
    assert "admin-th-mail-other@example.com" not in recipients and other


def test_ac_42_06_second_dead_check_sends_none_and_recovery_then_death_sends_again(session_factory, monkeypatch):
    st = _stub(monkeypatch, check="dead")
    calls = _spy_email(monkeypatch)
    _user(session_factory, "mgr2@example.com", ["channels.manage"])
    cid = _wa_channel(session_factory)
    _run_check(session_factory, cid)
    first = len(calls)
    assert first == 2  # control: the first death mails the two managers
    _run_check(session_factory, cid)
    assert len(calls) == first
    st.check = "ok"
    _run_check(session_factory, cid)
    assert _read(session_factory, cid)[0] == "ACTIVE"
    assert len(calls) == first
    st.check = "dead"
    _run_check(session_factory, cid)
    assert _read(session_factory, cid)[0] == "ERROR"
    assert len(calls) == first * 2


def test_ac_42_06_text_names_the_channel_and_last_digits_without_token_or_brand(session_factory, monkeypatch):
    _stub(monkeypatch, check="dead")
    calls = _spy_email(monkeypatch)
    cid = _wa_channel(session_factory, name="Support Line")
    _run_check(session_factory, cid)
    assert calls, "control: an email was composed"
    for c in calls:
        blob = f"{c.subject}\n{c.html}\n{c.text}"
        assert "Support Line" in blob
        assert DIGITS in blob
        assert TOKEN_OLD not in blob and "tok-" not in blob
        assert "foundryx" not in blob.lower()


def test_ac_42_06_email_failure_does_not_stop_the_status_change(session_factory, monkeypatch):
    _stub(monkeypatch, check="dead")
    calls = _spy_email(monkeypatch, raises=RuntimeError("outbox down"))
    cid = _wa_channel(session_factory)
    _run_check(session_factory, cid)  # must not raise
    assert calls, "control: the email path was really exercised"
    assert _read(session_factory, cid)[0] == "ERROR"


# ── AC-42-07 credentials changed between read and write ─────────────────────
@pytest.mark.parametrize("change_creds,expected", [(True, "ACTIVE"), (False, "ERROR")])
def test_ac_42_07_status_not_written_when_credentials_changed(session_factory, monkeypatch, change_creds, expected):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.security import encrypt_credentials

    calls = _spy_email(monkeypatch)
    cid = _wa_channel(session_factory)

    def dead_after_optional_replace(credentials, phone_number_id):
        if change_creds:
            other = session_factory()
            ch = other.query(Channel).filter(Channel.id == cid).first()
            ch.credentials_json = encrypt_credentials({"access_token": "tok-replaced-meanwhile"})
            other.commit()
            other.close()
        return "dead"

    _stub(monkeypatch, check=dead_after_optional_replace)
    _run_check(session_factory, cid)
    assert _read(session_factory, cid)[0] == expected
    assert (len(calls) > 0) is (not change_creds)


# ── AC-42-08 replace-token route: permission, scope, type ───────────────────
def _replace(client, headers, cid, token=TOKEN_NEW):
    return client.post(f"/omnichannel/channels/{cid}/replace-token", headers=headers, json={"accessToken": token})


def test_ac_42_08_admin_can_replace_control(client, session_factory, monkeypatch):
    _stub(monkeypatch, check="ok")
    cid = _wa_channel(session_factory, status_key="ERROR")
    res = _replace(client, _auth(client), cid)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ACTIVE"


def test_ac_42_08_forbidden_without_channels_manage(client, session_factory, monkeypatch):
    st = _stub(monkeypatch, check="ok")
    _user(session_factory, "reader@example.com", ["channels.read"])
    cid = _wa_channel(session_factory, status_key="ERROR")
    h = _auth(client, email="reader@example.com", password="Passw0rd!x")
    res = _replace(client, h, cid)
    assert res.status_code == 403
    assert st.check_calls == []
    assert _read(session_factory, cid)[3]["access_token"] == TOKEN_OLD
    assert _replace(client, _auth(client), cid).status_code == 200  # control: admin on the same channel


def test_ac_42_08_other_tenants_channel_is_404(client, session_factory, monkeypatch):
    from tests.test_omnichannel_channels_connect import _other_tenant_auth

    st = _stub(monkeypatch, check="ok")
    cid = _wa_channel(session_factory)
    other_h = _other_tenant_auth(client, session_factory, slug="th-scope")
    res = _replace(client, other_h, cid)
    assert res.status_code == 404
    assert st.check_calls == []
    assert _read(session_factory, cid)[3]["access_token"] == TOKEN_OLD
    # control: the owning tenant reaches the same channel through the same route
    assert _replace(client, _auth(client), cid).status_code == 200


def test_ac_42_08_trashed_channel_is_404_and_restored_is_not(client, session_factory, monkeypatch):
    from modules.omnichannel.models import Channel

    st = _stub(monkeypatch, check="ok")
    cid = _wa_channel(session_factory, trashed=True)
    h = _auth(client)
    assert _replace(client, h, cid).status_code == 404
    assert st.check_calls == []
    db = session_factory()
    db.query(Channel).filter(Channel.id == cid).update({Channel.is_trashed: False})
    db.commit()
    db.close()
    assert _replace(client, h, cid).status_code == 200  # control: same channel, not trashed


@pytest.mark.parametrize("channel_type,expected", [("WHATSAPP", 200), ("WEBCHAT", 409), ("FACEBOOK", 409)])
def test_ac_42_08_non_whatsapp_channel_gets_the_sibling_refusal(client, session_factory, monkeypatch, channel_type, expected):
    _stub(monkeypatch, check="ok")
    cid = _wa_channel(session_factory, channel_type=channel_type)
    res = _replace(client, _auth(client), cid)
    assert res.status_code == expected, res.text
    if expected == 409:
        assert "channel_type_unsupported" in res.text


def test_ac_42_08_missing_body_field_is_422(client, session_factory, monkeypatch):
    _stub(monkeypatch, check="ok")
    cid = _wa_channel(session_factory)
    h = _auth(client)
    bad = client.post(f"/omnichannel/channels/{cid}/replace-token", headers=h, json={})
    assert bad.status_code == 422
    assert _replace(client, h, cid).status_code == 200  # control: same channel, valid body


# ── AC-42-09 refusals change nothing ────────────────────────────────────────
@pytest.mark.parametrize("verdict", ["dead", "unknown"])
def test_ac_42_09_refused_token_is_422_and_nothing_changes(client, session_factory, monkeypatch, verdict):
    st = _stub(monkeypatch, check=verdict)
    cid = _wa_channel(session_factory, status_key="ERROR")
    before = _read(session_factory, cid)
    h = _auth(client)
    res = _replace(client, h, cid)
    assert res.status_code == 422, res.text
    assert st.check_calls and st.check_calls[0][0]["access_token"] == TOKEN_NEW
    assert st.check_calls[0][1] == PN, "tried on the channel's own phone_number_id"
    after = _read(session_factory, cid)
    assert (after[0], after[2]) == (before[0], before[2])
    assert res.text == _replace(client, h, cid).text, "fixed message text"
    assert TOKEN_NEW not in res.text


def test_ac_42_09_same_setup_with_ok_is_saved_control(client, session_factory, monkeypatch):
    _stub(monkeypatch, check="ok")
    cid = _wa_channel(session_factory, status_key="ERROR")
    assert _replace(client, _auth(client), cid).status_code == 200
    assert _read(session_factory, cid)[3]["access_token"] == TOKEN_NEW


# ── AC-42-10 in-place save ──────────────────────────────────────────────────
@pytest.mark.parametrize("active,expected_key", [(True, "ACTIVE"), (False, "INACTIVE")])
def test_ac_42_10_replaces_in_place_and_keeps_history(client, session_factory, monkeypatch, active, expected_key):
    from modules.omnichannel.models import Channel, ConversationMessage, WhatsappTemplate
    from tests.test_omnichannel_api_gateway import _default_workspace_id, _seed_open_contact

    _stub(monkeypatch, check="ok")
    cid = _wa_channel(session_factory, status_key="ERROR", active=active)
    contact = _seed_open_contact(session_factory, _default_workspace_id(session_factory), phone="+601234567891")
    db = session_factory()
    db.add(ConversationMessage(tenant_id=DEFAULT_TENANT_ID, contact_id=contact, channel_id=cid,
                               sender_type="AGENT", message_type="TEXT", body="old"))
    db.add(WhatsappTemplate(tenant_id=DEFAULT_TENANT_ID, channel_id=cid, name="tpl_old"))
    db.commit()
    db.close()

    res = _replace(client, _auth(client), cid)
    assert res.status_code == 200, res.text
    assert res.json()["id"] == cid

    key, is_active, _, creds = _read(session_factory, cid)
    assert creds["access_token"] == TOKEN_NEW
    assert creds["extra_key"] == "keep-me"
    assert (key, is_active) == (expected_key, active)

    db = session_factory()
    assert db.query(Channel).filter(Channel.tenant_id == DEFAULT_TENANT_ID, Channel.phone_number_id == PN).count() == 1
    assert db.query(ConversationMessage).filter(ConversationMessage.channel_id == cid).count() == 1
    assert db.query(WhatsappTemplate).filter(WhatsappTemplate.channel_id == cid).count() == 1
    db.close()


# ── AC-42-11 the token appears nowhere ──────────────────────────────────────
@pytest.mark.parametrize("verdict", ["ok", "dead"])
def test_ac_42_11_token_never_in_response_logs_or_activity(client, session_factory, monkeypatch, caplog, verdict):
    _stub(monkeypatch, check=verdict)
    caplog.set_level(logging.DEBUG)
    cid = _wa_channel(session_factory, status_key="ERROR")
    res = _replace(client, _auth(client), cid, token=TOKEN_NEW)
    assert res.status_code == (200 if verdict == "ok" else 422)
    assert TOKEN_NEW not in res.text
    assert TOKEN_NEW not in caplog.text
    assert TOKEN_NEW not in _activity_dump(session_factory)
    if verdict == "ok":
        assert _read(session_factory, cid)[3]["access_token"] == TOKEN_NEW  # control: it was really used


# ── AC-42-12 webhook renewal ────────────────────────────────────────────────
@pytest.mark.parametrize(
    "subscribe,expected",
    [(True, True), (False, False), (RuntimeError("meta down"), False)],
    ids=["true", "false", "raises"],
)
def test_ac_42_12_subscribed_reflects_the_renewal_and_token_stays_saved(client, session_factory, monkeypatch, subscribe, expected):
    from app.config import settings

    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    st = _stub(monkeypatch, check="ok", subscribe=subscribe, app_id="test-app-id")
    cid = _wa_channel(session_factory)
    res = _replace(client, _auth(client), cid)
    assert res.status_code == 200, res.text
    assert res.json()["subscribed"] is expected
    assert st.subscribe_calls and st.subscribe_calls[0][1] == "waba-th-1"
    assert _read(session_factory, cid)[3]["access_token"] == TOKEN_NEW


def test_ac_42_12_no_waba_id_gives_null_and_no_adapter_call(client, session_factory, monkeypatch):
    st = _stub(monkeypatch, check="ok")
    cid = _wa_channel(session_factory, waba=None)
    res = _replace(client, _auth(client), cid)
    assert res.status_code == 200, res.text
    assert "subscribed" in res.json() and res.json()["subscribed"] is None
    assert st.subscribe_calls == []
    assert _read(session_factory, cid)[3]["access_token"] == TOKEN_NEW


# ── AC-42-13 expiry ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "expiry,expected_prefix",
    [(datetime(2027, 3, 1, tzinfo=timezone.utc), "2027-03-01T00:00:00"), (None, None), (RuntimeError("debug refused"), None)],
    ids=["date", "none", "raises"],
)
def test_ac_42_13_replace_response_carries_token_expires_at(client, session_factory, monkeypatch, expiry, expected_prefix):
    st = _stub(monkeypatch, check="ok", expiry=expiry)
    cid = _wa_channel(session_factory)
    res = _replace(client, _auth(client), cid)
    assert res.status_code == 200, res.text
    body = res.json()
    assert "tokenExpiresAt" in body
    if expected_prefix:
        assert body["tokenExpiresAt"].startswith(expected_prefix) and body["tokenExpiresAt"].endswith("Z")
        assert st.expiry_calls == [TOKEN_NEW]
    else:
        assert body["tokenExpiresAt"] is None
    assert _read(session_factory, cid)[3]["access_token"] == TOKEN_NEW


@pytest.mark.parametrize(
    "expiry,expected_prefix",
    [(datetime(2027, 3, 1, tzinfo=timezone.utc), "2027-03-01T00:00:00"), (None, None)],
    ids=["date", "none"],
)
def test_ac_42_13_manual_connect_response_carries_token_expires_at(client, session_factory, monkeypatch, expiry, expected_prefix):
    from tests.test_omnichannel_api_gateway import _default_workspace_id

    _stub(monkeypatch, expiry=expiry)
    res = client.post(
        "/omnichannel/onboarding/manual-connect",
        headers=_auth(client),
        json={"workspaceId": _default_workspace_id(session_factory), "accessToken": TOKEN_NEW,
              "phoneNumberId": "pn-th-manual", "phoneNumber": "+60 11-111 0099"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert "tokenExpiresAt" in body
    if expected_prefix:
        assert body["tokenExpiresAt"].startswith(expected_prefix)
    else:
        assert body["tokenExpiresAt"] is None


# ── AC-42-14 PATCH leaves ERROR alone ───────────────────────────────────────
def _patch(client, cid, body):
    return client.patch(f"/omnichannel/channels/{cid}", headers=_auth(client), json=body)


def test_ac_42_14_rename_keeps_error(client, session_factory):
    cid = _wa_channel(session_factory, status_key="ERROR")
    res = _patch(client, cid, {"name": "Renamed"})
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Renamed"
    assert res.json()["status"] == "ERROR"


def test_ac_42_14_rename_with_unchanged_is_active_keeps_error(client, session_factory):
    cid = _wa_channel(session_factory, status_key="ERROR", active=True)
    res = _patch(client, cid, {"name": "Renamed too", "isActive": True})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ERROR"


def test_ac_42_14_changing_is_active_on_error_keeps_error(client, session_factory):
    cid = _wa_channel(session_factory, status_key="ERROR", active=True)
    res = _patch(client, cid, {"isActive": False})
    assert res.status_code == 200, res.text
    assert res.json()["isActive"] is False
    assert res.json()["status"] == "ERROR"
    assert _read(session_factory, cid)[:2] == ("ERROR", False)


def test_ac_42_14_normal_channel_still_moves_status_control(client, session_factory):
    cid = _wa_channel(session_factory)
    off = _patch(client, cid, {"isActive": False})
    assert (off.json()["status"], off.json()["isActive"]) == ("INACTIVE", False)
    on = _patch(client, cid, {"isActive": True})
    assert (on.json()["status"], on.json()["isActive"]) == ("ACTIVE", True)


# ── AC-42-15 list status filter ─────────────────────────────────────────────
def _flt(op, value):
    return json.dumps({"kind": "group", "combinator": "and", "rules": [
        {"kind": "condition", "field": "status", "operator": op, "value": value}]})


@pytest.mark.parametrize("wanted", ["ACTIVE", "INACTIVE", "ERROR"])
@pytest.mark.parametrize("op", ["eq", "in"])
def test_ac_42_15_status_filter_returns_only_that_status_within_tenant(client, session_factory, wanted, op):
    mine = {
        "ACTIVE": _wa_channel(session_factory, name="a1", pn="pn-f-a1"),
        "INACTIVE": _wa_channel(session_factory, name="i1", pn="pn-f-i1", status_key="INACTIVE", active=False),
        "ERROR": _wa_channel(session_factory, name="e1", pn="pn-f-e1", status_key="ERROR"),
    }
    _wa_channel(session_factory, name="e2", pn="pn-f-e2", status_key="ERROR")
    other = _provision_tenant(session_factory, f"th-flt-{wanted.lower()}-{op}")
    foreign = _wa_channel(session_factory, name="foreign", pn=f"pn-f-x-{wanted}-{op}", status_key=wanted, tenant_id=other)
    value = wanted if op == "eq" else [wanted]
    res = client.get("/omnichannel/channels", headers=_auth(client), params={"filter": _flt(op, value)})
    assert res.status_code == 200, res.text
    body = res.json()
    got = body["data"]
    assert got and {c["status"] for c in got} == {wanted}
    assert mine[wanted] in {c["id"] for c in got}
    assert foreign not in {c["id"] for c in got}
    assert body["total"] == len(got)
    if wanted == "ERROR":
        assert len(got) == 2
    unfiltered = client.get("/omnichannel/channels", headers=_auth(client)).json()
    assert unfiltered["total"] > body["total"], "control: the unfiltered list has other statuses"


def test_ac_42_15_pagination_count_matches_the_filter(client, session_factory):
    _wa_channel(session_factory, name="e1", pn="pn-g-1", status_key="ERROR")
    _wa_channel(session_factory, name="e2", pn="pn-g-2", status_key="ERROR")
    _wa_channel(session_factory, name="a1", pn="pn-g-3")
    res = client.get("/omnichannel/channels", headers=_auth(client),
                     params={"filter": _flt("eq", "ERROR"), "page": 0, "page_size": 1})
    body = res.json()
    assert res.status_code == 200
    assert len(body["data"]) == 1 and body["total"] == 2


# ── AC-42-16 public gateway shows ERROR but does not refuse sends ───────────
@pytest.mark.parametrize("status_key", ["ACTIVE", "ERROR"])
def test_ac_42_16_gateway_lists_error_with_is_active_and_send_reaches_adapter(client, session_factory, monkeypatch, status_key):
    from modules.omnichannel.adapters.whatsapp_cloud import WhatsAppCloudAdapter
    from tests.test_omnichannel_api_gateway import _default_workspace_id, _seed_open_contact
    from tests.test_omnichannel_gateway_channels import _hdr, _list, _post_without_channel_id

    sent = []

    def fake_send(self, credentials, phone_number_id, to, **kw):
        sent.append(phone_number_id)
        return {"external_message_id": "wamid.th-gw"}

    monkeypatch.setattr(WhatsAppCloudAdapter, "send", fake_send)
    cid = _wa_channel(session_factory, status_key=status_key)
    ws = _default_workspace_id(session_factory)
    _seed_open_contact(session_factory, ws, phone="+601234567892", open_window=True)
    hdr = _hdr(client, ws)

    items = {i["id"]: i for i in _list(client, hdr)}
    assert items[cid]["status"] == status_key
    assert items[cid]["isActive"] is True

    res = _post_without_channel_id(client, hdr, "+601234567892")
    assert res.status_code == 202, res.text
    assert sent == [PN]
