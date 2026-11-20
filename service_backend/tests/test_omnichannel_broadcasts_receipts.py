"""Omnichannel Broadcasts - plan 29 S2b (receipts, the ambiguous-state
reconciler, the scheduled-broadcast beat tick, test-send). Covers
AC-BRD-36..42.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.jobs.service import JobService
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import BackgroundJob
from modules.omnichannel.models import (
    Broadcast,
    BroadcastRecipient,
    Channel,
    Contact,
    ConversationMessage,
)
from modules.omnichannel.services import realtime, statuses
from modules.omnichannel.services.broadcast_audience import snapshot_audience
from modules.omnichannel.services.broadcast_send_service import (
    SEND_JOB_TYPE,
    STUCK_SENDING_MINUTES,
    finalize_broadcast,
    reconcile_broadcast,
    run_broadcast_send,
    run_due_broadcasts,
)
from modules.omnichannel.services.broadcast_service import BroadcastService, start_scheduled_broadcast
from tests.test_omnichannel_broadcasts import (
    _broadcasts_base,
    _create_payload,
    _fixture,
)
from tests.test_omnichannel_contacts_module import (
    _auth,
    _no_perm_auth,
    _other_tenant_auth,
    _seed_contact,
)
from tests.test_omnichannel_webhooks import _wa_payload


@pytest.fixture(autouse=True)
def _fake_realtime():
    import fakeredis

    client = fakeredis.FakeRedis(decode_responses=True)
    realtime.set_client(client)
    yield client
    realtime.set_client(None)


def _process_status(session_factory, channel_id, external_id, wa_status, errors=None):
    from modules.omnichannel.services.inbound_service import InboundService

    row = {"id": external_id, "status": wa_status, "timestamp": "1717550001"}
    if errors:
        row["errors"] = errors
    db = session_factory()
    try:
        return InboundService(db).process_payload(channel_id, _wa_payload(statuses=[row]))
    finally:
        db.close()


def _send_one(client, session_factory, h, ws, channel_id, contact_id, template_id):
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()
    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})
    assert res.status_code == 200, res.text
    return created["id"]


# ── AC-BRD-37: receipts at each of the three seams, forward-only, idempotent ─
def test_send_runner_sent_stamps_recipient_sent_and_message_id(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    broadcast_id = _send_one(client, session_factory, h, ws, channel_id, contact_id, template_id)

    db = session_factory()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast_id).first()
    assert recip.state == "sent"
    assert recip.message_id
    broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
    assert broadcast.sent_count == 1
    db.close()


def test_inbound_delivered_then_read_advance_recipient_and_counts(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    broadcast_id = _send_one(client, session_factory, h, ws, channel_id, contact_id, template_id)

    db = session_factory()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast_id).first()
    msg = db.query(ConversationMessage).filter(ConversationMessage.id == recip.message_id).first()
    ext_id = msg.external_message_id
    db.close()
    assert ext_id

    _process_status(session_factory, channel_id, ext_id, "delivered")
    db = session_factory()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast_id).first()
    broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
    assert recip.state == "delivered"
    assert broadcast.delivered_count == 1
    assert broadcast.sent_count == 0
    db.close()

    _process_status(session_factory, channel_id, ext_id, "read")
    db = session_factory()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast_id).first()
    broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
    assert recip.state == "read"
    assert broadcast.read_count == 1
    db.close()

    # Late DELIVERED after READ is dropped (forward-only, AC-BRD-37).
    _process_status(session_factory, channel_id, ext_id, "delivered")
    db = session_factory()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast_id).first()
    broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
    assert recip.state == "read"
    assert broadcast.read_count == 1
    assert broadcast.delivered_count == 0
    db.close()

    # Idempotent replay of the SAME status is a no-op too.
    _process_status(session_factory, channel_id, ext_id, "read")
    db = session_factory()
    broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
    assert broadcast.read_count == 1
    db.close()


def test_inbound_failed_after_sent_marks_recipient_failed_with_error(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    broadcast_id = _send_one(client, session_factory, h, ws, channel_id, contact_id, template_id)

    db = session_factory()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast_id).first()
    msg = db.query(ConversationMessage).filter(ConversationMessage.id == recip.message_id).first()
    ext_id = msg.external_message_id
    db.close()

    _process_status(session_factory, channel_id, ext_id, "failed", errors=[{"code": 131047, "title": "Number blocked"}])
    db = session_factory()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast_id).first()
    broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
    assert recip.state == "failed"
    assert recip.error_code is not None
    assert broadcast.failed_count == 1
    assert broadcast.sent_count == 0
    db.close()


def test_record_delivery_realtime_publish(client, session_factory, monkeypatch):
    published = []
    monkeypatch.setattr(realtime, "publish", lambda ws_id, event: published.append((ws_id, event)))

    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    broadcast_id = _send_one(client, session_factory, h, ws, channel_id, contact_id, template_id)

    db = session_factory()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast_id).first()
    msg = db.query(ConversationMessage).filter(ConversationMessage.id == recip.message_id).first()
    ext_id = msg.external_message_id
    db.close()
    published.clear()

    _process_status(session_factory, channel_id, ext_id, "delivered")
    types = [e["type"] for _, e in published]
    assert "broadcast.updated" in types


# ── receipt hooks never break the underlying message path ───────────────────
def test_receipt_hook_raising_never_breaks_the_send(client, session_factory, monkeypatch):
    from modules.omnichannel.services import broadcast_receipts

    def _boom(db, row):
        raise RuntimeError("boom")

    monkeypatch.setattr(broadcast_receipts, "record_delivery", _boom)
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    broadcast_id = _send_one(client, session_factory, h, ws, channel_id, contact_id, template_id)

    db = session_factory()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast_id).first()
    msg = db.query(ConversationMessage).filter(ConversationMessage.id == recip.message_id).first()
    assert msg.delivery_status == "SENT"
    db.close()


def test_receipt_hook_raising_never_breaks_inbound_webhook(client, session_factory, monkeypatch):
    from modules.omnichannel.services import broadcast_receipts

    def _boom(db, row):
        raise RuntimeError("boom")

    monkeypatch.setattr(broadcast_receipts, "record_delivery", _boom)
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    broadcast_id = _send_one(client, session_factory, h, ws, channel_id, contact_id, template_id)

    db = session_factory()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast_id).first()
    msg = db.query(ConversationMessage).filter(ConversationMessage.id == recip.message_id).first()
    ext_id = msg.external_message_id
    db.close()

    result = _process_status(session_factory, channel_id, ext_id, "delivered")
    assert result["statuses"] == 1  # the webhook pipeline itself still succeeded


# ── AC-BRD-38: the crash-window reconciler ──────────────────────────────────
def test_reconcile_adopts_matching_outbound_message(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    db = session_factory()
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    snapshot_audience(db, broadcast)
    db.commit()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast.id).first()
    claim_time = datetime.now(timezone.utc) - timedelta(seconds=5)
    recip.attempted_at = claim_time
    recip.attempts = 1
    # Simulate the crash: a message was actually created + carries the
    # marker, but the recipient row's own update never landed.
    msg = ConversationMessage(
        tenant_id=DEFAULT_TENANT_ID, contact_id=contact_id, channel_id=channel_id,
        sender_type="AGENT", message_type="TEMPLATE", body="hi",
        delivery_status="SENT", external_message_id="wamid.crash-1",
        metadata_json={"broadcast": {"id": broadcast.id, "recipientId": recip.id}},
        created_at=claim_time + timedelta(seconds=1),
    )
    db.add(msg)
    db.commit()

    resolved = reconcile_broadcast(db, broadcast)
    assert resolved == 1
    db.refresh(recip)
    assert recip.state == "sent"
    assert recip.message_id == msg.id
    db.close()


def test_reconcile_no_matching_message_marks_send_result_unknown(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    db = session_factory()
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    snapshot_audience(db, broadcast)
    db.commit()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast.id).first()
    recip.attempted_at = datetime.now(timezone.utc)
    recip.attempts = 1
    db.commit()

    resolved = reconcile_broadcast(db, broadcast)
    assert resolved == 1
    db.refresh(recip)
    assert recip.state == "failed"
    assert recip.error_code == "send_result_unknown"
    db.close()


def test_reconcile_idempotent_second_call_no_op(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()
    db = session_factory()
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    snapshot_audience(db, broadcast)
    db.commit()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast.id).first()
    recip.attempted_at = datetime.now(timezone.utc)
    db.commit()

    assert reconcile_broadcast(db, broadcast) == 1
    assert reconcile_broadcast(db, broadcast) == 0  # nothing ambiguous left
    db.close()


def test_finalize_broadcast_calls_reconcile_before_terminal(client, session_factory):
    """AC-BRD-38/39: `finalize_broadcast` resolves ambiguity before the
    broadcast is allowed to reach SENT, so the invariant (denormalized counts
    == a live aggregate) always holds at finalize."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    db = session_factory()
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    broadcast.status_id = statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "SENDING")
    db.commit()
    snapshot_audience(db, broadcast)
    db.commit()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast.id).first()
    recip.attempted_at = datetime.now(timezone.utc)
    db.commit()
    job = JobService(db).create(type=SEND_JOB_TYPE, tenant_id=DEFAULT_TENANT_ID, payload={"broadcastId": broadcast.id})

    finalize_broadcast(db, broadcast, job)

    db.refresh(broadcast)
    db.refresh(recip)
    assert recip.state == "failed"
    assert recip.error_code == "send_result_unknown"
    assert statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "SENT") == broadcast.status_id
    assert broadcast.failed_count == 1
    db.close()


