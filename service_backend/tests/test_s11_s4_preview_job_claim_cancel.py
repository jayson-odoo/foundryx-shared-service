"""Sprint-5/11 S4 - AC-11-23 (one preview per task, re-attachable, claim
released on every terminal path) and AC-11-24 (cooperative cancel).

RED before the coder: ``AcEntityConfig`` has no ``preview_job_id`` column at
all yet (an ``AttributeError``/mapper error - a "missing feature" RED), and
neither ``POST /autocount/previews/{jobId}/cancel`` nor the claim exist.

ASSUMED NAMES (flagged per house convention - the coder confirms rather than
silently renames): the claim column is ``AcEntityConfig.preview_job_id``
(pinned by the plan's own text and by ``types/autocount.ts``'s
``previewJobId``, not a guess); the module's ``on_job_orphaned`` hook (already
real, ``modules/autocount/bootstrap.py``) gains a branch for
``autocount_source_preview`` mirroring its existing ``autocount_sync``/
``autocount_pull_snapshot`` branches.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx
import pytest
import sqlalchemy as sa

from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.models.background_job import (
    JOB_ABORTED,
    JOB_DONE,
    JOB_FAILED,
    JOB_RUNNING,
    BackgroundJob,
)
from app.models.connection import Connection
from app.repositories.permission_repository import PermissionRepository
from app.secrets import encrypt_secret
from app.security import hash_password
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import (
    ETL_STATUS_DRAFT,
    SINK_IMPL_SORENTO,
    SOURCE_IMPL_AUTOCOUNT_HTTP,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)
from modules.autocount.sorento_provider import SORENTO_PROVIDER_KEY

JOB_TYPE = "autocount_source_preview"


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
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


def _open_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="s11-s4 claim REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="S11S4CLAIM",
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _http_task(db, company, connection_id, *, entity_type=ENTITY_PRODUCT) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
        source_impl=SOURCE_IMPL_AUTOCOUNT_HTTP, etl_status=ETL_STATUS_DRAFT,
        source_config={
            "connectionId": connection_id, "path": "/itembypage",
            "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
            "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
            "reconcileAt": "02:00", "lookups": [],
        },
    )
    db.add(config)
    db.add(
        AcFieldMapping(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
            scope="header", sort_order=0, source_path="ItemCode", canonical_field="code",
            transform="string", is_required=True, formula=None,
        )
    )
    db.commit()
    db.refresh(config)
    return config


def _entity_config(db, company_id: str, entity_type: str = ENTITY_PRODUCT) -> AcEntityConfig:
    return (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == DEFAULT_TENANT_ID,
            AcEntityConfig.company_id == company_id,
            AcEntityConfig.entity_type == entity_type,
        )
        .one()
    )


def _single_page_transport(rows: List[Dict[str, Any]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"TotalCount": len(rows), "Page": 1, "PageSize": 50, "TotalPages": 1, "Data": rows},
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def _failing_transport() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream boom")

    return httpx.Client(transport=httpx.MockTransport(handler))


def _preview_jobs(db) -> List[BackgroundJob]:
    return (
        db.query(BackgroundJob)
        .filter(BackgroundJob.type == JOB_TYPE, BackgroundJob.tenant_id == DEFAULT_TENANT_ID)
        .order_by(BackgroundJob.created_at.asc())
        .all()
    )


# ── AC-11-23 - one preview per task, re-attachable ───────────────────────────


def test_a_second_sample_post_reattaches_to_an_already_claimed_job(client, db):
    """The claim is set BEFORE the walk starts (an atomic
    ``UPDATE ... WHERE preview_job_id IS NULL``); a task that already carries
    a non-terminal claim must not start a second walk - the second POST
    returns the SAME jobId and no second ``autocount_source_preview`` row is
    created."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)

    in_flight = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=JOB_TYPE, status=JOB_RUNNING,
        payload_json={
            "scope": "sample", "companyId": company.id, "entityType": ENTITY_PRODUCT,
            "request": {"connectionId": conn.id, "path": "/itembypage"},
        },
    )
    db.add(in_flight)
    db.flush()
    config = _entity_config(db, company.id)
    config.preview_job_id = in_flight.id
    db.commit()

    from app.main import app
    from modules.autocount.http_client import get_http_transport

    app.dependency_overrides[get_http_transport] = lambda: _single_page_transport(
        [{"ItemCode": "A1"}]
    )
    try:
        response = client.post(
            "/autocount/http/preview",
            json={
                "scope": "sample", "companyId": company.id, "entityType": ENTITY_PRODUCT,
                "connectionId": conn.id, "path": "/itembypage",
            },
            headers=_auth(client),
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)

    assert response.status_code == 202, response.text
    assert response.json()["jobId"] == in_flight.id, (
        "a second click while a preview is already claimed must re-attach to "
        "the SAME job id, never start a second walk"
    )
    assert len(_preview_jobs(db)) == 1, "a re-attach must never create a second job row"


