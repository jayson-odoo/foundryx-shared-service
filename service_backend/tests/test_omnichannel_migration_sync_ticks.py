"""Lane SS-MIGRATION-SYNC (plan sprint-5/52) - RED tests, part 2: the tick
(AC-SYNC-10..19), respond.io wins (20/21), errors / pause / stop (40..44).

Time-based ACs set `next_sync_at` / `last_full_sweep_at` on the row directly
(no sleeping). Ticks run in eager mode (`CELERY_TASK_ALWAYS_EAGER`), i.e.
`run_due_syncs(db)` enqueues through `JobService` and the handler runs inline;
tests that need a job to STAY pending stub `JobService.enqueue`.
"""
import inspect
from datetime import datetime, timedelta, timezone

import pytest

from app.jobs.service import run_job
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import (
    JOB_DONE,
    JOB_PENDING,
    JOB_RUNNING,
    BackgroundJob,
)
from tests.conftest import ACTIVE_EMAIL

from modules.omnichannel.models import (
    Contact,
    ContactChannelIdentity,
    ContactTag,
    ConversationEvent,
    ConversationMessage,
    MigrationRef,
    Workspace,
)
from modules.omnichannel.services.migration_service import MIGRATION_JOB_TYPE

from tests.test_omnichannel_migration_sync_support import (
    close_all_worlds,
    SYNC_JOB_TYPE_LITERAL,
    SYNCS,
    add_done_job,
    aware,
    get_sync,
    hint_ids,
    make_due,
    new_world,
    not_due,
    post_hint,
    run_due_syncs,
    seam_counters,
    set_sync,
    start_sync,
    stub_enqueue,
    sync_jobs,
    sync_models,
    sync_row,
    sync_service_module,
    utcnow,
    webhook_path,
)
from tests.test_omnichannel_respondio_migration_jobs import _auth, _make_connection


@pytest.fixture(autouse=True)
def _close_worlds(session_factory):
    yield
    close_all_worlds()


def _ready(client, session_factory, monkeypatch, *, contacts=(910001,), rps="1000",
           channel_target="mapped", lifecycle_map=None, setup=None):
    """World + a real migration over `contacts` (1 message each) + a started
    sync. Returns (world, auth headers, sync id)."""
    w = new_world(session_factory, monkeypatch, rps=rps)
    for cid in contacts:
        w.fake.add_contact(cid, first=f"C{cid}")
        w.fake.add_message(cid, 1, text=f"hello {cid}")
    if setup:
        setup(w)
    w.run_migration(channel_target=channel_target, lifecycle_map=lifecycle_map)
    w.db.commit()
    h = _auth(client)
    item = start_sync(client, w.ws.id, h)
    w.fake.clear_calls()
    return w, h, item["id"]


def _snapshot(db):
    db.expire_all()
    t = DEFAULT_TENANT_ID
    return {
        "contacts": db.query(Contact).filter(Contact.tenant_id == t).count(),
        "messages": db.query(ConversationMessage).filter(ConversationMessage.tenant_id == t).count(),
        "identities": db.query(ContactChannelIdentity).filter(ContactChannelIdentity.tenant_id == t).count(),
        "events": db.query(ConversationEvent).filter(ConversationEvent.tenant_id == t).count(),
        "refs": db.query(MigrationRef).filter(MigrationRef.tenant_id == t).count(),
    }


def _epoch(dt):
    return int(dt.timestamp())


def _iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ═══════════════════════════════════════════════════════════════════════════
# Slice 2 - the tick
# ═══════════════════════════════════════════════════════════════════════════


