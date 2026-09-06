"""Omnichannel Broadcasts - plan 29 S2a (send job, fan-out through
`MessageService.send_message`, per-channel rate tier, per-recipient
idempotency, cooperative cancel). Covers AC-BRD-26..35, 40, plus this slice's
share of AC-BRD-51 (permission gates, tenant isolation, realtime publish,
entity-event emission, actor resolution). Receipts / the crash-window
reconciler / the scheduled beat tick / test-send are S2b (AC-BRD-36..39, 41,
42 are only partially exercised here - the parts reachable without those
seams).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.workflow_engine.entity_events import register_event_subscriber, unregister_event_subscriber
from modules.omnichannel.models import (
    Broadcast,
    BroadcastRecipient,
    Channel,
    Contact,
    ConversationMessage,
    WhatsappTemplate,
)
from modules.omnichannel.services import realtime, statuses
from modules.omnichannel.services.broadcast_audience import snapshot_audience
from modules.omnichannel.services.broadcast_send_service import (
    CHUNK_SIZE,
    SEND_JOB_TYPE,
    compute_chunk_pacing,
    finalize_broadcast,
    rate_for_channel,
    run_broadcast_send,
    run_one_chunk,
)
from tests.test_omnichannel_contacts_module import (
    _auth,
    _base,
    _ensure_channel,
    _no_perm_auth,
    _other_tenant_auth,
    _seed_contact,
    _workspace_id,
)
from tests.test_omnichannel_broadcasts import (
    _add_contact_field,
    _add_identity,
    _broadcasts_base,
    _create_payload,
    _ensure_template,
    _fixture,
    _valid_bindings,
)

from app.jobs.service import JobService
from app.models.background_job import JOB_DONE, BackgroundJob


def _read_only_send_auth(client, session_factory, email="brd-readonly@example.com"):
    """A user holding `broadcasts.read` + `broadcasts.manage` but NOT
    `broadcasts.send` (AC-BRD-25)."""
    from app.models import Role, User, UserStatus
    from app.repositories.permission_repository import PermissionRepository
    from app.security import hash_password

    db = session_factory()
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="Broadcasts No-Send")
    role.permissions = PermissionRepository(db).get_by_keys(["broadcasts.read", "broadcasts.manage"])
    db.add(role)
    user = User(
        tenant_id=DEFAULT_TENANT_ID, email=email, name="No Send",
        password=hash_password("Password123!"), status=UserStatus.ACTIVE.value,
    )
    user.roles = [role]
    db.add(user)
    db.commit()
    db.close()
    return _auth(client, email=email, password="Password123!")


def _broadcast_row(session_factory, broadcast_id):
    db = session_factory()
    row = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
    return row, db


# ── AC-BRD-26/27/28/32/33/39: the full happy-path send ──────────────────────
def test_send_now_full_happy_path_sent_with_counts_and_message(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "SENT"
    assert body["jobId"]
    assert body["startedAt"] and body["finishedAt"]
    assert body["counts"] == {"total": 1, "sent": 1, "delivered": 0, "read": 0, "failed": 0, "skipped": 0}

    db = session_factory()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == created["id"]).first()
    assert recip.state == "sent"
    assert recip.message_id

    msg = db.query(ConversationMessage).filter(ConversationMessage.id == recip.message_id).first()
    assert msg is not None
    assert msg.message_type == "TEMPLATE"
    assert msg.metadata_json["broadcast"] == {"id": created["id"], "recipientId": recip.id}

    job = db.query(BackgroundJob).filter(BackgroundJob.id == body["jobId"]).first()
    assert job.type == SEND_JOB_TYPE
    assert job.status == "done"
    assert job.progress_total == 1
    assert job.progress_done == 1
    assert job.progress_failed == 0
    assert job.result_json == {"total": 1, "sent": 1, "failed": 0, "skipped": 0, "cancelled": False}
    db.close()


def test_start_scheduled_broadcast_claim_not_atomic_with_job_creation_bl_ss_102(client, session_factory, monkeypatch):
    """Tester observation (review round 1, backlogged as BL-SS-102, NOT
    fixed in this pass): the SENDING claim and the `background_jobs` row are
    NOT atomic. `BroadcastRepository.claim_status` commits INTERNALLY as
    part of its own atomic-claim pattern (mirrors `BackgroundJobRepository.
    claim`), so if job creation then raises (e.g. a process that never ran
    the module boot hook, so `omnichannel.broadcast_send` isn't registered),
    the claim is ALREADY durable - the broadcast is left stuck SENDING with
    `job_id NULL` (the 15-minute stuck-sweep in `run_due_broadcasts` is the
    only recovery). This test PINS today's actual (buggy) behavior so a
    future change doesn't silently make it worse without anyone noticing;
    BL-SS-102 tracks the real fix (`claim_status(commit=False)` for this ONE
    caller only)."""
    import app.jobs.service as jobs_service_module
    from app.jobs.registry import UnknownJobType
    from modules.omnichannel.services.broadcast_service import start_scheduled_broadcast

    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    def boom(job_type: str):
        raise UnknownJobType(f"No handler registered for job type '{job_type}'.")

    monkeypatch.setattr(jobs_service_module, "handler_for", boom)

    db = session_factory()
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    with pytest.raises(UnknownJobType):
        start_scheduled_broadcast(db, broadcast)
    db.rollback()  # what the request-teardown `get_db` finally-block does

    db2 = session_factory()
    survivor = db2.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    # Today: stuck SENDING with no job - this is BL-SS-102, not a passing
    # contract. Flip this assertion to DRAFT/job_id is None once fixed.
    assert statuses.status_id_for(db2, DEFAULT_TENANT_ID, "BROADCAST", "SENDING") == survivor.status_id
    assert survivor.job_id is None
    db2.close()


def test_send_csw_exempt_expired_window_still_sends(client, session_factory):
    """AC-BRD-33: an approved-template send is NOT gated by the 24h CSW - a
    contact whose window closed still receives the broadcast."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    db = session_factory()
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    contact.csw_expires_at = datetime.now(timezone.utc) - timedelta(days=3)
    db.commit()
    db.close()

    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()
    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})
    assert res.status_code == 200
    assert res.json()["status"] == "SENT"
    assert res.json()["counts"]["sent"] == 1


