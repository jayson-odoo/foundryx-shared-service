"""Plan 33 (roadmap A6) - Opus security review round 1 fixes.

Covers the blockers (B1 media-redirect SSRF, B2 client-supplied storage
keys, B3 non-terminating vendor pagination) and the should-fix findings
(S1 dry-run storage write, S2 epoch bounds, S4 userMap/teamMap validation,
S5 teamMap contact assignment, S11 per-contact message cap, S13 test cost)
from the review, PLUS the tester's own report Defect 1 (connectionId=null
500) and Defect 2 (CSV-mode Lifecycle column silently ignored). Reuses the
established cross-test-helper-import pattern (`_auth`/`_default_workspace`/
`_make_connection`/`_stub_client`/`_make_full_job`/`_pages_handler_full`
etc.) rather than duplicating fixtures.
"""
from datetime import datetime, timedelta, timezone

import httpx

from app.models import DEFAULT_TENANT_ID
from app.models.team import Team
from app.services.team_capabilities import ensure_team_capabilities

from modules.omnichannel.models import Contact
from modules.omnichannel.services import migration_media
from modules.omnichannel.services.lifecycle_service import stages_for_workspace
from modules.omnichannel.services.migration_service import MIGRATION_JOB_TYPE, run_migration_job
from modules.omnichannel.services.migration_writer import _EPOCH_FLOOR, epoch_to_dt, resolve_message_timestamps
from modules.omnichannel.respondio.client import RespondIoClient
from modules.omnichannel.respondio.shapes import MessageItem

from tests.test_omnichannel_respondio_migration_jobs import (
    _auth,
    _create_connection,
    _default_workspace,
    _default_workspace_id,
    _make_connection,
    _minimal_job_body,
)
from tests.test_omnichannel_respondio_migration_s3 import _make_full_job, _pages_handler_full
from tests.test_omnichannel_respondio_migration_s5 import _csv_bytes, _make_csv_job, _upload_key


def _stub_client(monkeypatch, handler):
    def fake_from_connection(config, credentials, *, client=None, on_milestone=None):
        return RespondIoClient(
            base_url="https://api.respond.io/v2", api_token=str(credentials.get("apiToken", "")),
            requests_per_second=1000, client=httpx.Client(transport=httpx.MockTransport(handler)),
            on_milestone=on_milestone, sleep=lambda s: None,
        )

    monkeypatch.setattr(RespondIoClient, "from_connection", staticmethod(fake_from_connection))


# ═══════════════════════════════════════════════════════════════════════════
# B1 - migration_media redirect SSRF (follow_redirects=False + guarded hops)
# ═══════════════════════════════════════════════════════════════════════════


def test_media_redirect_to_a_private_ip_is_blocked_never_requested(session_factory, monkeypatch):
    """A stub transport answering the first hop with `302 -> https://
    169.254.169.254/` must produce `ok=False` and the malicious host must
    NEVER actually be requested (proves the guard runs BEFORE the follow,
    not just that the eventual read fails)."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "93.184.216.34":
            return httpx.Response(302, headers={"location": "https://169.254.169.254/latest/meta-data/"})
        return httpx.Response(200, content=b"should never be reached")  # pragma: no cover

    def fake_factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    monkeypatch.setattr(migration_media, "_client_factory", fake_factory)

    db = session_factory()
    result = migration_media.fetch_and_store_media(
        db, tenant_id=DEFAULT_TENANT_ID, workspace_id="ws-b1", message_id="msg-b1",
        url="https://93.184.216.34/redirect-me", filename=None, declared_kind="IMAGE",
    )
    assert result.ok is False
    assert result.key is None
    # Exactly ONE request was made (the first hop) - the malicious redirect
    # target was validated and rejected BEFORE any second request.
    assert calls == ["https://93.184.216.34/redirect-me"]
    db.close()


def test_media_client_factory_builds_with_follow_redirects_false():
    client = migration_media._default_client_factory()
    assert client.follow_redirects is False
    client.close()


def test_media_redirect_hop_ceiling_stops_an_infinite_redirect_chain(session_factory, monkeypatch):
    """A vendor endlessly redirecting to itself (each hop individually a
    SAFE public address) must still terminate - the `MAX_REDIRECT_HOPS`
    ceiling, not just the SSRF guard."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://93.184.216.34/next"})

    def fake_factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    monkeypatch.setattr(migration_media, "_client_factory", fake_factory)

    db = session_factory()
    result = migration_media.fetch_and_store_media(
        db, tenant_id=DEFAULT_TENANT_ID, workspace_id="ws-b1", message_id="msg-b1b",
        url="https://93.184.216.34/start", filename=None, declared_kind="IMAGE",
    )
    assert result.ok is False
    assert len(calls) == migration_media.MAX_REDIRECT_HOPS
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# S12 - vendor media URL query strings never leak into a failure message
# ═══════════════════════════════════════════════════════════════════════════


