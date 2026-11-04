"""Plan 56 section C - contact erase, review round 1 (AC-56-40..55 refinements).

RED tests written BEFORE the fixes. Behaviour pinned here:
* the file purge keeps to the erasing tenant's own storage area;
* the staff route follows the module's activation like the other staff routes;
* the contact row is held (FOR UPDATE) before its files are collected;
* the continuous respond.io sync passes over an erased contact quietly;
* a voice conversion never leaves a row pointing at a removed file;
* a deactivated ideation module never makes the erase fail;
* reaction webhook deliveries are reduced to ids like the other events.

Every test seeds its own chain. Fake values only.
"""
from pathlib import Path

import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from app.models.tenant import PLATFORM_TENANT_ID
from modules.omnichannel.models import (
    Contact,
    ConversationMessage,
    MigrationRef,
    WebhookDelivery,
)
from tests.test_omnichannel_api_gateway import _auth
from tests.test_omnichannel_contact_erase import (  # noqa: F401 - _env is an autouse fixture
    Rig,
    _contact,
    _digits,
    _env,
    _file,
)
from tests.test_omnichannel_contact_erase_staff import ideation_client  # noqa: F401 - fixture

OTHER = "other-tenant-round1"
PUBLIC = f"{settings.public_base_url}/omnichannel/media/"


@pytest.fixture
def rig(client, session_factory):
    return Rig(client, session_factory)


def _actor():
    from modules.omnichannel.services.contact_erase_service import EraseActor

    return EraseActor.staff("u-round1")


def _exists(rel):
    return (Path(settings.media_root) / rel).exists()


def _add_message(sf, cid, channel, **kw):
    db = sf()
    try:
        row = ConversationMessage(tenant_id=DEFAULT_TENANT_ID, contact_id=cid, channel_id=channel,
                                  sender_type="CONTACT", message_type="IMAGE", **kw)
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# 1 - the purge keeps to the tenant's own storage area
# ═════════════════════════════════════════════════════════════════════════════
def test_purge_deletes_files_in_the_tenants_own_area_and_keeps_other_areas(rig):
    own = _file(f"omnichannel/{DEFAULT_TENANT_ID}/inbound-own1.png")
    own_url = _file(f"omnichannel/{DEFAULT_TENANT_ID}/inbound-own2.png")
    other_url = _file(f"omnichannel/{OTHER}/inbound-other1.png")
    other_key = _file(f"omnichannel/{OTHER}/inbound-other2.png")
    cid = _contact(rig.sf, rig.ws, "+60100000601")
    _add_message(rig.sf, cid, rig.channel, media_key=own)
    _add_message(rig.sf, cid, rig.channel, media_url=PUBLIC + own_url)
    _add_message(rig.sf, cid, rig.channel, media_url=PUBLIC + other_url)
    _add_message(rig.sf, cid, rig.channel, media_key=other_key)
    res = rig.erase(cid)
    assert res.status_code == 200, res.text
    assert rig.counts(cid)["contact"] == 0 and rig.counts(cid)["messages"] == 0  # rows are erased
    assert not _exists(own) and not _exists(own_url)  # control: own area is deleted
    assert _exists(other_url), "a legacy url into another area is not purged"
    assert _exists(other_key), "a media key in another area is not purged"


def test_purge_covers_the_tenants_migration_area_only(rig):
    mine = _file(f"omnichannel/migration/{DEFAULT_TENANT_ID}/ws/pic1.png")
    theirs = _file(f"omnichannel/migration/{OTHER}/ws/pic2.png")
    cid = _contact(rig.sf, rig.ws, "+60100000602")
    _add_message(rig.sf, cid, rig.channel, media_key=mine)
    _add_message(rig.sf, cid, rig.channel, media_url=PUBLIC + theirs)
    assert rig.erase(cid).status_code == 200
    assert not _exists(mine)
    assert _exists(theirs)


