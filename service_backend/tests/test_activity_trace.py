"""Correlated-trace tests (sprint-4/12 Slice 2, AC-DLC-14..18).

Covers: an outbound Meta send records an ``outbound_meta`` row carrying the wamid
as ``external_ref``; an inbound gateway send and its resulting outbound Meta call
share ONE ``trace_id`` (contextvar propagation, AC-DLC-15); the webhook-delivery
seam writes a ``webhook_delivery`` activity row attached to the trace by wamid
(AC-DLC-16); the trace endpoint returns the ordered legs, tenant-scoped +
permission-gated (AC-DLC-17/18).
"""
import pytest

from app.models import DEFAULT_TENANT_ID
from app.activity_log.service import ActivityLogService
from app.models.integration_activity import (
    SOURCE_INBOUND_API,
    SOURCE_OUTBOUND_META,
    SOURCE_WEBHOOK_DELIVERY,
    IntegrationActivity,
)
from modules.omnichannel.services import idempotency
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.test_omnichannel_api_gateway import (
    _default_workspace_id,
    _mint,
    _seed_channel,
    _seed_open_contact,
)


@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


@pytest.fixture(autouse=True)
def _reset_trace():
    """Each test starts + ends with the trace contextvar at its default (None) -
    ``run_send(trace_id=...)`` sets it without a reset, so isolate the leak."""
    from app.activity_log.context import trace_id_var

    token = trace_id_var.set(None)
    yield
    trace_id_var.reset(token)


def _headers(client):
    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _rows(session_factory, source=None):
    db = session_factory()
    try:
        q = db.query(IntegrationActivity).filter(
            IntegrationActivity.tenant_id == DEFAULT_TENANT_ID
        )
        if source:
            q = q.filter(IntegrationActivity.source == source)
        return q.all()
    finally:
        db.close()


# ── AC-DLC-14 / AC-DLC-15: outbound Meta row + shared trace ─────────────────


def _gateway_send(client, session_factory, phone="+60123123123"):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone=phone, open_window=True)
    key = _mint(client, ws).json()["fullKey"]
    r = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": phone, "type": "text", "text": {"body": "Hi there"}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 202, r.text
    return r


def test_gateway_send_records_outbound_meta_with_wamid(client, session_factory):
    _gateway_send(client, session_factory)

    outbound = _rows(session_factory, SOURCE_OUTBOUND_META)
    assert len(outbound) == 1
    row = outbound[0]
    assert row.operation == "graph:send"
    assert row.status == "success"
    # AC-DLC-14: the wamid is stamped as the external ref (async webhook join key).
    assert row.external_ref and row.external_ref.startswith("wamid.")
    assert row.latency_ms is not None


def test_inbound_and_outbound_share_trace_id(client, session_factory):
    """AC-DLC-15: the inbound gateway request and its outbound Meta send land on
    the SAME trace (the middleware's trace contextvar reaches the adapter)."""
    _gateway_send(client, session_factory)

    inbound = _rows(session_factory, SOURCE_INBOUND_API)
    outbound = _rows(session_factory, SOURCE_OUTBOUND_META)
    assert inbound and outbound
    send_inbound = [r for r in inbound if r.operation.endswith("/messages")]
    assert send_inbound, "no inbound_api row for POST /messages"
    trace = send_inbound[0].trace_id
    assert trace is not None
    assert outbound[0].trace_id == trace


def test_worker_boundary_threads_trace_to_outbound(client, session_factory):
    """AC-DLC-15 across the Celery boundary: a worker process has no trace
    contextvar (it defaults to None), so ``run_send`` must re-seed it from the
    passed ``trace_id`` for the outbound Meta row to land on the inbound trace.
    Simulated by calling ``run_send(trace_id=...)`` with NO contextvar set (as the
    enqueue→worker path does), which is what prod does - eager dev never crosses
    processes."""
    from modules.omnichannel.models import Channel, ConversationMessage
    from modules.omnichannel.services.send_runner import run_send
    from app.activity_log.context import trace_id_var

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    contact_id = _seed_open_contact(session_factory, ws, phone="+60123123999", open_window=True)

    # Seed a QUEUED outbound row (as the gateway would) WITHOUT sending it.
    db = session_factory()
    channel = db.query(Channel).filter(Channel.tenant_id == DEFAULT_TENANT_ID).first()
    row = ConversationMessage(
        tenant_id=DEFAULT_TENANT_ID,
        contact_id=contact_id,
        channel_id=channel.id,
        sender_type="AGENT",
        message_type="TEXT",
        body="worker-path",
        delivery_status="QUEUED",
    )
    db.add(row)
    db.commit()
    msg_id = row.id
    db.close()

    # The worker's contextvar is at its default - the trace arrives ONLY via kwarg.
    assert trace_id_var.get() is None
    db = session_factory()
    run_send(db, msg_id, trace_id="trace-worker")
    db.close()

    outbound = _rows(session_factory, SOURCE_OUTBOUND_META)
    assert len(outbound) == 1
    assert outbound[0].trace_id == "trace-worker"
    assert outbound[0].external_ref and outbound[0].external_ref.startswith("wamid.")