def test_sync_10_due_sync_enqueues_exactly_one_job(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    enqueued = stub_enqueue(monkeypatch)
    make_due(w.db, sid)

    run_due_syncs(w.db)
    jobs = sync_jobs(w.db)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.tenant_id == DEFAULT_TENANT_ID
    assert job.payload_json["syncId"] == sid
    assert job.payload_json["kind"] == "poll"
    assert job.status == JOB_PENDING and enqueued == [job.id]

    run_due_syncs(w.db)  # a second sweep while that job is pending
    assert len(sync_jobs(w.db)) == 1
    job.status = JOB_RUNNING
    w.db.commit()
    run_due_syncs(w.db)  # ... or running
    assert len(sync_jobs(w.db)) == 1

    # Control: once it is done and the sync is due again, the sweep enqueues.
    job.status = JOB_DONE
    w.db.commit()
    set_sync(w.db, sid, running_job_id=None)
    make_due(w.db, sid)
    run_due_syncs(w.db)
    assert len(sync_jobs(w.db)) == 2


def test_sync_10_not_due_enqueues_nothing(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    stub_enqueue(monkeypatch)
    not_due(w.db, sid)
    run_due_syncs(w.db)
    assert sync_jobs(w.db) == []
    # control: the same row, due, is picked up
    make_due(w.db, sid)
    run_due_syncs(w.db)
    assert len(sync_jobs(w.db)) == 1


def test_sync_10_beat_task_registered_every_60_seconds():
    from app.workflow_engine import worker

    assert "omnichannel.migration_sync_due" in worker.celery_app.tasks
    entries = [e for e in worker.celery_app.conf.beat_schedule.values() if e["task"] == "omnichannel.migration_sync_due"]
    assert len(entries) == 1 and entries[0]["schedule"] == 60.0


def test_sync_10_job_type_constant():
    assert sync_service_module().SYNC_JOB_TYPE == SYNC_JOB_TYPE_LITERAL == "omnichannel.respondio_sync"


def test_sync_11_poll_creates_new_contacts_and_skips_untouched_histories(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    # respond.io moves on: a brand-new contact N with history, and a new
    # message on the already-migrated A (no webhook hint, full sweep not due).
    w.fake.add_contact(910002, first="Newbie")
    w.fake.add_message(910002, 1, text="hi there")
    w.fake.add_message(910002, 2, traffic="outgoing", text="welcome")
    w.fake.add_message(910001, 2, text="a new message on A")
    make_due(w.db, sid, full_sweep="not_due")

    run_due_syncs(w.db)

    n = w.contact_by_phone("+6011910002")
    assert n is not None, "the new contact was created"
    assert [m.body for m in w.messages_of(n)] == ["hi there", "welcome"]
    assert w.db.query(ContactChannelIdentity).filter(ContactChannelIdentity.contact_id == n.id).count() == 1
    assert w.db.query(ConversationEvent).filter(ConversationEvent.contact_id == n.id).count() >= 1

    a = w.contact_by_cid(910001)
    assert len(w.messages_of(a)) == 1, "A's history was not re-read"
    assert w.fake.message_list_calls(910001) == 0
    assert w.fake.message_list_calls(910002) >= 1
    assert w.fake.contact_list_calls == 1, "the contact list is walked once per poll"

    item = get_sync(client, h, sid)
    assert item["lastResult"]["contactsCreated"] == 1
    assert item["lastResult"]["messagesCreated"] == 2
    assert item["lastSyncAt"] is not None


def test_sync_12_hints_tick_fetches_flagged_and_creates_unknown(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch, contacts=(910001, 910003))
    path = webhook_path(client, h, sid)
    w.fake.add_contact(910002, first="HintB")  # not yet in SS
    w.fake.add_message(910002, 1, text="b one")
    w.fake.add_message(910002, 2, text="b two")
    w.fake.add_message(910001, 2, text="a news")
    w.fake.add_message(910003, 2, text="c news (never flagged)")
    assert post_hint(client, path, {"contact": {"id": 910001}}).status_code == 200
    assert post_hint(client, path, {"contactId": 910002}).status_code == 200
    # The poll is NOT due: hints alone trigger the next sweep's tick.
    not_due(w.db, sid)
    w.fake.clear_calls()

    run_due_syncs(w.db)

    jobs = sync_jobs(w.db)
    assert len(jobs) == 1 and jobs[0].payload_json["kind"] == "hints"
    assert [m.body for m in w.messages_of(w.contact_by_cid(910001))] == ["hello 910001", "a news"]
    b = w.contact_by_phone("+6011910002")
    assert b is not None and [m.body for m in w.messages_of(b)] == ["b one", "b two"]
    assert w.fake.contact_get_calls(910002) == 1, "unknown contact created via GET /contact/id:B"
    assert len(w.messages_of(w.contact_by_cid(910003))) == 1, "unflagged C untouched"
    assert w.fake.message_list_calls(910003) == 0
    assert w.fake.contact_list_calls == 0, "a hints tick does not walk the contact list"
    assert hint_ids(w.db, sid) == [], "hints are consumed"


@pytest.mark.parametrize("full_sweep", ["due", "never"])
def test_sync_13_full_sweep_rechecks_everyone_and_stamps_on_completion(client, session_factory, monkeypatch, full_sweep):
    w, h, sid = _ready(client, session_factory, monkeypatch, contacts=(910001, 910003))
    w.fake.add_message(910001, 2, text="a2")
    w.fake.add_message(910003, 2, text="c2")
    make_due(w.db, sid, full_sweep=full_sweep)
    started = utcnow()

    run_due_syncs(w.db)

    for cid in (910001, 910003):
        assert w.fake.message_list_calls(cid) >= 1
        assert w.fake.count("GET", f"/contact/id:{cid}/channels") >= 1, "identities re-checked too"
        assert len(w.messages_of(w.contact_by_cid(cid))) == 2
    row = sync_row(w.db, sid)
    stamped = aware(row.last_full_sweep_at)
    assert stamped is not None and stamped >= started
    # completion, not start: stamped after the LAST message-list request.
    assert stamped >= w.fake.last_message_list_at


def test_sync_13_recent_full_sweep_is_not_repeated(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    w.fake.add_message(910001, 2, text="a2")
    make_due(w.db, sid, full_sweep="not_due")
    run_due_syncs(w.db)
    assert w.fake.message_list_calls(910001) == 0
    assert len(w.messages_of(w.contact_by_cid(910001))) == 1


def test_sync_14_second_identical_tick_writes_nothing(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    w.fake.add_contact(910002, first="Twice")
    w.fake.add_message(910002, 1, text="one")
    w.fake.add_message(910002, 2, traffic="outgoing", text="two")
    w.fake.add_message(910001, 2, text="a2")

    make_due(w.db, sid, full_sweep="due")
    run_due_syncs(w.db)
    first = _snapshot(w.db)
    assert get_sync(client, h, sid)["lastResult"]["messagesCreated"] == 3

    make_due(w.db, sid, full_sweep="due")
    run_due_syncs(w.db)
    assert _snapshot(w.db) == first, "nothing new: no messages, contacts, identities, events, refs"
    again = get_sync(client, h, sid)["lastResult"]
    assert again["messagesCreated"] == 0 and again["contactsCreated"] == 0
    assert len(sync_jobs(w.db)) == 2


def test_sync_14_native_whatsapp_id_is_skipped_and_counted(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    a = w.contact_by_cid(910001)
    w.db.add(ConversationMessage(
        tenant_id=DEFAULT_TENANT_ID, contact_id=a.id, channel_id=w.channel.id, sender_type="CONTACT",
        message_type="TEXT", body="arrived natively", external_message_id="wamid.NATIVE1",
        created_at=utcnow() - timedelta(minutes=5),
    ))
    w.db.commit()
    w.fake.add_message(910001, 2, text="same message via respond.io", channel_message_id="wamid.NATIVE1")
    w.fake.add_message(910001, 3, text="fresh", channel_message_id="wamid.FRESH3")
    make_due(w.db, sid, full_sweep="due")

    run_due_syncs(w.db)

    msgs = w.messages_of(a)
    assert sorted(m.body for m in msgs) == ["arrived natively", "fresh", "hello 910001"]
    assert "same message via respond.io" not in [m.body for m in msgs]
    assert sum(1 for m in msgs if m.external_message_id == "wamid.NATIVE1") == 1
    item = get_sync(client, h, sid)["lastResult"]
    assert item["messagesSkipped"] >= 1
    assert item["messagesCreated"] == 1


def test_sync_14_synced_rows_store_the_whatsapp_id_in_payload(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    w.fake.add_message(910001, 2, text="with wamid", channel_message_id="wamid.STORED2")
    make_due(w.db, sid, full_sweep="due")
    run_due_syncs(w.db)
    row = next(m for m in w.messages_of(w.contact_by_cid(910001)) if m.body == "with wamid")
    assert row.payload_json["migration"]["channelMessageId"] == "wamid.STORED2"
    assert row.external_message_id is None, "the native dedupe column stays NULL on synced rows"
    assert row.migrated_from == "respondio"


def test_sync_15_synced_messages_follow_the_read_only_history_rules(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    w.fake.add_contact(910002, first="Quiet")
    recent = _epoch(utcnow() - timedelta(minutes=30))
    w.fake.add_message(910002, 1, text="hi", ts=recent)
    w.fake.add_message(910001, 2, text="a new one", ts=recent)
    calls = seam_counters(monkeypatch)
    make_due(w.db, sid, full_sweep="due")

    run_due_syncs(w.db)

    assert calls == {k: 0 for k in calls}, calls
    for cid in (910001, 910002):
        c = w.contact_by_cid(cid)
        assert c.last_message_at is not None
        assert aware(c.last_message_at) == datetime.fromtimestamp(recent, tz=timezone.utc)
        assert aware(c.agent_last_read_at) == aware(c.last_message_at), "marked read (Q4)"
        assert c.csw_expires_at is None, "no CSW recompute while syncing"
    assert get_sync(client, h, sid)["lastResult"]["messagesCreated"] == 2


def test_sync_16_skipped_channel_then_mapped_relinks_on_next_tick(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch, channel_target=None)
    a = w.contact_by_cid(910001)
    assert w.db.query(ContactChannelIdentity).filter(ContactChannelIdentity.contact_id == a.id).count() == 0

    w.fake.add_message(910001, 2, text="while skipped")
    make_due(w.db, sid, full_sweep="due")
    run_due_syncs(w.db)
    msgs = w.messages_of(a)
    assert len(msgs) == 2 and all(m.channel_id is None for m in msgs), "imported with no channel"
    assert w.db.query(ContactChannelIdentity).filter(ContactChannelIdentity.contact_id == a.id).count() == 0

    # The owner connects the channel and re-runs the migration with it mapped.
    add_done_job(
        w.db, w.ws, w.conn, mode="run", channel_target=w.channel.id,
        finished_at=utcnow() + timedelta(minutes=1),
    )
    make_due(w.db, sid, full_sweep="due")
    run_due_syncs(w.db)

    msgs = w.messages_of(a)
    assert len(msgs) == 2
    assert {m.channel_id for m in msgs} == {w.channel.id}, "the #179 re-link"
    idents = w.db.query(ContactChannelIdentity).filter(ContactChannelIdentity.contact_id == a.id).all()
    assert [i.channel_id for i in idents] == [w.channel.id]
    assert idents[0].external_user_id == "6011910001"


def test_sync_17_mapping_follows_the_newest_done_real_api_run(client, session_factory, monkeypatch):
    from tests.test_omnichannel_respondio_migration_s3 import _make_channel

    w, h, sid = _ready(client, session_factory, monkeypatch)
    chan_b = _make_channel(w.db, DEFAULT_TENANT_ID, w.ws.id, channel_type="WHATSAPP", name="Second WA")
    w.db.commit()
    # A newer DONE real API run maps the channel to B ...
    add_done_job(w.db, w.ws, w.conn, mode="run", channel_target=chan_b.id, finished_at=utcnow() + timedelta(minutes=1))
    # ... and newer-still dry-run / CSV jobs (which must NOT count) point back at A.
    add_done_job(w.db, w.ws, w.conn, mode="dry_run", channel_target=w.channel.id, finished_at=utcnow() + timedelta(minutes=2))
    add_done_job(w.db, w.ws, None, mode="run", source="csv", finished_at=utcnow() + timedelta(minutes=3))

    w.fake.add_message(910001, 2, text="after the re-map")
    make_due(w.db, sid, full_sweep="due")
    run_due_syncs(w.db)

    row = next(m for m in w.messages_of(w.contact_by_cid(910001)) if m.body == "after the re-map")
    assert row.channel_id == chan_b.id


def test_sync_18_tick_waits_while_a_migration_job_runs(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    stub_enqueue(monkeypatch)
    running = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=MIGRATION_JOB_TYPE, status=JOB_RUNNING,
        payload_json={"workspaceId": w.ws.id, "mode": "run", "source": "api", "connectionId": w.conn.id},
    )
    w.db.add(running)
    w.db.commit()
    make_due(w.db, sid)

    run_due_syncs(w.db)
    assert sync_jobs(w.db) == [], "no tick while a migration job is pending/running"

    running.status = JOB_DONE
    w.db.commit()
    run_due_syncs(w.db)
    assert len(sync_jobs(w.db)) == 1, "re-tried on the next sweep"


def test_sync_18_migration_create_is_409_while_a_sync_job_runs(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    stub_enqueue(monkeypatch)
    make_due(w.db, sid)
    run_due_syncs(w.db)
    (sync_job,) = sync_jobs(w.db)
    assert sync_job.status == JOB_PENDING

    body = {
        "connectionId": w.conn.id, "workspaceId": w.ws.id, "mode": "dry_run", "source": "api",
        "channelMap": [{"sourceChannelId": "1001", "targetChannelId": None}],
        "userMap": [], "teamMap": [], "lifecycleMap": [], "contactsOnly": False,
    }
    res = client.post("/omnichannel/migration/jobs", headers=h, json=body)
    assert res.status_code == 409, res.text
    assert res.json()["detail"]["reason"] == "migration_in_progress"

    sync_job.status = JOB_RUNNING
    w.db.commit()
    assert client.post("/omnichannel/migration/jobs", headers=h, json=body).status_code == 409

    # Control: once the sync job is finished the same request is accepted.
    sync_job.status = JOB_DONE
    w.db.commit()
    ok = client.post("/omnichannel/migration/jobs", headers=h, json=body)
    assert ok.status_code == 201, ok.text


def test_sync_19_one_bad_contact_does_not_stop_the_tick(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    for cid in (910011, 910012, 910013, 910014):
        w.fake.add_contact(cid, first=f"Iso{cid}")
        w.fake.add_message(cid, 1, text=f"msg {cid}")
    w.fake.fail_paths["/contact/id:910011/channels"] = 404
    w.fake.fail_paths["/contact/id:910014/message/list"] = 500
    before = sync_row(w.db, sid).last_sync_at
    make_due(w.db, sid, full_sweep="not_due")

    run_due_syncs(w.db)

    for good in (910012, 910013):
        c = w.contact_by_cid(good)
        assert c is not None and len(w.messages_of(c)) == 1, f"{good} synced despite its neighbours failing"
    item = get_sync(client, h, sid)
    assert item["status"] == "active"
    assert item["lastResult"]["errors"] >= 2
    assert len(item["lastResult"]["failureSample"]) >= 1
    assert item["lastSyncAt"] is not None
    assert before is None or aware(sync_row(w.db, sid).last_sync_at) > aware(before)
    (job,) = sync_jobs(w.db)
    assert job.status == JOB_DONE, job.error


# ═══════════════════════════════════════════════════════════════════════════
# Slice 3 - respond.io wins
# ═══════════════════════════════════════════════════════════════════════════


FIELDS = [{"id": 1, "name": "Plan", "dataType": "text"}]


def _tag_names(db, contact):
    from modules.omnichannel.services.contact_tag_service import ContactTagService

    ids = ContactTagService(db).ids_for_contact(contact.id, DEFAULT_TENANT_ID)
    db.expire_all()
    return {t.name for t in db.query(ContactTag).filter(ContactTag.id.in_(ids), ContactTag.tenant_id == DEFAULT_TENANT_ID)}


def _world_for_q3(client, session_factory, monkeypatch, **kwargs):
    def setup(w):
        w.fake.custom_fields = FIELDS
        w.fake.set_contact(
            910001, firstName="Ann", lastName="Lee", email="ann@lee.test", language="en", countryCode="MY",
            tags=["t1", "t2"], custom_fields=[{"name": "Plan", "value": "basic"}],
        )
    return _ready(client, session_factory, monkeypatch, setup=setup, **kwargs)


def test_sync_20_source_wins_overwrites_non_empty_and_never_clears(client, session_factory, monkeypatch):
    from modules.omnichannel.services.statuses import status_id_for

    w, h, sid = _world_for_q3(client, session_factory, monkeypatch)
    a = w.contact_by_cid(910001)
    assert (a.first_name, a.last_name, a.email) == ("Ann", "Lee", "ann@lee.test")
    assert _tag_names(w.db, a) == {"t1", "t2"}

    w.fake.set_contact(
        910001, firstName="Anna", lastName=None, email="anna@lee.test", language="ms", countryCode="SG",
        tags=["t2", "t3"], custom_fields=[{"name": "Plan", "value": "pro"}], status="close",
    )
    calls = seam_counters(monkeypatch)
    make_due(w.db, sid, full_sweep="not_due")
    run_due_syncs(w.db)

    a = w.contact_by_cid(910001)
    assert a.first_name == "Anna"
    assert a.last_name == "Lee", "empty on respond.io never clears SS"
    assert a.email == "anna@lee.test"
    assert a.language == "ms" and a.country_code == "SG"
    assert _tag_names(w.db, a) == {"t2", "t3"}, "tags become exactly respond.io's set"
    assert list((a.custom_fields_json or {}).values()) == ["pro"]
    assert a.status_id == status_id_for(w.db, DEFAULT_TENANT_ID, "THREAD", "CLOSED")
    assert calls == {k: 0 for k in calls}, "no entity event / realtime / webhook"
    assert w.fake.message_list_calls(910001) == 0

    w.fake.set_contact(910001, status="open")
    make_due(w.db, sid, full_sweep="not_due")
    run_due_syncs(w.db)
    assert w.contact_by_cid(910001).status_id == status_id_for(w.db, DEFAULT_TENANT_ID, "THREAD", "OPEN")


def test_sync_20_no_change_no_write(client, session_factory, monkeypatch):
    w, h, sid = _world_for_q3(client, session_factory, monkeypatch)
    a = w.contact_by_cid(910001)
    sentinel = datetime(2001, 1, 1, tzinfo=timezone.utc)

    def park_updated_at():
        w.db.query(Contact).filter(Contact.id == a.id).update({Contact.updated_at: sentinel}, synchronize_session=False)
        w.db.commit()
        w.db.expire_all()

    park_updated_at()
    make_due(w.db, sid, full_sweep="not_due")
    run_due_syncs(w.db)  # respond.io unchanged since the migration
    w.db.expire_all()
    assert aware(w.db.get(Contact, a.id).updated_at) == sentinel, "an identical contact is not rewritten"

    # Control: the same setup DOES write once respond.io changes a value.
    w.fake.set_contact(910001, firstName="Changed")
    make_due(w.db, sid, full_sweep="not_due")
    run_due_syncs(w.db)
    w.db.expire_all()
    changed = w.db.get(Contact, a.id)
    assert changed.first_name == "Changed"
    assert aware(changed.updated_at) > sentinel


def _make_agent(db, email):
    from app.models import Role, User, UserStatus
    from app.security import hash_password

    role = Role(tenant_id=DEFAULT_TENANT_ID, name=f"Agent {email}")
    db.add(role)
    db.flush()
    user = User(
        tenant_id=DEFAULT_TENANT_ID, email=email, password=hash_password("Password123!"),
        name=email, status="active",
    )
    user.roles = [role]
    db.add(user)
    db.commit()
    return user


def test_sync_20_lifecycle_and_assignee_follow_source_only_when_mapped(client, session_factory, monkeypatch):
    from modules.omnichannel.services.lifecycle_service import stages_for_workspace

    def setup(w):
        w.u1 = _make_agent(w.db, "agent1@sync.test")
        w.u2 = _make_agent(w.db, "agent2@sync.test")
        w.fake.set_contact(
            910001, lifecycle="trial",
            assignee={"id": 1, "firstName": "A", "lastName": "One", "email": "agent1@sync.test"},
        )

    holder = {}

    def prep(w):
        stages = stages_for_workspace(w.db, DEFAULT_TENANT_ID, w.ws.id)
        holder["hot"] = next(s for s in stages if s.key == "hot_lead")
        holder["cust"] = next(s for s in stages if s.key == "customer")
        setup(w)

    # build by hand so the lifecycle map can reference real stage ids
    w = new_world(session_factory, monkeypatch)
    w.fake.add_contact(910001, first="Life")
    w.fake.add_message(910001, 1)
    prep(w)
    w.run_migration(lifecycle_map=[
        {"sourceLabel": "trial", "targetStatusId": holder["hot"].id},
        {"sourceLabel": "won", "targetStatusId": holder["cust"].id},
    ])
    w.db.commit()
    h = _auth(client)
    sid = start_sync(client, w.ws.id, h)["id"]
    a = w.contact_by_cid(910001)
    assert a.lifecycle_status_id == holder["hot"].id and a.assigned_user_id == w.u1.id

    def tick():
        make_due(w.db, sid, full_sweep="not_due")
        run_due_syncs(w.db)
        return w.contact_by_cid(910001)

    w.fake.set_contact(910001, lifecycle="won", assignee={"id": 2, "email": "agent2@sync.test"})
    a = tick()
    assert a.lifecycle_status_id == holder["cust"].id, "mapped lifecycle follows respond.io"
    assert a.assigned_user_id == w.u2.id, "assignee (email-matched) follows respond.io"

    w.fake.set_contact(910001, lifecycle="never-mapped-label", assignee={"id": 3, "email": "nobody@sync.test"})
    a = tick()
    assert a.lifecycle_status_id == holder["cust"].id, "unmapped lifecycle label leaves SS alone"
    assert a.assigned_user_id == w.u2.id, "unmatched assignee leaves SS alone"

    w.fake.set_contact(910001, lifecycle=None, assignee=None)
    a = tick()
    assert a.lifecycle_status_id == holder["cust"].id and a.assigned_user_id == w.u2.id, "empty never clears"


def test_sync_21_one_off_migration_stays_fill_if_empty(session_factory, monkeypatch):
    from modules.omnichannel.services.migration_writer import MigrationWriter

    param = inspect.signature(MigrationWriter.__init__).parameters.get("contact_mode")
    assert param is not None, "the writer takes contact_mode (D7)"
    assert param.default == "fill_empty", "the one-off migration keeps plan 33 D-A6-11"

    w = new_world(session_factory, monkeypatch)
    local = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=w.ws.id, first_name="Local", last_name=None,
        phone="+6011910555", phone_digits="6011910555", priority="MEDIUM",
    )
    w.db.add(local)
    w.db.commit()
    w.fake.add_contact(910555, first="Remote", last="Name", phone="+6011910555")
    w.run_migration()
    w.db.expire_all()
    merged = w.db.get(Contact, local.id)
    assert merged.first_name == "Local", "an existing value is never overwritten by a migration"
    assert merged.last_name == "Name", "an empty value is still filled"


# ═══════════════════════════════════════════════════════════════════════════
# Slice 5 - errors, pause, stop
# ═══════════════════════════════════════════════════════════════════════════


def _outbox_count(db, to_email):
    from app.models.email_outbox import EmailOutbox

    db.expire_all()
    return db.query(EmailOutbox).filter(EmailOutbox.to_email == to_email).count()


@pytest.mark.parametrize("status_code", [401, 403])
def test_sync_40_token_rejected_pauses_emails_creator_and_resume_restarts(
    client, session_factory, monkeypatch, status_code
):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    emails_before = _outbox_count(w.db, ACTIVE_EMAIL)
    w.fake.fail_all = status_code
    make_due(w.db, sid)

    run_due_syncs(w.db)

    item = get_sync(client, h, sid)
    assert item["status"] == "paused"
    assert item["pausedReason"] == "token_rejected"
    assert all(j.status not in (JOB_PENDING, JOB_RUNNING) for j in sync_jobs(w.db)), "the tick ended"
    assert _outbox_count(w.db, ACTIVE_EMAIL) == emails_before + 1, "one email to the sync creator"

    # No retry until Resume (and no second email).
    w.fake.clear_calls()
    make_due(w.db, sid)
    run_due_syncs(w.db)
    assert w.fake.calls == []
    assert _outbox_count(w.db, ACTIVE_EMAIL) == emails_before + 1

    resumed = client.post(f"{SYNCS}/{sid}/resume", headers=h)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "active"
    assert resumed.json()["pausedReason"] is None
    assert _iso(resumed.json()["nextSyncAt"]) <= utcnow() + timedelta(seconds=5), "due now"

    w.fake.fail_all = None
    run_due_syncs(w.db)
    again = get_sync(client, h, sid)
    assert again["status"] == "active" and again["lastSyncAt"] is not None


def test_sync_41_rate_limited_tick_records_error_and_stays_active(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    emails_before = _outbox_count(w.db, ACTIVE_EMAIL)
    w.fake.rate_limited = True
    make_due(w.db, sid, full_sweep="due")

    run_due_syncs(w.db)

    item = get_sync(client, h, sid)
    assert item["status"] == "active"
    assert item["pausedReason"] is None
    assert item["lastError"], "the 429 ends the tick with lastError set"
    assert all(j.status not in (JOB_PENDING, JOB_RUNNING) for j in sync_jobs(w.db))
    assert _outbox_count(w.db, ACTIVE_EMAIL) == emails_before, "rate limits do not email anyone"

    # The next tick retries (and succeeds once respond.io relents).
    w.fake.rate_limited = False
    w.fake.add_message(910001, 2, text="after the storm")
    make_due(w.db, sid, full_sweep="due")
    run_due_syncs(w.db)
    assert any(m.body == "after the storm" for m in w.messages_of(w.contact_by_cid(910001)))


def test_sync_42_pause_resume_run_now(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    stub_enqueue(monkeypatch)

    paused = client.post(f"{SYNCS}/{sid}/pause", headers=h)
    assert paused.status_code == 200 and paused.json()["status"] == "paused"
    make_due(w.db, sid)
    run_due_syncs(w.db)
    assert sync_jobs(w.db) == [], "paused: no new ticks"

    resumed = client.post(f"{SYNCS}/{sid}/resume", headers=h)
    assert resumed.status_code == 200 and resumed.json()["status"] == "active"
    assert _iso(resumed.json()["nextSyncAt"]) <= utcnow() + timedelta(seconds=5)
    run_due_syncs(w.db)
    assert len(sync_jobs(w.db)) == 1

    # Sync now: an active, not-due sync becomes due.
    (job,) = sync_jobs(w.db)
    job.status = JOB_DONE
    w.db.commit()
    set_sync(w.db, sid, running_job_id=None)
    not_due(w.db, sid)
    run_due_syncs(w.db)
    assert len(sync_jobs(w.db)) == 1
    now_res = client.post(f"{SYNCS}/{sid}/run-now", headers=h)
    assert now_res.status_code == 200, now_res.text
    assert _iso(now_res.json()["nextSyncAt"]) <= utcnow() + timedelta(seconds=5)
    run_due_syncs(w.db)
    assert len(sync_jobs(w.db)) == 2


def test_sync_42_run_now_is_409_while_a_tick_is_running(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    running = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=SYNC_JOB_TYPE_LITERAL, status=JOB_RUNNING,
        payload_json={"syncId": sid, "kind": "poll"},
    )
    w.db.add(running)
    w.db.commit()
    set_sync(w.db, sid, running_job_id=running.id)
    assert client.post(f"{SYNCS}/{sid}/run-now", headers=h).status_code == 409
    # control: with no running tick the same call is accepted
    running.status = JOB_DONE
    w.db.commit()
    set_sync(w.db, sid, running_job_id=None)
    assert client.post(f"{SYNCS}/{sid}/run-now", headers=h).status_code == 200


def test_sync_42_running_tick_stops_at_its_next_checkpoint_when_paused(client, session_factory, monkeypatch):
    MigrationSync, _ = sync_models()
    w, h, sid = _ready(client, session_factory, monkeypatch)
    for cid in (910021, 910022, 910023):
        w.fake.add_contact(cid, first=f"Cp{cid}")
        w.fake.add_message(cid, 1, text=f"cp {cid}")

    def pause_during_first(method, path):
        if path.endswith("/contact/id:910021/message/list"):
            w.db.query(MigrationSync).filter(MigrationSync.id == sid).update(
                {"status": "paused"}, synchronize_session=False
            )

    w.fake.hooks.append(pause_during_first)
    make_due(w.db, sid, full_sweep="not_due")
    run_due_syncs(w.db)

    assert w.contact_by_phone("+6011910023") is None, "the tick stopped at its next checkpoint"
    assert sync_row(w.db, sid).status == "paused", "and the pause was not overwritten"
    assert all(j.status not in (JOB_PENDING, JOB_RUNNING) for j in sync_jobs(w.db))


def test_sync_43_stop_runs_one_final_tick_then_sets_csw_and_stops(client, session_factory, monkeypatch):
    now = utcnow()
    w, h, sid = _ready(client, session_factory, monkeypatch, contacts=(910001, 910002, 910003))
    # Fresh incoming traffic shapes the cutover: A spoke 2 h ago, B 3 days ago.
    # (Already-migrated rows are what the cutover reads.)
    a, b, c = (w.contact_by_cid(x) for x in (910001, 910002, 910003))
    w.db.query(Contact).filter(Contact.id == a.id).update(
        {Contact.last_incoming_message_at: now - timedelta(hours=2)}, synchronize_session=False)
    w.db.query(Contact).filter(Contact.id == b.id).update(
        {Contact.last_incoming_message_at: now - timedelta(days=3), Contact.csw_expires_at: now - timedelta(days=2)},
        synchronize_session=False)
    local = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=w.ws.id, first_name="Native", phone="+6011999",
        phone_digits="6011999", priority="MEDIUM", last_incoming_message_at=now - timedelta(hours=1),
    )
    w.db.add(local)
    w.db.commit()
    b_csw_before = aware(w.db.get(Contact, b.id).csw_expires_at)
    a_last_incoming = aware(w.db.get(Contact, a.id).last_incoming_message_at)

    path = webhook_path(client, h, sid)
    w.fake.add_message(910001, 4, traffic="outgoing", text="final agent reply", ts=_epoch(now - timedelta(minutes=30)))
    assert post_hint(client, path, {"contact": {"id": 910001}}).status_code == 200
    w.fake.add_contact(910004, first="LateNew")
    w.fake.add_message(910004, 1, text="late hello")
    w.fake.add_message(910003, 4, text="C news never flagged")  # a final tick has no full sweep
    w.fake.clear_calls()
    enqueued = stub_enqueue(monkeypatch)

    stopped = client.post(f"{SYNCS}/{sid}/stop", headers=h)
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] == "stopping"
    (job,) = sync_jobs(w.db)
    assert job.payload_json["kind"] == "final" and enqueued == [job.id]

    # Run that one final tick.
    run_job(w.db, job.id)

    row = sync_row(w.db, sid)
    assert row.status == "stopped" and row.stopped_at is not None
    assert w.contact_by_phone("+6011910004") is not None, "final tick polled new contacts"
    assert any(m.body == "final agent reply" for m in w.messages_of(w.contact_by_cid(910001))), "and consumed hints"
    assert len(w.messages_of(w.contact_by_cid(910003))) == 1 and w.fake.message_list_calls(910003) == 0, "no full sweep"
    assert hint_ids(w.db, sid) == []

    w.db.expire_all()
    a2, b2, c2, local2 = (w.db.get(Contact, x.id) for x in (a, b, c, local))
    assert aware(a2.csw_expires_at) == a_last_incoming + timedelta(hours=24), "last incoming + 24 h (still in the future)"
    assert aware(b2.csw_expires_at) == b_csw_before, "window already past: untouched"
    assert c2.csw_expires_at is None
    assert local2.csw_expires_at is None, "only respond.io-migrated contacts are touched"

    # A stopped sync takes no more hints and no more ticks.
    assert post_hint(client, path, {"contact": {"id": 1}}).status_code == 404
    make_due(w.db, sid)
    run_due_syncs(w.db)
    assert len(sync_jobs(w.db)) == 1


def test_sync_43_stop_end_to_end_in_eager_mode(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    res = client.post(f"{SYNCS}/{sid}/stop", headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["status"] in ("stopping", "stopped")
    final = get_sync(client, h, sid)
    assert final["status"] == "stopped" and final["stoppedAt"] is not None
    assert [j.payload_json["kind"] for j in sync_jobs(w.db)] == ["final"]


def test_sync_43_nothing_ever_stops_a_sync_automatically(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    set_sync(w.db, sid, last_sync_at=utcnow() - timedelta(days=30), last_full_sweep_at=utcnow() - timedelta(days=30))
    # The first native WhatsApp message lands in the workspace (rejected option (c)).
    a = w.contact_by_cid(910001)
    w.db.add(ConversationMessage(
        tenant_id=DEFAULT_TENANT_ID, contact_id=a.id, channel_id=w.channel.id, sender_type="CONTACT",
        message_type="TEXT", body="native", external_message_id="wamid.FIRSTNATIVE",
    ))
    w.db.commit()
    for _ in range(3):
        make_due(w.db, sid, full_sweep="due")
        run_due_syncs(w.db)
    item = get_sync(client, h, sid)
    assert item["status"] == "active" and item["stoppedAt"] is None
    assert [j.payload_json["kind"] for j in sync_jobs(w.db)].count("final") == 0


def test_sync_44_deleted_connection_pauses_with_reason_never_deletes(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    from app.models.connection import Connection

    w.db.query(Connection).filter(Connection.id == w.conn.id).delete(synchronize_session=False)
    w.db.commit()
    make_due(w.db, sid)

    run_due_syncs(w.db)

    item = get_sync(client, h, sid)  # still there
    assert item["status"] == "paused"
    assert item["pausedReason"] == "connection_missing"
    assert sync_row(w.db, sid) is not None


def test_sync_44_trashed_workspace_pauses_with_reason_never_deletes(client, session_factory, monkeypatch):
    w = new_world(session_factory, monkeypatch)
    ws2 = Workspace(tenant_id=DEFAULT_TENANT_ID, name="Sync Second WS", is_default=False)
    w.db.add(ws2)
    w.db.commit()
    add_done_job(w.db, ws2, w.conn, mode="run", channel_target=None)
    h = _auth(client)
    sid = start_sync(client, ws2.id, h)["id"]

    w.db.query(Workspace).filter(Workspace.id == ws2.id).update({"is_trashed": True}, synchronize_session=False)
    w.db.commit()
    make_due(w.db, sid)

    run_due_syncs(w.db)

    row = sync_row(w.db, sid)
    assert row is not None, "the sync row is kept"
    assert row.status == "paused" and row.paused_reason == "workspace_missing"
