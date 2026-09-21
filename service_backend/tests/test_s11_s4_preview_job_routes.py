"""Sprint-5/11 S4 - Group B, the preview-job HTTP surface (AC-11-21/22/23/26/
29/70/71, plus the AC-11-27 wire-status vocabulary and AC-11-23's
``previewJobId`` echo on the task view).

RED before the coder: ``modules.autocount.routers.http``/``routers.companies``
carry no job-start shape yet (``POST /autocount/http/preview`` and
``POST .../etl-task/preview`` still run the walk INLINE and answer 200 with
the old synchronous body - never a 202 ``{jobId, status}``), so every test
below either 500s/asserts a wrong status code, or fails at collection with an
``ImportError`` when it reaches for the new ``BackgroundJob`` row shape.
``GET /autocount/previews/{jobId}`` and ``POST .../cancel`` do not exist at
all (404) - a "missing feature" RED, never a bare ``assert False``.

WIRE CONTRACT pinned from the S3 frontend (the highest-authority source, per
this slice's brief): ``service_frontend/services/autocount-service.real.ts``
(``startPreviewJob``/``getPreviewJob``/``cancelPreviewJob``) and
``service_frontend/types/autocount.ts`` (``AutocountPreviewJob*``).

  POST /autocount/http/preview                                  scope=sample
    body   {scope:'sample', companyId, entityType, connectionId, path,
             distinctOf?, lookups?, combine?}
  POST /autocount/companies/{id}/entities/{type}/etl-task/preview  scope=full
    body   {scope:'full', companyId, entityType}
  both -> 202 {jobId, status}

  GET  /autocount/previews/{jobId}
    -> {id, scope, status, progress, result, error, taskError, fieldErrors?,
        createdAt}

  POST /autocount/previews/{jobId}/cancel
    -> the SAME AutocountPreviewJob shape

STATUS VOCABULARY (a real, load-bearing translation, easy to miss): the
background-job table's own statuses are ``pending/running/needs_review/done/
failed/aborted`` (``app/models/background_job.py``); the wire contract's
``AutocountPreviewJobStatus`` is ``queued/running/done/failed/cancelled``.
``pending`` -> ``queued`` and ``aborted`` -> ``cancelled`` are ASSUMED
translations (the only two that differ) - the coder should confirm rather
than silently leave the backend's raw ``pending``/``aborted`` strings on the
wire, which would silently break the FE's ``AutocountPreviewJobStatus``
switch (``job-progress.tsx``).

PERMISSION ASSUMPTION (flagged, not blindly followed): the brief that spawned
this file states "both scopes require autocount.companies.manage". That
contradicts the ALREADY-PINNED, ALREADY-GREEN
``test_preview_requires_sync_run_and_404s_cross_tenant`` in
``test_autocount_etl_task_routes.py``, which asserts the EXISTING
``POST .../etl-task/preview`` route requires ``autocount.sync.run`` - a
route this plan does not move to a new path (D6: "the POST routes keep their
paths"). Changing its permission would break that pinned test for no reason
the plan states (AC-11-70 only says new/changed routes REUSE the two
``companies.*`` keys, not that the full-scope preview swaps to
``companies.manage``). This file therefore pins the SAMPLE scope
(``POST /autocount/http/preview``, unchanged since sprint-5/08) on
``autocount.companies.manage`` (unchanged) and the FULL scope
(``POST .../etl-task/preview``, unchanged) on ``autocount.sync.run``
(unchanged) - the coder/reviewer should treat a deliberate departure from
this as a plan amendment, not a silent implementation choice.
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest
import sqlalchemy as sa

from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.models.background_job import (
    JOB_ABORTED,
    JOB_DONE,
    JOB_FAILED,
    JOB_PENDING,
    JOB_RUNNING,
    BackgroundJob,
)
from app.models.connection import Connection
from app.models.tenant import Tenant
from app.repositories.permission_repository import PermissionRepository
from app.security import hash_password
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import (
    ETL_STATUS_DRAFT,
    SOURCE_IMPL_AUTOCOUNT_HTTP,
    AcCompany,
    AcEntityConfig,
)

OTHER_TENANT = "tenant-other-s11-s4-routes"
JOB_TYPE = "autocount_source_preview"


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule (see ``test_s10_s3_snapshot_build_job.py``'s own copy) - this
    file is not under the ``test_(autocount|s10_)`` glob the shared conftest
    fixture auto-applies to, so it carries its own copy."""
    real_send = httpx.Client.send

    def guarded_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return real_send(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", guarded_send)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _auth(client, email="demo@example.com", password="demo1234") -> Dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _limited_user(db, keys: List[str], email: str) -> None:
    perms = PermissionRepository(db)
    role = Role(tenant_id=DEFAULT_TENANT_ID, name=f"Limited {email}", description="")
    role.permissions = [p for p in perms.list_all() if p.key in keys]
    db.add(role)
    db.flush()
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email=email,
        password=hash_password("limited1234"),
        name="Limited",
        status=UserStatus.ACTIVE.value,
        email_verified_at=sa.func.now(),
    )
    user.roles = [role]
    db.add(user)
    db.commit()


