"""Plan 33 (roadmap A6), slice S2 - migration job, contacts phase, dry run
(AC-MIG-18..29).

Two layers: (1) HTTP route tests (`client` fixture) - create/list/get/cancel,
the `dry_run_required`/`migration_in_progress` guards, permission gating,
tenant isolation, the failures.csv download; (2) direct handler/writer tests
(`session_factory` fixture) - `run_migration_job` called directly against a
hand-built `BackgroundJob` row so the contact match ladder, merge rules,
custom-field type map, tag cap, assignee tenant scoping, cursor resume,
cooperative abort and the dry-run write-absence control can all be asserted
against real DB state without a live respond.io API.
"""
import httpx

from app.models import DEFAULT_TENANT_ID
from app.secrets import encrypt_secret
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

from modules.omnichannel.models import (
    Contact,
    ContactField,
    ContactTag,
    ContactTagLink,
    MigrationRef,
    Workspace,
)
from modules.omnichannel.repositories.migration_ref_repository import MigrationRefRepository
from modules.omnichannel.respondio.client import RespondIoClient
from modules.omnichannel.services.contact_tag_service import ContactTagService, MAX_TAGS_PER_WORKSPACE
from modules.omnichannel.services.lifecycle_service import stages_for_workspace
from modules.omnichannel.services.migration_service import (
    MIGRATION_JOB_TYPE,
    RESPONDIO_PROVIDER,
    run_migration_job,
)