# ── AC-BRD-26: schedule branch + status-conflict matrix ─────────────────────
def test_send_with_future_scheduled_at_becomes_scheduled_no_job(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")

    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={"scheduledAt": future})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "SCHEDULED"
    assert body["jobId"] is None

    db = session_factory()
    assert db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == created["id"]).count() == 0
    db.close()


def test_send_past_scheduled_at_422(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={"scheduledAt": past})
    assert res.status_code == 422
    assert "scheduledAt" in res.json()["detail"]["fieldErrors"]


def test_send_already_sent_returns_409(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()
    assert client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={}).status_code == 200

    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})
    assert res.status_code == 409
    assert res.json()["detail"]["reason"] == "broadcast_not_editable"


def test_send_race_second_atomic_claim_loses_no_second_job(client, session_factory):
    """AC-BRD-26: the atomic status-claim, isolated from full job execution -
    two sessions racing the SAME DRAFT -> SENDING transition, only one wins."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    from modules.omnichannel.repositories.broadcast_repository import BroadcastRepository

    db1 = session_factory()
    db2 = session_factory()
    draft_id = statuses.status_id_for(db1, DEFAULT_TENANT_ID, "BROADCAST", "DRAFT")
    sending_id = statuses.status_id_for(db1, DEFAULT_TENANT_ID, "BROADCAST", "SENDING")
    ok1 = BroadcastRepository(db1).claim_status(
        created["id"], DEFAULT_TENANT_ID, from_status_ids=[draft_id], to_status_id=sending_id
    )
    ok2 = BroadcastRepository(db2).claim_status(
        created["id"], DEFAULT_TENANT_ID, from_status_ids=[draft_id], to_status_id=sending_id
    )
    assert ok1 is True
    assert ok2 is False
    db1.close()
    db2.close()


# ── AC-BRD-27/28: snapshot at send time, skip reasons wired into the job ────
def test_send_no_identity_contact_skipped_others_sent(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    no_identity = _seed_contact(session_factory, ws, first="NoId", last="Contact", phone="+60 12-000 9999")

    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id, no_identity]},
    )).json()
    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "SENT"
    assert body["counts"] == {"total": 2, "sent": 1, "delivered": 0, "read": 0, "failed": 0, "skipped": 1}

    db = session_factory()
    recips = {
        r.contact_id: (r.state, r.skip_reason)
        for r in db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == created["id"])
    }
    assert recips[contact_id] == ("sent", None)
    assert recips[no_identity] == ("skipped", "no_identity")
    db.close()


# ── AC-BRD-34: binding resolution + missing_variable skip ───────────────────
def test_send_missing_variable_skip_others_sent(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    _add_contact_field(session_factory, ws, "vip_tier")
    blank_field_contact = _seed_contact(session_factory, ws, first="Blank", last="Field", phone="+60 12-000 8888")
    _add_identity(session_factory, blank_field_contact, channel_id)

    bindings = {
        "header": [],
        "body": [
            {"source": "contactField", "field": "customFields.vip_tier", "fallback": "n/a"},
            {"source": "static", "text": "hello"},
        ],
        "buttons": [],
    }
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id,
        audience={"kind": "contacts", "contactIds": [contact_id, blank_field_contact]},
        bindings=bindings,
    )).json()

    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})
    assert res.status_code == 200, res.text
    body = res.json()
    # Both contacts have NO `vip_tier` custom field value -> fallback "n/a"
    # fills it, so nothing is actually skipped in THIS scenario; assert the
    # fallback path sent successfully for both (the direct SkipMissingVariable
    # unit test below covers the true skip path).
    assert body["counts"]["sent"] == 2
    assert body["counts"]["skipped"] == 0


def test_resolve_bindings_direct_skip_missing_variable():
    """Direct unit coverage of the `SkipMissingVariable` path (AC-BRD-34) -
    a `contactField` binding whose value AND fallback both resolve empty
    after sanitization (whitespace-only fallback)."""
    from modules.omnichannel.services.broadcast_bindings import SkipMissingVariable, resolve
    from modules.omnichannel.schemas import BroadcastBindings

    contact = Contact(tenant_id=DEFAULT_TENANT_ID, workspace_id="ws", first_name=None, custom_fields_json={})
    bindings = BroadcastBindings.model_validate({
        "header": [], "buttons": [],
        "body": [{"source": "contactField", "field": "firstName", "fallback": "   "}],
    })
    with pytest.raises(SkipMissingVariable) as exc:
        resolve(bindings, contact)
    assert exc.value.field == "firstName"


def test_sanitize_param_strips_control_chars_and_long_runs():
    from modules.omnichannel.services.broadcast_bindings import _sanitize_param

    assert _sanitize_param("Hello\nWorld\t!") == "Hello World !"
    assert _sanitize_param("a" + " " * 10 + "b") == "a b"
    assert _sanitize_param("x" * 2000) == "x" * 1024


# ── AC-BRD-36: transient vs permanent send failure ──────────────────────────
def test_broadcast_recipient_permanent_send_failure_marks_failed(client, session_factory, monkeypatch):
    """A permanent send rejection (`SendError` with no `transient` flag)
    stamps the outbound message FAILED - `_process_recipient` maps that to
    `failed`/`send_failed`, and the broadcast still finalizes SENT overall
    (SENT means "every recipient reached a terminal state", not "every send
    succeeded" - counts disambiguate)."""
    from modules.omnichannel.adapters import whatsapp_cloud
    from modules.omnichannel.adapters.base import SendError

    def boom(self, creds, phone, to, **kw):
        raise SendError("Recipient number is invalid.")

    monkeypatch.setattr(whatsapp_cloud.WhatsAppCloudAdapter, "send", boom)

    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()
    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})
    assert res.status_code == 200, res.text

    db = session_factory()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == created["id"]).first()
    assert recip.state == "failed"
    assert recip.error_code == "send_failed"
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    assert broadcast.failed_count == 1
    assert broadcast.sent_count == 0
    assert statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "SENT") == broadcast.status_id
    db.close()