def test_media_fetch_failure_strips_the_query_string_from_the_url(session_factory, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    def fake_factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    monkeypatch.setattr(migration_media, "_client_factory", fake_factory)

    db = session_factory()
    signed_url = "https://93.184.216.34/media/secret-blob?token=super-secret-signed-token&exp=999"
    result = migration_media.fetch_and_store_media(
        db, tenant_id=DEFAULT_TENANT_ID, workspace_id="ws-s12", message_id="msg-s12",
        url=signed_url, filename=None, declared_kind="IMAGE",
    )
    assert result.ok is False
    assert "super-secret-signed-token" not in (result.reason or "")
    assert "?" not in (result.reason or "")
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# B3 - respond.io pagination cursor-walk termination guards
# ═══════════════════════════════════════════════════════════════════════════


def test_pagination_stops_when_vendor_returns_the_same_cursor_twice():
    def handler(request: httpx.Request) -> httpx.Response:
        # ALWAYS answers with one item and the SAME "next" cursor - a
        # vendor stuck on the same page (an observed real-world failure
        # mode this API's own contract does not rule out).
        return httpx.Response(200, json={"items": [{"id": 1}], "pagination": {"next": "stuck-cursor"}})

    client = RespondIoClient(
        base_url="https://api.respond.io/v2", api_token="tok",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda s: None,
    )
    pages = list(client.list_contacts_pages(timezone="UTC", limit=10))
    # Terminates after detecting the repeat - never loops forever.
    assert len(pages) == 2
    assert pages[-1][1] is None


def test_pagination_stops_on_an_empty_page_that_still_carries_a_cursor():
    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursorId")
        if cursor is None:
            return httpx.Response(200, json={"items": [{"id": 1}], "pagination": {"next": "c2"}})
        # Nothing left, but the vendor never says so via an absent `next`.
        return httpx.Response(200, json={"items": [], "pagination": {"next": "c2"}})

    client = RespondIoClient(
        base_url="https://api.respond.io/v2", api_token="tok",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda s: None,
    )
    pages = list(client.list_contacts_pages(timezone="UTC", limit=10))
    assert len(pages) == 2
    assert pages[-1] == ([], None)


def test_pagination_max_pages_ceiling_stops_a_genuinely_unbounded_walk(monkeypatch):
    from modules.omnichannel.respondio import client as respondio_client_module

    monkeypatch.setattr(respondio_client_module, "MAX_PAGES", 3)
    seen_cursors = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursorId") or "0"
        seen_cursors.append(cursor)
        # A monotonically-incrementing cursor - never repeats, never empty -
        # only the MAX_PAGES ceiling can stop this.
        return httpx.Response(200, json={"items": [{"id": 1}], "pagination": {"next": str(int(cursor) + 1)}})

    client = RespondIoClient(
        base_url="https://api.respond.io/v2", api_token="tok",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda s: None,
    )
    pages = list(client.list_contacts_pages(timezone="UTC", limit=10))
    assert len(pages) == 3
    assert pages[-1][1] is None
    assert len(seen_cursors) == 3


# ═══════════════════════════════════════════════════════════════════════════
# B2 - upload receipts (cross-tenant 404, retired free-string field 422)
# ═══════════════════════════════════════════════════════════════════════════


def test_create_job_foreign_tenant_upload_id_404(client, session_factory):
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    h = _auth(client)
    content = _csv_bytes(["First Name", "Phone"], [["Foreign", "+15550001234"]])
    up = client.post(
        "/omnichannel/migration/uploads", headers=h,
        files={"file": ("contacts.csv", content, "text/csv")}, data={"kind": "contacts"},
    )
    assert up.status_code == 201, up.text
    upload_id = up.json()["id"]

    db = session_factory()
    tenant = TenantService(db).provision(
        name="Other Tenant Review1", slug="other-rio-review1",
        admin_email="admin-other-rio-review1@example.com", admin_password="Password123!", admin_name="Admin",
    )
    db.flush()
    AppStoreService(db).install(tenant.id, "omnichannel")
    db.commit()
    db.close()

    h2 = _auth(
        client, email="admin-other-rio-review1@example.com", password="Password123!",
        tenant_slug="other-rio-review1",
    )
    ws2_id = _default_workspace_id(client, h2)
    res = client.post(
        "/omnichannel/migration/jobs", headers=h2,
        json={
            "workspaceId": ws2_id, "mode": "dry_run", "source": "csv",
            "channelMap": [], "userMap": [], "teamMap": [], "lifecycleMap": [],
            "contactsUploadId": upload_id,
        },
    )
    assert res.status_code == 404, res.text


def test_create_job_unknown_upload_id_404(client):
    h = _auth(client)
    ws_id = _default_workspace_id(client, h)
    res = client.post(
        "/omnichannel/migration/jobs", headers=h,
        json={
            "workspaceId": ws_id, "mode": "dry_run", "source": "csv",
            "channelMap": [], "userMap": [], "teamMap": [], "lifecycleMap": [],
            "contactsUploadId": "not-a-real-upload-id",
        },
    )
    assert res.status_code == 404, res.text


def test_create_job_rejects_the_retired_free_string_key_field_422(client):
    """`contactsCsvKey` (the RETIRED free-string field, pre-review-round-1)
    must 422 `extra_forbidden`, never silently pass through and be
    ignored."""
    h = _auth(client)
    connection_id = _create_connection(client, h)
    ws_id = _default_workspace_id(client, h)
    body = _minimal_job_body(connection_id, ws_id)
    body["contactsCsvKey"] = "../../etc/hosts"
    res = client.post("/omnichannel/migration/jobs", headers=h, json=body)
    assert res.status_code == 422, res.text
    detail = res.json()["detail"]
    assert any(err.get("type") == "extra_forbidden" for err in detail)


def test_upload_receipt_wrong_kind_is_unresolvable(client):
    """A snippets receipt id supplied as `contactsUploadId` (or vice versa)
    reads back as the SAME 404 as a foreign/unknown id."""
    h = _auth(client)
    ws_id = _default_workspace_id(client, h)
    up = client.post(
        "/omnichannel/migration/uploads", headers=h,
        files={"file": ("snippets.csv", b"shortcut,body\r\nhi,Hello\r\n", "text/csv")},
        data={"kind": "snippets"},
    )
    assert up.status_code == 201, up.text
    snippets_upload_id = up.json()["id"]

    res = client.post(
        "/omnichannel/migration/jobs", headers=h,
        json={
            "workspaceId": ws_id, "mode": "dry_run", "source": "csv",
            "channelMap": [], "userMap": [], "teamMap": [], "lifecycleMap": [],
            "contactsUploadId": snippets_upload_id,
        },
    )
    assert res.status_code == 404, res.text


# ═══════════════════════════════════════════════════════════════════════════
# S1 - a dry run writes zero storage blobs (AC-MIG-27)
# ═══════════════════════════════════════════════════════════════════════════


def test_dry_run_writes_no_failures_storage_blob(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    # A malformed contact row forces at least one failure - proving the
    # `fileKey is None` assertion below isn't vacuous (a run with zero
    # failures would trivially have nothing to write either way).
    bad_row = {"id": "not-an-int", "firstName": "Bad"}
    handler = _pages_handler_full({None: ([bad_row], None)})
    _stub_client(monkeypatch, handler)

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="dry_run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error
    failures_meta = job.result_json["failures"]
    assert failures_meta["rowCount"] >= 1
    assert failures_meta["fileKey"] is None
    db.close()


def test_dry_run_failures_csv_download_falls_back_to_the_inline_sample(client, session_factory, monkeypatch):
    """The download route must still serve something useful for a dry run
    (no `fileKey` at all) rather than an empty file."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    bad_row = {"id": "not-an-int", "firstName": "Bad"}
    handler = _pages_handler_full({None: ([bad_row], None)})
    _stub_client(monkeypatch, handler)

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="dry_run")
    run_migration_job(db, job)
    db.refresh(job)
    job_id = job.id
    db.close()

    h = _auth(client)
    res = client.get(f"/omnichannel/migration/jobs/{job_id}/failures.csv", headers=h)
    assert res.status_code == 200
    lines = [ln for ln in res.text.strip().splitlines() if ln]
    assert len(lines) >= 2  # header + at least one failure row


# ═══════════════════════════════════════════════════════════════════════════
# S2 - epoch bounds (ms detection, garbage, future clamp, per-contact isolation)
# ═══════════════════════════════════════════════════════════════════════════


def test_epoch_to_dt_detects_millisecond_magnitude():
    seconds_epoch = 1700000000
    ms_epoch = seconds_epoch * 1000 + 123
    dt = epoch_to_dt(ms_epoch)
    assert dt == datetime.fromtimestamp(seconds_epoch, tz=timezone.utc).replace(microsecond=123000)


def test_epoch_to_dt_clamps_garbage_values_to_the_floor():
    assert epoch_to_dt("not-a-number") == _EPOCH_FLOOR
    assert epoch_to_dt(None) == _EPOCH_FLOOR
    assert epoch_to_dt(object()) == _EPOCH_FLOOR
    assert epoch_to_dt(-999999999999) == _EPOCH_FLOOR  # far pre-1970, floored


def test_epoch_to_dt_clamps_a_future_date_to_now_plus_24h():
    far_future_seconds = 99_999_999_999  # ~year 5138 - still SECONDS magnitude (below the ms threshold)
    dt = epoch_to_dt(far_future_seconds)
    ceiling = datetime.now(timezone.utc) + timedelta(hours=24)
    assert dt <= ceiling
    assert (ceiling - dt).total_seconds() < 10


def test_epoch_to_dt_never_raises_on_overflow_magnitude():
    # A value so large `datetime.fromtimestamp` itself raises OverflowError/
    # OSError - must still clamp, never propagate.
    dt = epoch_to_dt(10**30)
    ceiling = datetime.now(timezone.utc) + timedelta(hours=24)
    assert dt <= ceiling


def test_resolve_message_timestamps_uses_epoch_to_dt_for_the_explicit_branch():
    base = 1700000000
    item = MessageItem(
        messageId=1, traffic="incoming", message={"type": "text", "text": "x"},
        status=[{"value": "sent", "timestamp": base * 1000}],  # a MILLISECOND vendor timestamp
    )
    (dt, inferred), = resolve_message_timestamps([item], datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert inferred is False
    assert dt == datetime.fromtimestamp(base, tz=timezone.utc)


def test_one_contact_with_broken_timestamp_resolution_does_not_fail_the_whole_run(session_factory, monkeypatch):
    """Review round 1, finding S2 - `resolve_message_timestamps` is wrapped
    in the per-contact failure handler; a raise for ONE contact must be
    reported and skipped, never propagate out of the whole job."""
    import modules.omnichannel.services.migration_service as migration_service_module

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    contact_bad = {"id": 996101, "firstName": "Bad", "lastName": "Timestamps", "phone": "+15550096101"}
    contact_good = {"id": 996102, "firstName": "Good", "lastName": "Timestamps", "phone": "+15550096102"}
    messages_by_contact = {
        "id:996101": {None: ([
            {"messageId": 1, "traffic": "incoming", "channelId": 901,
             "message": {"type": "text", "text": "bad"}},
        ], None)},
        "id:996102": {None: ([
            {"messageId": 2, "traffic": "incoming", "channelId": 901,
             "message": {"type": "text", "text": "good"}},
        ], None)},
    }
    handler = _pages_handler_full(
        {None: ([contact_bad, contact_good], None)}, messages_by_contact=messages_by_contact,
    )
    _stub_client(monkeypatch, handler)

    original = migration_service_module.resolve_message_timestamps

    def flaky(items, fallback):
        if any(i.messageId == 1 for i in items):
            raise ValueError("simulated corrupt vendor payload")
        return original(items, fallback)

    monkeypatch.setattr(migration_service_module, "resolve_message_timestamps", flaky)

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    good_contact = db.query(Contact).filter(
        Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15550096102"
    ).first()
    assert good_contact is not None
    from modules.omnichannel.models import ConversationMessage

    good_msg = db.query(ConversationMessage).filter(ConversationMessage.contact_id == good_contact.id).first()
    assert good_msg is not None, "the SECOND contact's message must still migrate despite the first one's failure"

    failures = (job.result_json or {}).get("failures", {})
    reasons = " ".join(r.get("reason", "") for r in failures.get("sample", []))
    assert "simulated corrupt vendor payload" in reasons
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# S4 - userMap/teamMap tenant-scoped at CREATE + reported (not silent) at USE
# ═══════════════════════════════════════════════════════════════════════════


def test_create_job_invalid_user_map_target_422(client):
    h = _auth(client)
    connection_id = _create_connection(client, h)
    ws_id = _default_workspace_id(client, h)
    body = _minimal_job_body(connection_id, ws_id)
    body["userMap"] = [{"sourceUserId": "rio-usr-1", "targetUserId": "not-a-real-user"}]
    res = client.post("/omnichannel/migration/jobs", headers=h, json=body)
    assert res.status_code == 422, res.text
    assert "userMap.0" in res.json()["detail"]["fieldErrors"]


def test_create_job_invalid_team_map_target_422(client):
    h = _auth(client)
    connection_id = _create_connection(client, h)
    ws_id = _default_workspace_id(client, h)
    body = _minimal_job_body(connection_id, ws_id)
    body["teamMap"] = [{"sourceTeamId": "rio-team-1", "targetTeamId": "not-a-real-team"}]
    res = client.post("/omnichannel/migration/jobs", headers=h, json=body)
    assert res.status_code == 422, res.text
    assert "teamMap.0" in res.json()["detail"]["fieldErrors"]


def test_user_map_and_team_map_drop_at_use_time_is_reported_not_silent(session_factory, monkeypatch):
    """A mapping entry deleted BETWEEN create and run (simulated here by a
    hand-built job payload the create-time validator never saw) must be
    reported as a report blocker, never silently discarded."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    handler = _pages_handler_full({None: ([], None)})
    _stub_client(monkeypatch, handler)

    job = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run",
        user_map=[{"sourceUserId": "rio-usr-1", "targetUserId": "deleted-user-id"}],
        team_map=[{"sourceTeamId": "rio-team-1", "targetTeamId": "deleted-team-id"}],
    )
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error
    blockers = " ".join(job.result_json["report"]["blockers"])
    assert "agent mapping" in blockers
    assert "team mapping" in blockers
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# S5 - teamMap sets `assigned_team_id` from the contact's ASSIGNEE's team
# ═══════════════════════════════════════════════════════════════════════════


def test_team_map_sets_assigned_team_id_from_the_contacts_assignee_team(session_factory, monkeypatch):
    ensure_team_capabilities()

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    target_team = Team(tenant_id=DEFAULT_TENANT_ID, name="Support Review1", is_active=True)
    db.add(target_team)
    db.commit()
    target_team_id = target_team.id

    contact_row = {
        "id": 997101, "firstName": "Teamed", "lastName": "Up", "phone": "+15550097101",
        "assignee": {"id": 501, "firstName": "Priya", "lastName": "Nair", "email": "priya-review1@example.com"},
    }
    space_users = [
        {
            "id": 501, "firstName": "Priya", "lastName": "Nair", "email": "priya-review1@example.com",
            "team": {"id": 701, "name": "Support"},
        },
    ]
    handler = _pages_handler_full({None: ([contact_row], None)}, space_users=space_users)
    _stub_client(monkeypatch, handler)

    job = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run",
        team_map=[{"sourceTeamId": "701", "targetTeamId": target_team_id}],
    )
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    contact = db.query(Contact).filter(
        Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15550097101"
    ).first()
    assert contact is not None
    assert contact.assigned_team_id == target_team_id
    db.close()