# ── shared HTTP helpers (mirrors test_omnichannel_respondio_migration.py) ──


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, tenant_slug=None) -> str:
    payload = {"email": email, "password": password}
    if tenant_slug is not None:
        payload["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _default_workspace_id(client, headers) -> str:
    res = client.get("/omnichannel/workspaces", headers=headers)
    assert res.status_code == 200
    return next(w["id"] for w in res.json()["data"] if w["isDefault"])


def _create_connection(client, headers, *, api_token="secret-token-xyz") -> str:
    res = client.post(
        "/integrations/connections",
        headers=headers,
        json={
            "provider": "respondio",
            "name": "Acme Space",
            "config": {
                "spaceLabel": "Acme Support",
                "timezone": "Asia/Kuala_Lumpur",
                "requestsPerSecond": "1000",
            },
            "credentials": {"apiToken": api_token},
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _minimal_job_body(connection_id: str, workspace_id: str, *, mode: str = "dry_run") -> dict:
    return {
        "connectionId": connection_id,
        "workspaceId": workspace_id,
        "mode": mode,
        "source": "api",
        "channelMap": [],
        "userMap": [],
        "teamMap": [],
        "lifecycleMap": [],
        "contactsOnly": True,
    }


def _empty_pages_handler(request: httpx.Request) -> httpx.Response:
    """Every list call returns an empty single page - enough for a job whose
    test only cares about the create/list/get/cancel HTTP contract, not the
    contacts walk itself."""
    return httpx.Response(200, json={"items": [], "pagination": {"next": None}})


def _patch_client_factory(monkeypatch, handler):
    def fake_from_connection(config, credentials, *, client=None, on_milestone=None):
        return RespondIoClient(
            base_url=str(config.get("baseUrl") or "https://api.respond.io/v2"),
            api_token=str(credentials.get("apiToken", "")),
            requests_per_second=float(config.get("requestsPerSecond") or 1000),
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            on_milestone=on_milestone,
            sleep=lambda s: None,
        )

    monkeypatch.setattr(RespondIoClient, "from_connection", staticmethod(fake_from_connection))


def test_gateway_contract_files_carry_no_migration_trace():
    """S6 (AC-MIG-55) - a content guard, not a `git diff` (which depends on
    the checkout's branch state and would be flaky across a rebase/merge):
    the public gateway router/schemas and the consumer guide must carry no
    trace of anything this plan introduced. A real coupling (a shared
    helper, a doc cross-reference, a schema field) would show up as one of
    these needles landing in either file."""
    import pathlib

    backend_root = pathlib.Path(__file__).resolve().parents[1]
    repo_root = backend_root.parent
    gateway_router = (backend_root / "modules/omnichannel/routers/api_v1.py").read_text()
    guide = (repo_root / "documentation/omnichannel/consumer-integration-guide.md").read_text()
    needles = (
        "respondio_migration",
        "MigrationJobItem",
        "MigrationPreflight",
        "migration_refs",
        "/migration/jobs",
        "/migration/preflight",
        "/migration/uploads",
    )
    for needle in needles:
        assert needle not in gateway_router, f"{needle!r} leaked into the public gateway router"
        assert needle not in guide, f"{needle!r} leaked into the consumer integration guide"


# ═══════════════════════════════════════════════════════════════════════════
# HTTP route tests (AC-MIG-19..21, 50..53)
# ═══════════════════════════════════════════════════════════════════════════


def test_create_dry_run_job_succeeds_and_report_shape(client, monkeypatch):
    h = _auth(client)
    connection_id = _create_connection(client, h)
    ws_id = _default_workspace_id(client, h)
    _patch_client_factory(monkeypatch, _empty_pages_handler)

    res = client.post(
        "/omnichannel/migration/jobs", headers=h, json=_minimal_job_body(connection_id, ws_id)
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["mode"] == "dry_run"
    assert body["status"] == "done"
    assert body["report"]["entities"]["contacts"] == {
        "fetched": 0, "wouldCreate": 0, "wouldUpdate": 0, "wouldSkip": 0, "errors": 0,
    }
    assert set(body["report"]["entities"].keys()) == {
        "contacts", "fields", "tags", "identities", "messages", "media", "events", "quickReplies",
    }
    assert body["failureCount"] == 0
    assert body["spaceLabel"] == "Acme Support"


def test_create_run_job_refused_without_fresh_dry_run(client, monkeypatch):
    h = _auth(client)
    connection_id = _create_connection(client, h)
    ws_id = _default_workspace_id(client, h)
    _patch_client_factory(monkeypatch, _empty_pages_handler)

    res = client.post(
        "/omnichannel/migration/jobs",
        headers=h,
        json=_minimal_job_body(connection_id, ws_id, mode="run"),
    )
    assert res.status_code == 409
    assert res.json()["detail"]["reason"] == "dry_run_required"


def test_create_run_job_succeeds_after_matching_dry_run(client, monkeypatch):
    h = _auth(client)
    connection_id = _create_connection(client, h)
    ws_id = _default_workspace_id(client, h)
    _patch_client_factory(monkeypatch, _empty_pages_handler)

    dry = client.post(
        "/omnichannel/migration/jobs", headers=h, json=_minimal_job_body(connection_id, ws_id)
    )
    assert dry.status_code == 201, dry.text

    run = client.post(
        "/omnichannel/migration/jobs",
        headers=h,
        json=_minimal_job_body(connection_id, ws_id, mode="run"),
    )
    assert run.status_code == 201, run.text
    assert run.json()["mode"] == "run"
    assert run.json()["status"] == "done"


def test_create_job_migration_in_progress_409(client, monkeypatch, session_factory):
    h = _auth(client)
    connection_id = _create_connection(client, h)
    ws_id = _default_workspace_id(client, h)

    # A job that never completes (the handler blocks forever) is simulated by
    # inserting a RUNNING background_jobs row directly for this workspace -
    # cheaper and more deterministic than racing a real in-flight HTTP call.
    from app.models.background_job import JOB_RUNNING, BackgroundJob

    db = session_factory()
    db.add(
        BackgroundJob(
            tenant_id=DEFAULT_TENANT_ID, type=MIGRATION_JOB_TYPE, status=JOB_RUNNING,
            payload_json={"workspaceId": ws_id, "mode": "dry_run"},
        )
    )
    db.commit()
    db.close()

    res = client.post(
        "/omnichannel/migration/jobs", headers=h, json=_minimal_job_body(connection_id, ws_id)
    )
    assert res.status_code == 409
    assert res.json()["detail"]["reason"] == "migration_in_progress"


def test_create_job_invalid_channel_map_target_422(client, monkeypatch):
    h = _auth(client)
    connection_id = _create_connection(client, h)
    ws_id = _default_workspace_id(client, h)

    body = _minimal_job_body(connection_id, ws_id)
    body["channelMap"] = [{"sourceChannelId": "rio-1", "targetChannelId": "not-a-real-channel"}]
    res = client.post("/omnichannel/migration/jobs", headers=h, json=body)
    assert res.status_code == 422
    assert "channelMap.0" in res.json()["detail"]["fieldErrors"]


def test_create_job_invalid_lifecycle_map_target_422(client, monkeypatch):
    h = _auth(client)
    connection_id = _create_connection(client, h)
    ws_id = _default_workspace_id(client, h)

    body = _minimal_job_body(connection_id, ws_id)
    body["lifecycleMap"] = [{"sourceLabel": "lead", "targetStatusId": "not-a-real-stage"}]
    res = client.post("/omnichannel/migration/jobs", headers=h, json=body)
    assert res.status_code == 422
    assert "lifecycleMap.0" in res.json()["detail"]["fieldErrors"]


def test_create_job_requires_manage_not_read(client, session_factory):
    from app.models import Permission, Role, User, UserStatus
    from app.security import hash_password

    db = session_factory()
    read_perm = db.query(Permission).filter(Permission.key == "omnichannel_migration.read").first()
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="Migration Reader 2")
    role.permissions = [read_perm]
    db.add(role)
    db.flush()
    user = User(
        tenant_id=DEFAULT_TENANT_ID, email="reader2@example.com",
        password=hash_password("Password123!"), name="Reader2", status=UserStatus.ACTIVE.value,
    )
    user.roles = [role]
    db.add(user)
    db.commit()
    db.close()

    h = _auth(client, email="reader2@example.com", password="Password123!")
    res = client.post(
        "/omnichannel/migration/jobs", headers=h,
        json=_minimal_job_body("whatever", "whatever"),
    )
    assert res.status_code == 403


def test_get_job_surfaces_milestone_log_list_does_not(client, session_factory):
    """S6 (AC-MIG-08) - `JobService.log()` writes to `background_jobs.logs_json`
    on every abort/backoff/page milestone; the detail read now surfaces it,
    the list read stays lean (no per-row log payload)."""
    ws_id = _default_workspace_id(client, _auth(client))
    h = _auth(client)

    db = session_factory()
    from app.jobs.service import JobService
    from app.models.background_job import JOB_DONE, BackgroundJob

    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=MIGRATION_JOB_TYPE, status=JOB_DONE,
        payload_json={"workspaceId": ws_id, "mode": "dry_run"},
    )
    db.add(job)
    db.commit()
    JobService(db).log(job, "Aborted after 3 contacts.", level="warning")
    job_id = job.id
    db.close()

    got = client.get(f"/omnichannel/migration/jobs/{job_id}", headers=h)
    assert got.status_code == 200
    logs = got.json()["logs"]
    assert len(logs) == 1
    assert logs[0]["level"] == "warning"
    assert logs[0]["message"] == "Aborted after 3 contacts."

    listed = client.get("/omnichannel/migration/jobs", headers=h)
    assert listed.status_code == 200
    row = next(j for j in listed.json()["data"] if j["id"] == job_id)
    assert row["logs"] == []


def test_list_and_get_job_tenant_scoped(client, monkeypatch, session_factory):
    h = _auth(client)
    connection_id = _create_connection(client, h)
    ws_id = _default_workspace_id(client, h)
    _patch_client_factory(monkeypatch, _empty_pages_handler)

    created = client.post(
        "/omnichannel/migration/jobs", headers=h, json=_minimal_job_body(connection_id, ws_id)
    )
    job_id = created.json()["id"]

    listed = client.get("/omnichannel/migration/jobs", headers=h)
    assert listed.status_code == 200
    assert any(j["id"] == job_id for j in listed.json()["data"])

    got = client.get(f"/omnichannel/migration/jobs/{job_id}", headers=h)
    assert got.status_code == 200
    assert got.json()["id"] == job_id

    # A different tenant sees NEITHER the list entry nor the detail (AC-MIG-51/52).
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    db = session_factory()
    tenant = TenantService(db).provision(
        name="Other Tenant 2", slug="other-rio-2",
        admin_email="admin-other-rio-2@example.com", admin_password="Password123!", admin_name="Admin",
    )
    db.flush()
    AppStoreService(db).install(tenant.id, "omnichannel")
    db.commit()
    db.close()
    h2 = _auth(
        client, email="admin-other-rio-2@example.com", password="Password123!", tenant_slug="other-rio-2"
    )

    listed2 = client.get("/omnichannel/migration/jobs", headers=h2)
    assert listed2.json()["data"] == []
    got2 = client.get(f"/omnichannel/migration/jobs/{job_id}", headers=h2)
    assert got2.status_code == 404


def test_list_jobs_search_sort_and_filter(client, session_factory):
    """S6 (AC-MIG-02/56) - the list's search box, column sort and Filter
    popover all resolve against `spaceLabel`/`workspaceName`/`mode`, none of
    which are native `background_jobs` columns (`_list_row_fields`). Rows are
    hand-built directly (mirrors `test_create_job_migration_in_progress_409`)
    rather than via two respond.io connections, which the one-active-per-
    -tenant partial index would refuse."""
    h = _auth(client)
    ws_id = _default_workspace_id(client, h)

    from app.models.background_job import JOB_DONE, BackgroundJob

    db = session_factory()
    db.add_all(
        [
            BackgroundJob(
                tenant_id=DEFAULT_TENANT_ID, type=MIGRATION_JOB_TYPE, status=JOB_DONE,
                payload_json={"workspaceId": ws_id, "mode": "dry_run", "spaceLabel": "Acme Support", "workspaceName": "Main"},
            ),
            BackgroundJob(
                tenant_id=DEFAULT_TENANT_ID, type=MIGRATION_JOB_TYPE, status=JOB_DONE,
                payload_json={"workspaceId": ws_id, "mode": "run", "spaceLabel": "Acme Support", "workspaceName": "Main"},
            ),
            BackgroundJob(
                tenant_id=DEFAULT_TENANT_ID, type=MIGRATION_JOB_TYPE, status=JOB_DONE,
                payload_json={"workspaceId": ws_id, "mode": "dry_run", "spaceLabel": "Zed Corp", "workspaceName": "Main"},
            ),
        ]
    )
    db.commit()
    db.close()

    # Free-text search over spaceLabel (case-insensitive substring).
    searched = client.get("/omnichannel/migration/jobs?search=zed", headers=h)
    assert searched.status_code == 200
    labels = {j["spaceLabel"] for j in searched.json()["data"]}
    assert labels == {"Zed Corp"}

    # Column sort ascending by spaceLabel (Acme Support < Zed Corp).
    sorted_asc = client.get(
        "/omnichannel/migration/jobs?sortBy=spaceLabel&sortDir=asc", headers=h
    )
    assert sorted_asc.status_code == 200
    ordered_labels = [j["spaceLabel"] for j in sorted_asc.json()["data"]]
    assert ordered_labels.index("Acme Support") < ordered_labels.index("Zed Corp")

    # Filter popover: mode == "run" (a single leaf FilterGroup, the frontend's
    # own `{combinator, rules}` wire shape).
    import json

    mode_filter = json.dumps(
        {"kind": "group", "combinator": "and", "rules": [{"kind": "condition", "field": "mode", "operator": "eq", "value": "run"}]}
    )
    filtered = client.get(f"/omnichannel/migration/jobs?filter={mode_filter}", headers=h)
    assert filtered.status_code == 200
    assert filtered.json()["data"] and all(j["mode"] == "run" for j in filtered.json()["data"])

    # An unparseable filter never breaks the list read - it just goes unfiltered.
    garbage = client.get("/omnichannel/migration/jobs?filter=not-json", headers=h)
    assert garbage.status_code == 200
    assert len(garbage.json()["data"]) >= 3


def test_get_job_uniform_404_for_missing_and_wrong_type(client, session_factory):
    h = _auth(client)
    res = client.get("/omnichannel/migration/jobs/does-not-exist", headers=h)
    assert res.status_code == 404

    from app.jobs.service import JobService

    # A job of a DIFFERENT ALREADY-registered type belonging to the SAME
    # tenant must not resolve through this migration-specific route (the
    # contacts-export handler is registered by the real module boot path,
    # `bootstrap_modules`, so no extra registration is needed here).
    db = session_factory()
    other_job = JobService(db).create(type="omnichannel.contacts_export", tenant_id=DEFAULT_TENANT_ID)
    other_job_id = other_job.id
    db.close()

    res2 = client.get(f"/omnichannel/migration/jobs/{other_job_id}", headers=h)
    assert res2.status_code == 404


def test_cancel_job_aborts_running_and_409_when_terminal(client, session_factory):
    h = _auth(client)
    ws_id = _default_workspace_id(client, h)
    from app.models.background_job import JOB_RUNNING, BackgroundJob

    db = session_factory()
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=MIGRATION_JOB_TYPE, status=JOB_RUNNING,
        payload_json={"workspaceId": ws_id, "mode": "run"},
    )
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()

    res = client.post(f"/omnichannel/migration/jobs/{job_id}/cancel", headers=h)
    assert res.status_code == 200
    assert res.json()["status"] == "aborted"

    res2 = client.post(f"/omnichannel/migration/jobs/{job_id}/cancel", headers=h)
    assert res2.status_code == 409


def test_failures_csv_download_authed_private_no_store(client, session_factory):
    h = _auth(client)
    ws_id = _default_workspace_id(client, h)
    from app.models.background_job import JOB_DONE, BackgroundJob

    db = session_factory()
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=MIGRATION_JOB_TYPE, status=JOB_DONE,
        payload_json={"workspaceId": ws_id, "mode": "run"},
        result_json={
            "report": {}, "failures": {
                "rowCount": 1,
                "rows": [
                    {"entity": "contacts", "sourceId": "1", "sourceLabel": "Jane, Doe",
                     "reason": "bad phone", "action": "skipped"},
                ],
            },
        },
    )
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()

    res = client.get(f"/omnichannel/migration/jobs/{job_id}/failures.csv", headers=h)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert res.headers["cache-control"] == "private, no-store"
    assert "Jane, Doe" in res.text

    # Unauthed = 401/403, never a bearer-less capability URL (D-A6-23).
    res_unauth = client.get(f"/omnichannel/migration/jobs/{job_id}/failures.csv")
    assert res_unauth.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════