def test_broadcast_recipient_transient_send_failure_stays_queued_not_failed(client, session_factory, monkeypatch):
    """A transient send failure (`SendError(transient=True)`, e.g. a Meta 5xx)
    must NOT be marked `failed` - it stays `queued` for a later retry
    (`_requeue_transient` resets the outbound row to QUEUED; the bounded
    in-run retry re-attempts once, and a still-transient outcome after that
    retry is deliberately left ambiguous for S2b's reconciler/beat tick,
    never silently counted as a permanent failure). Asserted straight after
    `run_one_chunk` - BEFORE `finalize_broadcast`'s `reconcile_broadcast` runs
    - because that reconciler unconditionally ADOPTS any ambiguous
    claimed-but-queued recipient with a matching outbound message as `sent`
    (by design, F6/AC-BRD-38); this test is about the mid-run outcome, not
    the eventual reconciled one."""
    from modules.omnichannel.adapters import whatsapp_cloud
    from modules.omnichannel.adapters.base import SendError

    def boom(self, creds, phone, to, **kw):
        raise SendError("Meta 503", transient=True)

    monkeypatch.setattr(whatsapp_cloud.WhatsAppCloudAdapter, "send", boom)

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
    job = JobService(db).create(type=SEND_JOB_TYPE, tenant_id=DEFAULT_TENANT_ID, payload={"broadcastId": broadcast.id})

    more = run_one_chunk(db, broadcast, job)
    assert more is False

    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast.id).first()
    assert recip.state == "queued"
    assert recip.error_code is None
    db.close()


