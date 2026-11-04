"""Lane SS-CHANNEL-SKIP (plan sprint-5/51) - a migration can run before the
target workspace has a channel connected, and the channel is attached later.

AC-SKIP-02: every channel skipped -> the dry run and the real run are both
accepted and contacts + history import with no channel identity.
AC-SKIP-04: connect the channel afterwards and run again with it mapped ->
every previously migrated contact gets its identity, no message duplicates.
AC-SKIP-05: sending to such a contact while no channel is connected is
refused with a clear message (never a 500, never a silent drop).
AC-SKIP-01 (copy): the preflight warning says the channel can be connected
later instead of reading like data loss.
"""
import httpx
import pytest

from app.models import DEFAULT_TENANT_ID

from modules.omnichannel.models import (
    Channel,
    Contact,
    ContactChannelIdentity,
    ConversationMessage,
    MigrationRef,
)
from modules.omnichannel.schemas import MigrationSourceChannel, SendMessageRequest
from modules.omnichannel.services.message_service import MessageService, SendRejected
from modules.omnichannel.services.migration_service import (
    MigrationPreflightService,
    run_migration_job,
)

from tests.test_omnichannel_respondio_migration_jobs import (
    _auth,
    _create_connection,
    _default_workspace,
    _default_workspace_id,
    _make_connection,
    _patch_client_factory,
    _stub_client,
)
from tests.test_omnichannel_respondio_migration_s3 import (
    _make_channel,
    _make_full_job,
    _pages_handler_full,
)

SOURCE_CHANNEL_ID = "701"


def _skip_all_body(connection_id: str, workspace_id: str, *, mode: str) -> dict:
    return {
        "connectionId": connection_id,
        "workspaceId": workspace_id,
        "mode": mode,
        "source": "api",
        "channelMap": [{"sourceChannelId": SOURCE_CHANNEL_ID, "targetChannelId": None}],
        "userMap": [],
        "teamMap": [],
        "lifecycleMap": [],
        "contactsOnly": False,
    }


def _skip_handler(request: httpx.Request) -> httpx.Response:
    """The source space has one readable WhatsApp channel and no contacts -
    enough for the create-time checks (`_require_channels_readable`)."""
    if request.url.path.endswith("/space/channel"):
        return httpx.Response(
            200,
            json={
                "items": [{"id": int(SOURCE_CHANNEL_ID), "name": "WA Main", "source": "whatsapp"}],
                "pagination": {"next": None},
            },
        )
    return httpx.Response(200, json={"items": [], "pagination": {"next": None}})


def test_ac_skip_02_dry_run_and_run_accepted_with_every_channel_skipped(client, monkeypatch):
    h = _auth(client)
    connection_id = _create_connection(client, h)
    ws_id = _default_workspace_id(client, h)
    _patch_client_factory(monkeypatch, _skip_handler)

    dry = client.post(
        "/omnichannel/migration/jobs", headers=h, json=_skip_all_body(connection_id, ws_id, mode="dry_run")
    )
    assert dry.status_code == 201, dry.text

    run = client.post(
        "/omnichannel/migration/jobs", headers=h, json=_skip_all_body(connection_id, ws_id, mode="run")
    )
    assert run.status_code == 201, run.text
    assert run.json()["status"] == "done"


def _message_channels(db, contact_id):
    """`{source messageId: channel_id}` for one contact's migrated history."""
    db.expire_all()
    rows = (
        db.query(MigrationRef.external_id, ConversationMessage.channel_id)
        .join(ConversationMessage, ConversationMessage.id == MigrationRef.local_id)
        .filter(MigrationRef.entity_type == "message", ConversationMessage.contact_id == contact_id)
        .all()
    )
    return {int(ext): channel_id for ext, channel_id in rows}