def test_purge_ignores_legacy_urls_on_migrated_rows_but_not_on_native_rows(rig):
    migrated = _file(f"omnichannel/{DEFAULT_TENANT_ID}/inbound-mig.png")
    native = _file(f"omnichannel/{DEFAULT_TENANT_ID}/inbound-native.png")
    cid = _contact(rig.sf, rig.ws, "+60100000603")
    mid = _add_message(rig.sf, cid, rig.channel, media_url=PUBLIC + migrated)
    _add_message(rig.sf, cid, rig.channel, media_url=PUBLIC + native)
    db = rig.sf()
    try:
        db.add(MigrationRef(tenant_id=DEFAULT_TENANT_ID, workspace_id=rig.ws, source="respondio",
                            entity_type="message", external_id="rio-m-r1", local_id=mid))
        db.commit()
    finally:
        db.close()
    assert rig.erase(cid).status_code == 200
    assert _exists(migrated), "a legacy url on a migrated row is never a purge target"
    assert not _exists(native), "control: the same kind of url on a native row is purged"


def test_purge_through_connections_follows_connection_owner_and_the_tenants_area(
    rig, session_factory, monkeypatch
):
    import app.database as appdb
    from app.integrations.s3_provider import S3CompatibleAdapter
    from app.services import storage as storage_module
    from tests.test_storage_providers import StubS3Client
    from tests.test_storage_resolution import _storage_connection

    client = StubS3Client()
    monkeypatch.setattr(S3CompatibleAdapter, "_build_client", lambda self: client)
    storage_module.clear_adapter_cache()
    monkeypatch.setattr(appdb, "SessionLocal", session_factory)
    db = session_factory()
    try:
        own = _storage_connection(db, DEFAULT_TENANT_ID).id
        platform = _storage_connection(db, PLATFORM_TENANT_ID).id
        foreign = _storage_connection(db, OTHER).id
    finally:
        db.close()
    area = f"omnichannel/{DEFAULT_TENANT_ID}"
    raws = {
        "own_conn_own_area": f"{area}/own-conn.png",
        "platform_conn_own_area": f"{area}/platform-conn.png",
        "platform_conn_other_area": f"omnichannel/{OTHER}/platform-other.png",
        "foreign_conn_own_area": f"{area}/foreign-conn.png",
    }
    for raw in raws.values():
        client.objects[raw] = b"x"
    cid = _contact(rig.sf, rig.ws, "+60100000604")
    _add_message(rig.sf, cid, rig.channel, media_key=f"conn:{own}:{raws['own_conn_own_area']}")
    _add_message(rig.sf, cid, rig.channel, media_key=f"conn:{platform}:{raws['platform_conn_own_area']}")
    _add_message(rig.sf, cid, rig.channel, media_url=PUBLIC + f"conn:{platform}:{raws['platform_conn_other_area']}")
    _add_message(rig.sf, cid, rig.channel, media_url=PUBLIC + f"conn:{foreign}:{raws['foreign_conn_own_area']}")
    res = rig.erase(cid)
    assert res.status_code == 200, res.text
    assert rig.counts(cid)["messages"] == 0
    assert raws["own_conn_own_area"] not in client.objects  # control: own connection, own area
    assert raws["platform_conn_own_area"] not in client.objects, "platform default storage, own area: purged"
    assert raws["platform_conn_other_area"] in client.objects, "platform storage under another area is kept"
    assert raws["foreign_conn_own_area"] in client.objects, "another tenant's connection is never used"
    assert res.json()["files"] == 2