# Direct handler/writer tests (AC-MIG-22..29) - `run_migration_job` called
# directly against a hand-built job row, no HTTP layer.
# ═══════════════════════════════════════════════════════════════════════════


def _make_connection(db, tenant_id, *, api_token="tok", timezone="Asia/Kuala_Lumpur"):
    from app.models.connection import Connection

    conn = Connection(
        tenant_id=tenant_id, provider=RESPONDIO_PROVIDER, type="migration", name="Test Space",
        config_json={"spaceLabel": "Test Space", "timezone": timezone, "requestsPerSecond": "1000"},
        credentials_json=encrypt_secret({"apiToken": api_token}),
        status="ACTIVE",
    )
    db.add(conn)
    db.flush()
    return conn


def _default_workspace(db, tenant_id):
    return db.query(Workspace).filter(Workspace.tenant_id == tenant_id, Workspace.is_default.is_(True)).first()


def _make_job(db, tenant_id, *, connection_id, workspace_id, mode="run", lifecycle_map=None, cursor=None, result=None):
    from app.models.background_job import JOB_RUNNING, BackgroundJob

    job = BackgroundJob(
        tenant_id=tenant_id, type=MIGRATION_JOB_TYPE, status=JOB_RUNNING,
        payload_json={
            "mode": mode, "source": "api", "connectionId": connection_id, "workspaceId": workspace_id,
            "channelMap": [], "userMap": [], "teamMap": [],
            "lifecycleMap": lifecycle_map or [], "contactsOnly": True, "mappingHash": "test",
        },
        cursor_json=cursor,
        result_json=result,
    )
    db.add(job)
    db.commit()
    return job


