"""Consumer webhook delivery attempts: a delivery that cannot be attempted counts
as a failed attempt, and a URL the HTTP client cannot parse is refused when saved.

Behaviour pinned here:
1. A URL the HTTP client cannot parse is refused at save time (public 422
   ``invalid_request``, operator 400) and nothing is stored.
2. The shared URL guard raises ``UrlGuardError`` (naming the caller's subject) for
   such a URL; ordinary URLs stay accepted.
3. A STORED endpoint with such a URL (an older row) is a failed attempt: retry with
   backoff, dead-letter at ``MAX_ATTEMPTS``, auto-disable at the threshold, and no
   HTTP call is made.
4. Any other error while sending is a failed attempt whose stored text does not
   echo the raised message.
5. ``run_due_deliveries`` carries on with later due rows (any tenant) when
   ``dispatch`` raises for one, and leaves the session usable.
6. Controls: 2xx success, 5xx retry, blocked host refused with no POST.
"""
import socket
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app
from app.models import DEFAULT_TENANT_ID
from app.models.integration_activity import SOURCE_WEBHOOK_DELIVERY, IntegrationActivity
from app.services.url_guard import UrlGuardError, assert_deliverable, validate_public_https_url
from modules.omnichannel.models import WebhookDelivery, WebhookEndpoint
from modules.omnichannel.security import encrypt_secret
from modules.omnichannel.services import webhook_delivery as wd
from modules.omnichannel.services.webhook_service import AUTO_DISABLE_THRESHOLD
from tests.test_omnichannel_api_gateway import (
    _default_workspace_id,
    _mint,
    _seed_channel,
)
from tests.test_omnichannel_consumer_webhooks import (
    _capture_post,  # noqa: F401 - fixture
    _create_endpoint,
    _make_channel,
)
from tests.test_omnichannel_conversations import _auth
from tests.test_omnichannel_webhooks import _channel_id, _seed_thread

UNPARSEABLE_URLS = ["https://example.com/a\u0001b", "https://[::1/x"]
MARKER = "detail-from-client"


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    """Every host resolves to a public address; nothing touches the network."""

    def fake(host, *_a, **_k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]

    monkeypatch.setattr("socket.getaddrinfo", fake)


@pytest.fixture
def soft_client(client):
    """Same app and DB override as ``client`` but an unhandled server error comes
    back as a 500 response instead of raising into the test."""
    return TestClient(app, raise_server_exceptions=False)


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _now():
    return datetime.now(timezone.utc)


# ── 2. the shared guard ──────────────────────────────────────────────────────
@pytest.mark.parametrize("url", UNPARSEABLE_URLS)
def test_guard_refuses_url_the_client_cannot_parse(url):
    with pytest.raises(UrlGuardError) as exc:
        validate_public_https_url(url, subject="Widget URL")
    assert "Widget URL" in str(exc.value)


@pytest.mark.parametrize("url", UNPARSEABLE_URLS)
def test_deliverable_check_refuses_url_the_client_cannot_parse(url):
    with pytest.raises(UrlGuardError) as exc:
        assert_deliverable(url, subject="Widget URL")
    assert "Widget URL" in str(exc.value)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/a/b?x=1&y=two",
        "https://example.com/a%20b/%E2%9C%93",
        "https://bücher.example/path",
    ],
)
def test_guard_keeps_accepting_ordinary_urls(url):
    # control: passes today and must keep passing
    assert validate_public_https_url(url, subject="Widget URL")
    assert_deliverable(url, subject="Widget URL")


# ── 1. refused at save time ──────────────────────────────────────────────────
def _gateway(client, session_factory, phone_number_id):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id=phone_number_id)
    key = _mint(client, ws).json()["fullKey"]
    return {"Authorization": f"Bearer {key}"}


def _endpoint_count(session_factory):
    db = session_factory()
    try:
        return db.query(WebhookEndpoint).count()
    finally:
        db.close()


@pytest.mark.parametrize("url", UNPARSEABLE_URLS)
def test_public_create_refuses_url_the_client_cannot_parse(client, soft_client, session_factory, url):
    hdr = _gateway(client, session_factory, "pn-save-create")
    res = soft_client.post(
        "/api/v1/omnichannel/webhooks",
        json={"name": "bad", "url": url, "events": ["message.inbound"]},
        headers=hdr,
    )
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "invalid_request"
    assert _endpoint_count(session_factory) == 0