# ═════════════════════════════════════════════════════════════════════════════
# 2 - staff route follows module activation
# ═════════════════════════════════════════════════════════════════════════════
def test_staff_erase_is_refused_while_the_module_is_not_active_and_the_contact_stays(
    rig, client, session_factory
):
    from app.models.module import Module, TenantModule

    cid = _contact(session_factory, rig.ws, "+60100000605")
    hdr = _auth(client)
    assert client.get(f"/omnichannel/contacts/{cid}", headers=hdr).status_code == 200  # control
    db = session_factory()
    try:
        tm = (db.query(TenantModule).join(Module, TenantModule.module_id == Module.id)
              .filter(TenantModule.tenant_id == DEFAULT_TENANT_ID, Module.name == "omnichannel").one())
        tm.status = "INACTIVE"
        db.commit()
    finally:
        db.close()
    read = client.get(f"/omnichannel/contacts/{cid}", headers=hdr)
    assert read.status_code != 200  # the other staff routes refuse
    res = client.delete(f"/omnichannel/contacts/{cid}", headers=hdr)
    assert res.status_code == read.status_code, res.text
    db = session_factory()
    try:
        assert db.query(Contact).filter(Contact.id == cid).count() == 1
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# 3 - the contact row is held before files are collected
# ═════════════════════════════════════════════════════════════════════════════
def test_erase_loads_the_contact_for_update_before_collecting_file_keys(rig, monkeypatch):
    """Seam: ``with_for_update`` on a query whose entity is Contact (Query or
    Select, sqlite emits no FOR UPDATE so the call is what can be observed),
    compared in order with ``ContactEraseRepository.messages`` (file key
    collection)."""
    from sqlalchemy.orm import Query
    from sqlalchemy.sql import Select

    from modules.omnichannel.repositories.contact_erase_repository import ContactEraseRepository

    calls = []

    def spy_for_update(cls):
        orig = cls.with_for_update

        def wrapped(self, *a, **k):
            try:
                entities = [d.get("entity") for d in self.column_descriptions]
            except Exception:  # noqa: BLE001
                entities = []
            calls.append(("for_update", Contact in entities))
            return orig(self, *a, **k)

        monkeypatch.setattr(cls, "with_for_update", wrapped)

    spy_for_update(Query)
    spy_for_update(Select)
    orig_messages = ContactEraseRepository.messages

    def messages(self, *a, **k):
        calls.append(("messages", None))
        return orig_messages(self, *a, **k)

    monkeypatch.setattr(ContactEraseRepository, "messages", messages)
    fp = rig.footprint("+60100000606", "lk")
    assert rig.erase(fp["cid"]).status_code == 200
    names = [(n, is_contact) for n, is_contact in calls]
    assert ("messages", None) in names
    first_lock = next((i for i, c in enumerate(names) if c == ("for_update", True)), None)
    assert first_lock is not None, "the contact row is never loaded FOR UPDATE"
    assert first_lock < names.index(("messages", None)), "the lock must come before key collection"


# ═════════════════════════════════════════════════════════════════════════════
# 4 - the continuous sync passes over an erased contact quietly
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("mode", ["poll", "sweep", "hint"])
def test_continuous_sync_skips_an_erased_contact_cleanly_and_imports_the_next(
    client, session_factory, monkeypatch, mode
):
    from modules.omnichannel.services.contact_erase_service import ContactEraseService
    from tests.test_omnichannel_migration_sync_support import (
        close_all_worlds,
        get_sync,
        make_due,
        not_due,
        post_hint,
        run_due_syncs,
        webhook_path,
    )
    from tests.test_omnichannel_migration_sync_ticks import _ready, _snapshot

    try:
        w, h, sid = _ready(client, session_factory, monkeypatch, contacts=(910001, 910002))
        gone = w.contact_by_cid(910001)
        gone_id, gone_phone = gone.id, gone.phone
        ContactEraseService(w.db).erase_in_tenant(DEFAULT_TENANT_ID, gone_id, actor=_actor())
        w.fake.add_message(910001, 2, text="after the erase")
        w.fake.add_contact(910003, first="After")
        w.fake.add_message(910003, 1, text="imported after the skip")
        w.fake.clear_calls()
        before = _snapshot(w.db)
        if mode == "hint":
            path = webhook_path(client, h, sid)
            assert post_hint(client, path, {"contact": {"id": 910001}}).status_code == 200
            assert post_hint(client, path, {"contact": {"id": 910003}}).status_code == 200
            not_due(w.db, sid)
        else:
            make_due(w.db, sid, full_sweep="due" if mode == "sweep" else "not_due")
        run_due_syncs(w.db)
        result = get_sync(client, h, sid)["lastResult"]
        assert result["errors"] == 0, result
        assert result["failureSample"] == [], result
        w.db.expire_all()
        assert w.db.query(Contact).filter(Contact.id == gone_id).count() == 0
        assert w.db.query(Contact).filter(Contact.phone == gone_phone).count() == 0
        assert w.db.query(ConversationMessage).filter(ConversationMessage.contact_id == gone_id).count() == 0
        assert w.db.query(ConversationMessage).filter(ConversationMessage.body == "after the erase").count() == 0
        assert not [c for c in w.fake.calls if "910001" in c[1] and "channels" in c[1]], w.fake.calls
        nxt = w.contact_by_phone("+601000910003")
        assert nxt is not None, "the next contact in the same tick still imports"
        assert [m.body for m in w.messages_of(nxt)] == ["imported after the skip"]
        assert _snapshot(w.db)["contacts"] == before["contacts"] + 1
    finally:
        close_all_worlds()


