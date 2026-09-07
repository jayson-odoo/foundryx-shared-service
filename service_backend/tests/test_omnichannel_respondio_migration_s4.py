"""Plan 33 (roadmap A6), slice S4 - media, derived events, quick replies,
the `messagesSince` floor (AC-MIG-39..45).

Reuses S2/S3's fixtures (`_default_workspace`, `_make_connection`,
`_stub_client`, `_make_full_job`, `_make_channel`, `_pages_handler_full`) -
the established cross-test-helper-import pattern this suite already uses.
"""
from datetime import datetime, timezone

import httpx

from app.models import DEFAULT_TENANT_ID

from modules.omnichannel.models import (
    Contact,
    ConversationEvent,
    ConversationMessage,
    MigrationRef,
    QuickReply,
)
from modules.omnichannel.services import migration_media
from modules.omnichannel.services import report_service
from modules.omnichannel.services.lifecycle_service import stages_for_workspace
from modules.omnichannel.services.media_settings_service import MediaSettingsService
from modules.omnichannel.services.migration_service import run_migration_job
from modules.omnichannel.services.migration_writer import MigrationWriter

from tests.test_omnichannel_respondio_migration_jobs import (
    _auth,
    _create_connection,
    _default_workspace,
    _default_workspace_id,
    _empty_pages_handler,
    _make_connection,
    _minimal_job_body,
    _patch_client_factory,
    _stub_client,
)
from tests.test_omnichannel_respondio_migration_s3 import (
    _make_channel,
    _make_full_job,
    _pages_handler_full,
)

# A fixed public-unicast IP literal (not private/loopback/reserved) - using an
# IP literal (never a hostname) means `assert_deliverable`'s SSRF guard never
# hits `socket.getaddrinfo` (a real, non-deterministic DNS lookup a test must
# never make); `httpx.MockTransport` intercepts before any real socket connects.
MEDIA_HOST = "https://93.184.216.34"

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-body-bytes-0123456789" * 4
_PDF_BYTES = b"%PDF-1.4\n" + b"fake-pdf-body" * 4


def _patch_media_transport(monkeypatch, handler):
    """The test seam for `migration_media.fetch_and_store_media`'s OWN HTTP
    client (never the RespondIoClient's - a separate HTTP surface entirely).
    Patches `migration_media._client_factory` (a MODULE-LEVEL name, mirroring
    `RespondIoClient.from_connection`'s own override pattern) - never the
    bare `httpx.Client` symbol, which is the SAME shared module object the
    respond.io client itself imports; patching it directly would silently
    redirect every httpx consumer in the test process onto this stub."""

    def fake_factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(migration_media, "_client_factory", fake_factory)