# ── AC-BRD-42: the scheduled-broadcast beat tick ────────────────────────────
def test_run_due_broadcasts_starts_overdue_scheduled_broadcast(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()
    future = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={"scheduledAt": future})

    # Simulate the schedule passing (downtime-safe - a tick that runs after
    # the moment still fires it).
    db = session_factory()
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    broadcast.scheduled_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.commit()

    result = run_due_broadcasts(db)
    assert result["started"] == 1
    db.refresh(broadcast)
    assert statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "SENT") == broadcast.status_id
    assert broadcast.job_id
    db.close()


def test_run_due_broadcasts_is_a_no_op_when_nothing_due(session_factory):
    db = session_factory()
    result = run_due_broadcasts(db)
    assert result == {"started": 0, "reconciled": 0, "finalized": 0}
    db.close()


def test_start_scheduled_broadcast_claim_race_only_one_wins(client, session_factory):
    """Two concurrent callers (a manual /send and a tick, or two ticks) never
    create two jobs - the shared atomic-claim seam."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    db1 = session_factory()
    db2 = session_factory()
    broadcast1 = db1.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    broadcast2 = db2.query(Broadcast).filter(Broadcast.id == created["id"]).first()

    ok1 = start_scheduled_broadcast(db1, broadcast1)
    ok2 = start_scheduled_broadcast(db2, broadcast2)
    assert ok1 is True
    assert ok2 is False

    jobs = db1.query(BackgroundJob).filter(BackgroundJob.tenant_id == DEFAULT_TENANT_ID, BackgroundJob.type == SEND_JOB_TYPE).all()
    assert len(jobs) == 1
    db1.close()
    db2.close()


def test_run_due_broadcasts_reconciles_and_finalizes_stuck_sending(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    db = session_factory()
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    broadcast.status_id = statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "SENDING")
    db.commit()
    snapshot_audience(db, broadcast)
    db.commit()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast.id).first()
    recip.attempted_at = datetime.now(timezone.utc)
    db.commit()
    # Force the row to look STALE (no chunk progress for longer than the
    # threshold) without waiting in real time.
    stale = datetime.now(timezone.utc) - timedelta(minutes=STUCK_SENDING_MINUTES + 5)
    db.query(Broadcast).filter(Broadcast.id == broadcast.id).update({"updated_at": stale})
    db.commit()

    result = run_due_broadcasts(db)
    assert result["reconciled"] == 1
    assert result["finalized"] == 1

    db.refresh(broadcast)
    db.refresh(recip)
    assert recip.state == "failed"
    assert statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "SENT") == broadcast.status_id
    db.close()


def test_run_due_broadcasts_leaves_genuinely_queued_broadcast_alone(client, session_factory):
    """A SENDING broadcast that is merely STALE-looking but still has real
    unclaimed queued work is left alone - the tick never prematurely
    finishes a broadcast that hasn't actually failed."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    db = session_factory()
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    broadcast.status_id = statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "SENDING")
    db.commit()
    snapshot_audience(db, broadcast)  # recipient stays `queued`, never claimed
    db.commit()
    stale = datetime.now(timezone.utc) - timedelta(minutes=STUCK_SENDING_MINUTES + 5)
    db.query(Broadcast).filter(Broadcast.id == broadcast.id).update({"updated_at": stale})
    db.commit()

    result = run_due_broadcasts(db)
    assert result["finalized"] == 0

    db.refresh(broadcast)
    assert statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "SENDING") == broadcast.status_id
    db.close()