# ── AC-BRD-29: preflight failure -> broadcast FAILED, zero recipients ───────
def test_preflight_channel_inactive_fails_broadcast_zero_recipients(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    channel.is_active = False
    db.commit()
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    sending_id = statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "SENDING")
    broadcast.status_id = sending_id
    db.commit()

    job = JobService(db).create(type=SEND_JOB_TYPE, tenant_id=DEFAULT_TENANT_ID, payload={"broadcastId": broadcast.id})
    run_broadcast_send(db, job)

    db.refresh(broadcast)
    db.refresh(job)
    assert statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "FAILED") == broadcast.status_id
    assert broadcast.error
    assert job.status == "failed"
    assert db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast.id).count() == 0
    db.close()


def test_preflight_template_not_approved_fails_broadcast(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    db = session_factory()
    tpl = db.query(WhatsappTemplate).filter(WhatsappTemplate.id == template_id).first()
    tpl.status = "PAUSED"
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    broadcast.status_id = statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "SENDING")
    db.commit()

    job = JobService(db).create(type=SEND_JOB_TYPE, tenant_id=DEFAULT_TENANT_ID, payload={"broadcastId": broadcast.id})
    run_broadcast_send(db, job)

    db.refresh(broadcast)
    assert statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "FAILED") == broadcast.status_id
    db.close()