# ═════════════════════════════════════════════════════════════════════════════
# 5 - the original voice upload outlives a failure before the commit
# ═════════════════════════════════════════════════════════════════════════════
def test_voice_conversion_failing_before_the_commit_leaves_a_readable_file_on_the_row(
    client, session_factory, monkeypatch
):
    from modules.omnichannel.services.send_runner import run_send
    from tests.test_omnichannel_outbound_event import _rig

    r = _rig(client, session_factory, "+60100000607", events=())
    original = _file("voice/original-upload-r1.webm", b"webm-bytes")
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

    class _Adapter:
        def upload_media(self, *a, **k):
            raise RuntimeError("upload stopped before the commit")

        def send(self, *a, **k):  # pragma: no cover - never reached
            raise AssertionError("send must not run")

    monkeypatch.setattr("modules.omnichannel.services.send_runner.get_adapter", lambda *a, **k: _Adapter())
    db = session_factory()
    try:
        try:
            run_send(db, mid)  # may re-raise or answer a failed outcome; both are fine here
        except RuntimeError:
            pass
        db.rollback()  # the caller's session ends without committing the new key
    finally:
        db.close()
    db = session_factory()
    try:
        key = db.query(ConversationMessage).filter(ConversationMessage.id == mid).one().media_key
    finally:
        db.close()
    assert _exists(key), "the row points at a file that no longer exists"
    assert _exists(original), "the original upload is deleted only after the new key commits"


# ═════════════════════════════════════════════════════════════════════════════
# 6 - ideation installed but not active
# ═════════════════════════════════════════════════════════════════════════════
def test_erase_with_ideation_not_active_answers_200_and_clears_the_submitter_link(
    ideation_client, ideation_session_factory
):
    from app.models.module import Module, TenantModule
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id
    from tests.test_omnichannel_api_gateway import _default_workspace_id, _mint

    sf = ideation_session_factory
    ws = _default_workspace_id(sf)
    gone = _contact(sf, ws, "+60100000608")
    db = sf()
    try:
        idea = Idea(tenant_id=DEFAULT_TENANT_ID, product_id="prod-erase-r1",
                    status_id=idea_status_id(db, "captured", DEFAULT_TENANT_ID),
                    intake_definition_key="ideation", problem="problem r1", raw_text="x",
                    source="whatsapp", submitter_contact_id=gone, is_test=True)
        db.add(idea)
        db.flush()
        idea_id = idea.id
        tm = (db.query(TenantModule).join(Module, TenantModule.module_id == Module.id)
              .filter(TenantModule.tenant_id == DEFAULT_TENANT_ID, Module.name == "ideation").one())
        tm.status = "INACTIVE"
        db.commit()
    finally:
        db.close()
    hdr = {"Authorization": f"Bearer {_mint(ideation_client, ws).json()['fullKey']}"}
    res = ideation_client.delete(f"/api/v1/omnichannel/contacts/{gone}", headers=hdr)
    assert res.status_code == 200, res.text
    db = sf()
    try:
        assert db.query(Contact).filter(Contact.id == gone).count() == 0
        assert db.query(Idea).filter(Idea.id == idea_id).one().submitter_contact_id is None
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# 7 - reaction deliveries are reduced to ids
# ═════════════════════════════════════════════════════════════════════════════
def _reaction_delivery(sf, ws, target_message_id, event_id):
    db = sf()
    try:
        row = WebhookDelivery(
            tenant_id=DEFAULT_TENANT_ID, endpoint_id="ep-r1", event_id=event_id, event_type="message.reaction",
            payload_json={"id": event_id, "type": "message.reaction", "workspaceId": ws, "channelId": "ch-1",
                          "occurredAt": "2026-11-04T00:00:00Z",
                          "data": {"targetMessageId": target_message_id, "reactorType": "CONTACT",
                                   "emoji": "\U0001F44D", "removed": False}},
            status="SUCCESS", attempt_count=1, response_status=200,
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _delivery_state(sf, delivery_id):
    db = sf()
    try:
        r = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_id).one()
        return {"event_id": r.event_id, "payload": r.payload_json, "status": r.status}
    finally:
        db.close()


