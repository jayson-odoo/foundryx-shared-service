"""Sprint-5/11 S4 - AC-11-25 (failure never silently swallowed, nothing
stamped), AC-11-26 (the AC-08-20 save gate preserved exactly), AC-11-29 (the
column probe's Cloudflare-safe timeout ceiling) and AC-11-30 (the stored
result caps ``predictions`` at 500 with ``predictionsTruncated``).

RED before the coder: same reasons as the sibling S4 files in this batch -
the job type/routes/claim do not exist yet, so every POST below either
misbehaves (200 sync body, not 202) or the job never reaches the assertions
this file makes about ``result_json``/task stamps.
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest
import sqlalchemy as sa

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import (
    ETL_STATUS_DRAFT,
    SINK_IMPL_SORENTO,
    SOURCE_IMPL_AUTOCOUNT_HTTP,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)
from modules.autocount.services.company_service import CompanyService
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


def _open_connection(db, *, timeout_seconds: str = None) -> Connection:
    config = {"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"}
    if timeout_seconds is not None:
        config["requestTimeoutSeconds"] = timeout_seconds
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="s11-s4 stamp REST",
        config_json=config, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="S11S4STAMP",
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


def _point_at_sorento(db, company, *, timeout_seconds=None) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider=SORENTO_PROVIDER_KEY, type="consumer",
        name="Sorento", config_json={"baseUrl": "http://sorento.test"},
        credentials_json=encrypt_secret({"apiKey": "sk_test"}),
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id, sink_impl=SINK_IMPL_SORENTO,
        sink_connection_id=conn.id, sorento_company_code="SRT",
    )
    db.refresh(company)
    return conn


def _dry_run_response(request: httpx.Request, *, failed_refs: set = frozenset()) -> httpx.Response:
    import json as _json

    body = _json.loads(request.content)
    records = body.get("records", [])
    recs = []
    failed = 0
    for r in records:
        ref = r["source_ref"]
        if ref in failed_refs:
            recs.append({"source_ref": ref, "outcome": "failed", "errors": ["boom"]})
            failed += 1
        else:
            recs.append({"source_ref": ref, "outcome": "created", "entity_id": f"id-{ref}"})
    n = len(recs)
    return httpx.Response(200, json={
        "summary": {
            "total": n, "created": n - failed, "updated": 0, "failed": failed, "retryable": 0,
        },
        "records": recs,
    })


def _patch_http_transport(monkeypatch, transport: httpx.Client) -> None:
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(
            base_url, transport=transport, timeout_seconds=kw.get("timeout_seconds"),
        ),
    )


def _patch_sorento_sink(monkeypatch, transport: httpx.Client) -> None:
    """A full-scope dry run ALSO opens a real ``SorentoSink`` client (its own
    ``httpx.Client``, independent of the source's ``HttpApiClient`` above) -
    forgetting this patch is a real test bug, not a legitimate RED: the sink
    call would hit the autouse live-network guard regardless of whether the
    S4 job/route work has landed, so it teaches nothing about the feature
    under test. Mirrors ``test_autocount_pipeline.py``'s own ``sorento_sink``
    fixture: the CALLER's own ``transport=None`` (production never passes
    one) is unconditionally REPLACED with the given stub, shared with the
    source patch above via the SAME path-dispatching handler."""
    import modules.autocount.services.company_service as company_module
    from modules.autocount.sinks_sorento import sorento_sink_from_connection as real

    stub_transport = transport

    def fake(config, credentials, *, entity_type, company_code=None, transport=None):
        # The incoming ``transport`` kwarg (always ``None`` in production) is
        # deliberately IGNORED - every dry run in this file goes through the
        # ONE stub captured above.
        return real(
            config, credentials, entity_type=entity_type, company_code=company_code,
            transport=stub_transport,
        )

    monkeypatch.setattr(company_module, "sorento_sink_from_connection", fake)


# ── AC-11-26 - the sample scope's save gate, exactly as preview_http today ──


def test_a_successful_sample_job_stamps_result_columns_and_last_preview_at(client, db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)

    from app.main import app
    from modules.autocount.http_client import get_http_transport

    app.dependency_overrides[get_http_transport] = lambda: _single_page_transport(
        [{"ItemCode": "A1", "Description": "Widget"}]
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
    assert config.last_preview_at is not None
    assert "ItemCode" in config.result_columns

    poll = client.get(f"/autocount/previews/{response.json()['jobId']}", headers=_auth(client))
    result = poll.json()["result"]
    assert result["scope"] == "sample"
    assert result["preview"]["columns"], result
    # AC-11-26 - "its job result carries the SAME task echo the route used to
    # return, so the Source tab adopts the fresh stamp with no second GET".
    echoed_task = result["preview"].get("task")
    assert echoed_task is not None, result
    assert echoed_task["lastPreviewAt"] is not None


def test_a_failed_sample_job_stamps_nothing_and_reports_a_field_error(client, db):
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

    config = _entity_config(db, company.id)
    assert config.last_preview_at is None
    assert config.result_columns == []

    poll = client.get(f"/autocount/previews/{response.json()['jobId']}", headers=_auth(client))
    body = poll.json()
    assert body["status"] == "failed", body
    assert body["error"], body
    assert body["result"] is None, body


# ── AC-11-26 - the full scope's save gate, exactly as preview_task today ────


def test_a_successful_full_job_stamps_last_preview_at_and_failed_count(client, db, monkeypatch):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)
    _point_at_sorento(db, company)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/itembypage"):
            return httpx.Response(200, json={
                "TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                "Data": [{"ItemCode": "A1", "Description": "Widget"}],
            })
        return _dry_run_response(request)

    # ONE bare MockTransport, wrapped differently for each client: the
    # source's ``HttpApiClient`` wants a full ``httpx.Client``
    # (house convention, used AS-IS); the Sorento sink wants the BARE
    # transport (its own ``_call`` builds a fresh ``httpx.Client`` per
    # request internally, so a pre-built Client instance would raise
    # "Cannot reopen a client instance" on the second call).
    mock_transport = httpx.MockTransport(handler)
    _patch_http_transport(monkeypatch, httpx.Client(transport=mock_transport))
    _patch_sorento_sink(monkeypatch, mock_transport)

    response = client.post(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task/preview",
        json={"scope": "full", "companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=_auth(client),
    )
    assert response.status_code == 202, response.text

    config = _entity_config(db, company.id)
    assert config.last_preview_at is not None
    assert config.last_preview_failed_count == 0

    poll = client.get(f"/autocount/previews/{response.json()['jobId']}", headers=_auth(client))
    result = poll.json()["result"]
    assert result["scope"] == "full"
    assert result["preview"]["summary"]["total"] == 1


def test_a_failed_full_job_stamps_nothing(client, db, monkeypatch):
    """A source-page failure mid-walk (one of AC-11-25's named fault
    classes) leaves the task's stamps untouched."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)
    _point_at_sorento(db, company)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream boom")

    # ONE bare MockTransport, wrapped differently for each client: the
    # source's ``HttpApiClient`` wants a full ``httpx.Client``
    # (house convention, used AS-IS); the Sorento sink wants the BARE
    # transport (its own ``_call`` builds a fresh ``httpx.Client`` per
    # request internally, so a pre-built Client instance would raise
    # "Cannot reopen a client instance" on the second call).
    mock_transport = httpx.MockTransport(handler)
    _patch_http_transport(monkeypatch, httpx.Client(transport=mock_transport))
    _patch_sorento_sink(monkeypatch, mock_transport)

    response = client.post(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task/preview",
        json={"scope": "full", "companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=_auth(client),
    )
    assert response.status_code == 202, response.text

    config = _entity_config(db, company.id)
    assert config.last_preview_at is None
    assert config.last_preview_failed_count is None

    poll = client.get(f"/autocount/previews/{response.json()['jobId']}", headers=_auth(client))
    body = poll.json()
    assert body["status"] == "failed", body
    assert body["error"], body


# ── AC-11-25 - the fault classes the S4 red batch left uncovered ────────────
#
# Driven at the SAME seam ``test_s10_s3_pull_build_error_codes.py`` already
# uses for the pull-snapshot job's own error ladder: a fake ``HttpApiSource``
# that raises the EXACT ``HttpSourceError`` shape the real walker would
# raise, isolating the preview job's own fault-class handling from the
# walker's internals (already covered elsewhere - ``test_s10_http_retry.py``
# for the row cap, ``http_source/source.py``'s own ``phase="enrich"`` tag for
# a lookup-endpoint failure). ``_extract_and_map`` imports ``HttpApiSource``
# LOCALLY (``from ..http_source.source import HttpApiSource`` inside the
# function body), so patching the NAME on its home module is what a local
# import actually resolves against.


def _fake_http_source_raising(exc: HttpSourceError):
    class _FakeSource:
        def fetch_changes(self, since):
            raise exc

        def close(self):
            pass

    def factory(ctx, **kwargs):
        return _FakeSource()

    return factory


def test_a_lookup_endpoint_failure_fails_the_job_and_stamps_nothing(client, db, monkeypatch):
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.errors import HttpSourceError

    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)
    _point_at_sorento(db, company)

    exc = HttpSourceError(
        "The 'uom' lookup endpoint '/itemuombypage' failed: AutoCount answered "
        "HTTP 500 on page 1.",
        code="http_status", page=1, status=500, phase="enrich",
    )
    monkeypatch.setattr(http_source_module, "HttpApiSource", _fake_http_source_raising(exc))

    response = client.post(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task/preview",
        json={"scope": "full", "companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=_auth(client),
    )
    assert response.status_code == 202, response.text

    config = _entity_config(db, company.id)
    assert config.last_preview_at is None
    assert config.last_preview_failed_count is None

    poll = client.get(f"/autocount/previews/{response.json()['jobId']}", headers=_auth(client))
    body = poll.json()
    assert body["status"] == "failed", body
    assert "lookup" in body["error"].lower(), body


def test_a_shape_change_mid_walk_fails_the_job_and_stamps_nothing(client, db, monkeypatch):
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.errors import HttpSourceError

    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)
    _point_at_sorento(db, company)

    exc = HttpSourceError(
        "Page 2 answered a 'list' shape but page 1 was 'paged'.",
        code="shape_change", page=2, status=200,
    )
    monkeypatch.setattr(http_source_module, "HttpApiSource", _fake_http_source_raising(exc))

    response = client.post(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task/preview",
        json={"scope": "full", "companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=_auth(client),
    )
    assert response.status_code == 202, response.text

    config = _entity_config(db, company.id)
    assert config.last_preview_at is None
    assert config.last_preview_failed_count is None

    poll = client.get(f"/autocount/previews/{response.json()['jobId']}", headers=_auth(client))
    body = poll.json()
    assert body["status"] == "failed", body
    assert "shape" in body["error"].lower(), body


def test_a_row_cap_breach_fails_the_job_and_stamps_nothing(client, db, monkeypatch):
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.errors import HttpSourceError

    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)
    _point_at_sorento(db, company)

    exc = HttpSourceError(
        "This task's extract exceeded the 200000 row cap.", code="row_limit", page=7,
    )
    monkeypatch.setattr(http_source_module, "HttpApiSource", _fake_http_source_raising(exc))

    response = client.post(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task/preview",
        json={"scope": "full", "companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=_auth(client),
    )
    assert response.status_code == 202, response.text

    config = _entity_config(db, company.id)
    assert config.last_preview_at is None
    assert config.last_preview_failed_count is None

    poll = client.get(f"/autocount/previews/{response.json()['jobId']}", headers=_auth(client))
    body = poll.json()
    assert body["status"] == "failed", body
    assert "row cap" in body["error"].lower(), body


def test_an_unreachable_sink_fails_the_full_job_and_stamps_nothing(client, db, monkeypatch):
    """AC-11-25's own named class: an unreachable Sorento sink during the
    dry run (``PreviewUnavailable``) - the SOURCE walk succeeds, the
    consumer call fails at the transport level."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)
    _point_at_sorento(db, company)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/itembypage"):
            return httpx.Response(200, json={
                "TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                "Data": [{"ItemCode": "A1", "Description": "Widget"}],
            })
        raise httpx.ConnectError("connection refused", request=request)

    mock_transport = httpx.MockTransport(handler)
    _patch_http_transport(monkeypatch, httpx.Client(transport=mock_transport))
    _patch_sorento_sink(monkeypatch, mock_transport)

    response = client.post(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task/preview",
        json={"scope": "full", "companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=_auth(client),
    )
    assert response.status_code == 202, response.text

    config = _entity_config(db, company.id)
    assert config.last_preview_at is None
    assert config.last_preview_failed_count is None

    poll = client.get(f"/autocount/previews/{response.json()['jobId']}", headers=_auth(client))
    body = poll.json()
    assert body["status"] == "failed", body
    assert body["error"], body


# ── AC-11-30 - the stored result caps predictions at 500 ────────────────────


def test_a_900_prediction_dry_run_stores_500_rows_the_flag_and_the_full_summary(
    client, db, monkeypatch,
):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _http_task(db, company, conn.id)
    _point_at_sorento(db, company)

    rows = [{"ItemCode": f"P{i:04d}", "Description": f"Item {i}"} for i in range(900)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/itembypage"):
            return httpx.Response(200, json={
                "TotalCount": len(rows), "Page": 1, "PageSize": 1000, "TotalPages": 1,
                "Data": rows,
            })
        return _dry_run_response(request)

    # ONE bare MockTransport, wrapped differently for each client: the
    # source's ``HttpApiClient`` wants a full ``httpx.Client``
    # (house convention, used AS-IS); the Sorento sink wants the BARE
    # transport (its own ``_call`` builds a fresh ``httpx.Client`` per
    # request internally, so a pre-built Client instance would raise
    # "Cannot reopen a client instance" on the second call).
    mock_transport = httpx.MockTransport(handler)
    _patch_http_transport(monkeypatch, httpx.Client(transport=mock_transport))
    _patch_sorento_sink(monkeypatch, mock_transport)

    response = client.post(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task/preview",
        json={"scope": "full", "companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=_auth(client),
    )
    assert response.status_code == 202, response.text

    poll = client.get(f"/autocount/previews/{response.json()['jobId']}", headers=_auth(client))
    result = poll.json()["result"]
    preview = result["preview"]
    assert len(preview["predictions"]) == 500, len(preview["predictions"])
    assert preview.get("predictionsTruncated") is True, preview
    assert preview["summary"]["total"] == 900, preview["summary"]
    assert preview["summary"]["created"] == 900, preview["summary"]


# ── AC-11-29 - the column probe's Cloudflare-safe timeout ceiling ───────────


def test_preview_columns_clamps_a_100s_connection_timeout_to_the_45s_ceiling(client, db, monkeypatch):
    import modules.autocount.services.etl_service as etl_service_module

    conn = _open_connection(db, timeout_seconds="100")
    captured: Dict[str, Any] = {}
    real_run_http_preview = etl_service_module.run_http_preview

    def _spy(*args, **kwargs):
        captured.update(kwargs)
        return real_run_http_preview(*args, **kwargs)

    monkeypatch.setattr(etl_service_module, "run_http_preview", _spy)

    from app.main import app
    from modules.autocount.http_client import get_http_transport

    app.dependency_overrides[get_http_transport] = lambda: _single_page_transport(
        [{"ItemCode": "A1"}]
    )
    try:
        response = client.post(
            "/autocount/http/preview-columns",
            json={"connectionId": conn.id, "path": "/itembypage"},
            headers=_auth(client),
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)

    assert response.status_code == 200, response.text
    assert captured.get("timeout_seconds") == 45.0, (
        f"a 100s connection timeout must clamp to the 45s "
        f"PREVIEW_REQUEST_TIMEOUT_CEILING_SECONDS ceiling; captured: {captured!r}"
    )


def test_preview_columns_leaves_a_30s_connection_timeout_unclamped_control(client, db, monkeypatch):
    import modules.autocount.services.etl_service as etl_service_module

    conn = _open_connection(db, timeout_seconds="30")
    captured: Dict[str, Any] = {}
    real_run_http_preview = etl_service_module.run_http_preview

    def _spy(*args, **kwargs):
        captured.update(kwargs)
        return real_run_http_preview(*args, **kwargs)

    monkeypatch.setattr(etl_service_module, "run_http_preview", _spy)

    from app.main import app
    from modules.autocount.http_client import get_http_transport

    app.dependency_overrides[get_http_transport] = lambda: _single_page_transport(
        [{"ItemCode": "A1"}]
    )
    try:
        response = client.post(
            "/autocount/http/preview-columns",
            json={"connectionId": conn.id, "path": "/itembypage"},
            headers=_auth(client),
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)

    assert response.status_code == 200, response.text
    assert captured.get("timeout_seconds") == 30.0, (
        f"a 30s connection timeout (below the 45s ceiling) must pass through "
        f"unclamped; captured: {captured!r}"
    )