def _pages_handler(pages: dict, custom_fields: list = None):
    """`pages = {cursorId_or_None: (items, next_cursor)}`; `/space/custom_field`
    always answers with `custom_fields or []`."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/space/custom_field"):
            return httpx.Response(200, json={"items": custom_fields or [], "pagination": {"next": None}})
        assert request.url.path.endswith("/contact/list")
        cursor = request.url.params.get("cursorId")
        items, next_cursor = pages[cursor]
        return httpx.Response(200, json={"items": items, "pagination": {"next": next_cursor}})

    handler.calls = calls
    return handler


def _stub_client(monkeypatch, handler):
    def fake_from_connection(config, credentials, *, client=None, on_milestone=None):
        return RespondIoClient(
            base_url="https://api.respond.io/v2", api_token=str(credentials.get("apiToken", "")),
            requests_per_second=1000, client=httpx.Client(transport=httpx.MockTransport(handler)),
            on_milestone=on_milestone, sleep=lambda s: None,
        )

    monkeypatch.setattr(RespondIoClient, "from_connection", staticmethod(fake_from_connection))


def _row_counts(db, tenant_id, workspace_id) -> dict:
    """The AC-MIG-29 "savepoint fixture paired with a real-mode control" -
    snapshot every table the writer touches so a dry run's absence claim is
    checked by an actual count, not assumed."""
    return {
        "contacts": db.query(Contact).filter(Contact.tenant_id == tenant_id, Contact.workspace_id == workspace_id).count(),
        "fields": db.query(ContactField).filter(ContactField.tenant_id == tenant_id, ContactField.workspace_id == workspace_id).count(),
        "tags": db.query(ContactTag).filter(ContactTag.tenant_id == tenant_id, ContactTag.workspace_id == workspace_id).count(),
        "refs": db.query(MigrationRef).filter(MigrationRef.tenant_id == tenant_id, MigrationRef.workspace_id == workspace_id).count(),
    }


def test_dry_run_writes_nothing_paired_with_real_mode_control(session_factory, monkeypatch):
    """AC-MIG-27/29: the dry run leaves zero rows anywhere; the SAME source
    data run in `mode=run` DOES create them - a control proving the counting
    mechanism would have caught a leak (memory: pair absence with a mutation
    test, never a bare absence check)."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    contact_row = {
        "id": 900001, "firstName": "Dry", "lastName": "Run", "phone": "+15550001111",
        "email": "dry.run@example.com", "tags": ["vip"],
        "custom_fields": [{"name": "Plan Tier", "value": "Gold"}],
    }
    handler = _pages_handler({None: ([contact_row], None)}, custom_fields=[
        {"id": 1, "name": "Plan Tier", "dataType": "list", "allowedValues": ["Gold", "Silver"]},
    ])
    _stub_client(monkeypatch, handler)

    before = _row_counts(db, DEFAULT_TENANT_ID, ws.id)
    dry_job = _make_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="dry_run")
    run_migration_job(db, dry_job)
    after_dry = _row_counts(db, DEFAULT_TENANT_ID, ws.id)
    assert after_dry == before, "dry run must write zero rows anywhere (AC-MIG-27)"
    assert dry_job.status == "done"
    assert dry_job.result_json["report"]["entities"]["contacts"]["wouldCreate"] == 1

    # Control: the SAME data, mode=run, DOES persist (proves the count check
    # is a real mutation-detector, not a tautology).
    real_job = _make_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, real_job)
    after_real = _row_counts(db, DEFAULT_TENANT_ID, ws.id)
    assert after_real["contacts"] == before["contacts"] + 1
    assert after_real["tags"] == before["tags"] + 1
    assert after_real["fields"] == before["fields"] + 1
    assert after_real["refs"] == before["refs"] + 1
    db.close()


