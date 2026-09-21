"""Sprint-5/11 S5 - AC-11-40, contract 2: both handlers (the
``autocount_source_preview`` job's ``full`` scope, and
``autocount_pull_snapshot``'s ``_run_pull_snapshot``) stamp the SAME named
stages, in order, as they advance - via ``JobService.beat_progress`` (S5's
own single-UPDATE helper, pinned in ``test_s11_s5_progress_beat.py``).
Stage names exactly: ``source``, ``lookup:<alias>``, ``combine``,
``mapping``, ``dry_run``, ``storing``.

Scope of this file (stated so a reader is not surprised by what is absent):
``combine`` is NOT independently pinned here - a real combine-carrying task
needs grouping/measure fixtures well beyond a stage-ordering test, and
neither handler's stage sequence NEEDS a combine step to exist for the rest
of the walk to proceed. Its firing is left to the coder's own judgement
(fires only when the task's own `combine` config is present) and is named
as an open item in the tester's final report, never silently assumed.

RED before the coder: ``JobService.beat_progress`` does not exist yet, so
``stage_spy`` fails every test in this file EXPLICITLY (never a bare
AttributeError at collection - the fixture's own ``pytest.fail`` names the
missing method), before a single stub HTTP request is even built.

Fixtures mirror the established house style byte-for-byte:
``test_s11_s4_preview_job_stamping_cap_timeout.py`` (the full-scope preview
job + Sorento dry-run stub pair) and ``test_s10_s3_snapshot_build_job.py`` /
``test_s10_http_lookups.py`` (the pull-snapshot build + the lookup alias
``"as": "uom"`` convention, already used by
``test_s11_s4_preview_job_progress_projection.py``'s own ``"lookup:uom"``
fixture - so the alias resolved here is not a new guess, it is the
established one).
"""
from __future__ import annotations

import json as _json
from typing import Any, Dict, List

import httpx
import pytest

from app.jobs.service import JobService
from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    ETL_STATUS_DRAFT,
    SINK_IMPL_SORENTO,
    SOURCE_IMPL_AUTOCOUNT_HTTP,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sorento_provider import SORENTO_PROVIDER_KEY

ROW_INSERT_HEARTBEAT_INTERVAL = 200  # mirrors modules.autocount.sync's own constant


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


@pytest.fixture
def stage_spy(monkeypatch):
    """Wraps ``JobService.beat_progress`` (if it exists) recording every
    ``stage`` kwarg in call order, while delegating to the REAL
    implementation - so the handler's own writes still happen and every
    other assertion in a test (job status, snapshot status) still reflects
    reality. If ``beat_progress`` does not exist yet, fails immediately and
    explicitly: the right RED reason for this whole file."""
    if not hasattr(JobService, "beat_progress"):
        pytest.fail(
            "JobService.beat_progress does not exist yet (sprint-5/11 S5, "
            "AC-11-40) - the stage sequence cannot be pinned until it does."
        )
    stages: List[Any] = []
    original = JobService.beat_progress

    def spy(self, job_id, *, done=None, total=None, stage=None):
        stages.append(stage)
        return original(self, job_id, done=done, total=total, stage=stage)

    monkeypatch.setattr(JobService, "beat_progress", spy)
    return stages


def _assert_subsequence(expected: List[str], actual: List[str]) -> None:
    """Every item of ``expected`` appears in ``actual`` IN ORDER - extras
    and repeats interleaved are fine (a multi-page walk beats "source"
    several times); this only pins relative ordering, never an exact call
    count."""
    it = iter(actual)
    for item in expected:
        for seen in it:
            if seen == item:
                break
        else:
            pytest.fail(
                f"stage {item!r} never appeared (in the expected order) in "
                f"the recorded sequence {actual!r}"
            )


def _auth(client, email="demo@example.com", password="demo1234") -> Dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _open_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="s11-s5 stage REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str, *, database_name: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name=database_name,
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _http_task(db, company, connection_id, *, lookups=None) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl=SOURCE_IMPL_AUTOCOUNT_HTTP, etl_status=ETL_STATUS_DRAFT,
        source_config={
            "connectionId": connection_id, "path": "/itembypage",
            "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
            "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
            "reconcileAt": "02:00", "lookups": lookups or [],
        },
    )
    db.add(config)
    db.add(AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        scope="header", sort_order=0, source_path="ItemCode", canonical_field="code",
        transform="string", is_required=True, formula=None,
    ))
    db.commit()
    db.refresh(config)
    return config


def _point_at_sorento(db, company) -> Connection:
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