@pytest.mark.parametrize("url", UNPARSEABLE_URLS)
def test_public_update_refuses_url_the_client_cannot_parse(client, soft_client, session_factory, url):
    hdr = _gateway(client, session_factory, "pn-save-patch")
    created = client.post(
        "/api/v1/omnichannel/webhooks",
        json={"name": "ok", "url": "https://hooks.example.com/fx", "events": ["message.inbound"]},
        headers=hdr,
    )
    assert created.status_code == 201, created.text
    eid = created.json()["endpoint"]["id"]

    res = soft_client.patch(f"/api/v1/omnichannel/webhooks/{eid}", json={"url": url}, headers=hdr)
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "invalid_request"

    db = session_factory()
    try:
        assert db.query(WebhookEndpoint).filter(WebhookEndpoint.id == eid).one().url == (
            "https://hooks.example.com/fx"
        )
    finally:
        db.close()


@pytest.mark.parametrize("url", UNPARSEABLE_URLS)
def test_operator_create_refuses_url_the_client_cannot_parse(client, soft_client, session_factory, url):
    _seed_thread(session_factory, messages=[{}])
    channel_id = _channel_id(session_factory)
    h = _auth(client)
    res = soft_client.post(
        f"/omnichannel/channels/{channel_id}/webhooks",
        headers=h,
        json={"name": "bad", "url": url, "events": ["message.inbound"]},
    )
    assert res.status_code == 400, res.text
    assert _endpoint_count(session_factory) == 0


# ── helpers for stored rows ──────────────────────────────────────────────────
def _real_other_tenant(session_factory):
    """A second real tenant with the module installed, so `gateway_key_enabled`
    finds an active module and its default workspace. Returns (tenant_id, workspace_id)."""
    from app.models import Tenant
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService
    from modules.omnichannel.models import Workspace

    db = session_factory()
    try:
        TenantService(db).provision(
            name="Other",
            slug="other-due-run",
            admin_name="Olu",
            admin_email="admin@other-due-run.example.com",
            admin_password="pw12345678",
        )
        tenant = db.query(Tenant).filter(Tenant.slug == "other-due-run").first()
        AppStoreService(db).install(tenant.id, "omnichannel")
        ws = (
            db.query(Workspace)
            .filter(Workspace.tenant_id == tenant.id, Workspace.is_default.is_(True))
            .first()
        )
        return tenant.id, ws.id
    finally:
        db.close()


def _stored_endpoint(session_factory, phone, url, tenant_id=DEFAULT_TENANT_ID, workspace_id="ws-other"):
    """A row inserted directly, as an older row could exist."""
    if tenant_id == DEFAULT_TENANT_ID:
        channel_id = _make_channel(session_factory, phone)
        endpoint_id, _ = _create_endpoint(session_factory, channel_id, ["message.inbound"])
        db = session_factory()
        try:
            ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == endpoint_id).one()
            ep.url = url
            db.commit()
        finally:
            db.close()
        return endpoint_id
    db = session_factory()
    try:
        ep = WebhookEndpoint(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            channel_id="ch-other",
            name="Other",
            url=url,
            secret_encrypted=encrypt_secret("whsec_test"),
            events_json=["message.inbound"],
            status="ACTIVE",
        )
        db.add(ep)
        db.commit()
        return ep.id
    finally:
        db.close()


def _stored_delivery(session_factory, endpoint_id, event_id, tenant_id=DEFAULT_TENANT_ID, minutes_ago=5):
    db = session_factory()
    try:
        row = WebhookDelivery(
            tenant_id=tenant_id,
            endpoint_id=endpoint_id,
            event_id=event_id,
            event_type="message.inbound",
            payload_json={"id": event_id, "type": "message.inbound", "data": {"x": 1}},
            status="PENDING",
            next_attempt_at=_now() - timedelta(minutes=minutes_ago),
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _drive(db, delivery_id):
    """Run attempts until the delivery leaves PENDING; return the outcomes."""
    outcomes = []
    for _ in range(wd.MAX_ATTEMPTS):
        row = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_id).one()
        db.refresh(row)
        if row.status != "PENDING":
            break
        row.next_attempt_at = None  # skip the backoff wait
        db.commit()
        outcomes.append(wd.dispatch(db, delivery_id))
    return outcomes