def test_preflight_deleted_segment_fails_broadcast_instead_of_wedging(client, session_factory):
    """Review round 1, S5: a segment-audience broadcast whose segment was
    deleted between save and send used to raise `SegmentNotFound` straight
    out of `run_broadcast_send` (uncaught) - the broadcast stayed SENDING
    forever instead of failing cleanly like the channel/template preflight
    checks above."""
    from modules.omnichannel.models import ContactSegment

    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)

    db = session_factory()
    segment = ContactSegment(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, name="Doomed segment",
        filter_json={"kind": "group", "combinator": "and", "rules": []},
    )
    db.add(segment)
    db.commit()
    segment_id = segment.id
    db.close()

    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "segment", "segmentId": segment_id},
    )).json()

    db = session_factory()
    db.query(ContactSegment).filter(ContactSegment.id == segment_id).delete()
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    broadcast.status_id = statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "SENDING")
    db.commit()

    job = JobService(db).create(type=SEND_JOB_TYPE, tenant_id=DEFAULT_TENANT_ID, payload={"broadcastId": broadcast.id})
    run_broadcast_send(db, job)

    db.refresh(broadcast)
    db.refresh(job)
    assert statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "FAILED") == broadcast.status_id
    assert broadcast.error
    assert job.status == "failed"
    assert db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast.id).count() == 0
    db.close()


# ── AC-BRD-31: atomic per-recipient claim (never double-send) ──────────────
def test_claim_recipient_atomic_second_call_loses(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    from modules.omnichannel.repositories.broadcast_repository import BroadcastRepository

    db = session_factory()
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    snapshot_audience(db, broadcast)
    db.commit()
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast.id).first()

    repo = BroadcastRepository(db)
    assert repo.claim_recipient(DEFAULT_TENANT_ID, recip.id) is True
    assert repo.claim_recipient(DEFAULT_TENANT_ID, recip.id) is False
    db.close()


def test_job_retry_resumed_run_no_double_send(client, session_factory):
    """AC-BRD-31: a resumed/retried job (simulated: call `run_broadcast_send`
    again after it already completed) asserts exactly ONE
    `conversation_messages` row per recipient - nothing sends twice."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()
    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})
    assert res.status_code == 200
    job_id = res.json()["jobId"]

    db = session_factory()
    before = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact_id).count()
    assert before == 1

    # Simulate a resumed job re-entry: put the broadcast back in SENDING and
    # re-run the SAME job handler from scratch.
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    broadcast.status_id = statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "SENDING")
    db.commit()
    job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
    run_broadcast_send(db, job)

    after = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact_id).count()
    assert after == 1  # unchanged - never double-sent
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == created["id"]).first()
    assert recip.state == "sent"
    db.close()


def test_run_one_chunk_called_twice_on_same_chunk_no_double_send(client, session_factory):
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
    job = JobService(db).create(type=SEND_JOB_TYPE, tenant_id=DEFAULT_TENANT_ID, payload={"broadcastId": broadcast.id})

    more1 = run_one_chunk(db, broadcast, job)
    more2 = run_one_chunk(db, broadcast, job)
    assert more1 is False  # everything dispatched in the first pass
    assert more2 is False  # nothing left `queued` - second pass is a no-op

    count = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact_id).count()
    assert count == 1
    db.close()


# ── AC-BRD-30 (non-eager half) / S4: `worker.broadcast_chunk` ───────────────
def test_worker_broadcast_chunk_reschedules_then_finalizes(client, session_factory, monkeypatch):
    """`worker.broadcast_chunk` is the CHAINED Celery task that stands in for
    `run_one_chunk`'s inline eager-dev loop in prod (D-A4-7/AC-BRD-30) - the
    whole suite always takes the eager branch elsewhere, so this task had
    ZERO coverage until now. Stub `run_one_chunk` to return True once
    (forcing the RE-SCHEDULE branch, `broadcast_chunk.apply_async`) then
    fall through to the real implementation (forcing the `finalize_broadcast`
    branch) - Celery's OWN eager mode (set at `worker.py` import time, same
    as every other test in this suite) runs the re-scheduled call inline, so
    the whole chain completes synchronously with no real broker.

    The task opens its OWN `app.database.SessionLocal` (a worker process has
    its own DB engine, `send_runner`'s docstring) - the SAME reason
    `test_omnichannel_consumer_webhooks.py` avoids calling a Celery task
    directly. Monkeypatch `SessionLocal` to the test's session factory so
    the task sees this test's SQLite data."""
    import app.database as app_database
    from modules.omnichannel.services import broadcast_send_service
    from modules.omnichannel.worker import broadcast_chunk

    monkeypatch.setattr(app_database, "SessionLocal", session_factory)

    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    db = session_factory()
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    broadcast_id = broadcast.id
    broadcast.status_id = statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "SENDING")
    db.commit()
    snapshot_audience(db, broadcast)
    db.commit()
    job = JobService(db).create(type=SEND_JOB_TYPE, tenant_id=DEFAULT_TENANT_ID, payload={"broadcastId": broadcast_id})
    job_id = job.id
    db.close()

    calls = {"n": 0}
    real_run_one_chunk = broadcast_send_service.run_one_chunk

    def fake_run_one_chunk(db2, bcast, jobrow, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return True  # forces `broadcast_chunk`'s re-schedule branch
        return real_run_one_chunk(db2, bcast, jobrow, **kw)

    monkeypatch.setattr(broadcast_send_service, "run_one_chunk", fake_run_one_chunk)

    broadcast_chunk(job_id)

    assert calls["n"] == 2  # one re-scheduled (no-op) call + the real terminal chunk

    db = session_factory()
    broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
    job_row = JobService(db).repo.get_unscoped(job_id)
    assert statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "SENT") == broadcast.status_id
    assert job_row.status == JOB_DONE
    recip = db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast_id).first()
    assert recip.state == "sent"
    db.close()