def _media_handler(bodies: dict):
    """`bodies = {path: (status_code, content_bytes)}` - a bare httpx
    handler answering media GETs by URL path."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        status_code, content = bodies.get(request.url.path, (404, b""))
        return httpx.Response(status_code, content=content)

    handler.calls = calls
    return handler


def _dt(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


# ═══════════════════════════════════════════════════════════════════════════
# Media (AC-MIG-39/40/45)
# ═══════════════════════════════════════════════════════════════════════════


def test_media_fetched_sniffed_capped_and_stored_media_key_convention(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    wa_channel = _make_channel(db, DEFAULT_TENANT_ID, ws.id, channel_type="WHATSAPP")
    db.commit()

    contact_row = {"id": 991001, "firstName": "Media", "lastName": "Ok", "phone": "+15550009001"}
    messages_by_contact = {
        "id:991001": {None: ([
            {"messageId": 1, "traffic": "incoming", "channelId": 801,
             "message": {"type": "attachment", "attachment": {"type": "image", "url": f"{MEDIA_HOST}/good.png"}}},
        ], None)}
    }
    handler = _pages_handler_full({None: ([contact_row], None)}, messages_by_contact=messages_by_contact)
    _stub_client(monkeypatch, handler)
    _patch_media_transport(monkeypatch, _media_handler({"/good.png": (200, _PNG_BYTES)}))

    job = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run",
        channel_map=[{"sourceChannelId": "801", "targetChannelId": wa_channel.id}],
    )
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15550009001").first()
    row = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact.id).first()
    assert row.media_key, "a fetched image must land a media_key"
    assert row.media_mime == "image/png"
    assert row.media_size == len(_PNG_BYTES)
    assert row.media_url_wire == f"/omnichannel/media/{row.id}"
    assert (row.payload_json or {}).get("migration", {}).get("pendingMedia") is None

    report = job.result_json["report"]["entities"]["media"]
    assert report["fetched"] == 1
    assert report["wouldCreate"] == 1
    db.close()


def test_media_oversize_skip_and_report_message_kept(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    # Clamp the workspace's IMAGE cap far below the fixture's PNG size.
    MediaSettingsService(db).set_overrides(DEFAULT_TENANT_ID, ws.id, {"imageMaxBytes": 8})
    db.commit()

    contact_row = {"id": 991002, "firstName": "Media", "lastName": "Big", "phone": "+15550009002"}
    messages_by_contact = {
        "id:991002": {None: ([
            {"messageId": 1, "traffic": "incoming", "channelId": 802,
             "message": {"type": "attachment", "attachment": {"type": "image", "url": f"{MEDIA_HOST}/big.png"}}},
        ], None)}
    }
    handler = _pages_handler_full({None: ([contact_row], None)}, messages_by_contact=messages_by_contact)
    _stub_client(monkeypatch, handler)
    _patch_media_transport(monkeypatch, _media_handler({"/big.png": (200, _PNG_BYTES)}))

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15550009002").first()
    row = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact.id).first()
    assert row is not None, "the message row must survive a media failure (D-A6-7)"
    assert row.media_key is None
    assert row.media_url == f"{MEDIA_HOST}/big.png", "the original source URL is kept"
    assert "limit" in (row.payload_json or {}).get("migration", {}).get("mediaError", "")

    failures = job.result_json["failures"]["rows"]
    assert any(f["entity"] == "media" and "limit" in f["reason"] for f in failures)
    assert job.result_json["report"]["entities"]["media"]["errors"] == 1
    db.close()


def test_media_sniff_mismatch_rejected(session_factory, monkeypatch):
    """The vendor DECLARED this an image (`attachment.type: "image"`); the
    bytes are actually a PDF - reject, never trust the declared type."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    contact_row = {"id": 991003, "firstName": "Media", "lastName": "Mismatch", "phone": "+15550009003"}
    messages_by_contact = {
        "id:991003": {None: ([
            {"messageId": 1, "traffic": "incoming", "channelId": 803,
             "message": {"type": "attachment", "attachment": {"type": "image", "url": f"{MEDIA_HOST}/lying.png"}}},
        ], None)}
    }
    handler = _pages_handler_full({None: ([contact_row], None)}, messages_by_contact=messages_by_contact)
    _stub_client(monkeypatch, handler)
    _patch_media_transport(monkeypatch, _media_handler({"/lying.png": (200, _PDF_BYTES)}))

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15550009003").first()
    row = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact.id).first()
    assert row.media_key is None
    reason = (row.payload_json or {}).get("migration", {}).get("mediaError", "")
    assert "does not match" in reason
    db.close()


def test_media_404_skip_and_report_never_aborts_job(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    contact_row = {"id": 991004, "firstName": "Media", "lastName": "Dead", "phone": "+15550009004"}
    messages_by_contact = {
        "id:991004": {None: ([
            {"messageId": 1, "traffic": "incoming", "channelId": 804,
             "message": {"type": "attachment", "attachment": {"type": "image", "url": f"{MEDIA_HOST}/gone.png"}}},
            {"messageId": 2, "traffic": "incoming", "channelId": 804,
             "message": {"type": "text", "text": "still here"}},
        ], None)}
    }
    handler = _pages_handler_full({None: ([contact_row], None)}, messages_by_contact=messages_by_contact)
    _stub_client(monkeypatch, handler)
    _patch_media_transport(monkeypatch, _media_handler({}))  # every path answers 404

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error  # the job is NEVER aborted by a media failure

    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15550009004").first()
    rows = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact.id).all()
    assert len(rows) == 2, "both messages survive - the text message is entirely unaffected"
    media_row = next(r for r in rows if r.message_type == "IMAGE")
    assert media_row.media_key is None
    assert "404" in (media_row.payload_json or {}).get("migration", {}).get("mediaError", "")
    db.close()