def _dry_run_response(request: httpx.Request) -> httpx.Response:
    body = _json.loads(request.content)
    records = body.get("records", [])
    recs = [
        {"source_ref": r["source_ref"], "outcome": "created", "entity_id": f"id-{r['source_ref']}"}
        for r in records
    ]
    n = len(recs)
    return httpx.Response(200, json={
        "summary": {"total": n, "created": n, "updated": 0, "failed": 0, "retryable": 0},
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


def _patch_sorento_sink(monkeypatch, mock_transport: httpx.MockTransport) -> None:
    """Mirrors ``test_s11_s4_preview_job_stamping_cap_timeout.py``'s own
    helper: a full-scope dry run also opens a REAL ``SorentoSink`` client
    (its own ``httpx.Client``), independent of the source's
    ``HttpApiClient`` patched above - forgetting this would trip the
    autouse live-network guard regardless of this file's own feature."""
    import modules.autocount.services.company_service as company_module
    from modules.autocount.sinks_sorento import sorento_sink_from_connection as real

    def fake(config, credentials, *, entity_type, company_code=None, transport=None):
        return real(
            config, credentials, entity_type=entity_type, company_code=company_code,
            transport=mock_transport,
        )

    monkeypatch.setattr(company_module, "sorento_sink_from_connection", fake)


# ── the preview job's `full` scope (source -> mapping -> dry_run) ──────────


def test_full_preview_job_stage_sequence_is_source_then_mapping_then_dry_run(
    client, db, stage_spy, monkeypatch
):
    conn = _open_connection(db)
    company = _company(db, conn.id, database_name="S11S5STAGEBASE")
    _http_task(db, company, conn.id)
    _point_at_sorento(db, company)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/itembypage"):
            return httpx.Response(200, json={
                "TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                "Data": [{"ItemCode": "A1", "Description": "Widget"}],
            })
        return _dry_run_response(request)

    mock_transport = httpx.MockTransport(handler)
    _patch_http_transport(monkeypatch, httpx.Client(transport=mock_transport))
    _patch_sorento_sink(monkeypatch, mock_transport)

    response = client.post(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task/preview",
        json={"scope": "full", "companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=_auth(client),
    )
    assert response.status_code == 202, response.text

    _assert_subsequence(["source", "mapping", "dry_run"], stage_spy)


def test_full_preview_job_stage_sequence_includes_the_lookup_alias(
    client, db, stage_spy, monkeypatch
):
    conn = _open_connection(db)
    company = _company(db, conn.id, database_name="S11S5STAGELOOKUP")
    lookup = {
        "path": "/itemuombypage", "as": "uom",
        "on": [{"local": "ItemCode", "remote": "ItemCode"}],
        "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
    }
    _http_task(db, company, conn.id, lookups=[lookup])
    _point_at_sorento(db, company)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/itembypage"):
            return httpx.Response(200, json={
                "TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                "Data": [{"ItemCode": "A1", "Description": "Widget"}],
            })
        if request.url.path.endswith("/itemuombypage"):
            return httpx.Response(200, json={
                "TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                "Data": [{"ItemCode": "A1", "Price": 9.5}],
            })
        return _dry_run_response(request)

    mock_transport = httpx.MockTransport(handler)
    _patch_http_transport(monkeypatch, httpx.Client(transport=mock_transport))
    _patch_sorento_sink(monkeypatch, mock_transport)

    response = client.post(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task/preview",
        json={"scope": "full", "companyId": company.id, "entityType": ENTITY_PRODUCT},
        headers=_auth(client),
    )
    assert response.status_code == 202, response.text

    _assert_subsequence(["source", "lookup:uom", "mapping", "dry_run"], stage_spy)


# ── the pull-snapshot build (source -> storing) ─────────────────────────────


def test_pull_snapshot_stage_sequence_is_source_then_storing(db, monkeypatch, stage_spy):
    conn = _open_connection(db)
    company = _company(db, conn.id, database_name="S11S5STAGEPULL")

    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl=SOURCE_IMPL_AUTOCOUNT_HTTP, etl_status=ETL_STATUS_ACTIVE,
        delivery_mode="pull",
        source_config={
            "connectionId": conn.id, "path": "/itembypage",
            "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
            "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
            "reconcileAt": "02:00", "lookups": [],
        },
    )
    db.add(config)
    db.add(AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        scope="header", sort_order=0, source_path="ItemCode", canonical_field="code",
        transform="string", is_required=True, formula=None,
    ))
    db.commit()

    # Strictly more than ROW_INSERT_HEARTBEAT_INTERVAL rows, ALL in ONE page
    # (kept the source walk to a single beat) - so the row-insert loop's own
    # existing "beat every N rows" mechanism (``sync.py``'s
    # ``ROW_INSERT_HEARTBEAT_INTERVAL``) fires at least once, which is the
    # `storing` stage's only opportunity to be observed with a small fixture.
    row_count = ROW_INSERT_HEARTBEAT_INTERVAL + 50
    rows = [{"ItemCode": f"A{i}", "Description": "Widget"} for i in range(row_count)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "TotalCount": row_count, "Page": 1, "PageSize": row_count, "TotalPages": 1,
            "Data": rows,
        })

    _patch_http_transport(monkeypatch, httpx.Client(transport=httpx.MockTransport(handler)))

    from modules.autocount.services.pull_service import PullService

    snapshot = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator",
    )
    db.refresh(snapshot)
    assert snapshot.status == "ready", getattr(snapshot, "error", None)
    assert snapshot.record_count == row_count

    _assert_subsequence(["source", "storing"], stage_spy)