# ── 3. stored endpoint with an unparseable URL ───────────────────────────────
@pytest.mark.parametrize("url", UNPARSEABLE_URLS)
def test_stored_unparseable_url_is_a_failed_attempt(session_factory, _capture_post, url):
    calls, _state = _capture_post
    eid = _stored_endpoint(session_factory, "pn-stored-1", url)
    did = _stored_delivery(session_factory, eid, "evt-stored-1")
    before = _now()

    db = session_factory()
    try:
        outcome = wd.dispatch(db, did)  # must not raise
        row = db.query(WebhookDelivery).filter(WebhookDelivery.id == did).one()
        db.refresh(row)
        assert outcome == "retry"
        assert row.attempt_count == 1
        assert row.status == "PENDING"
        assert row.error
        assert row.next_attempt_at is not None and _aware(row.next_attempt_at) > before
    finally:
        db.close()
    assert calls == []


@pytest.mark.parametrize("url", UNPARSEABLE_URLS)
def test_stored_unparseable_url_dead_letters_after_max_attempts(session_factory, _capture_post, url):
    calls, _state = _capture_post
    eid = _stored_endpoint(session_factory, "pn-stored-2", url)
    did = _stored_delivery(session_factory, eid, "evt-stored-2")

    db = session_factory()
    try:
        outcomes = _drive(db, did)
        assert outcomes == ["retry"] * (wd.MAX_ATTEMPTS - 1) + ["dead"]
        row = db.query(WebhookDelivery).filter(WebhookDelivery.id == did).one()
        db.refresh(row)
        assert row.status == "FAILED"
        assert row.attempt_count == wd.MAX_ATTEMPTS
        ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == eid).one()
        assert ep.consecutive_failures == 1
    finally:
        db.close()
    assert calls == []


@pytest.mark.parametrize("url", UNPARSEABLE_URLS)
def test_stored_unparseable_url_endpoint_auto_disables(session_factory, _capture_post, url):
    calls, _state = _capture_post
    eid = _stored_endpoint(session_factory, "pn-stored-3", url)
    ids = [
        _stored_delivery(session_factory, eid, f"evt-auto-{i}") for i in range(AUTO_DISABLE_THRESHOLD)
    ]
    db = session_factory()
    try:
        for did in ids:
            _drive(db, did)
        ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == eid).one()
        db.refresh(ep)
        assert ep.consecutive_failures >= AUTO_DISABLE_THRESHOLD
        assert ep.status == "AUTO_DISABLED"
    finally:
        db.close()
    assert calls == []


# ── 4. any other send error is a failed attempt, text not echoed ─────────────
@pytest.mark.parametrize(
    "make_error",
    [lambda: RuntimeError(MARKER), lambda: httpx.InvalidURL(MARKER)],
    ids=["runtime-error", "invalid-url"],
)
def test_other_send_error_is_a_failed_attempt_without_echo(session_factory, monkeypatch, make_error):
    eid = _stored_endpoint(session_factory, "pn-err-1", "https://consumer.example/hook")
    did = _stored_delivery(session_factory, eid, "evt-err-1")

    reached = []

    def boom(url, *, content, headers, timeout):
        reached.append(url)
        raise make_error()

    monkeypatch.setattr(wd, "_post", boom)
    before = _now()

    db = session_factory()
    try:
        outcome = wd.dispatch(db, did)  # must not raise
        assert reached, "the stubbed send was reached"
        row = db.query(WebhookDelivery).filter(WebhookDelivery.id == did).one()
        db.refresh(row)
        assert outcome == "retry"
        assert row.attempt_count == 1
        assert row.error
        assert MARKER not in row.error
        assert row.next_attempt_at is not None and _aware(row.next_attempt_at) > before
        acts = (
            db.query(IntegrationActivity)
            .filter(
                IntegrationActivity.tenant_id == DEFAULT_TENANT_ID,
                IntegrationActivity.source == SOURCE_WEBHOOK_DELIVERY,
            )
            .all()
        )
        assert acts, "the failed attempt is recorded in the activity log"
        assert all(MARKER not in (a.error_message or "") for a in acts)
    finally:
        db.close()