def _other_tenant(db) -> None:
    if db.get(Tenant, OTHER_TENANT) is None:
        default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(
            Tenant(
                id=OTHER_TENANT,
                slug="other-co-s11-s4-routes",
                name="Other Co",
                status_id=default_tenant.status_id,
            )
        )
        db.commit()


def _open_connection(db, *, tenant_id: str = DEFAULT_TENANT_ID) -> Connection:
    conn = Connection(
        tenant_id=tenant_id, provider="autocount", type="erp", name="s11-s4 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str, *, tenant_id: str = DEFAULT_TENANT_ID) -> AcCompany:
    company = AcCompany(
        tenant_id=tenant_id, connection_id=connection_id, database_name="S11S4",
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _http_task(
    db, company, connection_id, *, entity_type=ENTITY_PRODUCT, tenant_id: str = DEFAULT_TENANT_ID,
) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=tenant_id, company_id=company.id, entity_type=entity_type,
        source_impl=SOURCE_IMPL_AUTOCOUNT_HTTP, etl_status=ETL_STATUS_DRAFT,
        source_config={
            "connectionId": connection_id, "path": "/itembypage",
            "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
            "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
            "reconcileAt": "02:00", "lookups": [],
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _single_page_transport(rows: List[Dict[str, Any]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"TotalCount": len(rows), "Page": 1, "PageSize": 50, "TotalPages": 1, "Data": rows},
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def _job(db, job_id: str) -> BackgroundJob:
    return db.query(BackgroundJob).filter(BackgroundJob.id == job_id).one()


def _job_count(db) -> int:
    return db.query(BackgroundJob).filter(BackgroundJob.type == JOB_TYPE).count()


# ── AC-11-21/22 - the sample-scope POST becomes an async job start ──────────


def test_sample_scope_post_returns_202_and_creates_one_job_row(client, db):
    from app.main import app
    from modules.autocount.http_client import get_http_transport

    conn = _open_connection(db)
    app.dependency_overrides[get_http_transport] = lambda: _single_page_transport(
        [{"ItemCode": "A1", "Description": "Widget"}]
    )
    try:
        response = client.post(
            "/autocount/http/preview",
            json={"scope": "sample", "connectionId": conn.id, "path": "/itembypage"},
            headers=_auth(client),
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)

    assert response.status_code == 202, response.text
    body = response.json()
    assert set(body.keys()) >= {"jobId", "status"}, body
    assert body["status"] in {"queued", "running", "done", "failed", "cancelled"}, body

    job = _job(db, body["jobId"])
    assert job.type == JOB_TYPE
    assert job.tenant_id == DEFAULT_TENANT_ID
    assert (job.payload_json or {}).get("scope") == "sample"


def test_sample_scope_validation_failure_422s_before_any_job_is_created(client, db):
    """A bad ``connectionId`` (today's ``EtlValidationError``) must answer the
    SAME 422 ``{fieldErrors}`` shape as the old synchronous route, BEFORE a
    ``BackgroundJob`` row is ever written - never queued, then failed."""
    before = _job_count(db)
    response = client.post(
        "/autocount/http/preview",
        json={"scope": "sample", "connectionId": "not-a-real-connection", "path": "/itembypage"},
        headers=_auth(client),
    )
    assert response.status_code == 422, response.text
    detail = response.json().get("detail")
    assert isinstance(detail, dict) and "connectionId" in (detail.get("fieldErrors") or {}), (
        response.json()
    )
    assert _job_count(db) == before, "a validation failure must never create a job row"


def test_sample_scope_never_calls_preview_http_directly_from_the_router(monkeypatch, client, db):
    """AC-11-22's second pin: the route handler must not call
    ``EtlService.preview_http`` itself - only the job HANDLER may, so the
    request truly returns before any walk happens."""
    import modules.autocount.services.etl_service as etl_service_module

    def _boom(*args, **kwargs):
        raise AssertionError(
            "POST /autocount/http/preview must not call EtlService.preview_http "
            "directly from the request - only the background job handler may."
        )

    monkeypatch.setattr(etl_service_module.EtlService, "preview_http", _boom)

    conn = _open_connection(db)
    response = client.post(
        "/autocount/http/preview",
        json={"scope": "sample", "connectionId": conn.id, "path": "/itembypage"},
        headers=_auth(client),
    )
    # A 500 here would mean the assertion above fired from INSIDE the request
    # (the forbidden direct call happened); any other outcome (202, or a
    # clean 4xx before the job even reaches the handler) is fine.
    assert response.status_code != 500, response.text


def test_sample_scope_post_is_non_blocking_under_a_real_worker_and_never_touches_the_source(
    client, db, monkeypatch,
):
    """sprint-5/11 review round 1 (S9) - AC-11-22's non-blocking pin under a
    REAL (non-eager) worker deployment: with
    ``settings.celery_task_always_eager=False`` and job dispatch stubbed
    (mirrors ``test_autocount_http_lifecycle.py``'s own sweep-dispatch seam),
    the POST must land well under a second and the source must NEVER be
    requested from inside the request/response cycle - only a worker
    (stubbed away here) would ever run the job."""
    import time

    from app.config import settings
    from app.jobs import worker as worker_module

    monkeypatch.setattr(settings, "celery_task_always_eager", False)
    dispatched: List[Any] = []
    monkeypatch.setattr(
        worker_module.run_job_task, "delay", lambda job_id: dispatched.append(job_id)
    )
    monkeypatch.setattr(
        worker_module.run_job_task, "apply_async",
        lambda args=None, queue=None, **kw: dispatched.append((args, queue)),
    )

    conn = _open_connection(db)
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1, "Data": [{"ItemCode": "A1"}]},
        )

    from app.main import app
    from modules.autocount.http_client import get_http_transport

    app.dependency_overrides[get_http_transport] = lambda: httpx.Client(
        transport=httpx.MockTransport(handler)
    )
    try:
        started = time.monotonic()
        response = client.post(
            "/autocount/http/preview",
            json={"scope": "sample", "connectionId": conn.id, "path": "/itembypage"},
            headers=_auth(client),
        )
        elapsed = time.monotonic() - started
    finally:
        app.dependency_overrides.pop(get_http_transport, None)

    assert response.status_code == 202, response.text
    assert elapsed < 1.0, f"the POST took {elapsed:.3f}s - it must never block on the walk"
    assert len(calls) == 0, "no source page must be requested inside the request/response cycle"
    assert len(dispatched) == 1, "the job must be handed to the worker, never run inline"
    assert response.json()["status"] == "queued", response.json()


# ── AC-11-21/22 - the full-scope POST becomes an async job start too ────────


def test_full_scope_post_returns_202_and_creates_one_job_row_with_full_scope(client, db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)

    response = client.post(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task/preview",
        json={"scope": "full", "companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=_auth(client),
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert set(body.keys()) >= {"jobId", "status"}, body

    job = _job(db, body["jobId"])
    assert job.type == JOB_TYPE
    assert (job.payload_json or {}).get("scope") == "full"
    assert (job.payload_json or {}).get("companyId") == company.id
    assert (job.payload_json or {}).get("entityType") == ENTITY_PRODUCT


def test_full_scope_preflight_state_error_422_or_409s_before_any_job_is_created(client, db):
    """A never-configured task (no ``AcEntityConfig`` row at all for this
    entity) still refuses SYNCHRONOUSLY (today's ``EtlStateError`` -> 409,
    unchanged) - no job is ever created for a task that cannot run."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    before = _job_count(db)

    response = client.post(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task/preview",
        json={"scope": "full", "companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=_auth(client),
    )

    assert response.status_code in (404, 409, 422), response.text
    assert _job_count(db) == before


def test_full_scope_never_calls_preview_task_directly_from_the_router(monkeypatch, client, db):
    """sprint-5/11 review round 1 (S9) - the full-scope twin of
    ``test_sample_scope_never_calls_preview_http_directly_from_the_router``:
    the route handler must not call ``EtlService.preview_task`` itself -
    only the job HANDLER may, so the request truly returns before any walk
    happens."""
    import modules.autocount.services.etl_service as etl_service_module

    def _boom(*args, **kwargs):
        raise AssertionError(
            "POST .../etl-task/preview must not call EtlService.preview_task "
            "directly from the request - only the background job handler may."
        )

    monkeypatch.setattr(etl_service_module.EtlService, "preview_task", _boom)

    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)

    response = client.post(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task/preview",
        json={"scope": "full", "companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=_auth(client),
    )
    # A 500 here would mean the assertion above fired from INSIDE the request
    # (the forbidden direct call happened); any other outcome (202, or a
    # clean 4xx before the job even reaches the handler) is fine.
    assert response.status_code != 500, response.text


# ── AC-11-70/71 - permission + tenant scoping ────────────────────────────────


def test_sample_scope_requires_companies_manage(client, db):
    conn = _open_connection(db)
    _limited_user(db, ["autocount.companies.read"], "noviewer-sample@example.com")
    limited = _auth(client, "noviewer-sample@example.com", "limited1234")

    response = client.post(
        "/autocount/http/preview",
        json={"scope": "sample", "connectionId": conn.id, "path": "/itembypage"},
        headers=limited,
    )
    assert response.status_code == 403, response.text


def test_full_scope_requires_sync_run(client, db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)
    _limited_user(db, ["autocount.companies.read"], "noviewer-full@example.com")
    limited = _auth(client, "noviewer-full@example.com", "limited1234")

    response = client.post(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task/preview",
        json={"scope": "full", "companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=limited,
    )
    assert response.status_code == 403, response.text


def test_get_preview_job_requires_a_read_key_and_404s_cross_tenant(client, db):
    _other_tenant(db)
    other_job = BackgroundJob(
        tenant_id=OTHER_TENANT, type=JOB_TYPE, status=JOB_DONE,
        payload_json={"scope": "sample", "companyId": "x", "entityType": "product"},
    )
    db.add(other_job)
    db.commit()

    response = client.get(f"/autocount/previews/{other_job.id}", headers=_auth(client))
    assert response.status_code == 404, response.text


def test_cancel_preview_job_requires_companies_manage_and_404s_cross_tenant(client, db):
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=JOB_TYPE, status=JOB_RUNNING,
        payload_json={"scope": "sample", "companyId": "x", "entityType": "product"},
    )
    db.add(job)
    db.commit()

    _limited_user(db, ["autocount.companies.read"], "nocancel@example.com")
    limited = _auth(client, "nocancel@example.com", "limited1234")
    response = client.post(f"/autocount/previews/{job.id}/cancel", headers=limited)
    assert response.status_code == 403, response.text

    _other_tenant(db)
    theirs = BackgroundJob(
        tenant_id=OTHER_TENANT, type=JOB_TYPE, status=JOB_RUNNING,
        payload_json={"scope": "sample", "companyId": "x", "entityType": "product"},
    )
    db.add(theirs)
    db.commit()
    response = client.post(f"/autocount/previews/{theirs.id}/cancel", headers=_auth(client))
    assert response.status_code == 404, response.text


# ── sprint-5/11 review round 1 (S1) - the poll route stays on companies.read
# for status/progress, but withholds `result` (the walked rows / dry-run
# predictions) unless the caller ALSO holds the scope's own start key -
# companies.manage for sample, autocount.sync.run for full. Resolved in the
# SERVICE (`PreviewJobService._can_see_result`), never the router.


def test_get_preview_job_omits_result_for_a_sample_job_without_companies_manage(client, db):
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=JOB_TYPE, status=JOB_DONE,
        payload_json={"scope": "sample", "companyId": "x", "entityType": "product"},
        result_json={
            "scope": "sample",
            "preview": {"envelope": "list", "columns": [], "rows": [{"ItemCode": "A1"}], "durationMs": 1},
        },
    )
    db.add(job)
    db.commit()

    _limited_user(db, ["autocount.companies.read"], "readonly-sample@example.com")
    limited = _auth(client, "readonly-sample@example.com", "limited1234")

    response = client.get(f"/autocount/previews/{job.id}", headers=limited)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "done", body
    assert body["result"] is None, body


def test_get_preview_job_includes_result_for_a_sample_job_with_companies_manage(client, db):
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=JOB_TYPE, status=JOB_DONE,
        payload_json={"scope": "sample", "companyId": "x", "entityType": "product"},
        result_json={
            "scope": "sample",
            "preview": {"envelope": "list", "columns": [], "rows": [{"ItemCode": "A1"}], "durationMs": 1},
        },
    )
    db.add(job)
    db.commit()

    _limited_user(
        db, ["autocount.companies.read", "autocount.companies.manage"], "manager-sample@example.com"
    )
    manager = _auth(client, "manager-sample@example.com", "limited1234")

    response = client.get(f"/autocount/previews/{job.id}", headers=manager)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] is not None, body
    assert body["result"]["scope"] == "sample"


def test_get_preview_job_omits_result_for_a_full_job_without_sync_run(client, db):
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=JOB_TYPE, status=JOB_DONE,
        payload_json={"scope": "full", "companyId": "x", "entityType": "product"},
        result_json={
            "scope": "full", "task": {},
            "preview": {
                "previewable": True, "sink": "sorento",
                "summary": {"total": 0, "created": 0, "updated": 0, "failed": 0, "retryable": 0},
                "predictions": [],
            },
        },
    )
    db.add(job)
    db.commit()

    # companies.manage alone (no sync.run) is the SAMPLE scope's own start
    # key, deliberately insufficient here - proves the gate is per-SCOPE,
    # not just "any start key".
    _limited_user(
        db, ["autocount.companies.read", "autocount.companies.manage"], "readonly-full@example.com"
    )
    limited = _auth(client, "readonly-full@example.com", "limited1234")

    response = client.get(f"/autocount/previews/{job.id}", headers=limited)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] is None, body


def test_get_preview_job_includes_result_for_a_full_job_with_sync_run(client, db):
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=JOB_TYPE, status=JOB_DONE,
        payload_json={"scope": "full", "companyId": "x", "entityType": "product"},
        result_json={
            "scope": "full", "task": {},
            "preview": {
                "previewable": True, "sink": "sorento",
                "summary": {"total": 0, "created": 0, "updated": 0, "failed": 0, "retryable": 0},
                "predictions": [],
            },
        },
    )
    db.add(job)
    db.commit()

    _limited_user(
        db, ["autocount.companies.read", "autocount.sync.run"], "sync-full@example.com"
    )
    manager = _auth(client, "sync-full@example.com", "limited1234")

    response = client.get(f"/autocount/previews/{job.id}", headers=manager)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] is not None, body
    assert body["result"]["scope"] == "full"


# ── the wire status vocabulary translation (AC-11-22/27) ───────────────────


@pytest.mark.parametrize(
    "backend_status, wire_status",
    [
        (JOB_PENDING, "queued"),
        (JOB_RUNNING, "running"),
        (JOB_DONE, "done"),
        (JOB_FAILED, "failed"),
        (JOB_ABORTED, "cancelled"),
    ],
)
def test_get_preview_job_translates_the_backend_status_onto_the_wire_vocabulary(
    client, db, backend_status, wire_status,
):
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=JOB_TYPE, status=backend_status,
        payload_json={"scope": "sample", "companyId": "x", "entityType": "product"},
    )
    db.add(job)
    db.commit()

    response = client.get(f"/autocount/previews/{job.id}", headers=_auth(client))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == wire_status, body
    assert body["id"] == job.id
    assert body["scope"] == "sample"
    for key in ("progress", "result", "error", "taskError", "createdAt"):
        assert key in body, body


def test_eager_mode_post_returns_an_already_terminal_job(client, db):
    """AC-11-31 - under ``settings.celery_task_always_eager`` (the test/dev
    default) the POST runs the job INLINE, so by the time the response is
    serialized the job is ALREADY terminal (``done``/``failed``), never
    ``queued`` - the UI's first poll must resolve immediately with no
    further transitions to wait for."""
    from app.main import app
    from modules.autocount.http_client import get_http_transport

    conn = _open_connection(db)
    app.dependency_overrides[get_http_transport] = lambda: _single_page_transport(
        [{"ItemCode": "A1", "Description": "Widget"}]
    )
    try:
        response = client.post(
            "/autocount/http/preview",
            json={"scope": "sample", "connectionId": conn.id, "path": "/itembypage"},
            headers=_auth(client),
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] in ("done", "failed"), (
        f"eager mode must return an already-terminal job, got {body['status']!r}"
    )

    poll = client.get(f"/autocount/previews/{body['jobId']}", headers=_auth(client))
    assert poll.status_code == 200, poll.text
    assert poll.json()["status"] == body["status"]


# ── AC-11-23 - the task view echoes the in-flight claim ─────────────────────


def test_get_etl_task_exposes_preview_job_id_only_while_claimed(client, db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)

    unclaimed = client.get(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task",
        headers=_auth(client),
    )
    assert unclaimed.status_code == 200, unclaimed.text
    assert unclaimed.json().get("previewJobId") in (None, ""), unclaimed.json()

    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=JOB_TYPE, status=JOB_RUNNING,
        payload_json={"scope": "sample", "companyId": company.id, "entityType": ENTITY_PRODUCT},
    )
    db.add(job)
    db.flush()
    config = (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == DEFAULT_TENANT_ID,
            AcEntityConfig.company_id == company.id,
            AcEntityConfig.entity_type == ENTITY_PRODUCT,
        )
        .one()
    )
    config.preview_job_id = job.id
    db.commit()

    claimed = client.get(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task",
        headers=_auth(client),
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json().get("previewJobId") == job.id, claimed.json()