# ── AC-DLC-16: webhook seam writes a webhook_delivery row on the trace ───────


def test_webhook_delivery_records_activity_on_trace(client, session_factory):
    """A status webhook's delivery attempt writes a ``webhook_delivery`` activity
    row attached (by wamid) to the same trace as the outbound send."""
    from tests.test_omnichannel_webhooks import _channel_id, _process, _wa_payload
    from tests.test_omnichannel_conversations import _seed_thread
    from tests.test_omnichannel_consumer_webhooks import _create_endpoint
    from modules.omnichannel.models import WebhookDelivery
    from modules.omnichannel.services.webhook_delivery import dispatch
    import modules.omnichannel.services.webhook_delivery as wd

    # An outbound_meta leg already recorded for wamid.o1 on trace "trace-xyz".
    db = session_factory()
    ActivityLogService(db).record(
        tenant_id=DEFAULT_TENANT_ID,
        source=SOURCE_OUTBOUND_META,
        operation="graph:send",
        status="success",
        trace_id="trace-xyz",
        external_ref="wamid.o1",
    )
    db.close()

    _seed_thread(
        session_factory,
        messages=[
            {
                "body": "out",
                "sender_type": "AGENT",
                "external_message_id": "wamid.o1",
                "delivery_status": "SENT",
            }
        ],
    )
    channel_id = _channel_id(session_factory)
    endpoint_id, _ = _create_endpoint(session_factory, channel_id, ["message.status"])
    _process(session_factory, channel_id, _wa_payload(statuses=[{"id": "wamid.o1", "status": "delivered"}]))

    # Deliver the queued webhook with a stubbed 200 POST.
    class _Resp:
        status_code = 200

    original = wd.httpx.post
    wd.httpx.post = lambda *a, **k: _Resp()
    try:
        db = session_factory()
        row = (
            db.query(WebhookDelivery)
            .filter(WebhookDelivery.endpoint_id == endpoint_id)
            .one()
        )
        assert dispatch(db, row.id) == "success"
        db.close()
    finally:
        wd.httpx.post = original

    hooks = _rows(session_factory, SOURCE_WEBHOOK_DELIVERY)
    assert len(hooks) == 1
    hook = hooks[0]
    assert hook.operation == "webhook:message.status"
    assert hook.status == "success"
    assert hook.external_ref == "wamid.o1"
    # AC-DLC-16: attached to the originating trace by the wamid.
    assert hook.trace_id == "trace-xyz"


# ── AC-DLC-17 / AC-DLC-18: trace endpoint ───────────────────────────────────


def _seed_trace(session_factory, trace_id, tenant_id=DEFAULT_TENANT_ID):
    # Explicit increasing created_at so the ordering assertion is deterministic
    # regardless of SQLite's second-precision clock (Postgres µs never collides).
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)
    legs = [
        (SOURCE_INBOUND_API, "POST /messages", None),
        (SOURCE_OUTBOUND_META, "graph:send", "wamid.abc"),
        (SOURCE_WEBHOOK_DELIVERY, "webhook:message.status", "wamid.abc"),
    ]
    db = session_factory()
    for i, (source, operation, ref) in enumerate(legs):
        db.add(
            IntegrationActivity(
                tenant_id=tenant_id,
                source=source,
                operation=operation,
                status="success",
                trace_id=trace_id,
                external_ref=ref,
                latency_ms=(i + 1) * 10,
                created_at=base + timedelta(seconds=i),
            )
        )
    db.commit()
    db.close()


def test_trace_endpoint_returns_ordered_legs(client, session_factory):
    _seed_trace(session_factory, "trace-777")
    headers = _headers(client)
    res = client.get("/integration-logs/trace/trace-777", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["traceId"] == "trace-777"
    legs = body["legs"]
    assert len(legs) == 3
    # Oldest → newest.
    assert [leg["source"] for leg in legs] == [
        "inbound_api",
        "outbound_meta",
        "webhook_delivery",
    ]
    assert legs[0]["createdAt"].endswith("Z")


def test_trace_endpoint_gated_and_tenant_scoped(client, session_factory):
    # Another tenant's trace never leaks.
    _seed_trace(session_factory, "trace-other", tenant_id="tenant-other-xyz")
    # Unauthenticated → 401.
    assert client.get("/integration-logs/trace/trace-other").status_code == 401
    headers = _headers(client)
    res = client.get("/integration-logs/trace/trace-other", headers=headers)
    assert res.status_code == 200
    assert res.json()["legs"] == []