def test_rerun_via_migration_refs_creates_no_duplicates(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    contact_row = {"id": 900002, "firstName": "Once", "lastName": "Only", "phone": "+15550002222"}
    handler = _pages_handler({None: ([contact_row], None)})
    _stub_client(monkeypatch, handler)

    before = _row_counts(db, DEFAULT_TENANT_ID, ws.id)
    job1 = _make_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job1)
    after1 = _row_counts(db, DEFAULT_TENANT_ID, ws.id)
    assert after1["contacts"] == before["contacts"] + 1
    assert after1["refs"] == before["refs"] + 1

    job2 = _make_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job2)
    after2 = _row_counts(db, DEFAULT_TENANT_ID, ws.id)
    assert after2["contacts"] == after1["contacts"], "a re-run must create no duplicate contact"
    assert after2["refs"] == after1["refs"]
    assert job2.result_json["report"]["entities"]["contacts"]["wouldUpdate"] == 1
    db.close()


def test_cursor_resume_skips_already_completed_page(session_factory, monkeypatch):
    """AC-MIG-22: a crash-resume (status already `running` at pickup)
    continues from the stored cursor without re-processing page 1."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    page1 = [{"id": 900101, "firstName": "Page", "lastName": "One", "phone": "+15551110001"}]
    page2 = [{"id": 900102, "firstName": "Page", "lastName": "Two", "phone": "+15551110002"}]
    handler = _pages_handler({None: (page1, "cursor-2"), "cursor-2": (page2, None)})
    _stub_client(monkeypatch, handler)

    # Simulate a job that already completed page 1 (cursor stored) before a
    # crash - never asks for `cursorId=None` again.
    job = _make_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run",
        cursor={"phase": "contacts", "contactCursorId": "cursor-2", "counts": {
            "contacts": {"fetched": 1, "create": 1, "update": 0, "errors": 0},
        }},
    )
    run_migration_job(db, job)

    contact_list_calls = [c for c in handler.calls if c.endswith("/contact/list")]
    # Resumed straight to page 2 - page 1 (cursorId=None) was never re-requested.
    assert len(contact_list_calls) == 1

    assert db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15551110001").count() == 0
    assert db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15551110002").count() == 1
    assert job.result_json["report"]["entities"]["contacts"]["fetched"] == 2  # resumed counts + this page
    db.close()


def test_cooperative_abort_stops_before_next_page_and_resume_continues(session_factory, monkeypatch):
    """AC-MIG-28: a status flip to `aborted` (committed on a DIFFERENT
    session) is honoured BEFORE the next page/terminal step; a later re-run
    resumes from `migration_refs` and creates no duplicates."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    page1 = [{"id": 900201, "firstName": "Abort", "lastName": "Case", "phone": "+15552220001"}]
    page2 = [{"id": 900202, "firstName": "Never", "lastName": "Reached", "phone": "+15552220002"}]

    job_holder = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/space/custom_field"):
            return httpx.Response(200, json={"items": [], "pagination": {"next": None}})
        cursor = request.url.params.get("cursorId")
        if cursor is None:
            # A concurrent operator cancel, committed on a SEPARATE session -
            # takes effect for the NEXT checkpoint, not mid-flight.
            other = session_factory()
            from app.models.background_job import JOB_ABORTED, BackgroundJob

            other.query(BackgroundJob).filter(BackgroundJob.id == job_holder["id"]).update(
                {BackgroundJob.status: JOB_ABORTED}
            )
            other.commit()
            other.close()
            return httpx.Response(200, json={"items": page1, "pagination": {"next": "cursor-2"}})
        return httpx.Response(200, json={"items": page2, "pagination": {"next": None}})

    handler.calls = []
    monkeypatch.setattr(
        RespondIoClient, "from_connection",
        staticmethod(
            lambda config, credentials, client=None, on_milestone=None: RespondIoClient(
                base_url="https://api.respond.io/v2", api_token="tok", requests_per_second=1000,
                client=httpx.Client(transport=httpx.MockTransport(handler)), on_milestone=on_milestone,
                sleep=lambda s: None,
            )
        ),
    )

    job = _make_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    job_holder["id"] = job.id
    run_migration_job(db, job)

    db.refresh(job)
    assert job.status == "aborted"
    assert job.cursor_json["contactCursorId"] == "cursor-2"
    assert db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15552220001").count() == 1
    assert db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15552220002").count() == 0

    # Later re-run: flip back to running (the worker's own crash-resume path)
    # and let it finish - resumes from the stored cursor, no duplicate.
    from app.models.background_job import JOB_RUNNING

    job.status = JOB_RUNNING
    db.commit()
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done"
    assert db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15552220001").count() == 1
    assert db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15552220002").count() == 1
    db.close()