# ── 5. run_due_deliveries keeps going ────────────────────────────────────────
@pytest.mark.parametrize(
    "make_error",
    [
        lambda: RuntimeError("dispatch broke"),
        lambda: OperationalError("SELECT 1", {}, Exception("connection lost")),
    ],
    ids=["runtime-error", "operational-error"],
)
def test_run_due_deliveries_continues_after_one_dispatch_raises(
    session_factory, _capture_post, monkeypatch, make_error
):
    calls, _state = _capture_post
    ep_a = _stored_endpoint(session_factory, "pn-due-a", "https://consumer.example/a")
    other_tid, other_ws = _real_other_tenant(session_factory)
    ep_c = _stored_endpoint(
        session_factory, "pn-due-c", "https://consumer.example/c", tenant_id=other_tid, workspace_id=other_ws
    )
    bad = _stored_delivery(session_factory, ep_a, "evt-due-bad", minutes_ago=30)
    same_tenant = _stored_delivery(session_factory, ep_a, "evt-due-same", minutes_ago=20)
    other_tenant = _stored_delivery(
        session_factory, ep_c, "evt-due-other", tenant_id=other_tid, minutes_ago=10
    )

    real = wd.dispatch

    def flaky(db, delivery_id):
        if delivery_id == bad:
            raise make_error()
        return real(db, delivery_id)

    monkeypatch.setattr(wd, "dispatch", flaky)

    db = session_factory()
    try:
        wd.run_due_deliveries(db)  # must return normally
        assert db.query(WebhookDelivery).count() == 3  # session still usable
        for did in (same_tenant, other_tenant):
            row = db.query(WebhookDelivery).filter(WebhookDelivery.id == did).one()
            db.refresh(row)
            assert row.status == "SUCCESS", did
            assert row.attempt_count == 1
    finally:
        db.close()
    assert len(calls) == 2


# ── 6. controls that pass today ──────────────────────────────────────────────
def _single(session_factory, phone, url):
    eid = _stored_endpoint(session_factory, phone, url)
    return eid, _stored_delivery(session_factory, eid, f"evt-{phone}")


def test_control_2xx_is_success(session_factory, _capture_post):
    _calls, state = _capture_post
    state["status"] = 200
    _eid, did = _single(session_factory, "pn-ctl-ok", "https://consumer.example/hook")
    db = session_factory()
    try:
        assert wd.dispatch(db, did) == "success"
        assert db.query(WebhookDelivery).filter(WebhookDelivery.id == did).one().status == "SUCCESS"
    finally:
        db.close()


def test_control_5xx_is_retry(session_factory, _capture_post):
    _calls, state = _capture_post
    state["status"] = 503
    _eid, did = _single(session_factory, "pn-ctl-5xx", "https://consumer.example/hook")
    db = session_factory()
    try:
        assert wd.dispatch(db, did) == "retry"
        row = db.query(WebhookDelivery).filter(WebhookDelivery.id == did).one()
        assert row.attempt_count == 1 and row.error
    finally:
        db.close()


def test_control_blocked_host_is_a_refused_attempt_with_no_post(session_factory, _capture_post):
    calls, _state = _capture_post
    _eid, did = _single(session_factory, "pn-ctl-blocked", "https://169.254.169.254/hook")
    db = session_factory()
    try:
        assert wd.dispatch(db, did) == "retry"
        row = db.query(WebhookDelivery).filter(WebhookDelivery.id == did).one()
        assert row.attempt_count == 1
        assert "refused" in (row.error or "").lower()
    finally:
        db.close()
    assert calls == []


def test_run_due_deliveries_continues_after_a_row_leaves_the_session_failed(
    session_factory, _capture_post, monkeypatch
):
    calls, _state = _capture_post
    ep_a = _stored_endpoint(session_factory, "pn-fail-a", "https://consumer.example/a")
    other_tid, other_ws = _real_other_tenant(session_factory)
    ep_c = _stored_endpoint(
        session_factory, "pn-fail-c", "https://consumer.example/c", tenant_id=other_tid, workspace_id=other_ws
    )
    bad = _stored_delivery(session_factory, ep_a, "evt-fail-bad", minutes_ago=30)
    other_tenant = _stored_delivery(
        session_factory, ep_c, "evt-fail-other", tenant_id=other_tid, minutes_ago=10
    )

    real = wd.dispatch

    def breaks_session(db, delivery_id):
        if delivery_id == bad:
            # a flush that violates NOT NULL: the session cannot be used until rolled back
            db.add(WebhookDelivery(tenant_id=DEFAULT_TENANT_ID, event_id="x", event_type="y"))
            db.flush()
        return real(db, delivery_id)

    monkeypatch.setattr(wd, "dispatch", breaks_session)

    db = session_factory()
    try:
        wd.run_due_deliveries(db)  # must return normally
        row = db.query(WebhookDelivery).filter(WebhookDelivery.id == other_tenant).one()
        assert row.status == "SUCCESS"
        assert row.attempt_count == 1
        assert db.query(WebhookDelivery).count() == 2  # session still usable, bad row not stored
    finally:
        db.close()
    assert len(calls) == 1