def test_worker_broadcast_chunk_missing_broadcast_fails_job(session_factory, monkeypatch):
    """`broadcast_chunk`'s own not-found guard (mirrors `run_broadcast_send`'s)
    - a job whose broadcast row has since been hard-deleted must fail the
    job loudly, never crash the task."""
    import app.database as app_database
    from modules.omnichannel.worker import broadcast_chunk

    monkeypatch.setattr(app_database, "SessionLocal", session_factory)

    db = session_factory()
    job = JobService(db).create(
        type=SEND_JOB_TYPE, tenant_id=DEFAULT_TENANT_ID, payload={"broadcastId": "no-such-broadcast"}
    )
    job_id = job.id
    db.close()

    broadcast_chunk(job_id)

    db = session_factory()
    job_row = JobService(db).repo.get_unscoped(job_id)
    assert job_row.status == "failed"
    db.close()


# ── AC-BRD-35: rate pacing pure function ────────────────────────────────────
def test_compute_chunk_pacing_pure_function():
    assert compute_chunk_pacing(100, 10) == 10.0
    assert compute_chunk_pacing(100, 10, elapsed_seconds=4) == 6.0
    assert compute_chunk_pacing(100, 10, elapsed_seconds=50) == 0.0
    assert compute_chunk_pacing(50, 0) == 0.0
    assert compute_chunk_pacing(50, -5) == 0.0


def test_rate_for_channel_prefers_channel_override(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    assert rate_for_channel(channel) == float(
        __import__("app.config", fromlist=["settings"]).settings.omnichannel_broadcast_rate_per_second
    )
    channel.broadcast_rate_per_second = 3
    db.commit()
    db.refresh(channel)
    assert rate_for_channel(channel) == 3.0
    db.close()


# ── AC-BRD-32: actor resolution (deleted / foreign user never leaks) ────────
def test_actor_resolution_deleted_user_resolves_to_none(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    db = session_factory()
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    broadcast.created_by_user_id = "does-not-exist"
    db.commit()
    db.close()

    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})
    assert res.status_code == 200, res.text
    assert res.json()["counts"]["sent"] == 1

    db2 = session_factory()
    recip = db2.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == created["id"]).first()
    msg = db2.query(ConversationMessage).filter(ConversationMessage.id == recip.message_id).first()
    assert msg.sender_id is None
    db2.close()


# ── AC-BRD-40: cancel ────────────────────────────────────────────────────────
def test_cancel_scheduled_zero_sends(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={"scheduledAt": future})

    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/cancel", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "CANCELLED"
    assert body["counts"]["total"] == 0

    db = session_factory()
    assert db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact_id).count() == 0
    db.close()