# ── AC-BRD-41: test send ─────────────────────────────────────────────────────
def test_test_send_sends_one_message_no_recipient_no_status_change(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    other_contact = _seed_contact(session_factory, ws, first="Other", last="Contact", phone="+60 12-000 5555")
    from tests.test_omnichannel_broadcasts import _add_identity

    _add_identity(session_factory, other_contact, channel_id)

    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    res = client.post(
        f"{_broadcasts_base(ws)}/{created['id']}/test-send", headers=h, json={"contactId": other_contact}
    )
    assert res.status_code == 200, res.text
    message_id = res.json()["messageId"]
    assert message_id

    db = session_factory()
    assert db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == created["id"]).count() == 0
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    assert broadcast.total_count == 0
    assert statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "DRAFT") == broadcast.status_id
    msg = db.query(ConversationMessage).filter(ConversationMessage.id == message_id).first()
    assert msg.metadata_json["broadcast"] == {"id": created["id"], "test": True}
    db.close()


def test_test_send_never_creates_a_receipt_recipient_link(client, session_factory):
    """A test-send message's later delivery receipt is a no-op (D-A4-18 -
    the `test` marker short-circuits `record_delivery`)."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()
    res = client.post(
        f"{_broadcasts_base(ws)}/{created['id']}/test-send", headers=h, json={"contactId": contact_id}
    )
    assert res.status_code == 200, res.text

    db = session_factory()
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    assert broadcast.sent_count == 0
    assert broadcast.total_count == 0
    db.close()


def test_test_send_unresolvable_binding_422(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    # Simulate drift AFTER save (D-A4-5 normally makes this unreachable via
    # the API: save-time validation requires a non-blank fallback) - write
    # directly to the row, mirroring the direct `SkipMissingVariable` unit
    # test in S2a, so the send-time defence-in-depth path is exercised.
    db = session_factory()
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    broadcast.bindings_json = {
        "header": [], "buttons": [],
        "body": [{"source": "contactField", "field": "firstName", "fallback": "   "}],
    }
    db.commit()
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    contact.first_name = None
    db.commit()
    db.close()

    res = client.post(
        f"{_broadcasts_base(ws)}/{created['id']}/test-send", headers=h, json={"contactId": contact_id}
    )
    assert res.status_code == 422
    assert "contactId" in res.json()["detail"]["fieldErrors"]


def test_test_send_contact_outside_workspace_404(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    res = client.post(
        f"{_broadcasts_base(ws)}/{created['id']}/test-send", headers=h, json={"contactId": "does-not-exist"}
    )
    assert res.status_code == 404


def test_test_send_works_regardless_of_broadcast_status(client, session_factory):
    """AC-BRD-41 - no status restriction: a test send after the broadcast has
    already SENT still works (previews the current saved config)."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    broadcast_id = _send_one(client, session_factory, h, ws, channel_id, contact_id, template_id)

    res = client.post(
        f"{_broadcasts_base(ws)}/{broadcast_id}/test-send", headers=h, json={"contactId": contact_id}
    )
    assert res.status_code == 200, res.text


def test_test_send_requires_broadcasts_send_permission(client, session_factory):
    from tests.test_omnichannel_broadcasts_send import _read_only_send_auth

    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    h_no_send = _read_only_send_auth(client, session_factory, email="brd-testsend-noperm@example.com")
    res = client.post(
        f"{_broadcasts_base(ws)}/{created['id']}/test-send", headers=h_no_send, json={"contactId": contact_id}
    )
    assert res.status_code == 403


def test_test_send_tenant_isolation_404(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    h2 = _other_tenant_auth(client, session_factory, slug="other-brd-testsend")
    res = client.post(
        f"{_broadcasts_base(ws)}/{created['id']}/test-send", headers=h2, json={"contactId": contact_id}
    )
    assert res.status_code == 404