def test_ac_skip_04_skip_now_then_connect_later_links_every_migrated_contact(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    contact_row = {"id": 970001, "firstName": "Later", "lastName": "Link", "phone": "+15557770000"}
    channels_by_contact = {
        "id:970001": [{"id": int(SOURCE_CHANNEL_ID), "name": "WA", "source": "whatsapp",
                       "meta": {"phone": "+15557770000"}}],
    }
    messages_by_contact = {
        "id:970001": {
            None: (
                [
                    {"messageId": 1, "traffic": "incoming", "channelId": int(SOURCE_CHANNEL_ID),
                     "message": {"type": "text", "text": "hello"}},
                    {"messageId": 2, "traffic": "outgoing", "channelId": int(SOURCE_CHANNEL_ID),
                     "message": {"type": "text", "text": "hi back"},
                     "status": [{"value": "sent", "timestamp": 1700000000}]},
                    # Source channel still unmapped on every run -> stays channel-less.
                    {"messageId": 3, "traffic": "incoming", "channelId": 702,
                     "message": {"type": "text", "text": "other channel"}},
                    # respond.io gave no channel at all -> nothing to match on.
                    {"messageId": 4, "traffic": "incoming", "channelId": None,
                     "message": {"type": "text", "text": "unknown channel"}},
                ],
                None,
            )
        }
    }
    handler = _pages_handler_full(
        {None: ([contact_row], None)}, channels_by_contact=channels_by_contact,
        messages_by_contact=messages_by_contact,
    )
    _stub_client(monkeypatch, handler)

    # Run 1: no channel connected yet -> the channel is skipped.
    job1 = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run",
        channel_map=[{"sourceChannelId": SOURCE_CHANNEL_ID, "targetChannelId": None}],
    )
    run_migration_job(db, job1)
    db.refresh(job1)
    assert job1.status == "done", job1.error

    contact = (
        db.query(Contact)
        .filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15557770000")
        .first()
    )
    assert contact is not None, "contacts import while the channel is skipped"
    assert db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact.id).count() == 4
    assert _message_channels(db, contact.id) == {1: None, 2: None, 3: None, 4: None}
    assert db.query(ContactChannelIdentity).filter(ContactChannelIdentity.contact_id == contact.id).count() == 0

    # Later: the channel is connected and the migration runs again, mapped.
    wa_channel = _make_channel(db, DEFAULT_TENANT_ID, ws.id, channel_type="WHATSAPP")
    db.commit()
    mapped = [
        {"sourceChannelId": SOURCE_CHANNEL_ID, "targetChannelId": wa_channel.id},
        {"sourceChannelId": "702", "targetChannelId": None},
    ]

    # The dry run previews the re-link but writes nothing.
    dry = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="dry_run", channel_map=mapped,
    )
    run_migration_job(db, dry)
    db.refresh(dry)
    assert dry.status == "done", dry.error
    assert dry.result_json["report"]["entities"]["messages"]["wouldUpdate"] == 2
    assert _message_channels(db, contact.id) == {1: None, 2: None, 3: None, 4: None}

    job2 = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run", channel_map=mapped,
    )
    run_migration_job(db, job2)
    db.refresh(job2)
    assert job2.status == "done", job2.error
    assert job2.result_json["report"]["entities"]["messages"]["wouldUpdate"] == 2
    # Earlier messages from the now-connected source channel carry it; the
    # still-skipped channel and the channel-less message stay empty.
    assert _message_channels(db, contact.id) == {1: wa_channel.id, 2: wa_channel.id, 3: None, 4: None}

    # A third run is a no-op: nothing re-linked, nothing duplicated.
    job3 = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run", channel_map=mapped,
    )
    run_migration_job(db, job3)
    db.refresh(job3)
    assert job3.status == "done", job3.error
    assert job3.result_json["report"]["entities"]["messages"]["wouldUpdate"] == 0
    assert _message_channels(db, contact.id) == {1: wa_channel.id, 2: wa_channel.id, 3: None, 4: None}

    identities = db.query(ContactChannelIdentity).filter(ContactChannelIdentity.contact_id == contact.id).all()
    assert [i.channel_id for i in identities] == [wa_channel.id]
    assert identities[0].external_user_id == "15557770000"
    assert db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact.id).count() == 4, (
        "re-runs must not duplicate history"
    )
    db.close()


def test_ac_skip_05_send_without_a_connected_channel_is_refused_cleanly(session_factory):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    # The workspace has no active channel: retire any the seed created.
    for ch in db.query(Channel).filter(Channel.tenant_id == DEFAULT_TENANT_ID, Channel.workspace_id == ws.id):
        ch.is_active = False
    contact = Contact(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, first_name="No", last_name="Channel", phone="+15558880000")
    db.add(contact)
    db.commit()

    with pytest.raises(SendRejected) as exc:
        MessageService(db).send_message(
            contact.id, DEFAULT_TENANT_ID, None, SendMessageRequest(messageType="TEXT", body="hi")
        )
    assert str(exc.value) == "No active channel is connected to this workspace."
    assert db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact.id).count() == 0
    db.close()


def test_ac_skip_01_preflight_warning_says_connect_later():
    warnings: list = []
    MigrationPreflightService._warn_no_compatible_target(
        [MigrationSourceChannel(id=SOURCE_CHANNEL_ID, name="WA Main", source="whatsapp")], [], warnings,
    )
    assert warnings == [
        'No connected channel in the target workspace matches source channel "WA Main" (whatsapp). '
        "Its contacts and history still import. Connect the channel later and run the migration "
        "again to link them."
    ]