def test_cancel_terminal_states_409(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()
    client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})  # -> SENT (eager)

    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/cancel", headers=h)
    assert res.status_code == 409
    assert res.json()["detail"]["reason"] == "broadcast_not_cancellable"


def test_cancel_mid_sending_remaining_skipped_already_sent_keeps_state(client, session_factory):
    """AC-BRD-40/D-A4-14: cooperative cancellation at chunk granularity - the
    chunk re-reads the broadcast's status FRESH before each batch. Drives
    `run_one_chunk` directly with `chunk_size=1` so a cancel can be committed
    on a SECOND session between two chunk calls (the plan-10 lesson: eager
    mode hides a non-cooperative abort unless the test forces a real
    inter-chunk boundary)."""
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    contact2 = _seed_contact(session_factory, ws, first="Second", last="Contact", phone="+60 12-000 2222")
    _add_identity(session_factory, contact2, channel_id)
    contact3 = _seed_contact(session_factory, ws, first="Third", last="Contact", phone="+60 12-000 3333")
    _add_identity(session_factory, contact3, channel_id)

    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id,
        audience={"kind": "contacts", "contactIds": [contact_id, contact2, contact3]},
    )).json()

    db = session_factory()
    broadcast = db.query(Broadcast).filter(Broadcast.id == created["id"]).first()
    broadcast.status_id = statuses.status_id_for(db, DEFAULT_TENANT_ID, "BROADCAST", "SENDING")
    db.commit()
    snapshot_audience(db, broadcast)
    db.commit()
    job = JobService(db).create(type=SEND_JOB_TYPE, tenant_id=DEFAULT_TENANT_ID, payload={"broadcastId": broadcast.id})

    more = run_one_chunk(db, broadcast, job, chunk_size=1)
    assert more is True  # 2 more `queued` recipients remain

    # Cancel from a SECOND session, mid-run.
    db2 = session_factory()
    from modules.omnichannel.repositories.broadcast_repository import BroadcastRepository

    sending_id = statuses.status_id_for(db2, DEFAULT_TENANT_ID, "BROADCAST", "SENDING")
    cancelled_id = statuses.status_id_for(db2, DEFAULT_TENANT_ID, "BROADCAST", "CANCELLED")
    ok = BroadcastRepository(db2).claim_status(
        broadcast.id, DEFAULT_TENANT_ID, from_status_ids=[sending_id], to_status_id=cancelled_id
    )
    assert ok is True
    db2.close()

    more2 = run_one_chunk(db, broadcast, job, chunk_size=1)
    assert more2 is False

    finalize_broadcast(db, broadcast, job)

    db3 = session_factory()
    recips = {
        r.contact_id: (r.state, r.skip_reason)
        for r in db3.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id == broadcast.id)
    }
    sent = [k for k, v in recips.items() if v[0] == "sent"]
    skipped = [k for k, v in recips.items() if v[0] == "skipped"]
    assert len(sent) == 1  # the one recipient the first chunk already sent
    assert len(skipped) == 2
    assert all(v[1] == "cancelled" for k, v in recips.items() if v[0] == "skipped")

    final_broadcast = db3.query(Broadcast).filter(Broadcast.id == broadcast.id).first()
    assert statuses.status_id_for(db3, DEFAULT_TENANT_ID, "BROADCAST", "CANCELLED") == final_broadcast.status_id
    job_row = db3.query(BackgroundJob).filter(BackgroundJob.id == job.id).first()
    assert job_row.status == "done"
    assert job_row.result_json["cancelled"] is True
    db3.close()
    db.close()


# ── AC-BRD-43/44 (this slice's share - emission at sent/failed/cancelled) ──
def test_entity_event_completed_emitted_on_sent(client, session_factory):
    events = []

    def _capture(session, ev):
        events.append(ev)

    register_event_subscriber(_capture)
    try:
        h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
        created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
            channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
        )).json()
        res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})
        assert res.status_code == 200
    finally:
        unregister_event_subscriber(_capture)

    completed = [
        e for e in events
        if e["entity_type"] == "omnichannel_broadcast" and e["action"] == "completed"
        and e["record_id"] == created["id"]
    ]
    assert len(completed) == 1
    assert completed[0]["extra"]["status"] == "SENT"
    assert completed[0]["extra"]["counts"]["sent"] == 1