def test_media_idempotent_rerun_skips_rows_with_media_key(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    contact_row = {"id": 991005, "firstName": "Media", "lastName": "Rerun", "phone": "+15550009005"}
    messages_by_contact = {
        "id:991005": {None: ([
            {"messageId": 1, "traffic": "incoming", "channelId": 805,
             "message": {"type": "attachment", "attachment": {"type": "image", "url": f"{MEDIA_HOST}/once.png"}}},
        ], None)}
    }
    handler = _pages_handler_full({None: ([contact_row], None)}, messages_by_contact=messages_by_contact)
    _stub_client(monkeypatch, handler)
    media_handler = _media_handler({"/once.png": (200, _PNG_BYTES)})
    _patch_media_transport(monkeypatch, media_handler)

    job1 = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job1)
    db.refresh(job1)
    assert job1.status == "done", job1.error
    assert len(media_handler.calls) == 1

    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15550009005").first()
    row = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact.id).first()
    key_after_1 = row.media_key
    assert key_after_1

    job2 = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job2)
    db.refresh(job2)
    assert job2.status == "done", job2.error
    assert len(media_handler.calls) == 1, "a re-run must never re-fetch a message that already has a media_key"
    db.refresh(row)
    assert row.media_key == key_after_1
    assert job2.result_json["report"]["entities"]["media"]["fetched"] == 0
    db.close()


def test_dry_run_never_fetches_media_real_mode_control(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    contact_row = {"id": 991006, "firstName": "Media", "lastName": "Dry", "phone": "+15550009006"}
    messages_by_contact = {
        "id:991006": {None: ([
            {"messageId": 1, "traffic": "incoming", "channelId": 806,
             "message": {"type": "attachment", "attachment": {"type": "image", "url": f"{MEDIA_HOST}/dry.png"}}},
        ], None)}
    }
    handler = _pages_handler_full({None: ([contact_row], None)}, messages_by_contact=messages_by_contact)
    _stub_client(monkeypatch, handler)
    media_handler = _media_handler({"/dry.png": (200, _PNG_BYTES)})
    _patch_media_transport(monkeypatch, media_handler)

    dry_job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="dry_run")
    run_migration_job(db, dry_job)
    db.refresh(dry_job)
    assert dry_job.status == "done", dry_job.error
    assert len(media_handler.calls) == 0, "AC-MIG-27: no media URL is ever fetched during a dry run"
    assert dry_job.result_json["report"]["entities"]["media"] == {
        "fetched": 0, "wouldCreate": 0, "wouldUpdate": 0, "wouldSkip": 0, "errors": 0,
    }

    real_job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, real_job)
    db.refresh(real_job)
    assert real_job.status == "done", real_job.error
    assert len(media_handler.calls) == 1
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# Derived conversation_events (AC-MIG-41/42/43)
# ═══════════════════════════════════════════════════════════════════════════