def test_the_claim_column_holds_exactly_the_winning_jobs_id(client, db):
    """Direct pin on the claim column itself, not just the HTTP response -
    the atomic ``UPDATE ... WHERE preview_job_id IS NULL`` is the mechanism
    AC-11-23 names."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)

    from app.main import app
    from modules.autocount.http_client import get_http_transport

    app.dependency_overrides[get_http_transport] = lambda: _single_page_transport(
        [{"ItemCode": "A1"}]
    )
    try:
        first = client.post(
            "/autocount/http/preview",
            json={
                "scope": "sample", "companyId": company.id, "entityType": ENTITY_PRODUCT,
                "connectionId": conn.id, "path": "/itembypage",
            },
            headers=_auth(client),
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)
    assert first.status_code == 202, first.text

    # Under this suite's eager execution the winning job is ALREADY terminal
    # by the time the response lands, so its claim is already released
    # (AC-11-23's "released on every terminal path") - simulate a STILL
    # in-flight winner instead by re-claiming directly, then assert the
    # SAME conditional-update guarantee holds for a genuinely-in-flight row.
    config = _entity_config(db, company.id)
    winner = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=JOB_TYPE, status=JOB_RUNNING,
        payload_json={"scope": "sample", "companyId": company.id, "entityType": ENTITY_PRODUCT},
    )
    db.add(winner)
    db.flush()
    config.preview_job_id = winner.id
    db.commit()

    app.dependency_overrides[get_http_transport] = lambda: _single_page_transport(
        [{"ItemCode": "A2"}]
    )
    try:
        second = client.post(
            "/autocount/http/preview",
            json={
                "scope": "sample", "companyId": company.id, "entityType": ENTITY_PRODUCT,
                "connectionId": conn.id, "path": "/itembypage",
            },
            headers=_auth(client),
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)

    assert second.status_code == 202, second.text
    assert second.json()["jobId"] == winner.id
    db.refresh(config)
    assert config.preview_job_id == winner.id, (
        "the claim column must still hold the FIRST (winning) job id, "
        "untouched by the loser's request"
    )


# ── AC-11-23 - the claim is released on every terminal path ─────────────────


def test_claim_is_released_when_a_sample_job_completes(client, db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)

    from app.main import app
    from modules.autocount.http_client import get_http_transport

    app.dependency_overrides[get_http_transport] = lambda: _single_page_transport(
        [{"ItemCode": "A1"}]
    )
    try:
        response = client.post(
            "/autocount/http/preview",
            json={
                "scope": "sample", "companyId": company.id, "entityType": ENTITY_PRODUCT,
                "connectionId": conn.id, "path": "/itembypage",
            },
            headers=_auth(client),
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)

    assert response.status_code == 202, response.text
    config = _entity_config(db, company.id)
    assert config.preview_job_id is None, (
        "a DONE preview must release the claim - a re-attach would otherwise "
        "block the Source tab's Test button forever"
    )


def test_claim_is_released_when_a_sample_job_fails(client, db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)

    from app.main import app
    from modules.autocount.http_client import get_http_transport

    app.dependency_overrides[get_http_transport] = lambda: _failing_transport()
    try:
        response = client.post(
            "/autocount/http/preview",
            json={
                "scope": "sample", "companyId": company.id, "entityType": ENTITY_PRODUCT,
                "connectionId": conn.id, "path": "/itembypage",
            },
            headers=_auth(client),
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)

    assert response.status_code == 202, response.text
    job = db.query(BackgroundJob).filter(BackgroundJob.id == response.json()["jobId"]).one()
    assert job.status == JOB_FAILED, job.status
    config = _entity_config(db, company.id)
    assert config.preview_job_id is None


def test_claim_is_released_by_the_orphan_sweeps_module_hook(db):
    """AC-11-23's own test wording: 'a hook-closed job leaves preview_job_id
    NULL so the next Test is not blocked forever' - driven directly against
    ``JobService.fail_orphaned_running_jobs`` (the SAME sweep
    ``on_job_orphaned`` already serves for ``autocount_sync``/
    ``autocount_pull_snapshot``, AC-11-52)."""
    from app.jobs.service import JobService

    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)

    stale = datetime.now(timezone.utc) - timedelta(hours=1)
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=JOB_TYPE, status=JOB_RUNNING,
        payload_json={"scope": "sample", "companyId": company.id, "entityType": ENTITY_PRODUCT},
        started_at=stale, heartbeat_at=stale, created_at=stale,
    )
    db.add(job)
    db.flush()
    config = _entity_config(db, company.id)
    config.preview_job_id = job.id
    db.commit()

    swept = JobService(db).fail_orphaned_running_jobs(
        older_than=timedelta(minutes=15), now=datetime.now(timezone.utc),
    )
    assert swept == 1, "the sweep must judge autocount_source_preview (heartbeats=True)"

    db.refresh(job)
    assert job.status == JOB_FAILED
    db.refresh(config)
    assert config.preview_job_id is None, (
        "the orphan sweep's module hook must release the claim exactly as "
        "a normal done/failed job does"
    )


# ── AC-11-24 - cooperative cancel ────────────────────────────────────────────


def test_cancel_on_a_terminal_job_is_a_no_op_200_carrying_the_terminal_status(client, db):
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=JOB_TYPE, status=JOB_DONE,
        payload_json={"scope": "sample", "companyId": "x", "entityType": ENTITY_PRODUCT},
        result_json={"scope": "sample", "preview": {"envelope": "list", "columns": [], "rows": [], "durationMs": 1}},
    )
    db.add(job)
    db.commit()

    response = client.post(f"/autocount/previews/{job.id}/cancel", headers=_auth(client))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "done", response.json()


def test_cancel_stops_a_multi_page_full_scope_walk_before_it_completes(
    monkeypatch, client, session_factory,
):
    """AC-11-24 - a cooperative checkpoint mid-walk. Exercised end to end
    through the SAME session the request itself uses (``get_db`` overridden
    to a single held-open session), so a status flip fired from INSIDE the
    stub transport - simulating a concurrent cancel landing mid-walk - is
    visible to the handler's own fresh-status re-read without a genuine
    cross-connection race.

    SOFT assertion on request count (``< 3`` rather than pinned to exactly
    1): AC-11-24 only requires "no further page is requested" once the
    checkpoint observes the abort - the coder may choose to checkpoint
    before or after a given page's mapping step, so this test proves the
    walk stopped EARLY, not the exact page boundary.
    """
    from app.database import get_db
    from app.main import app
    from modules.autocount.services.company_service import CompanyService
    from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

    # A dedicated session, held open for the whole test - the SAME one both
    # the HTTP request and the transport-handler side effect below write
    # through, exactly like ``run_job``'s own single-session contract.
    held = session_factory()

    def override_get_db():
        yield held

    app.dependency_overrides[get_db] = override_get_db

    conn = _open_connection(held)
    company = _company(held, conn.id)
    _http_task(held, company, conn.id)
    sorento_conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider=SORENTO_PROVIDER_KEY, type="consumer",
        name="Sorento", config_json={"baseUrl": "http://sorento.test"},
        credentials_json=encrypt_secret({"apiKey": "sk_test"}),
    )
    held.add(sorento_conn)
    held.commit()
    CompanyService(held).set_sink_target(
        DEFAULT_TENANT_ID, company.id, sink_impl=SINK_IMPL_SORENTO,
        sink_connection_id=sorento_conn.id, sorento_company_code="SRT",
    )
    held.commit()

    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            job = (
                held.query(BackgroundJob)
                .filter(BackgroundJob.type == JOB_TYPE, BackgroundJob.tenant_id == DEFAULT_TENANT_ID)
                .order_by(BackgroundJob.created_at.desc())
                .first()
            )
            assert job is not None, "the preview job row must already exist by page 1"
            job.status = JOB_ABORTED
            held.commit()
        return httpx.Response(
            200,
            json={
                "TotalCount": 3, "Page": len(calls), "PageSize": 1, "TotalPages": 3,
                "Data": [{"ItemCode": f"P{len(calls)}"}],
            },
        )

    transport = httpx.Client(transport=httpx.MockTransport(handler))

    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(
            base_url, transport=transport, timeout_seconds=kw.get("timeout_seconds"),
        ),
    )

    login = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.post(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task/preview",
        json={"scope": "full", "companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=headers,
    )
    app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 202, response.text
    assert len(calls) < 3, (
        f"a cooperative cancel checkpoint should have stopped the walk before "
        f"every page was fetched; got {len(calls)} page request(s)"
    )

    job_id = response.json()["jobId"]
    job = held.query(BackgroundJob).filter(BackgroundJob.id == job_id).one()
    assert job.status == JOB_ABORTED, job.status

    config = _entity_config(held, company.id)
    assert config.preview_job_id is None, "cancel must release the claim"
    assert config.last_preview_at is None, "a cancelled preview must stamp nothing on the task"
    held.close()