def test_contact_match_ladder_phone_then_email_then_create(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)

    # Pre-existing local contact matched by PHONE (no migration_refs row yet).
    phone_match = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, phone="+15553330001",
        phone_digits="15553330001", first_name="Existing", priority="MEDIUM",
    )
    # Pre-existing local contact matched by EMAIL only.
    email_match = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, email="matched@example.com",
        priority="MEDIUM",
    )
    db.add_all([phone_match, email_match])
    db.commit()

    rows = [
        {"id": 900301, "firstName": "Phone", "lastName": "Wins", "phone": "+15553330001", "email": "different@example.com"},
        {"id": 900302, "firstName": "Email", "lastName": "Only", "email": "matched@example.com"},
        {"id": 900303, "firstName": "Brand", "lastName": "New"},
    ]
    handler = _pages_handler({None: (rows, None)})
    _stub_client(monkeypatch, handler)

    job = _make_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)

    db.refresh(phone_match)
    db.refresh(email_match)
    assert phone_match.last_name == "Wins"  # merged into the phone match, first_name untouched
    assert phone_match.first_name == "Existing"  # never overwritten (D-A6-11)
    assert phone_match.email == "different@example.com"  # filled (was empty)
    assert email_match.first_name == "Email"  # merged into the email match

    report = job.result_json["report"]["entities"]["contacts"]
    assert report["fetched"] == 3
    assert report["wouldCreate"] == 1
    assert report["wouldUpdate"] == 2

    refs = MigrationRefRepository(db).local_for(
        DEFAULT_TENANT_ID, ws.id, RESPONDIO_PROVIDER, "contact", ["900301", "900302", "900303"]
    )
    assert refs["900301"] == phone_match.id
    assert refs["900302"] == email_match.id
    db.close()