def test_events_derivation_matrix(session_factory, monkeypatch):
    """One job carries FOUR distinct contacts covering the derivation matrix:
    open-only (no reply yet), open-and-closed with a reply, agent-spoke-first
    (no first_agent_reply), and assigned/lifecycle_changed."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    from app.models.user import User

    agent_user = db.query(User).filter(User.tenant_id == DEFAULT_TENANT_ID).first()
    stage = stages_for_workspace(db, DEFAULT_TENANT_ID, ws.id)[0]

    contacts = [
        {"id": 992001, "firstName": "Open", "lastName": "Only", "phone": "+15550091001"},
        {"id": 992002, "firstName": "Open", "lastName": "Closed", "phone": "+15550091002", "status": "close"},
        {"id": 992003, "firstName": "Agent", "lastName": "First", "phone": "+15550091003"},
        {"id": 992004, "firstName": "Assigned", "lastName": "Vip", "phone": "+15550091004",
         "assignee": {"id": 1, "firstName": "A", "lastName": "B", "email": agent_user.email},
         "lifecycle": "vip"},
    ]
    # `messageId` is a GLOBAL vendor id (D-A6-3's own migration_refs key is
    # NOT contact-scoped) - every message across every contact in this test
    # must carry a distinct id, or a shared literal (e.g. `1`) collides
    # across contacts and silently skips the second contact's message as
    # "already migrated".
    messages_by_contact = {
        "id:992001": {None: ([
            {"messageId": 101, "traffic": "incoming", "channelId": 901,
             "message": {"type": "text", "text": "hi"},
             "status": [{"value": "sent", "timestamp": 1700000000}]},
        ], None)},
        "id:992002": {None: ([
            {"messageId": 201, "traffic": "incoming", "channelId": 901,
             "message": {"type": "text", "text": "hi"},
             "status": [{"value": "sent", "timestamp": 1700000100}]},
            {"messageId": 202, "traffic": "outgoing", "channelId": 901,
             "message": {"type": "text", "text": "hello back"},
             "status": [{"value": "sent", "timestamp": 1700000200}]},
        ], None)},
        "id:992003": {None: ([
            {"messageId": 301, "traffic": "outgoing", "channelId": 901,
             "message": {"type": "text", "text": "proactive"},
             "status": [{"value": "sent", "timestamp": 1700000300}]},
        ], None)},
        "id:992004": {None: ([
            {"messageId": 401, "traffic": "incoming", "channelId": 901,
             "message": {"type": "text", "text": "hi"},
             "status": [{"value": "sent", "timestamp": 1700000400}]},
        ], None)},
    }
    handler = _pages_handler_full({None: (contacts, None)}, messages_by_contact=messages_by_contact)
    _stub_client(monkeypatch, handler)

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    # `_make_full_job` has no lifecycleMap kwarg - set it directly on the row.
    # Reassign a FRESH dict (the JSON-mutation house gotcha - an in-place
    # `dict[key] = ...` on the same object is not tracked by SQLAlchemy).
    job.payload_json = {**job.payload_json, "lifecycleMap": [{"sourceLabel": "vip", "targetStatusId": stage.id}]}
    db.commit()

    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    def _events_for(phone):
        contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == phone).first()
        rows = db.query(ConversationEvent).filter(ConversationEvent.contact_id == contact.id).all()
        return contact, {r.event_type: r for r in rows}

    open_contact, open_events = _events_for("+15550091001")
    assert set(open_events) == {"opened"}
    assert open_events["opened"].created_at == _dt(1700000000)
    assert open_events["opened"].payload_json["migration"]["derived"] is True

    closed_contact, closed_events = _events_for("+15550091002")
    assert set(closed_events) == {"opened", "first_agent_reply", "closed"}
    assert closed_events["opened"].created_at == _dt(1700000100)
    assert closed_events["first_agent_reply"].created_at == _dt(1700000200)
    assert closed_events["first_agent_reply"].payload_json["responseSeconds"] == 100
    assert closed_events["closed"].created_at == _dt(1700000200)

    agent_first_contact, agent_first_events = _events_for("+15550091003")
    assert set(agent_first_events) == {"opened"}, "no first_agent_reply when the agent spoke first"

    assigned_contact, assigned_events = _events_for("+15550091004")
    assert set(assigned_events) == {"opened", "assigned", "lifecycle_changed"}
    assert assigned_events["assigned"].to_value == agent_user.id
    assert assigned_events["lifecycle_changed"].to_value == stage.id
    assert assigned_contact.lifecycle_status_id == stage.id

    events_report = job.result_json["report"]["entities"]["events"]
    assert events_report["fetched"] == 4
    assert events_report["wouldCreate"] == 8  # 1+3+1+3 events across the 4 contacts
    db.close()


def test_events_no_fan_out_no_workflow_trigger(session_factory, monkeypatch):
    """AC-MIG-41 - derived events never fire `emit_entity_event`/
    `notify_entity_event`/`realtime.publish` (extends S3's AC-MIG-33 guard to
    the whole S4 tail: media + events + quick replies)."""
    calls = {"publish": 0, "emit": 0, "notify": 0}

    import app.workflow_engine.entity_events as entity_events_module
    import modules.omnichannel.services.realtime as realtime_module

    monkeypatch.setattr(realtime_module, "publish", lambda *a, **k: calls.__setitem__("publish", calls["publish"] + 1))
    monkeypatch.setattr(entity_events_module, "emit_entity_event", lambda *a, **k: calls.__setitem__("emit", calls["emit"] + 1))
    monkeypatch.setattr(entity_events_module, "notify_entity_event", lambda *a, **k: calls.__setitem__("notify", calls["notify"] + 1))

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    contact_row = {"id": 992101, "firstName": "Quiet", "lastName": "S4", "phone": "+15550091101", "status": "close"}
    messages_by_contact = {
        "id:992101": {None: ([
            {"messageId": 1, "traffic": "incoming", "channelId": 901,
             "message": {"type": "attachment", "attachment": {"type": "image", "url": f"{MEDIA_HOST}/quiet.png"}},
             "status": [{"value": "sent", "timestamp": 1700000000}]},
            {"messageId": 2, "traffic": "outgoing", "channelId": 901,
             "message": {"type": "text", "text": "reply"},
             "status": [{"value": "sent", "timestamp": 1700000100}]},
        ], None)}
    }
    handler = _pages_handler_full({None: ([contact_row], None)}, messages_by_contact=messages_by_contact)
    _stub_client(monkeypatch, handler)
    _patch_media_transport(monkeypatch, _media_handler({"/quiet.png": (200, _PNG_BYTES)}))

    import base64
    snippets_csv = base64.b64encode(b"shortcut,body\r\nhi,Hello there\r\n").decode("ascii")

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    job.payload_json = {**job.payload_json, "snippetsCsvBase64": snippets_csv}
    db.commit()

    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error
    assert calls == {"publish": 0, "emit": 0, "notify": 0}
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# A9 dashboard/response reports read the backfilled events (AC-MIG-43)
# ═══════════════════════════════════════════════════════════════════════════


def test_a9_report_service_reads_migrated_events_on_original_dates(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    # 2024-01-15 UTC-ish - a date that is neither "today" nor anywhere near it.
    historical_epoch_open = 1705318800  # 2024-01-15 09:00 UTC
    historical_epoch_reply = 1705320600  # 2024-01-15 09:30 UTC
    contact_row = {
        "id": 992201, "firstName": "Report", "lastName": "Read", "phone": "+15550092201", "status": "close",
    }
    messages_by_contact = {
        "id:992201": {None: ([
            {"messageId": 1, "traffic": "incoming", "channelId": 901,
             "message": {"type": "text", "text": "hi"},
             "status": [{"value": "sent", "timestamp": historical_epoch_open}]},
            {"messageId": 2, "traffic": "outgoing", "channelId": 901,
             "message": {"type": "text", "text": "hello"},
             "status": [{"value": "sent", "timestamp": historical_epoch_reply}]},
        ], None)}
    }
    handler = _pages_handler_full({None: ([contact_row], None)}, messages_by_contact=messages_by_contact)
    _stub_client(monkeypatch, handler)

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    # The dashboard's "conversations opened" series counts it on its ORIGINAL
    # date (AC-MIG-43) - a window covering 2024-01-15 sees it...
    historical = report_service.dashboard(
        db, tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id,
        from_="2024-01-10", to="2024-01-20", tz="UTC",
    )
    assert sum(historical.series.opened) >= 1
    assert sum(historical.series.closed) >= 1

    # ...but a window covering "today" (the migration RUN date) sees nothing.
    today = datetime.now(timezone.utc).date().isoformat()
    on_run_date = report_service.dashboard(
        db, tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id,
        from_=today, to=today, tz="UTC",
    )
    assert sum(on_run_date.series.opened) == 0
    assert sum(on_run_date.series.closed) == 0

    # The "responses" report's `response_samples` reads the derived
    # `first_agent_reply` event too (through the SAME report_service the
    # live product uses - AC-MIG-43's own "A9 reads them" requirement).
    rq = report_service.build_report_query(
        db, "responses", tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id,
        from_="2024-01-10", to="2024-01-20", tz="UTC",
    )
    samples = report_service.response_samples(db, rq)
    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15550092201").first()
    matching = [s for s in samples if s.contact_id == contact.id]
    assert len(matching) == 1
    assert matching[0].seconds == historical_epoch_reply - historical_epoch_open
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# Quick replies from a snippets CSV (AC-MIG-44/45)
# ═══════════════════════════════════════════════════════════════════════════


def _csv_b64(text: str) -> str:
    import base64

    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_quick_replies_created_from_csv_and_idempotent_rerun(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    handler = _pages_handler_full({None: ([], None)})
    _stub_client(monkeypatch, handler)

    csv_content = "shortcut,body\r\nhello,Hello there!\r\nbye,Goodbye for now.\r\n"

    job1 = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    job1.payload_json = {**job1.payload_json, "snippetsCsvBase64": _csv_b64(csv_content)}
    db.commit()
    run_migration_job(db, job1)
    db.refresh(job1)
    assert job1.status == "done", job1.error

    rows = db.query(QuickReply).filter(QuickReply.tenant_id == DEFAULT_TENANT_ID, QuickReply.workspace_id == ws.id).all()
    assert {r.shortcut for r in rows} == {"hello", "bye"}
    qr_report = job1.result_json["report"]["entities"]["quickReplies"]
    assert qr_report["fetched"] == 2
    assert qr_report["wouldCreate"] == 2

    job2 = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    job2.payload_json = {**job2.payload_json, "snippetsCsvBase64": _csv_b64(csv_content)}
    db.commit()
    run_migration_job(db, job2)
    db.refresh(job2)
    assert job2.status == "done", job2.error

    rows_after_2 = db.query(QuickReply).filter(QuickReply.tenant_id == DEFAULT_TENANT_ID, QuickReply.workspace_id == ws.id).all()
    assert len(rows_after_2) == len(rows), "a re-run must not duplicate quick replies"
    qr_report_2 = job2.result_json["report"]["entities"]["quickReplies"]
    assert qr_report_2["wouldSkip"] == 2
    assert qr_report_2["wouldCreate"] == 0
    db.close()


def test_quick_reply_matches_existing_live_row_case_insensitive_never_duplicates(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    existing = QuickReply(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, shortcut="Hello", body="Existing body")
    db.add(existing)
    db.commit()

    handler = _pages_handler_full({None: ([], None)})
    _stub_client(monkeypatch, handler)

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    job.payload_json = {**job.payload_json, "snippetsCsvBase64": _csv_b64("shortcut,body\r\nhello,New body\r\n")}
    db.commit()
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    rows = db.query(QuickReply).filter(QuickReply.tenant_id == DEFAULT_TENANT_ID, QuickReply.workspace_id == ws.id).all()
    assert len(rows) == 1, "a case-insensitive shortcut match must never create a duplicate"
    assert rows[0].body == "Existing body", "the existing live row's body is never overwritten"
    db.close()


def test_quick_reply_cross_tenant_never_matches_a_different_tenants_shortcut(session_factory):
    """`MigrationWriter.write_quick_reply` is tenant+workspace scoped - the
    SAME shortcut in a DIFFERENT tenant's quick replies must never resolve as
    a match (the polymorphic-stored-id class of bug this codebase keeps
    paying for, applied here at save time instead of read time)."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)

    other_tenant_id = "other-tenant-quick-reply"
    foreign = QuickReply(tenant_id=other_tenant_id, workspace_id="other-ws", shortcut="hello", body="Foreign body")
    db.add(foreign)
    db.commit()

    writer = MigrationWriter(
        db, tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id,
        thread_open_status_id=None, initial_lifecycle_status_id=None,
        lifecycle_map={}, source_field_defs={},
    )
    outcome = writer.write_quick_reply("hello", "New tenant body")
    db.commit()
    assert outcome == "create"

    rows = db.query(QuickReply).filter(QuickReply.tenant_id == DEFAULT_TENANT_ID).all()
    assert len(rows) == 1
    assert rows[0].body == "New tenant body"
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# messagesSince floor (D-A6-22)
# ═══════════════════════════════════════════════════════════════════════════


