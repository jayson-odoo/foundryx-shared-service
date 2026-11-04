"""Plan 56 section C - contact erase for PDPA, backend (AC-56-40..51, 54).

RED tests written BEFORE the implementation. Black box: the HTTP routes, the
database rows, the files on (temporary local) storage, the consumer webhook
rows and the realtime publish. No private helper of the unwritten code is used.

Seams the implementation must honour:
* key route ``DELETE /api/v1/omnichannel/contacts/{identifier}`` answers 200
  ``{contactId, erasedAt, messages, files}``; staff route
  ``DELETE /api/omnichannel/contacts/{id}`` the same body;
* files are deleted AFTER commit through the storage layer (real local files
  under a temporary ``media_root``); a failing file delete never fails the erase;
* realtime: ``realtime.publish(workspace_id, {"type": "contact.erased",
  "contactId": id})`` (tests patch ``realtime.publish``);
* webhook event type ``contact.erased`` via ``enqueue_workspace_event``.

Every test seeds its own chain. Fake values only.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import (
    Broadcast,
    BroadcastRecipient,
    Contact,
    ContactChannelIdentity,
    ContactTag,
    ContactTagLink,
    ConversationEvent,
    ConversationMessage,
    MessageReaction,
    MigrationRef,
    WebhookDelivery,
    WorkflowContactFire,
)
from modules.omnichannel.services import idempotency, realtime
from modules.omnichannel.services import webhook_delivery as wd
from tests.test_omnichannel_api_gateway import (
    _auth,
    _default_workspace_id,
    _mint,
    _seed_channel,
    _seed_second_workspace,
)
from tests.test_omnichannel_outbound_event import _deliveries, _register
from tests.test_omnichannel_webhooks import _process, _wa_payload

FOREIGN_TENANT = "other-tenant-erase"
BASE = "/api/v1/omnichannel/contacts"
SECRET_NAME = "SECRETFILENAME"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    from app.services.storage import clear_adapter_cache, set_storage

    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    prev = settings.media_root
    settings.media_root = str(tmp_path)
    set_storage(None)
    clear_adapter_cache()

    class _Resp:
        status_code = 200

    monkeypatch.setattr(wd, "_post", lambda *a, **k: _Resp())
    yield
    settings.media_root = prev
    set_storage(None)
    clear_adapter_cache()
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


# ── seeding ──────────────────────────────────────────────────────────────────
def _digits(p):
    return "".join(c for c in p if c.isdigit())


def _file(rel, data=b"x"):
    path = Path(settings.media_root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel


def _contact(sf, ws, phone, *, tenant=DEFAULT_TENANT_ID, first="Erase"):
    db = sf()
    try:
        c = Contact(tenant_id=tenant, workspace_id=ws, first_name=first, phone=phone,
                    phone_digits=_digits(phone), priority="MEDIUM")
        db.add(c)
        db.commit()
        return c.id
    finally:
        db.close()


class Rig:
    def __init__(self, client, sf):
        self.client, self.sf = client, sf
        self.ws = _default_workspace_id(sf)
        self.channel = _seed_channel(sf, self.ws, phone_number_id="pn-erase")
        self.hdr = {"Authorization": f"Bearer {_mint(client, self.ws).json()['fullKey']}"}

    def footprint(self, phone, tag):
        """One contact with a row of every erasable kind. Returns its ids/files."""
        cid = _contact(self.sf, self.ws, phone)
        files = {
            "img": _file(f"omnichannel/{DEFAULT_TENANT_ID}/erase-{tag}/{SECRET_NAME}-img.png"),
            "voice_missing": f"omnichannel/{DEFAULT_TENANT_ID}/erase-{tag}/{SECRET_NAME}-gone.ogg",  # never written
            "legacy": _file(f"omnichannel/{DEFAULT_TENANT_ID}/erase-{tag}/{SECRET_NAME}-legacy.png"),
        }
        db = self.sf()
        try:
            db.add(ContactChannelIdentity(tenant_id=DEFAULT_TENANT_ID, contact_id=cid,
                                          channel_id=self.channel, external_user_id=_digits(phone)))

            def msg(**kw):
                kw.setdefault("message_type", "TEXT")
                row = ConversationMessage(tenant_id=DEFAULT_TENANT_ID, contact_id=cid,
                                          channel_id=self.channel, **kw)
                db.add(row)
                db.flush()
                return row

            msg(sender_type="CONTACT", body="hello", external_message_id=f"wamid.{tag}.in")
            out = msg(sender_type="AGENT", body="hi back", external_message_id=f"wamid.{tag}.out",
                      delivery_status="SENT")
            row_note = ConversationMessage(tenant_id=DEFAULT_TENANT_ID, contact_id=cid, channel_id=None,
                                           sender_type="SYSTEM", message_type="NOTE", body="internal note")
            db.add(row_note)
            msg(sender_type="CONTACT", message_type="IMAGE", media_key=files["img"])
            msg(sender_type="AGENT", message_type="VOICE", media_key=files["voice_missing"])
            msg(sender_type="CONTACT", message_type="IMAGE",
                media_url=f"{settings.public_base_url}/omnichannel/media/{files['legacy']}")
            db.add(MessageReaction(tenant_id=DEFAULT_TENANT_ID, workspace_id=self.ws,
                                   target_message_id=out.id, reactor_type="CONTACT",
                                   reactor=_digits(phone), emoji="\U0001F44D"))
            db.add(ConversationEvent(tenant_id=DEFAULT_TENANT_ID, workspace_id=self.ws, contact_id=cid,
                                     event_type="opened", created_at=datetime.now(timezone.utc)))
            t = ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=self.ws, name=f"tag-{tag}")
            db.add(t)
            db.flush()
            db.add(ContactTagLink(tenant_id=DEFAULT_TENANT_ID, contact_id=cid, tag_id=t.id))
            db.add(WorkflowContactFire(tenant_id=DEFAULT_TENANT_ID, workflow_id=f"wf-{tag}", contact_id=cid))
            b = Broadcast(tenant_id=DEFAULT_TENANT_ID, workspace_id=self.ws, name=f"b-{tag}",
                          channel_id=self.channel, audience_kind="contacts",
                          audience_contact_ids_json=[cid, f"keep-{tag}"],
                          template_id="tpl", template_name="tpl", status_id="st")
            db.add(b)
            db.flush()
            db.add(BroadcastRecipient(tenant_id=DEFAULT_TENANT_ID, broadcast_id=b.id, contact_id=cid))
            for etype, ext in (("contact", f"rio-{tag}"), ("message", f"rio-m-{tag}"),
                               ("identity", f"rio-i-{tag}")):
                db.add(MigrationRef(tenant_id=DEFAULT_TENANT_ID, workspace_id=self.ws, source="respondio",
                                    entity_type=etype, external_id=ext, local_id=cid))
            db.commit()
            return {"cid": cid, "broadcast": b.id, "files": files, "tag": tag, "phone": phone}
        finally:
            db.close()

    def counts(self, cid):
        """Rows that reference the contact, per table."""
        db = self.sf()
        try:
            msg_ids = [m.id for m in db.query(ConversationMessage.id).filter(
                ConversationMessage.contact_id == cid)]
            return {
                "contact": db.query(Contact).filter(Contact.id == cid).count(),
                "messages": len(msg_ids),
                "reactions": db.query(MessageReaction).filter(
                    MessageReaction.target_message_id.in_(msg_ids or ["-"])).count(),
                "events": db.query(ConversationEvent).filter(ConversationEvent.contact_id == cid).count(),
                "identities": db.query(ContactChannelIdentity).filter(
                    ContactChannelIdentity.contact_id == cid).count(),
                "tag_links": db.query(ContactTagLink).filter(ContactTagLink.contact_id == cid).count(),
                "fires": db.query(WorkflowContactFire).filter(WorkflowContactFire.contact_id == cid).count(),
                "recipients": db.query(BroadcastRecipient).filter(BroadcastRecipient.contact_id == cid).count(),
                "refs": db.query(MigrationRef).filter(MigrationRef.local_id == cid).count(),
            }
        finally:
            db.close()

    def audience(self, broadcast_id):
        db = self.sf()
        try:
            return list(db.query(Broadcast).filter(Broadcast.id == broadcast_id).one().audience_contact_ids_json)
        finally:
            db.close()

    def erase(self, identifier):
        return self.client.delete(f"{BASE}/{identifier}", headers=self.hdr)


@pytest.fixture
def rig(client, session_factory):
    return Rig(client, session_factory)


def _on_disk(files):
    return {k: (Path(settings.media_root) / v).exists() for k, v in files.items()}


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-40 - the key route
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("form", ["id", "phone", "bare"])
def test_ac_56_40_all_three_identifier_forms_erase_and_answer_the_body(rig, form):
    fp = rig.footprint("+60100000301", "f1")
    ident = {"id": f"id:{fp['cid']}", "phone": f"phone:{fp['phone']}", "bare": fp["cid"]}[form]
    res = rig.erase(ident)
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == {"contactId", "erasedAt", "messages", "files"}
    assert body["contactId"] == fp["cid"]
    assert body["messages"] == 6
    assert body["files"] == 3
    assert body["erasedAt"].endswith("Z")
    assert datetime.fromisoformat(body["erasedAt"].replace("Z", "+00:00")).tzinfo is not None
    assert rig.counts(fp["cid"])["contact"] == 0


def test_ac_56_40_second_call_unknown_and_malformed_answer_404_contact_not_found(rig):
    fp = rig.footprint("+60100000302", "f2")
    assert rig.erase(fp["cid"]).status_code == 200  # control: the first call erases
    for ident in (fp["cid"], f"id:{fp['cid']}", f"phone:{fp['phone']}", "does-not-exist", "phone:+60100009999"):
        res = rig.erase(ident)
        assert res.status_code == 404, (ident, res.text)
        assert res.json()["error"]["code"] == "contact_not_found", (ident, res.text)


def test_ac_56_40_contact_of_another_workspace_same_tenant_is_404_and_untouched(rig, session_factory):
    other_ws = _seed_second_workspace(session_factory)
    foreign = _contact(session_factory, other_ws, "+60100000303")
    own = rig.footprint("+60100000304", "f3")
    assert rig.erase(own["cid"]).status_code == 200  # control: the route works for our workspace
    for ident in (foreign, f"id:{foreign}", "phone:+60100000303"):
        res = rig.erase(ident)
        assert res.status_code == 404 and res.json()["error"]["code"] == "contact_not_found", ident
    assert rig.counts(foreign)["contact"] == 1


def test_ac_56_40_contact_of_another_tenant_is_404_and_untouched(rig, session_factory):
    foreign = _contact(session_factory, rig.ws, "+60100000305", tenant=FOREIGN_TENANT)
    own = rig.footprint("+60100000306", "f4")
    assert rig.erase(own["cid"]).status_code == 200  # control
    for ident in (foreign, f"id:{foreign}", "phone:+60100000305"):
        res = rig.erase(ident)
        assert res.status_code == 404 and res.json()["error"]["code"] == "contact_not_found", ident
    assert rig.counts(foreign)["contact"] == 1


def test_ac_56_40_requires_an_api_key(client, rig):
    fp = rig.footprint("+60100000307", "f5")
    assert client.delete(f"{BASE}/{fp['cid']}").status_code == 401
    assert client.delete(f"{BASE}/{fp['cid']}", headers={"Authorization": "Bearer fxw_live_nope"}).status_code == 401
    assert rig.counts(fp["cid"])["contact"] == 1


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-41 - every listed table, other contacts untouched, atomic
# ═════════════════════════════════════════════════════════════════════════════
ZERO = {"contact": 0, "messages": 0, "reactions": 0, "events": 0, "identities": 0,
        "tag_links": 0, "fires": 0, "recipients": 0}


def test_ac_56_41_every_listed_table_is_empty_for_the_contact_and_other_contacts_are_untouched(rig):
    gone = rig.footprint("+60100000311", "g1")
    keep = rig.footprint("+60100000312", "k1")
    before_keep = rig.counts(keep["cid"])
    assert before_keep["messages"] == 6 and before_keep["reactions"] == 1  # control: footprint is real
    assert rig.erase(gone["cid"]).status_code == 200
    after = rig.counts(gone["cid"])
    assert {k: after[k] for k in ZERO} == ZERO
    assert rig.counts(keep["cid"]) == before_keep


def test_ac_56_41_broadcast_audience_drops_only_the_erased_id(rig):
    gone = rig.footprint("+60100000313", "g2")
    keep = rig.footprint("+60100000314", "k2")
    assert gone["cid"] in rig.audience(gone["broadcast"])  # control
    assert rig.erase(gone["cid"]).status_code == 200
    assert rig.audience(gone["broadcast"]) == ["keep-g2"]
    assert rig.audience(keep["broadcast"]) == [keep["cid"], "keep-k2"]


def test_ac_56_41_parked_wait_is_deleted_and_its_run_ends_cancelled(session_factory, client):
    from app.models.workflow import RUN_CANCELLED, RUN_WAITING
    from modules.omnichannel.models import WorkflowWait
    from tests.test_omnichannel_workflow_waits import _park_via_inbound, _run_of

    wf_id, contact_id, _channel = _park_via_inbound(session_factory, phone="60111222344")
    db = session_factory()
    try:
        assert _run_of(db, wf_id).status == RUN_WAITING  # control: it really is parked
        assert db.query(WorkflowWait).filter(WorkflowWait.contact_id == contact_id).count() == 1
    finally:
        db.close()
    ws = _default_workspace_id(session_factory)
    hdr = {"Authorization": f"Bearer {_mint(client, ws).json()['fullKey']}"}
    res = client.delete(f"{BASE}/{contact_id}", headers=hdr)
    assert res.status_code == 200, res.text
    db = session_factory()
    try:
        assert db.query(WorkflowWait).filter(WorkflowWait.contact_id == contact_id).count() == 0
        assert _run_of(db, wf_id).status == RUN_CANCELLED
        assert db.query(Contact).filter(Contact.id == contact_id).count() == 0
    finally:
        db.close()


def _block_delete(sf, table):
    db = sf()
    try:
        db.execute(text(f"CREATE TRIGGER omni.blk_{table} BEFORE DELETE ON {table} "
                        "BEGIN SELECT RAISE(ABORT, 'forced failure'); END;"))
        db.commit()
    finally:
        db.close()


def _unblock_delete(sf, table):
    db = sf()
    try:
        db.execute(text(f"DROP TRIGGER omni.blk_{table}"))
        db.commit()
    finally:
        db.close()


def _erase_tolerating_a_crash(rig, ident):
    try:
        return rig.erase(ident).status_code
    except Exception:  # noqa: BLE001 - an unhandled error surfaces through the test client
        return 500


@pytest.mark.parametrize("table", ["contacts", "conversation_events", "broadcast_recipients", "contact_tag_links"])
def test_ac_56_41_a_failure_anywhere_rolls_everything_back_and_deletes_no_file(rig, table):
    fp = rig.footprint("+60100000321", "a1")
    before = rig.counts(fp["cid"])
    audience = rig.audience(fp["broadcast"])
    _block_delete(rig.sf, table)
    assert _erase_tolerating_a_crash(rig, fp["cid"]) >= 500
    assert rig.counts(fp["cid"]) == before, "nothing may be deleted when the erase fails"
    assert rig.audience(fp["broadcast"]) == audience
    assert _on_disk(fp["files"]) == {"img": True, "voice_missing": False, "legacy": True}
    # control: the very same seed IS erased once nothing raises (the proof is not vacuous)
    _unblock_delete(rig.sf, table)
    res = rig.erase(fp["cid"])
    assert res.status_code == 200, res.text
    assert rig.counts(fp["cid"])["contact"] == 0 and rig.counts(fp["cid"])["messages"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-42 / 43 - files
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_42_media_key_legacy_url_and_missing_files_are_all_handled(rig):
    fp = rig.footprint("+60100000331", "d1")
    keep = rig.footprint("+60100000332", "d2")
    assert _on_disk(fp["files"]) == {"img": True, "voice_missing": False, "legacy": True}  # control
    res = rig.erase(fp["cid"])
    assert res.status_code == 200, res.text
    assert res.json()["files"] == 3  # the file that was already gone counts as deleted
    assert _on_disk(fp["files"]) == {"img": False, "voice_missing": False, "legacy": False}
    assert _on_disk(keep["files"]) == {"img": True, "voice_missing": False, "legacy": True}


def test_ac_56_42_a_foreign_legacy_media_url_is_not_treated_as_a_stored_file(rig):
    fp = rig.footprint("+60100000333", "d3")
    db = rig.sf()
    try:
        db.add(ConversationMessage(tenant_id=DEFAULT_TENANT_ID, contact_id=fp["cid"], channel_id=rig.channel,
                                   sender_type="CONTACT", message_type="IMAGE",
                                   media_url="https://cdn.example.com/pic.png"))
        db.commit()
    finally:
        db.close()
    res = rig.erase(fp["cid"])
    assert res.status_code == 200, res.text
    assert res.json()["files"] == 3  # the external CDN link is not a stored file


def test_ac_56_42_a_failing_file_delete_never_undoes_the_erase_and_logs_no_names(rig, monkeypatch, caplog):
    from app.services import storage as storage_module

    fp = rig.footprint("+60100000334", "d4")

    def boom(self, key):
        raise OSError(f"disk exploded on {key}")

    monkeypatch.setattr(storage_module.LocalDiskStorage, "delete", boom)
    with caplog.at_level(logging.DEBUG):
        res = rig.erase(fp["cid"])
    assert res.status_code == 200, res.text
    counts = rig.counts(fp["cid"])
    assert counts["contact"] == 0 and counts["messages"] == 0
    log = caplog.text
    assert SECRET_NAME not in log
    assert fp["phone"] not in log and _digits(fp["phone"]) not in log
    assert "Erase" not in log.replace("erase", "")  # the contact's first name


def test_ac_56_43_voice_transcode_deletes_the_original_after_the_converted_file_is_stored(
    client, session_factory, monkeypatch
):
    from modules.omnichannel.services.send_runner import run_send
    from tests.test_omnichannel_outbound_event import _rig

    r = _rig(client, session_factory, "+60100000341", events=())
    original = _file("voice/original-upload.webm", b"webm-bytes")
    db = session_factory()
    try:
        row = ConversationMessage(tenant_id=DEFAULT_TENANT_ID, contact_id=r["cid"], channel_id=r["channel_id"],
                                  sender_type="AGENT", message_type="VOICE", media_key=original,
                                  media_mime="audio/webm", delivery_status="QUEUED")
        db.add(row)
        db.commit()
        mid = row.id
    finally:
        db.close()
    monkeypatch.setattr("modules.omnichannel.services.send_runner.transcode_voice",
                        lambda content: b"OggS" + b"\x00" * 64)
    db = session_factory()
    try:
        assert run_send(db, mid) == "SENT"
        new_key = db.query(ConversationMessage).filter(ConversationMessage.id == mid).one().media_key
    finally:
        db.close()
    assert new_key != original
    assert (Path(settings.media_root) / new_key).exists(), "the converted file stays"
    assert not (Path(settings.media_root) / original).exists(), "the unreachable original must be deleted"


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-44 - webhook deliveries reduced to ids
# ═════════════════════════════════════════════════════════════════════════════
def _delivery(sf, ws, endpoint_id, event_type, data):
    db = sf()
    try:
        row = WebhookDelivery(
            tenant_id=DEFAULT_TENANT_ID, endpoint_id=endpoint_id, event_id=f"evt-{event_type}-{id(data)}",
            event_type=event_type,
            payload_json={"id": "evt-1", "type": event_type, "workspaceId": ws, "channelId": "ch-1",
                          "occurredAt": "2026-11-04T00:00:00Z", "data": data},
            status="SUCCESS", attempt_count=2, response_status=200,
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _delivery_row(sf, delivery_id):
    db = sf()
    try:
        r = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_id).one()
        return {"status": r.status, "attempt_count": r.attempt_count, "event_type": r.event_type,
                "response_status": r.response_status, "payload": r.payload_json, "endpoint_id": r.endpoint_id}
    finally:
        db.close()


def test_ac_56_44_deliveries_naming_the_contact_keep_status_and_lose_everything_but_ids(rig):
    fp = rig.footprint("+60100000351", "w1")
    keep = rig.footprint("+60100000352", "w2")
    cid = fp["cid"]
    named = {
        "message.status": {"messageId": "m-1", "contactId": cid, "deliveryStatus": "SENT", "errorMessage": "SECRETTEXT"},
        "message.inbound": {"message": {"id": "m-2", "contactId": cid, "body": "SECRETTEXT"},
                            "contact": {"id": cid, "firstName": "SECRETTEXT", "phone": fp["phone"]}},
        "contact.updated": {"contact": {"id": cid, "firstName": "SECRETTEXT", "phone": fp["phone"]}},
    }
    ids = {t: _delivery(rig.sf, rig.ws, "ep-1", t, d) for t, d in named.items()}
    other = _delivery(rig.sf, rig.ws, "ep-1", "message.status",
                      {"messageId": "m-9", "contactId": keep["cid"], "errorMessage": "KEEPTEXT"})
    other_before = _delivery_row(rig.sf, other)
    assert rig.erase(cid).status_code == 200
    for etype, did in ids.items():
        row = _delivery_row(rig.sf, did)
        assert row["status"] == "SUCCESS" and row["attempt_count"] == 2 and row["response_status"] == 200
        assert row["event_type"] == etype
        payload = row["payload"]
        assert set(payload) <= {"id", "type", "workspaceId", "channelId", "occurredAt", "data"}, payload
        assert payload["type"] == etype and payload["workspaceId"] == rig.ws
        assert set(payload["data"]) <= {"contactId", "messageId"}, payload
        assert payload["data"]["contactId"] == cid
        assert "SECRETTEXT" not in str(payload) and fp["phone"] not in str(payload)
    assert _delivery_row(rig.sf, other) == other_before
    assert rig.counts(keep["cid"])["messages"] == 6


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-45 - respond.io tombstone
# ═════════════════════════════════════════════════════════════════════════════
def _writer(sf, ws):
    from modules.omnichannel.services import statuses
    from modules.omnichannel.services.migration_writer import MigrationWriter

    db = sf()
    open_id = statuses.status_id_for(db, DEFAULT_TENANT_ID, "THREAD", "OPEN")
    writer = MigrationWriter(db, tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, thread_open_status_id=open_id,
                             initial_lifecycle_status_id=None, lifecycle_map={}, source_field_defs={})
    return db, writer


def _src(ext_id, phone):
    from modules.omnichannel.respondio.shapes import Contact as SourceContact

    return SourceContact(id=ext_id, firstName="Rio", lastName="Person", phone=phone)


def _refs(sf, ws):
    db = sf()
    try:
        return sorted((r.entity_type, r.external_id, r.local_id) for r in db.query(MigrationRef).filter(
            MigrationRef.tenant_id == DEFAULT_TENANT_ID, MigrationRef.workspace_id == ws))
    finally:
        db.close()


def test_ac_56_45_contact_ref_is_rekeyed_to_a_tombstone_and_other_refs_are_deleted(rig):
    fp = rig.footprint("+60100000361", "m1")
    assert rig.erase(fp["cid"]).status_code == 200
    assert _refs(rig.sf, rig.ws) == [("contact_erased", "rio-m1", "erased")]


def test_ac_56_45_a_later_import_of_the_erased_respondio_contact_writes_nothing(rig):
    from modules.omnichannel.models import ContactChannelIdentity as Ident

    phone = "+60100000362"
    db, writer = _writer(rig.sf, rig.ws)
    created = writer.write_contact(_src(88001, phone))
    db.commit()
    cid = created.contact_id
    db.close()
    assert rig.counts(cid)["contact"] == 1 and _refs(rig.sf, rig.ws)[0][:2] == ("contact", "88001")  # control
    assert rig.erase(cid).status_code == 200

    db, writer = _writer(rig.sf, rig.ws)
    try:
        writer.write_contact(_src(88001, phone))  # same respond.io id, same phone
        db.commit()
    finally:
        db.close()
    db = rig.sf()
    try:
        assert db.query(Contact).filter(Contact.workspace_id == rig.ws, Contact.phone_digits == _digits(phone)).count() == 0
        assert db.query(Ident).filter(Ident.contact_id == cid).count() == 0
    finally:
        db.close()
    assert _refs(rig.sf, rig.ws) == [("contact_erased", "88001", "erased")]


def test_ac_56_45_a_different_respondio_contact_still_imports(rig):
    phone = "+60100000363"
    db, writer = _writer(rig.sf, rig.ws)
    cid = writer.write_contact(_src(88002, phone)).contact_id
    db.commit()
    db.close()
    assert rig.erase(cid).status_code == 200
    db, writer = _writer(rig.sf, rig.ws)
    try:
        other = writer.write_contact(_src(88003, "+60100000364"))
        db.commit()
        assert db.query(Contact).filter(Contact.id == other.contact_id).count() == 1
    finally:
        db.close()
    assert ("contact", "88003") in [(t, e) for t, e, _l in _refs(rig.sf, rig.ws)]


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-46 - re-contact creates a NEW contact
# ═════════════════════════════════════════════════════════════════════════════
def _contacts_by_phone(sf, ws, phone):
    db = sf()
    try:
        return [c.id for c in db.query(Contact).filter(Contact.workspace_id == ws,
                                                      Contact.phone_digits == _digits(phone))]
    finally:
        db.close()


def test_ac_56_46_inbound_from_the_same_number_creates_a_new_contact(rig, session_factory):
    fp = rig.footprint("+60100000371", "n1")
    assert rig.erase(fp["cid"]).status_code == 200
    assert _contacts_by_phone(session_factory, rig.ws, fp["phone"]) == []  # control: erased
    _process(session_factory, rig.channel,
             _wa_payload(wamid="wamid.erase-46", from_=_digits(fp["phone"]), text="I am back"))
    ids = _contacts_by_phone(session_factory, rig.ws, fp["phone"])
    assert len(ids) == 1 and ids[0] != fp["cid"]
    assert rig.counts(ids[0])["messages"] == 1  # only the new message; nothing carried over


def test_ac_56_46_post_messages_to_the_same_number_creates_a_new_contact(rig, session_factory):
    fp = rig.footprint("+60100000372", "n2")
    assert rig.erase(fp["cid"]).status_code == 200
    res = rig.client.post("/api/v1/omnichannel/messages", headers=rig.hdr,
                          json={"to": fp["phone"], "type": "text", "text": {"body": "hello again"}})
    ids = _contacts_by_phone(session_factory, rig.ws, fp["phone"])
    assert len(ids) == 1 and ids[0] != fp["cid"], res.text


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-47 - contact.erased webhook
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_47_event_type_is_accepted_on_create_and_update(rig):
    created = rig.client.post("/api/v1/omnichannel/webhooks", headers=rig.hdr, json={
        "name": "w", "url": "https://hooks.example.com/w", "events": ["contact.erased"]})
    assert created.status_code == 201, created.text
    assert created.json()["endpoint"]["events"] == ["contact.erased"]
    other = rig.client.post("/api/v1/omnichannel/webhooks", headers=rig.hdr, json={
        "name": "w2", "url": "https://hooks.example.com/w2", "events": ["message.status"]})
    assert other.status_code == 201, other.text
    upd = rig.client.patch(f"/api/v1/omnichannel/webhooks/{other.json()['endpoint']['id']}", headers=rig.hdr,
                           json={"events": ["message.status", "contact.erased"]})
    assert upd.status_code == 200, upd.text
    assert "contact.erased" in upd.json()["events"]


def test_ac_56_47_one_delivery_per_subscribed_endpoint_with_exactly_two_data_keys(rig):
    fp = rig.footprint("+60100000381", "e1")
    a = _register(rig.client, rig.hdr, ["contact.erased"], url="https://hooks.example.com/a", name="a")
    b = _register(rig.client, rig.hdr, ["contact.erased"], url="https://hooks.example.com/b", name="b")
    c = _register(rig.client, rig.hdr, ["message.status"], url="https://hooks.example.com/c", name="c")
    assert a.status_code == b.status_code == c.status_code == 201, (a.text, b.text, c.text)
    res = rig.erase(fp["cid"])
    assert res.status_code == 200
    rows = _deliveries(rig.sf, "contact.erased")
    assert sorted(r["endpoint_id"] for r in rows) == sorted(
        [a.json()["endpoint"]["id"], b.json()["endpoint"]["id"]])
    for r in rows:
        data = r["payload"]["data"]
        assert data == {"contactId": fp["cid"], "erasedAt": res.json()["erasedAt"]}
        assert r["payload"]["type"] == "contact.erased"
        assert r["payload"]["channelId"] is None
        assert r["payload"]["workspaceId"] == rig.ws
    assert fp["phone"] not in str(rows)


def test_ac_56_47_a_disabled_endpoint_gets_nothing(rig):
    fp = rig.footprint("+60100000382", "e2")
    ep_res = _register(rig.client, rig.hdr, ["contact.erased"], url="https://hooks.example.com/d", name="d")
    live_res = _register(rig.client, rig.hdr, ["contact.erased"], url="https://hooks.example.com/e", name="e")
    assert ep_res.status_code == live_res.status_code == 201, (ep_res.text, live_res.text)
    ep, live = ep_res.json(), live_res.json()
    dis = rig.client.post(f"/api/v1/omnichannel/webhooks/{ep['endpoint']['id']}/disable", headers=rig.hdr)
    assert dis.status_code == 200, dis.text
    assert rig.erase(fp["cid"]).status_code == 200
    assert [r["endpoint_id"] for r in _deliveries(rig.sf, "contact.erased")] == [live["endpoint"]["id"]]


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-48 - realtime
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_48_staff_inboxes_get_a_realtime_contact_erased_event(rig, monkeypatch):
    fp = rig.footprint("+60100000391", "r1")
    published = []
    monkeypatch.setattr(realtime, "publish", lambda ws_id, event: published.append((ws_id, event)))
    assert rig.erase(fp["cid"]).status_code == 200
    assert (rig.ws, {"type": "contact.erased", "contactId": fp["cid"]}) in published, published


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-49 - a send task for an erased message
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_49_send_task_for_an_erased_message_calls_nothing_and_raises_nothing(rig, monkeypatch):
    import app.database as appdb
    from modules.omnichannel.worker import omnichannel_send_message

    fp = rig.footprint("+60100000401", "s1")
    db = rig.sf()
    try:
        row = ConversationMessage(tenant_id=DEFAULT_TENANT_ID, contact_id=fp["cid"], channel_id=rig.channel,
                                  sender_type="AGENT", message_type="TEXT", body="queued", delivery_status="QUEUED")
        db.add(row)
        db.commit()
        mid = row.id
    finally:
        db.close()
    calls = []

    class _A:
        def send(self, *a, **k):
            calls.append("send")
            return {"external_message_id": "wamid.never"}

        def upload_media(self, *a, **k):
            calls.append("upload")
            return "m"

    monkeypatch.setattr("modules.omnichannel.services.send_runner.get_adapter", lambda *a, **k: _A())
    monkeypatch.setattr(appdb, "SessionLocal", rig.sf)
    assert rig.erase(fp["cid"]).status_code == 200  # the queued message is erased with the contact
    result = omnichannel_send_message.apply(args=[mid], throw=True)
    assert result.successful()
    assert calls == []