def test_merge_never_overwrites_and_unions_tags(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)

    tag_service = ContactTagService(db)
    existing_tag = tag_service.create(ws.id, DEFAULT_TENANT_ID, type("P", (), {"name": "vip", "emoji": None, "color": None, "description": None})())
    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, phone="+15554440001", phone_digits="15554440001",
        first_name="Local", priority="MEDIUM",
    )
    db.add(contact)
    db.flush()
    db.add(ContactTagLink(tenant_id=DEFAULT_TENANT_ID, contact_id=contact.id, tag_id=existing_tag.id))
    db.commit()

    rows = [{
        "id": 900401, "firstName": "Source", "lastName": "Value", "phone": "+15554440001",
        "tags": ["vip", "new-tag"],
    }]
    handler = _pages_handler({None: (rows, None)})
    _stub_client(monkeypatch, handler)

    job = _make_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)

    db.refresh(contact)
    assert contact.first_name == "Local"  # never overwritten
    assert contact.last_name == "Value"  # filled (was empty)
    tag_names = {
        t.name for t in db.query(ContactTag).join(ContactTagLink, ContactTagLink.tag_id == ContactTag.id)
        .filter(ContactTagLink.contact_id == contact.id).all()
    }
    assert tag_names == {"vip", "new-tag"}  # union, not replace
    db.close()


def test_custom_field_type_map_and_invalid_value_is_reported_not_fatal(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    rows = [{
        "id": 900501, "firstName": "Field", "lastName": "Types",
        "custom_fields": [
            {"name": "Plan Tier", "value": "Gold"},
            {"name": "Renewal Date", "value": "2025-01-15"},
            {"name": "Is VIP", "value": True},
            {"name": "Seats", "value": 12},
            {"name": "Bad Number", "value": "not-a-number"},
        ],
    }]
    custom_fields = [
        {"id": 1, "name": "Plan Tier", "dataType": "list", "allowedValues": ["Gold", "Silver"]},
        {"id": 2, "name": "Renewal Date", "dataType": "date"},
        {"id": 3, "name": "Is VIP", "dataType": "checkbox"},
        {"id": 4, "name": "Seats", "dataType": "number"},
        {"id": 5, "name": "Bad Number", "dataType": "number"},
    ]
    handler = _pages_handler({None: (rows, None)}, custom_fields=custom_fields)
    _stub_client(monkeypatch, handler)

    job = _make_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)

    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.first_name == "Field").first()
    assert contact is not None
    cf = contact.custom_fields_json
    assert cf["plan_tier"] == "Gold"
    assert cf["renewal_date"] == "2025-01-15"
    assert cf["is_vip"] is True
    assert cf["seats"] == 12
    assert "bad_number" not in cf  # invalid value dropped, never a raw JSON write

    report = job.result_json["report"]["entities"]
    assert report["fields"]["errors"] == 1  # the "Bad Number" value error
    assert report["contacts"]["errors"] == 0  # the whole CONTACT is never failed for one bad field
    db.close()


def test_tag_cap_reached_reports_error_without_failing_the_contact(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    for i in range(MAX_TAGS_PER_WORKSPACE):
        db.add(ContactTag(tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, name=f"tag-{i}"))
    db.commit()

    rows = [{"id": 900601, "firstName": "Capped", "lastName": "Out", "tags": ["brand-new-tag"]}]
    handler = _pages_handler({None: (rows, None)})
    _stub_client(monkeypatch, handler)

    job = _make_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)

    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.first_name == "Capped").first()
    assert contact is not None  # the contact itself still gets created
    report = job.result_json["report"]["entities"]["contacts"]
    assert report["errors"] == 0
    assert report["wouldCreate"] == 1
    db.close()