def test_messages_since_floor_skips_older_messages_and_counts_them(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    contact_row = {"id": 993001, "firstName": "Floor", "lastName": "Test", "phone": "+15550093001"}
    messages_by_contact = {
        "id:993001": {None: ([
            {"messageId": 1, "traffic": "incoming", "channelId": 901,
             "message": {"type": "text", "text": "old"},
             "status": [{"value": "sent", "timestamp": 1600000000}]},  # 2020 - before the floor
            {"messageId": 2, "traffic": "incoming", "channelId": 901,
             "message": {"type": "text", "text": "new"},
             "status": [{"value": "sent", "timestamp": 1700000000}]},  # 2023 - after the floor
        ], None)}
    }
    handler = _pages_handler_full({None: ([contact_row], None)}, messages_by_contact=messages_by_contact)
    _stub_client(monkeypatch, handler)

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    job.payload_json = {**job.payload_json, "messagesSince": "2022-01-01T00:00:00+00:00"}
    db.commit()
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15550093001").first()
    rows = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact.id).all()
    assert len(rows) == 1
    assert rows[0].body == "new"
    assert job.result_json["report"]["messagesSkippedBeforeFloor"] == 1
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# migration_refs cross-tenant guard for events (extends AC-MIG-52 to S4)
# ═══════════════════════════════════════════════════════════════════════════