def _msg_id(sf, external_id):
    db = sf()
    try:
        return db.query(ConversationMessage.id).filter(
            ConversationMessage.external_message_id == external_id).one()[0]
    finally:
        db.close()


def test_reaction_deliveries_for_the_erased_contacts_messages_keep_only_ids(rig):
    fp = rig.footprint("+60100000609", "rx1")
    keep = rig.footprint("+60100000610", "rx2")
    digits = _digits(fp["phone"])
    mine = _reaction_delivery(rig.sf, rig.ws, _msg_id(rig.sf, "wamid.rx1.out"), f"{_msg_id(rig.sf, 'wamid.rx1.out')}:{digits}")
    mine_wamid = _reaction_delivery(rig.sf, rig.ws, _msg_id(rig.sf, "wamid.rx1.in"), "wamid.REACTION-EVENT-1")
    other = _reaction_delivery(rig.sf, rig.ws, _msg_id(rig.sf, "wamid.rx2.out"),
                               f"{_msg_id(rig.sf, 'wamid.rx2.out')}:{_digits(keep['phone'])}")
    other_before = _delivery_state(rig.sf, other)
    assert rig.erase(fp["cid"]).status_code == 200
    for did in (mine, mine_wamid):
        state = _delivery_state(rig.sf, did)
        payload = state["payload"]
        assert state["status"] == "SUCCESS"
        assert set(payload["data"]) <= {"contactId", "messageId", "targetMessageId"}, payload
        assert "\U0001F44D" not in str(payload)
        assert digits not in str(payload), "the reactor's number stays in the payload"
        assert digits not in state["event_id"], "the reactor's number stays in the event id"
    assert _delivery_state(rig.sf, other) == other_before  # control: another contact's delivery untouched


# ═════════════════════════════════════════════════════════════════════════════
# 8 - the purge task retries; the service purges only after the commit
# ═════════════════════════════════════════════════════════════════════════════
def test_purge_task_retries_and_reraises_when_a_delete_fails(monkeypatch):
    from app.services import storage as storage_module
    from modules.omnichannel.worker import purge_erased_files

    rel = _file(f"omnichannel/{DEFAULT_TENANT_ID}/retry-me.png")

    def boom(self, key):
        raise OSError("disk unavailable")

    class _Retry(Exception):
        pass

    retried = []

    def fake_retry(*a, **k):
        retried.append(k.get("exc"))
        raise _Retry()

    monkeypatch.setattr(storage_module.LocalDiskStorage, "delete", boom)
    monkeypatch.setattr(purge_erased_files, "retry", fake_retry)
    assert Exception in tuple(purge_erased_files.autoretry_for)
    with pytest.raises(_Retry):
        purge_erased_files.run(DEFAULT_TENANT_ID, [rel])
    assert len(retried) == 1 and retried[0] is not None
    assert _exists(rel)