# ── time budget of a due run ─────────────────────────────────────────────────
def _budget():
    return getattr(wd, "DUE_RUN_BUDGET_SECONDS", 240)


@pytest.fixture
def fake_clock(monkeypatch):
    """``time.monotonic`` as the delivery module reads it: real time plus an offset
    the tests move forward."""
    import time as time_mod

    real = time_mod.monotonic
    state = {"offset": 0.0}
    monkeypatch.setattr("time.monotonic", lambda: real() + state["offset"])
    return state


def _three_due(session_factory, tag):
    ep = _stored_endpoint(session_factory, f"pn-{tag}", "https://consumer.example/hook")
    ids = [
        _stored_delivery(session_factory, ep, f"evt-{tag}-{i}", minutes_ago=30 - i) for i in range(3)
    ]
    db = session_factory()
    try:
        before = {
            i: _aware(db.query(WebhookDelivery).filter(WebhookDelivery.id == i).one().next_attempt_at)
            for i in ids
        }
    finally:
        db.close()
    return ids, before


def test_due_run_budget_default_is_below_the_worker_soft_limit():
    from modules.omnichannel.services.webhook_delivery import DUE_RUN_BUDGET_SECONDS

    assert 0 < DUE_RUN_BUDGET_SECONDS < 300


def test_due_run_stops_taking_rows_after_its_budget(session_factory, _capture_post, monkeypatch, fake_clock):
    calls, _state = _capture_post
    ids, before = _three_due(session_factory, "bud1")
    real = wd.dispatch

    def slow_first(db, delivery_id):
        result = real(db, delivery_id)
        fake_clock["offset"] += _budget() + 1  # the budget passes during the first row
        return result

    monkeypatch.setattr(wd, "dispatch", slow_first)
    db = session_factory()
    try:
        wd.run_due_deliveries(db)  # returns normally
        rows = {i: db.query(WebhookDelivery).filter(WebhookDelivery.id == i).one() for i in ids}
        for r in rows.values():
            db.refresh(r)
        attempted = [i for i in ids if rows[i].attempt_count > 0]
        assert attempted == [ids[0]]
        assert rows[ids[0]].status == "SUCCESS"  # the row in flight finished normally
        for i in ids[1:]:
            assert rows[i].status == "PENDING"
            assert rows[i].attempt_count == 0
            assert _aware(rows[i].next_attempt_at) == before[i]
    finally:
        db.close()
    assert len(calls) == 1


def test_due_run_within_budget_attempts_every_row(session_factory, _capture_post, monkeypatch, fake_clock):
    # control: passes today
    calls, _state = _capture_post
    ids, _before = _three_due(session_factory, "bud2")
    real = wd.dispatch

    def quick(db, delivery_id):
        fake_clock["offset"] += 1
        return real(db, delivery_id)

    monkeypatch.setattr(wd, "dispatch", quick)
    db = session_factory()
    try:
        wd.run_due_deliveries(db)
        for i in ids:
            row = db.query(WebhookDelivery).filter(WebhookDelivery.id == i).one()
            db.refresh(row)
            assert row.status == "SUCCESS" and row.attempt_count == 1
    finally:
        db.close()
    assert len(calls) == 3


def test_soft_time_limit_in_a_send_is_a_failed_attempt_and_the_run_ends(
    session_factory, monkeypatch, fake_clock
):
    from celery.exceptions import SoftTimeLimitExceeded

    ep = _stored_endpoint(session_factory, "pn-bud3", "https://consumer.example/hook")
    first = _stored_delivery(session_factory, ep, "evt-bud3-0", minutes_ago=30)
    second = _stored_delivery(session_factory, ep, "evt-bud3-1", minutes_ago=20)

    reached = []

    def limit_hit(url, *, content, headers, timeout):
        reached.append(url)
        fake_clock["offset"] += _budget() + 1
        raise SoftTimeLimitExceeded(MARKER)

    monkeypatch.setattr(wd, "_post", limit_hit)
    db = session_factory()
    try:
        wd.run_due_deliveries(db)
        assert reached, "the stubbed send was reached"
        a = db.query(WebhookDelivery).filter(WebhookDelivery.id == first).one()
        b = db.query(WebhookDelivery).filter(WebhookDelivery.id == second).one()
        db.refresh(a)
        db.refresh(b)
        assert a.attempt_count == 1
        assert a.error and MARKER not in a.error
        assert a.status == "PENDING" and a.next_attempt_at is not None
        assert b.attempt_count == 0 and b.status == "PENDING"
    finally:
        db.close()