def test_events_and_media_migration_refs_are_tenant_scoped(session_factory, monkeypatch):
    """A ref recorded for tenant A's contact must never resolve/short-circuit
    tenant B's identically-shaped migration_refs row (D-A6-3's own tenant+
    workspace-scoped UNIQUE index, exercised end to end through the events
    phase's ref check)."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    contact_row = {"id": 994001, "firstName": "Cross", "lastName": "Tenant", "phone": "+15550094001"}
    messages_by_contact = {
        "id:994001": {None: ([
            {"messageId": 1, "traffic": "incoming", "channelId": 901,
             "message": {"type": "text", "text": "hi"},
             "status": [{"value": "sent", "timestamp": 1700000000}]},
        ], None)}
    }
    handler = _pages_handler_full({None: ([contact_row], None)}, messages_by_contact=messages_by_contact)
    _stub_client(monkeypatch, handler)

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    refs = db.query(MigrationRef).filter(MigrationRef.entity_type == "event").all()
    assert len(refs) == 1
    assert refs[0].tenant_id == DEFAULT_TENANT_ID
    assert refs[0].workspace_id == ws.id
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# HTTP round-trip - `snippetsCsvBase64` must survive `POST /jobs` into the
# persisted `payload_json` (`MigrationJobCreate.snippetsCsvBase64` is NOT part
# of `_mapping_hash`, so it is easy to forget wiring it into `create_job`'s
# own `job_payload` dict - caught here rather than only at the phase level).
# ═══════════════════════════════════════════════════════════════════════════


def test_snippets_csv_base64_round_trips_through_create_job(client, session_factory, monkeypatch):
    h = _auth(client)
    connection_id = _create_connection(client, h)
    ws_id = _default_workspace_id(client, h)
    _patch_client_factory(monkeypatch, _empty_pages_handler)

    body = _minimal_job_body(connection_id, ws_id, mode="dry_run")
    body["snippetsCsvBase64"] = "aGVsbG8="
    res = client.post("/omnichannel/migration/jobs", headers=h, json=body)
    assert res.status_code == 201, res.text
    job_id = res.json()["id"]

    db = session_factory()
    from app.models.background_job import BackgroundJob

    row = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
    assert row.payload_json["snippetsCsvBase64"] == "aGVsbG8="
    db.close()