def test_no_team_map_configured_never_calls_space_user(session_factory, monkeypatch):
    """A job with an EMPTY `teamMap` (the common case) must never pay for
    the extra `/space/user` round trip."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    contact_row = {"id": 997201, "firstName": "No", "lastName": "Team", "phone": "+15550097201"}
    handler = _pages_handler_full({None: ([contact_row], None)})
    _stub_client(monkeypatch, handler)

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error
    assert not any(p.endswith("/space/user") for p in handler.calls)
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# B2a - core LocalDiskStorage traversal guard, exercised through the
# migration CSV-read path specifically (the original exploit shape).
# ═══════════════════════════════════════════════════════════════════════════


def test_csv_contacts_phase_cannot_be_pointed_at_an_arbitrary_storage_key(session_factory, monkeypatch, tmp_path):
    """Even if a caller managed to smuggle a traversal-shaped key into
    `payload_json["contactsCsvKey"]` directly (bypassing `create_job`'s own
    id-to-key resolution - this is the belt-and-suspenders layer, not the
    primary fix), the CORE storage guard rejects it - `_process_csv_contacts`
    reports a skip, never reads outside the media root."""
    from app.config import settings

    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    outside = tmp_path.parent / "review1-secret.txt"
    outside.write_text("host secret")

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    db.commit()

    from app.models.background_job import JOB_RUNNING, BackgroundJob
    from modules.omnichannel.services.migration_service import MIGRATION_JOB_TYPE

    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=MIGRATION_JOB_TYPE, status=JOB_RUNNING,
        payload_json={
            "mode": "run", "source": "csv", "connectionId": None, "workspaceId": ws.id,
            "channelMap": [], "userMap": [], "teamMap": [], "lifecycleMap": [],
            "contactsOnly": False, "mappingHash": "test-b2a",
            "contactsCsvKey": "../review1-secret.txt", "csvHeaderMap": {},
            "snippetsCsvKey": None,
        },
    )
    db.add(job)
    db.commit()

    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error
    failures = job.result_json["failures"]
    assert failures["rowCount"] >= 1
    # The row is skipped as "could not read" (the SAME FileNotFoundError a
    # genuinely-missing key raises) - crucially, NO contact is ever created
    # from the outside file's content, proving it was never actually read.
    assert db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.workspace_id == ws.id).count() == 0
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# S11 - per-contact message buffer cap (MAX_MESSAGES_PER_CONTACT)
# ═══════════════════════════════════════════════════════════════════════════


def test_message_cap_skips_only_the_capped_contact_reports_blocker_never_aborts(session_factory, monkeypatch):
    """A contact whose message history exceeds `MAX_MESSAGES_PER_CONTACT`
    (monkeypatched low here) is skipped WHOLE - never partially written,
    never fabricated - reported as a blocker with a `messagesSkippedOverCap`
    count; the job still finishes `done`, and an UNRELATED contact's own
    messages are entirely unaffected."""
    import modules.omnichannel.services.migration_service as migration_service_module

    monkeypatch.setattr(migration_service_module, "MAX_MESSAGES_PER_CONTACT", 2)

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    capped_contact = {"id": 998101, "firstName": "Capped", "lastName": "History", "phone": "+15550098101"}
    normal_contact = {"id": 998102, "firstName": "Normal", "lastName": "History", "phone": "+15550098102"}
    messages_by_contact = {
        "id:998101": {None: ([
            {"messageId": i, "traffic": "incoming", "channelId": 901, "message": {"type": "text", "text": f"m{i}"}}
            for i in range(1, 6)  # 5 messages, cap monkeypatched to 2
        ], None)},
        "id:998102": {None: ([
            {"messageId": 998200, "traffic": "incoming", "channelId": 901, "message": {"type": "text", "text": "hi"}},
        ], None)},
    }
    handler = _pages_handler_full(
        {None: ([capped_contact, normal_contact], None)}, messages_by_contact=messages_by_contact,
    )
    _stub_client(monkeypatch, handler)

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    from modules.omnichannel.models import ConversationMessage

    capped = db.query(Contact).filter(
        Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15550098101"
    ).first()
    assert capped is not None, "the CONTACT row itself still migrates"
    assert (
        db.query(ConversationMessage).filter(ConversationMessage.contact_id == capped.id).count() == 0
    ), "but NONE of its messages do - never a partial write"

    normal = db.query(Contact).filter(
        Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15550098102"
    ).first()
    assert (
        db.query(ConversationMessage).filter(ConversationMessage.contact_id == normal.id).count() == 1
    ), "an unrelated contact's own messages are entirely unaffected by the other contact's cap hit"

    report = job.result_json["report"]
    assert report["messagesSkippedOverCap"] == 1
    assert any("more messages than this migration tool will buffer" in b for b in report["blockers"])
    db.close()


def test_message_cap_stops_paging_immediately_never_fetches_further_pages(session_factory, monkeypatch):
    """The cap check runs INSIDE the page loop - once tripped, no further
    `/message/list` page is ever requested for that contact (bounds the
    network calls, not just the in-memory buffer)."""
    import modules.omnichannel.services.migration_service as migration_service_module

    monkeypatch.setattr(migration_service_module, "MAX_MESSAGES_PER_CONTACT", 1)

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    contact_row = {"id": 998301, "firstName": "Paged", "lastName": "Cap", "phone": "+15550098301"}
    # Two pages, 2 messages each - the FIRST page alone already exceeds a
    # cap of 1, so a correct implementation never requests the second page.
    messages_by_contact = {
        "id:998301": {
            None: ([
                {"messageId": 1, "traffic": "incoming", "channelId": 901, "message": {"type": "text", "text": "a"}},
                {"messageId": 2, "traffic": "incoming", "channelId": 901, "message": {"type": "text", "text": "b"}},
            ], "page2"),
            "page2": ([
                {"messageId": 3, "traffic": "incoming", "channelId": 901, "message": {"type": "text", "text": "c"}},
            ], None),
        },
    }
    handler = _pages_handler_full({None: ([contact_row], None)}, messages_by_contact=messages_by_contact)
    _stub_client(monkeypatch, handler)

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error
    message_list_calls = [c for c in handler.calls if c.endswith("/message/list")]
    assert len(message_list_calls) == 1, "the SECOND page must never be requested once the cap trips"
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# Test report Defect 1 - `MigrationJobItem.connectionId` tolerates a stored
# JSON `null` (a hand-built/legacy row) without 500ing the whole list/get
# ═══════════════════════════════════════════════════════════════════════════


def test_list_and_get_job_tolerate_a_stored_null_connection_id(client, session_factory):
    from app.models.background_job import JOB_PENDING, BackgroundJob

    db = session_factory()
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=MIGRATION_JOB_TYPE, status=JOB_PENDING,
        payload_json={
            "mode": "run", "source": "csv", "connectionId": None, "workspaceId": "ws-defect1",
            "channelMap": [], "userMap": [], "teamMap": [], "lifecycleMap": [],
            "contactsOnly": False, "mappingHash": "test-defect1",
        },
    )
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()

    h = _auth(client)
    list_res = client.get("/omnichannel/migration/jobs", headers=h)
    assert list_res.status_code == 200, list_res.text
    row = next(r for r in list_res.json()["data"] if r["id"] == job_id)
    assert row["connectionId"] is None

    get_res = client.get(f"/omnichannel/migration/jobs/{job_id}", headers=h)
    assert get_res.status_code == 200, get_res.text
    assert get_res.json()["connectionId"] is None


# ═══════════════════════════════════════════════════════════════════════════
# Test report Defect 2 - CSV mode's own Lifecycle column resolves via
# `lifecycleMap` (when present) else an exact key/label match against the
# target workspace's own stages (map-only, never create); unmapped values
# still land the contact on the initial stage but are reported.
# ═══════════════════════════════════════════════════════════════════════════


def test_csv_mode_lifecycle_resolves_by_stage_key_and_reports_the_unmapped_value(session_factory):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    db.commit()

    from modules.omnichannel.services.lifecycle_service import initial_status_id

    stage_ids = {s.key: s.id for s in stages_for_workspace(db, DEFAULT_TENANT_ID, ws.id)}
    initial_id = initial_status_id(db, DEFAULT_TENANT_ID, ws.id)

    content = _csv_bytes(
        ["First Name", "Phone", "Lifecycle"],
        [
            ["Ada", "+15550097301", "hot_lead"],  # exact KEY match, resolves
            ["Bob", "+15550097302", "customer"],  # exact KEY match, resolves
            ["Carl", "+15550097303", "not-a-real-stage"],  # unmapped
        ],
    )
    key = _upload_key(db, DEFAULT_TENANT_ID, "contacts", content)
    job = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    def _stage_of(phone):
        c = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == phone).first()
        return c.lifecycle_status_id

    assert _stage_of("+15550097301") == stage_ids["hot_lead"]
    assert _stage_of("+15550097302") == stage_ids["customer"]
    # unmapped -> contact still written, on the INITIAL stage (never blank,
    # never silently dropped) - the previous behavior was indistinguishable
    # from a MAPPED "New Lead" outcome; the report below is what fixes that.
    assert _stage_of("+15550097303") == initial_id

    report = job.result_json["report"]
    assert report["lifecycleUnmappedByValue"] == {"not-a-real-stage": 1}
    assert any(
        'a CSV Lifecycle value of "not-a-real-stage"' in b for b in report["blockers"]
    ), report["blockers"]
    db.close()


def test_csv_mode_lifecycle_via_explicit_map_still_wins_over_the_key_label_fallback(session_factory):
    """When `lifecycleMap` DOES carry an entry (a future CSV-mode mapping UI,
    or a hand-built payload), it is checked FIRST - the key/label fallback
    only fires when the map has no entry for that value."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    db.commit()

    stage_ids = {s.key: s.id for s in stages_for_workspace(db, DEFAULT_TENANT_ID, ws.id)}

    content = _csv_bytes(["First Name", "Phone", "Lifecycle"], [["Ada", "+15550097401", "trial"]])
    key = _upload_key(db, DEFAULT_TENANT_ID, "contacts", content)
    job = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key, mode="run")
    job.payload_json = {
        **job.payload_json,
        "lifecycleMap": [{"sourceLabel": "trial", "targetStatusId": stage_ids["cold_lead"]}],
    }
    db.commit()

    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    ada = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15550097401").first()
    assert ada.lifecycle_status_id == stage_ids["cold_lead"]
    assert job.result_json["report"]["lifecycleUnmappedByValue"] == {}
    db.close()