def test_assignee_email_match_tenant_scoped_foreign_tenant_never_matches(session_factory, monkeypatch):
    from app.models import Role, User, UserStatus
    from app.security import hash_password
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)

    other = TenantService(db).provision(
        name="Assignee Other Tenant", slug="assignee-other",
        admin_email="foreign-agent@example.com", admin_password="Password123!", admin_name="Foreign",
    )
    db.flush()
    AppStoreService(db).install(other.id, "omnichannel")
    db.commit()

    rows = [{
        "id": 900701, "firstName": "Assign", "lastName": "Me",
        "assignee": {"id": 1, "firstName": "Foreign", "lastName": "Agent", "email": "foreign-agent@example.com"},
    }]
    handler = _pages_handler({None: (rows, None)})
    _stub_client(monkeypatch, handler)

    job = _make_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)

    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.first_name == "Assign").first()
    assert contact.assigned_user_id is None  # the foreign-tenant email must NOT match

    # Now a SAME-tenant user with that email exists - re-run a FRESH contact
    # (a different source id) to prove the positive case.
    tenant_a_role = Role(tenant_id=DEFAULT_TENANT_ID, name="Agent Role")
    db.add(tenant_a_role)
    db.flush()
    tenant_a_user = User(
        tenant_id=DEFAULT_TENANT_ID, email="foreign-agent@example.com",
        password=hash_password("Password123!"), name="Local Agent", status=UserStatus.ACTIVE.value,
    )
    tenant_a_user.roles = [tenant_a_role]
    db.add(tenant_a_user)
    db.commit()

    rows2 = [{
        "id": 900702, "firstName": "Assign", "lastName": "Again",
        "assignee": {"id": 1, "firstName": "Foreign", "lastName": "Agent", "email": "foreign-agent@example.com"},
    }]
    handler2 = _pages_handler({None: (rows2, None)})
    _stub_client(monkeypatch, handler2)
    job2 = _make_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job2)

    contact2 = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.first_name == "Assign", Contact.last_name == "Again").first()
    assert contact2.assigned_user_id == tenant_a_user.id
    db.close()


def test_lifecycle_mapped_on_create_and_never_moved_on_merge(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    stages = stages_for_workspace(db, DEFAULT_TENANT_ID, ws.id)
    target_stage = next(s for s in stages if s.key == "hot_lead")
    other_stage = next(s for s in stages if s.key == "customer")

    already_staged = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, phone="+15559990001", phone_digits="15559990001",
        priority="MEDIUM", lifecycle_status_id=other_stage.id,
    )
    db.add(already_staged)
    db.commit()

    rows = [
        {"id": 900801, "firstName": "New", "lastName": "Lead", "lifecycle": "trial"},
        {"id": 900802, "firstName": "Already", "lastName": "Staged", "phone": "+15559990001", "lifecycle": "trial"},
    ]
    handler = _pages_handler({None: (rows, None)})
    _stub_client(monkeypatch, handler)

    job = _make_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run",
        lifecycle_map=[{"sourceLabel": "trial", "targetStatusId": target_stage.id}],
    )
    run_migration_job(db, job)

    new_lead = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.first_name == "New").first()
    assert new_lead.lifecycle_status_id == target_stage.id

    db.refresh(already_staged)
    assert already_staged.lifecycle_status_id == other_stage.id  # never moved (D-A6-11)
    db.close()


def test_no_realtime_publish_or_entity_event_ever_called(session_factory, monkeypatch):
    """AC-MIG-33 (pinned early in S2 since the writer lands here): the
    migration writer must never call the live-seam functions a real inbound/
    outbound message write would."""
    calls = {"publish": 0, "emit": 0, "notify": 0}

    import modules.omnichannel.services.realtime as realtime_module
    import app.workflow_engine.entity_events as entity_events_module

    monkeypatch.setattr(realtime_module, "publish", lambda *a, **k: calls.__setitem__("publish", calls["publish"] + 1))
    monkeypatch.setattr(entity_events_module, "emit_entity_event", lambda *a, **k: calls.__setitem__("emit", calls["emit"] + 1))
    monkeypatch.setattr(entity_events_module, "notify_entity_event", lambda *a, **k: calls.__setitem__("notify", calls["notify"] + 1))

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    rows = [{"id": 900901, "firstName": "Quiet", "lastName": "Backfill", "tags": ["silent"]}]
    handler = _pages_handler({None: (rows, None)})
    _stub_client(monkeypatch, handler)

    job = _make_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)

    assert calls == {"publish": 0, "emit": 0, "notify": 0}
    db.close()