def test_nothing_is_purged_and_no_row_goes_when_the_commit_fails(rig, monkeypatch):
    from modules.omnichannel.services.contact_erase_service import ContactEraseService
    from modules.omnichannel.worker import purge_erased_files

    keep_file = _file(f"omnichannel/{DEFAULT_TENANT_ID}/survives-1.png")
    cid = _contact(rig.sf, rig.ws, "+60100000611")
    _add_message(rig.sf, cid, rig.channel, media_key=keep_file)
    queued = []
    monkeypatch.setattr(purge_erased_files, "delay", lambda *a, **k: queued.append(a))
    db = rig.sf()
    try:
        def boom():
            raise RuntimeError("commit stopped")

        monkeypatch.setattr(db, "commit", boom)
        with pytest.raises(RuntimeError):
            ContactEraseService(db).erase(DEFAULT_TENANT_ID, rig.ws, cid, actor=_actor())
    finally:
        db.close()
    assert queued == [], "the purge was queued before the commit"
    assert _exists(keep_file)
    assert rig.counts(cid)["contact"] == 1 and rig.counts(cid)["messages"] == 1
    # control: the same erase with a working commit queues the purge and removes the rows
    db = rig.sf()
    try:
        ContactEraseService(db).erase(DEFAULT_TENANT_ID, rig.ws, cid, actor=_actor())
    finally:
        db.close()
    assert len(queued) == 1 and rig.counts(cid)["contact"] == 0