def test_no_conversation_events_written_for_a_broadcast(client, session_factory):
    from modules.omnichannel.models import ConversationEvent

    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()
    before = session_factory().query(ConversationEvent).count()
    client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})
    after = session_factory().query(ConversationEvent).count()
    assert after == before


def test_broadcast_send_leaves_an_unreplied_contact_unreplied(client, session_factory):
    """B2 (review round 1): a broadcast is not a reply in a conversation -
    it must NOT advance `last_agent_message_at` (only `last_message_at`), or
    it would silently mark every waiting contact "replied" and empty the
    agent team's Unreplied inbox view (plan 27 AC-IVE-11/12) on every blast."""
    from modules.omnichannel.repositories.contact_repository import _unreplied_expr

    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)

    incoming_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db = session_factory()
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    contact.last_incoming_message_at = incoming_at
    contact.last_agent_message_at = None
    contact.last_message_at = incoming_at
    db.commit()
    assert db.query(Contact.id).filter(Contact.id == contact_id, _unreplied_expr()).first() is not None
    db.close()

    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()
    client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})

    db = session_factory()
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    # Still unreplied - the broadcast must not have touched last_agent_message_at.
    assert contact.last_agent_message_at is None
    assert db.query(Contact.id).filter(Contact.id == contact_id, _unreplied_expr()).first() is not None
    # last_message_at DOES advance - the broadcast message really is in the thread.
    assert contact.last_message_at > incoming_at
    db.close()


# ── AC-BRD-45: realtime publish, best-effort ────────────────────────────────
def test_realtime_publish_on_send_and_cancel(client, session_factory, monkeypatch):
    published = []
    monkeypatch.setattr(realtime, "publish", lambda ws_id, event: published.append((ws_id, event)))

    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()
    client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})

    types_seen = [e["type"] for _, e in published]
    assert "broadcast.updated" in types_seen
    final = [e for _, e in published if e["type"] == "broadcast.updated" and e.get("status") == "SENT"]
    assert final


# ── AC-BRD-50: job surfaces (progress) ──────────────────────────────────────
def test_job_visible_in_jobs_endpoint_with_progress(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()
    res = client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h, json={})
    job_id = res.json()["jobId"]

    job_res = client.get(f"/jobs/{job_id}", headers=h)
    assert job_res.status_code == 200, job_res.text
    body = job_res.json()
    assert body["status"] == "done"
    assert body["progressTotal"] == 1
    assert body["progressDone"] == 1


# ── AC-BRD-25/24: permission gates + tenant isolation for send/cancel ──────
def test_send_and_cancel_require_broadcasts_send_permission(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    h_no_send = _read_only_send_auth(client, session_factory)
    assert client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h_no_send, json={}).status_code == 403
    assert client.post(f"{_broadcasts_base(ws)}/{created['id']}/cancel", headers=h_no_send).status_code == 403

    h_none = _no_perm_auth(client, session_factory, email="brd-noperm@example.com")
    assert client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h_none, json={}).status_code == 403


def test_send_and_cancel_tenant_isolation_404(client, session_factory):
    h, ws, channel_id, contact_id, template_id = _fixture(client, session_factory)
    created = client.post(_broadcasts_base(ws), headers=h, json=_create_payload(
        channel_id, template_id, audience={"kind": "contacts", "contactIds": [contact_id]},
    )).json()

    h2 = _other_tenant_auth(client, session_factory, slug="other-brd-send")
    assert client.post(f"{_broadcasts_base(ws)}/{created['id']}/send", headers=h2, json={}).status_code == 404
    assert client.post(f"{_broadcasts_base(ws)}/{created['id']}/cancel", headers=h2).status_code == 404