def test_a_failing_delete_inside_the_purge_task_never_fails_the_erase_request(rig, monkeypatch):
    from app.services import storage as storage_module

    rel = _file(f"omnichannel/{DEFAULT_TENANT_ID}/stuck.png")
    cid = _contact(rig.sf, rig.ws, "+60100000612")
    _add_message(rig.sf, cid, rig.channel, media_key=rel)

    def boom(self, key):
        raise OSError("disk unavailable")

    monkeypatch.setattr(storage_module.LocalDiskStorage, "delete", boom)
    res = rig.erase(cid)
    assert res.status_code == 200, res.text
    assert rig.counts(cid)["contact"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# 10 - contact.erased reaches every subscribed active endpoint once
# ═════════════════════════════════════════════════════════════════════════════
def test_contact_erased_reaches_all_channel_endpoints_and_endpoints_of_the_contacts_channels_once(rig):
    from modules.omnichannel.models import ContactChannelIdentity, WebhookEndpoint
    from tests.test_omnichannel_api_gateway import _seed_channel
    from tests.test_omnichannel_outbound_event import _deliveries

    fp = rig.footprint("+60100000613", "reach")  # identity on rig.channel
    second = _seed_channel(rig.sf, rig.ws, phone_number_id="pn-erase-2")
    unrelated = _seed_channel(rig.sf, rig.ws, phone_number_id="pn-erase-3")
    db = rig.sf()
    try:
        db.add(ContactChannelIdentity(tenant_id=DEFAULT_TENANT_ID, contact_id=fp["cid"],
                                      channel_id=second, external_user_id="second-wa-id"))

        def endpoint(name, channel_id):
            ep = WebhookEndpoint(tenant_id=DEFAULT_TENANT_ID, workspace_id=rig.ws, channel_id=channel_id,
                                 name=name, url=f"https://hooks.example.com/{name}",
                                 secret_encrypted="x", events_json=["contact.erased"], status="ACTIVE")
            db.add(ep)
            db.flush()
            return ep.id

        every = endpoint("all", None)
        on_first = endpoint("first", rig.channel)
        on_second = endpoint("second", second)
        on_unrelated = endpoint("unrelated", unrelated)
        db.commit()
    finally:
        db.close()
    assert rig.erase(fp["cid"]).status_code == 200
    got = sorted(r["endpoint_id"] for r in _deliveries(rig.sf, "contact.erased"))
    assert got == sorted([every, on_first, on_second]), "one delivery per reachable endpoint, none for an unrelated channel"
    assert on_unrelated not in got


# ═════════════════════════════════════════════════════════════════════════════
# 5b - the original voice upload goes once the converted file is the row's key
# ═════════════════════════════════════════════════════════════════════════════
def test_voice_original_is_removed_once_the_converted_file_is_committed_even_if_the_send_fails(
    client, session_factory, monkeypatch
):
    from modules.omnichannel.adapters.base import SendError
    from modules.omnichannel.services.send_runner import run_send
    from tests.test_omnichannel_outbound_event import _rig

    r = _rig(client, session_factory, "+60100000614", events=())
    original = _file("voice/original-upload-r1b.webm", b"webm-bytes")
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

    class _Adapter:
        def upload_media(self, *a, **k):
            return "media-1"

        def send(self, *a, **k):
            raise SendError("recipient number is not valid")  # permanent rejection

    monkeypatch.setattr("modules.omnichannel.services.send_runner.get_adapter", lambda *a, **k: _Adapter())
    db = session_factory()
    try:
        assert run_send(db, mid) == "FAILED"
    finally:
        db.close()
    db = session_factory()
    try:
        key = db.query(ConversationMessage).filter(ConversationMessage.id == mid).one().media_key
    finally:
        db.close()
    assert key != original and _exists(key), "the row points at the converted file, which stays"
    assert not _exists(original), "nothing points at the original upload any more"


# ═════════════════════════════════════════════════════════════════════════════
# Round 2 - which stored files an erase counts and removes
# ═════════════════════════════════════════════════════════════════════════════
def _migrated(sf, ws, message_id, ext):
    db = sf()
    try:
        db.add(MigrationRef(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, source="respondio",
                            entity_type="message", external_id=ext, local_id=message_id))
        db.commit()
    finally:
        db.close()


def test_server_minted_bare_key_on_a_native_row_is_counted_and_purged(rig, client):
    minted = _file("inbound-3fa9c2b1.png")  # `<basename>-<uuid8>.<ext>`, no tenant prefix
    cid = _contact(rig.sf, rig.ws, "+60100000615")
    _add_message(rig.sf, cid, rig.channel, media_key=minted)
    staff = client.get(f"/omnichannel/contacts/{cid}", headers=_auth(client))
    assert staff.status_code == 200 and staff.json()["fileCount"] == 1  # same rule as the erase
    res = rig.erase(cid)
    assert res.status_code == 200, res.text
    assert res.json()["files"] == 1
    assert not _exists(minted)


def test_server_minted_bare_key_on_a_migrated_row_is_neither_counted_nor_purged(rig):
    minted = _file("migrated-7be01d44.png")
    cid = _contact(rig.sf, rig.ws, "+60100000616")
    mid = _add_message(rig.sf, cid, rig.channel, media_key=minted)
    _migrated(rig.sf, rig.ws, mid, "rio-m-r2a")
    res = rig.erase(cid)
    assert res.status_code == 200, res.text
    assert res.json()["files"] == 0
    assert _exists(minted)


def test_keys_outside_the_tenants_area_that_are_not_minted_are_kept(rig):
    in_dir = _file("other/dir/file.png")
    escaped = _file("y.png")  # what `x/../y.png` would resolve to
    cid = _contact(rig.sf, rig.ws, "+60100000617")
    _add_message(rig.sf, cid, rig.channel, media_key="other/dir/file.png")
    _add_message(rig.sf, cid, rig.channel, media_key="x/../y.png")
    res = rig.erase(cid)
    assert res.status_code == 200, res.text
    assert res.json()["files"] == 0
    assert _exists(in_dir) and _exists(escaped)


def test_server_minted_bare_key_behind_a_connection_follows_the_connection_rule(
    rig, session_factory, monkeypatch
):
    import app.database as appdb
    from app.integrations.s3_provider import S3CompatibleAdapter
    from app.services import storage as storage_module
    from tests.test_storage_providers import StubS3Client
    from tests.test_storage_resolution import _storage_connection

    client = StubS3Client()
    monkeypatch.setattr(S3CompatibleAdapter, "_build_client", lambda self: client)
    storage_module.clear_adapter_cache()
    monkeypatch.setattr(appdb, "SessionLocal", session_factory)
    db = session_factory()
    try:
        platform = _storage_connection(db, PLATFORM_TENANT_ID).id
        foreign = _storage_connection(db, OTHER).id
    finally:
        db.close()
    for raw in ("via-platform-5c2e9a10.png", "via-foreign-9d4b7e21.png"):
        client.objects[raw] = b"x"
    cid = _contact(rig.sf, rig.ws, "+60100000618")
    _add_message(rig.sf, cid, rig.channel, media_key=f"conn:{platform}:via-platform-5c2e9a10.png")
    _add_message(rig.sf, cid, rig.channel, media_key=f"conn:{foreign}:via-foreign-9d4b7e21.png")
    res = rig.erase(cid)
    assert res.status_code == 200, res.text
    assert "via-platform-5c2e9a10.png" not in client.objects, "minted key behind the platform default: purged"
    assert "via-foreign-9d4b7e21.png" in client.objects, "another tenant's connection is never used"


def test_media_url_on_a_foreign_host_with_our_path_is_not_a_stored_file(rig):
    rel = f"omnichannel/{DEFAULT_TENANT_ID}/lookalike.png"
    _file(rel)
    cid = _contact(rig.sf, rig.ws, "+60100000619")
    _add_message(rig.sf, cid, rig.channel, media_url=f"https://cdn.example.org/omnichannel/media/{rel}")
    res = rig.erase(cid)
    assert res.status_code == 200, res.text
    assert res.json()["files"] == 0
    assert _exists(rel)
    # control: the same key behind our own public base URL is a stored file
    own = _file(f"omnichannel/{DEFAULT_TENANT_ID}/ours.png")
    cid2 = _contact(rig.sf, rig.ws, "+60100000620")
    _add_message(rig.sf, cid2, rig.channel, media_url=PUBLIC + own)
    res2 = rig.erase(cid2)
    assert res2.json()["files"] == 1 and not _exists(own)


def test_minted_looking_key_inside_another_tenants_area_is_neither_counted_nor_purged(
    rig, client, session_factory, monkeypatch
):
    import app.database as appdb
    from app.integrations.s3_provider import S3CompatibleAdapter
    from app.services import storage as storage_module
    from tests.test_storage_providers import StubS3Client
    from tests.test_storage_resolution import _storage_connection

    s3 = StubS3Client()
    monkeypatch.setattr(S3CompatibleAdapter, "_build_client", lambda self: s3)
    storage_module.clear_adapter_cache()
    monkeypatch.setattr(appdb, "SessionLocal", session_factory)
    db = session_factory()
    try:
        platform = _storage_connection(db, PLATFORM_TENANT_ID).id
    finally:
        db.close()
    local = _file(f"omnichannel/{OTHER}/inbound-3fa9c2b1.png")
    remote_raw = f"omnichannel/{OTHER}/inbound-5c2e9a10.png"
    s3.objects[remote_raw] = b"x"
    cid = _contact(rig.sf, rig.ws, "+60100000621")
    _add_message(rig.sf, cid, rig.channel, media_key=f"omnichannel/{OTHER}/inbound-3fa9c2b1.png")
    _add_message(rig.sf, cid, rig.channel, media_key=f"conn:{platform}:{remote_raw}")
    staff = client.get(f"/omnichannel/contacts/{cid}", headers=_auth(client))
    assert staff.status_code == 200 and staff.json()["fileCount"] == 0
    res = rig.erase(cid)
    assert res.status_code == 200, res.text
    assert res.json()["files"] == 0
    assert _exists(local)
    assert remote_raw in s3.objects


def test_minted_bare_key_on_a_migrated_row_is_not_counted_on_the_staff_reads(rig, client):
    minted = _file("converted-8a1c4e77.png")
    cid = _contact(rig.sf, rig.ws, "+60100000622")
    mid = _add_message(rig.sf, cid, rig.channel, media_key=minted)
    _migrated(rig.sf, rig.ws, mid, "rio-m-r2b")
    hdr = _auth(client)
    one = client.get(f"/omnichannel/contacts/{cid}", headers=hdr)
    assert one.status_code == 200 and one.json()["fileCount"] == 0
    from tests.test_omnichannel_contact_counts import _list

    row = _list(client, rig)[cid]
    assert row["fileCount"] == 0
    assert rig.erase(cid).json()["files"] == 0  # same number as the erase
    assert _exists(minted)
