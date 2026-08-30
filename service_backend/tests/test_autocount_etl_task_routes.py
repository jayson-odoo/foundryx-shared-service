"""The task-lifecycle HTTP surface + auto-push (plan 22 S2).

The six routes the phase-1 frontend contract pins
(``service_frontend/services/autocount-service.ts``):

    POST .../etl-task/{preview,activate,pause,resume,run}
    GET  .../etl-task/runs

plus the two EXISTING routes S2 widened (the ``sourceImpl`` switch and the
sink-target's ``sorentoCompanyCode``).

Every route gets happy path + 403 + cross-tenant 404 + its 409/422; the
activation matrix and the auto-push carry-over get their own sections. The
source database is an in-process SQLite bound through ``RUNTIME.put_engine``
and the consumer is an ``httpx.MockTransport`` - no socket anywhere.
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.models.background_job import JOB_DONE, BackgroundJob
from app.models.connection import Connection
from app.models.tenant import Tenant
from app.repositories.permission_repository import PermissionRepository
from app.secrets import encrypt_secret
from app.security import hash_password
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    ETL_STATUS_DRAFT,
    ETL_STATUS_PAUSED,
    STAGED,
    STAGED_PUSHED,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
    AcStagedRecord,
    AcSyncRun,
    AcWatermark,
)
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sql_source.runtime import RUNTIME

PASSWORD = "S3cret!Pa55"
DB_NAME = "AED_2024"
OTHER_TENANT = "tenant-other-etl-task"
CODE = "SRT"

QUERY = "SELECT acc_no, company_name, email, last_modified FROM debtor"
RESULT_COLUMNS = ["acc_no", "company_name", "email", "last_modified"]

ROWS = [
    ("300-A001", "Acme", "a@x.com", "2026-08-01 09:00:00"),
    ("300-A002", "Bolt", "b@x.com", "2026-08-02 09:00:00"),
]


# ── fixtures ─────────────────────────────────────────────────────────────────


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
                slug="other-co-etl-task",
                name="Other Co",
                status_id=default_tenant.status_id,
            )
        )
        db.commit()


def _source_engine() -> sa.engine.Engine:
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE debtor (acc_no TEXT PRIMARY KEY, company_name TEXT, "
            "email TEXT, last_modified TEXT)"
        )
        for row in ROWS:
            conn.exec_driver_sql("INSERT INTO debtor VALUES (?, ?, ?, ?)", row)
    return engine


def _connection(db, provider: str, config, credentials, *, tenant_id=DEFAULT_TENANT_ID):
    conn = Connection(
        tenant_id=tenant_id,
        provider=provider,
        type="erp" if provider != "sorento" else "consumer",
        name=f"{provider} conn",
        config_json=config,
        credentials_json=encrypt_secret(credentials),
        is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    db.expunge(conn)  # usable after the session closes
    return conn


def _company(db, *, tenant_id=DEFAULT_TENANT_ID, database_name=DB_NAME) -> AcCompany:
    api = _connection(
        db,
        "autocount",
        {"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        {"appId": "app-1", "password": "secret"},
        tenant_id=tenant_id,
    )
    company = AcCompany(
        tenant_id=tenant_id,
        connection_id=api.id,
        database_name=database_name,
        company_name="AED Sdn Bhd",
        name="AED",
        is_active=True,
    )
    db.add(company)
    db.flush()
    CompanyService(db).seed_company_defaults(tenant_id, company.id)
    db.commit()
    db.refresh(company)
    db.expunge(company)  # usable after the session closes
    return company


def _watermark_row(db, company, tenant_id=DEFAULT_TENANT_ID) -> AcWatermark:
    return (
        db.query(AcWatermark)
        .filter(
            AcWatermark.tenant_id == tenant_id,
            AcWatermark.company_id == company.id,
            AcWatermark.entity_type == ENTITY_CUSTOMER,
        )
        .one()
    )


def _config_row(db, company, tenant_id=DEFAULT_TENANT_ID) -> AcEntityConfig:
    return (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == tenant_id,
            AcEntityConfig.company_id == company.id,
            AcEntityConfig.entity_type == ENTITY_CUSTOMER,
        )
        .one()
    )


def _save_task(db, company, sql_conn, *, tenant_id=DEFAULT_TENANT_ID, **overrides):
    config = _config_row(db, company, tenant_id)
    config.source_impl = "sql_db"
    config.source_config = {
        "connectionId": sql_conn.id,
        "query": QUERY,
        "keyColumns": ["acc_no"],
        "watermarkColumn": "last_modified",
        "comparedColumns": [],
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileAt": "02:00",
        **overrides,
    }
    config.result_columns = list(RESULT_COLUMNS)
    db.commit()
    return config


FLAT_PATHS = {"code": "acc_no", "name": "company_name", "email": "email"}


def _map_customer(db, company, tenant_id=DEFAULT_TENANT_ID) -> None:
    """Re-point the SEEDED mapping rows at FLAT source paths (AC-22-09).

    ``seed_company_defaults`` already created a row per canonical field with
    the API path's nested paths (``Data.0.AccNo``); switching an entity to the
    DB source is a re-POINTING of those rows, not a second set - which is
    exactly what the unique key on (tenant, company, entity, scope, field)
    enforces.
    """
    rows = (
        db.query(AcFieldMapping)
        .filter(
            AcFieldMapping.tenant_id == tenant_id,
            AcFieldMapping.company_id == company.id,
            AcFieldMapping.entity_type == ENTITY_CUSTOMER,
        )
        .all()
    )
    for row in rows:
        path = FLAT_PATHS.get(row.canonical_field)
        if path is not None:
            row.source_path = path
        else:
            # Anything the DB query does not return (provenance/watermark rows
            # pointing at the vendor envelope) is disabled rather than left
            # reading a path that will always be absent.
            row.is_enabled = False
    db.commit()


class Consumer:
    """A scripted Sorento. ``script`` maps a path suffix to a responder."""

    def __init__(self) -> None:
        self.requests: List[Dict[str, Any]] = []
        self.responder = self.created

    @staticmethod
    def created(body: Dict[str, Any]) -> httpx.Response:
        records = body.get("records") or []
        return httpx.Response(
            200,
            json={
                "summary": {
                    "total": len(records), "created": len(records),
                    "updated": 0, "failed": 0, "retryable": 0,
                },
                "records": [
                    {"source_ref": r["source_ref"], "outcome": "created", "entity_id": "x"}
                    for r in records
                ],
            },
        )

    @property
    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            import json

            body = json.loads(request.content or b"{}")
            self.requests.append(
                {"path": request.url.path, "params": dict(request.url.params), "json": body}
            )
            return self.responder(body)

        return httpx.MockTransport(handle)


@pytest.fixture
def consumer(monkeypatch) -> Consumer:
    """Route every ``SorentoSink`` the resolver builds through one recorder."""
    import modules.autocount.services.company_service as company_module
    from modules.autocount.sinks_sorento import sorento_sink_from_connection as real

    rec = Consumer()

    def fake(config, credentials, *, entity_type, company_code=None, transport=None):
        return real(
            config,
            credentials,
            entity_type=entity_type,
            company_code=company_code,
            transport=rec.transport,
        )

    monkeypatch.setattr(company_module, "sorento_sink_from_connection", fake)
    return rec


@pytest.fixture(autouse=True)
def _clean_runtime():
    yield
    RUNTIME.dispose_all()


@pytest.fixture
def rig(session_factory):
    """A company with a saved DB task, mapped, pointed at Sorento."""
    db = session_factory()
    sql_conn = _connection(
        db,
        "sql_database",
        {
            "dbType": "postgresql",
            "host": "db.example.com",
            "port": "5432",
            "database": DB_NAME,
            "username": "readonly",
        },
        {"password": PASSWORD},
    )
    RUNTIME.put_engine(sql_conn.id, _source_engine())
    company = _company(db)
    sorento = _connection(
        db, "sorento", {"baseUrl": "https://sorento.example.com"}, {"apiKey": "k"}
    )
    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID,
        company.id,
        sink_impl="sorento",
        sink_connection_id=sorento.id,
        sorento_company_code=CODE,
    )
    _save_task(db, company, sql_conn)
    _map_customer(db, company)
    db.commit()
    # Read the ids BEFORE the session closes - a detached instance cannot
    # refresh an attribute, and every test below only needs the ids.
    company_id, sql_connection_id = company.id, sql_conn.id
    db.close()
    yield company_id, sql_connection_id
    RUNTIME.dispose_all()


def _url(company_id: str, suffix: str = "") -> str:
    return f"/autocount/companies/{company_id}/entities/customer/etl-task{suffix}"


# ── PATCH .../entities/{entityType} - the sourceImpl switch (AC-22-08) ───────


def test_source_impl_switches_and_keeps_the_saved_query(client, session_factory, rig):
    company_id, _sql_id = rig
    url = f"/autocount/companies/{company_id}/entities/customer"
    body = client.patch(
        url, json={"sourceImpl": "autocount_read"}, headers=_auth(client)
    )
    assert body.status_code == 200, body.text
    assert body.json()["sourceImpl"] == "autocount_read"
    # The task survives - switching back must never discard a built query.
    task = client.get(_url(company_id), headers=_auth(client)).json()
    assert task["sourceConfig"]["query"] == QUERY


def test_switching_an_ACTIVE_task_to_the_api_path_pauses_it(client, session_factory, rig):
    """An active task means "scheduled runs push without approval". Leaving it
    active under a source that no longer runs it is a task that looks live and
    does nothing."""
    company_id, _sql_id = rig
    db = session_factory()
    config = _config_row(db, db.get(AcCompany, company_id))
    config.etl_status = ETL_STATUS_ACTIVE
    db.commit()
    db.close()

    client.patch(
        f"/autocount/companies/{company_id}/entities/customer",
        json={"sourceImpl": "autocount_read"},
        headers=_auth(client),
    )
    assert client.get(_url(company_id), headers=_auth(client)).json()["etlStatus"] == (
        ETL_STATUS_PAUSED
    )


def test_an_unknown_source_impl_is_a_422(client, rig):
    company_id, _sql_id = rig
    response = client.patch(
        f"/autocount/companies/{company_id}/entities/customer",
        json={"sourceImpl": "carrier_pigeon"},
        headers=_auth(client),
    )
    assert response.status_code == 422


# ── PATCH .../sink-target - the company anchor (Appendix A6) ─────────────────


def test_the_sorento_sink_requires_a_company_code_per_field(client, session_factory):
    db = session_factory()
    company = _company(db)
    sorento = _connection(
        db, "sorento", {"baseUrl": "https://sorento.example.com"}, {"apiKey": "k"}
    )
    db.close()
    response = client.patch(
        f"/autocount/companies/{company.id}/sink-target",
        json={"sinkImpl": "sorento", "sinkConnectionId": sorento.id},
        headers=_auth(client),
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["fieldErrors"] == {
        "sorentoCompanyCode": (
            "Enter the Sorento company code this company delivers into."
        )
    }


def test_the_company_code_is_trimmed_stored_and_echoed(client, session_factory):
    db = session_factory()
    company = _company(db)
    sorento = _connection(
        db, "sorento", {"baseUrl": "https://sorento.example.com"}, {"apiKey": "k"}
    )
    db.close()
    response = client.patch(
        f"/autocount/companies/{company.id}/sink-target",
        json={
            "sinkImpl": "sorento",
            "sinkConnectionId": sorento.id,
            "sorentoCompanyCode": "  SRT  ",
        },
        headers=_auth(client),
    )
    assert response.status_code == 200, response.text
    assert response.json()["sorentoCompanyCode"] == "SRT"


def test_switching_to_logging_clears_the_company_code(client, session_factory, rig):
    """A code left behind would silently anchor a later switch back to Sorento
    at a company nobody re-chose."""
    company_id, _sql_id = rig
    response = client.patch(
        f"/autocount/companies/{company_id}/sink-target",
        json={"sinkImpl": "logging"},
        headers=_auth(client),
    )
    assert response.status_code == 200, response.text
    assert response.json()["sorentoCompanyCode"] is None


# ── POST .../etl-task/preview (AC-22-18) ────────────────────────────────────


def test_preview_dry_runs_the_initial_load_and_stamps_the_gate(client, rig, consumer):
    company_id, _sql_id = rig
    response = client.post(_url(company_id, "/preview"), headers=_auth(client))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["preview"]["previewable"] is True
    assert body["preview"]["summary"]["created"] == 2
    assert [p["sourceRef"] for p in body["preview"]["predictions"]] == [
        f"{DB_NAME}:300-A001", f"{DB_NAME}:300-A002"
    ]
    assert body["task"]["lastPreviewAt"] is not None
    # It really was a DRY RUN - Sorento was asked, and asked to roll back.
    assert consumer.requests[0]["params"] == {"dry_run": "true"}
    assert consumer.requests[0]["json"]["companyCode"] == CODE


def test_preview_writes_nothing_local(client, session_factory, rig, consumer):
    company_id, _sql_id = rig
    client.post(_url(company_id, "/preview"), headers=_auth(client))
    db = session_factory()
    assert db.query(AcStagedRecord).count() == 0
    assert db.query(AcSyncRun).count() == 0
    db.close()


def test_preview_on_a_logging_sink_company_is_not_previewable(client, rig, consumer):
    company_id, _sql_id = rig
    client.patch(
        f"/autocount/companies/{company_id}/sink-target",
        json={"sinkImpl": "logging"},
        headers=_auth(client),
    )
    body = client.post(_url(company_id, "/preview"), headers=_auth(client)).json()
    assert body["preview"]["previewable"] is False
    # NOT stamped: a DB task auto-pushes, so activating one with nowhere to
    # push would run forever and deliver nothing.
    assert body["task"]["lastPreviewAt"] is None


def test_preview_409s_without_a_query_or_key_columns(client, session_factory, rig):
    company_id, _sql_id = rig
    db = session_factory()
    config = _config_row(db, db.get(AcCompany, company_id))
    config.source_config = {**config.source_config, "keyColumns": []}
    db.commit()
    db.close()
    assert client.post(
        _url(company_id, "/preview"), headers=_auth(client)
    ).status_code == 409


def test_an_anchor_422_is_a_TASK_level_error_carrying_its_code(client, rig, consumer):
    """Appendix A6: Sorento answers before it looks at a record, so this is
    never attributed to one."""
    consumer.responder = lambda _body: httpx.Response(
        422,
        json={
            "message": "Company 'SRT' was not found.",
            "detail": None,
            "code": "UNKNOWN_COMPANY",
        },
    )
    company_id, _sql_id = rig
    response = client.post(_url(company_id, "/preview"), headers=_auth(client))
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["detail"]["code"] == "UNKNOWN_COMPANY"
    assert body["detail"]["message"] == "Company 'SRT' was not found."
    assert body["message"] == "Company 'SRT' was not found."


def test_an_unreachable_consumer_is_a_502(client, rig, consumer):
    consumer.responder = lambda _body: httpx.Response(500, json={"detail": "boom"})
    company_id, _sql_id = rig
    assert client.post(
        _url(company_id, "/preview"), headers=_auth(client)
    ).status_code == 502


def test_a_source_connect_failure_at_preview_is_a_502_not_a_500(client, session_factory, rig):
    """S2 review SHOULD-FIX 4: ``EtlService.preview_task`` only caught
    ``AutocountServiceError``, so ``SqlConnectError``/``SqlQueryError``/
    ``SqlTaskNotConfigured`` (raised while extracting from the SOURCE, not
    the consumer) escaped as an unhandled 500. Same translation as the raw
    ``/sql/preview`` route (``routers/sql.py``'s ``raise_sql_error``): a
    connect failure is a 502, never a stack trace."""
    company_id, sql_id = rig
    db = session_factory()
    conn = db.get(Connection, sql_id)
    # Port 1 is closed - refused immediately, no network wait needed (the
    # same fixture the SQL-source runtime tests use).
    conn.config_json = {**conn.config_json, "host": "127.0.0.1", "port": "1"}
    db.commit()
    db.close()
    RUNTIME.evict(sql_id)  # drop the injected SQLite engine - force a REAL one

    response = client.post(_url(company_id, "/preview"), headers=_auth(client))
    assert response.status_code == 502, response.text
    assert PASSWORD not in response.text
    assert "://" not in response.json()["detail"]


def test_a_query_the_source_rejects_at_preview_is_a_400_not_a_500(client, session_factory, rig):
    """The SAVED query is re-run at preview time - a table dropped AFTER save
    must surface as the source's own 400, not an unhandled 500 (mirrors the
    ``/sql/preview`` route's ``SqlQueryError`` mapping)."""
    company_id, _sql_id = rig
    db = session_factory()
    config = _config_row(db, db.get(AcCompany, company_id))
    # A row edited straight into the JSON column - the save-time guard proved
    # what WAS saved, this proves what happens when the source has since
    # moved on (AC-22-03's "re-runs on the STORED query" rule).
    config.source_config = {
        **config.source_config,
        "query": "SELECT acc_no FROM table_that_no_longer_exists",
    }
    db.commit()
    db.close()

    response = client.post(_url(company_id, "/preview"), headers=_auth(client))
    assert response.status_code == 400, response.text


def test_a_cleared_connection_at_preview_is_a_422_not_a_500(client, session_factory, rig):
    """``SqlTaskNotConfigured`` (a stored ``connectionId`` no longer set) is
    a configuration problem, same class as the static guard - 422, never an
    unhandled 500. ``_require_runnable`` only checks query/keyColumns, so a
    cleared connection reaches ``SqlDbSource`` itself."""
    company_id, _sql_id = rig
    db = session_factory()
    config = _config_row(db, db.get(AcCompany, company_id))
    config.source_config = {**config.source_config, "connectionId": ""}
    db.commit()
    db.close()

    response = client.post(_url(company_id, "/preview"), headers=_auth(client))
    assert response.status_code == 422, response.text


def test_a_not_yet_extractable_entity_maps_a_clean_error_not_a_crash(
    client, session_factory, rig
):
    """NIT (S2 review): ``ETL_ENTITY_TYPES`` (a DB task CAN be SAVED for
    these) is wider than ``mapping.ENTITY_PROFILES`` (mapping actually knows
    how to SHAPE these) - product/warehouse/... have no canonical dataclass
    yet. In today's wiring Sorento only ingests masters, so a non-master
    entity's preview is short-circuited by the sink-routing gate before ever
    reaching the mapping engine (AC-14 - "deliverability, not a
    misconfiguration") - but that gate is a SINK property, not a mapping one,
    and ``_extract_and_map`` must not crash uncaught the day a consumer that
    DOES support more entities exists. Exercised directly at the service
    layer (the only place that currently reaches it)."""
    from modules.autocount.services.etl_service import EtlService, EtlStateError

    company_id, sql_id = rig
    db = session_factory()
    company = db.get(AcCompany, company_id)
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID,
        company_id=company_id,
        entity_type="product",
        source_impl="sql_db",
        source_config={
            "connectionId": sql_id,
            "query": QUERY,
            "keyColumns": ["acc_no"],
            "watermarkColumn": None,
            "comparedColumns": [],
            "incrementalMinutes": 15,
            "reconcileMode": "dailyAt",
            "reconcileAt": "02:00",
        },
        result_columns=list(RESULT_COLUMNS),
    )
    db.add(config)
    db.commit()

    with pytest.raises(EtlStateError) as excinfo:
        EtlService(db)._extract_and_map(DEFAULT_TENANT_ID, company, config, "product")
    message = str(excinfo.value).lower()
    assert "product" in message
    assert "not yet extractable" in message
    db.close()


def test_preview_requires_sync_run_and_404s_cross_tenant(client, session_factory, rig):
    company_id, _sql_id = rig
    db = session_factory()
    _other_tenant(db)
    theirs = _company(db, tenant_id=OTHER_TENANT, database_name="THEIRS")
    _limited_user(db, ["autocount.companies.read"], "nopreview@example.com")
    db.close()

    limited = _auth(client, "nopreview@example.com", "limited1234")
    assert client.post(_url(company_id, "/preview"), headers=limited).status_code == 403
    assert client.post(
        _url(theirs.id, "/preview"), headers=_auth(client)
    ).status_code == 404


# ── POST .../etl-task/activate (AC-22-18) ───────────────────────────────────


def _activate(client, company_id):
    return client.post(_url(company_id, "/activate"), headers=_auth(client))


def test_activate_is_refused_until_a_preview_succeeded(client, rig):
    company_id, _sql_id = rig
    response = _activate(client, company_id)
    assert response.status_code == 409, response.text
    assert "preview" in response.json()["detail"].lower()


def test_activate_is_refused_without_a_sorento_company_code(
    client, session_factory, rig, consumer
):
    company_id, _sql_id = rig
    client.post(_url(company_id, "/preview"), headers=_auth(client))
    db = session_factory()
    company = db.get(AcCompany, company_id)
    company.sorento_company_code = None
    db.commit()
    db.close()
    response = _activate(client, company_id)
    assert response.status_code == 409
    assert "company code" in response.json()["detail"].lower()


def test_activate_after_a_preview_arms_the_task(client, session_factory, rig, consumer):
    company_id, _sql_id = rig
    client.post(_url(company_id, "/preview"), headers=_auth(client))
    body = _activate(client, company_id).json()
    assert body["etlStatus"] == ETL_STATUS_ACTIVE
    assert body["activatedAt"] is not None

    db = session_factory()
    config = _config_row(db, db.get(AcCompany, company_id))
    # Activation IS the switch to the DB path, and it arms the sweep's due keys.
    assert config.source_impl == "sql_db"
    assert config.next_incremental_at is not None
    assert config.next_reconcile_at is not None
    db.close()


def test_saving_the_config_again_RE_CLOSES_the_gate(client, rig, consumer, session_factory):
    """A preview proves what a SPECIFIC query would deliver - an edit must
    re-open the gate or an operator activates something nobody previewed."""
    company_id, sql_id = rig
    client.post(_url(company_id, "/preview"), headers=_auth(client))
    saved = client.put(
        _url(company_id),
        json={
            "sourceConfig": {
                "connectionId": sql_id,
                "query": QUERY,
                "keyColumns": ["acc_no"],
                # No watermark on THIS save: the fixture source is SQLite, whose
                # TEXT ``last_modified`` previews as ``string`` and is rightly
                # refused as a watermark. The gate/columns behaviour under test
                # is independent of the cadence.
                "watermarkColumn": None,
                "comparedColumns": [],
                "incrementalMinutes": 15,
                "reconcileMode": "dailyAt",
                "reconcileAt": "02:00",
            }
        },
        headers=_auth(client),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["lastPreviewAt"] is None
    # …and the columns the save proved are stored for the Mapping tab.
    assert saved.json()["resultColumns"] == RESULT_COLUMNS
    assert _activate(client, company_id).status_code == 409


def test_activate_twice_is_a_409(client, rig, consumer):
    company_id, _sql_id = rig
    client.post(_url(company_id, "/preview"), headers=_auth(client))
    assert _activate(client, company_id).status_code == 200
    assert _activate(client, company_id).status_code == 409


def test_activate_requires_manage_and_404s_cross_tenant(client, session_factory, rig):
    company_id, _sql_id = rig
    db = session_factory()
    _other_tenant(db)
    theirs = _company(db, tenant_id=OTHER_TENANT, database_name="THEIRS2")
    _limited_user(
        db, ["autocount.companies.read", "autocount.sync.run"], "noactivate@example.com"
    )
    db.close()
    limited = _auth(client, "noactivate@example.com", "limited1234")
    assert client.post(_url(company_id, "/activate"), headers=limited).status_code == 403
    assert _activate(client, theirs.id).status_code == 404


# ── pause / resume (AC-22-19) ───────────────────────────────────────────────


def test_pause_then_resume_needs_no_second_preview(client, rig, consumer):
    company_id, _sql_id = rig
    client.post(_url(company_id, "/preview"), headers=_auth(client))
    _activate(client, company_id)

    paused = client.post(_url(company_id, "/pause"), headers=_auth(client))
    assert paused.status_code == 200
    assert paused.json()["etlStatus"] == ETL_STATUS_PAUSED

    resumed = client.post(_url(company_id, "/resume"), headers=_auth(client))
    assert resumed.status_code == 200
    assert resumed.json()["etlStatus"] == ETL_STATUS_ACTIVE
    assert resumed.json()["lastPreviewAt"] is not None


def test_pausing_a_draft_and_resuming_an_active_task_are_409s(client, rig, consumer):
    company_id, _sql_id = rig
    assert client.post(_url(company_id, "/pause"), headers=_auth(client)).status_code == 409
    client.post(_url(company_id, "/preview"), headers=_auth(client))
    _activate(client, company_id)
    assert client.post(_url(company_id, "/resume"), headers=_auth(client)).status_code == 409


def test_pause_requires_manage(client, session_factory, rig):
    company_id, _sql_id = rig
    db = session_factory()
    _limited_user(db, ["autocount.companies.read"], "nopause@example.com")
    db.close()
    limited = _auth(client, "nopause@example.com", "limited1234")
    assert client.post(_url(company_id, "/pause"), headers=limited).status_code == 403


# ── POST .../etl-task/run + auto-push (AC-22-17/20) ─────────────────────────


def _activated(client, company_id):
    client.post(_url(company_id, "/preview"), headers=_auth(client))
    assert _activate(client, company_id).status_code == 200


def test_run_is_refused_on_a_draft_task(client, rig):
    company_id, _sql_id = rig
    response = client.post(_url(company_id, "/run"), headers=_auth(client))
    assert response.status_code == 409
    assert "activate" in response.json()["detail"].lower()


def test_a_manual_run_fetches_maps_stages_and_PUSHES_in_one_job(
    client, session_factory, rig, consumer
):
    """AC-22-20: an activated task has no review gate - the activate-once
    ceremony was the approval."""
    company_id, _sql_id = rig
    _activated(client, company_id)
    consumer.requests.clear()

    response = client.post(_url(company_id, "/run"), headers=_auth(client))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["jobId"]
    assert body["runId"]  # eager dev/test runs the handler inline

    db = session_factory()
    job = db.get(BackgroundJob, body["jobId"])
    # DONE, never needs_review - there is no gate on an active task.
    assert job.status == JOB_DONE
    assert job.result_json["pushed"] == 2
    assert job.result_json["mode"] == "manual"
    staged = db.query(AcStagedRecord).all()
    assert {row.status for row in staged} == {STAGED_PUSHED}
    db.close()

    pushed = [r for r in consumer.requests if r["params"] == {}]
    assert len(pushed) == 1
    assert pushed[0]["json"]["companyCode"] == CODE


def test_the_run_row_carries_the_cost_columns(client, rig, consumer):
    company_id, _sql_id = rig
    _activated(client, company_id)
    client.post(_url(company_id, "/run"), headers=_auth(client))

    runs = client.get(_url(company_id, "/runs"), headers=_auth(client)).json()
    assert runs["total"] == 1
    run = runs["data"][0]
    assert run["mode"] == "manual"
    assert run["rowsScanned"] == 2
    assert run["addedCount"] == 2
    assert run["updatedCount"] == 0
    assert run["deletedCount"] == 0
    assert run["pushedCount"] == 2
    assert isinstance(run["durationMs"], int)
    assert run["skipReason"] is None
    assert run["jobId"]


def test_a_second_run_after_a_source_edit_reports_exactly_one_update(
    client, session_factory, rig, consumer
):
    """The incremental leg end to end: watermark → 1 changed row → 1 update."""
    company_id, sql_id = rig
    _activated(client, company_id)
    client.post(_url(company_id, "/run"), headers=_auth(client))

    engine = RUNTIME.engine_for(sql_id, {}, {})
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE debtor SET company_name = 'Acme Holdings', "
            "last_modified = '2026-08-20 09:00:00' WHERE acc_no = '300-A001'"
        )

    second = client.post(_url(company_id, "/run"), headers=_auth(client)).json()

    runs = client.get(_url(company_id, "/runs"), headers=_auth(client)).json()["data"]
    assert len(runs) == 2
    # Addressed by ID, not by position: two runs a fraction of a second apart
    # share a ``started_at`` second on SQLite, so "newest first" has nothing
    # left to order by. The surface holds the id too (``POST /run`` returns it).
    latest = next(r for r in runs if r["id"] == second["runId"])
    assert latest["rowsScanned"] == 1
    assert latest["updatedCount"] == 1
    assert latest["addedCount"] == 0
    assert latest["pushedCount"] == 1


def test_a_retryable_verdict_stays_staged_and_re_pushes_on_the_next_run(
    client, session_factory, rig, consumer
):
    """AC-22-20 - the reason auto-push looks at the ENTITY's undelivered rows
    and not just this job's: the retry lands under a DIFFERENT job."""
    company_id, _sql_id = rig
    _activated(client, company_id)

    def retryable(body):
        records = body.get("records") or []
        return httpx.Response(
            200,
            json={
                "summary": {
                    "total": len(records), "created": 0, "updated": 0,
                    "failed": 0, "retryable": len(records),
                },
                "records": [
                    {"source_ref": r["source_ref"], "outcome": "retryable"}
                    for r in records
                ],
            },
        )

    consumer.responder = retryable
    client.post(_url(company_id, "/run"), headers=_auth(client))

    db = session_factory()
    assert {row.status for row in db.query(AcStagedRecord).all()} == {STAGED}
    config = _config_row(db, db.get(AcCompany, company_id))
    # Repeated delivery failures surface on the TASK, never silently.
    assert config.last_run_error
    db.close()

    consumer.responder = Consumer.created
    client.post(_url(company_id, "/run"), headers=_auth(client))
    db = session_factory()
    # The carried-over rows delivered on the SECOND run's job.
    assert {row.status for row in db.query(AcStagedRecord).all()} == {STAGED_PUSHED}
    assert _config_row(db, db.get(AcCompany, company_id)).last_run_error is None
    db.close()


def test_an_anchor_422_on_a_RUN_lands_on_the_task_not_the_records(
    client, session_factory, rig, consumer
):
    """BLOCKER 1 (S2 review): a failing sink must not roll back the fetch's
    own uncommitted watermark/cursor advance - only the push failed, the
    fetch+stage genuinely succeeded, so the next run must NOT full-reload."""
    company_id, _sql_id = rig
    _activated(client, company_id)
    consumer.responder = lambda _body: httpx.Response(
        422,
        json={"message": "no binding", "detail": None, "code": "COMPANY_BINDING_INVALID"},
    )
    client.post(_url(company_id, "/run"), headers=_auth(client))

    db = session_factory()
    company = db.get(AcCompany, company_id)
    config = _config_row(db, company)
    assert config.last_run_error_code == "COMPANY_BINDING_INVALID"
    assert config.last_run_error == "no binding"
    assert config.last_run_at is not None
    # Nothing was attributed to a record; every row is still staged.
    assert {row.status for row in db.query(AcStagedRecord).all()} == {STAGED}
    # The fetch's own resume point (this SQL-DB source tracks its own cursor,
    # not a timestamp column) must survive the sink failure - only the PUSH
    # failed, the fetch+stage genuinely succeeded.
    watermark = _watermark_row(db, company)
    assert watermark.cursor_json is not None
    assert watermark.cursor_json["sqlWatermark"] == "2026-08-02 09:00:00"
    assert watermark.consecutive_failures == 0
    db.close()

    # A second run must be idempotent: it re-reads nothing new because the
    # cursor truly advanced past both existing rows on the first run - a
    # lost cursor would re-scan both rows from scratch (a full re-extract).
    consumer.responder = Consumer.created
    second = client.post(_url(company_id, "/run"), headers=_auth(client)).json()
    # Addressed by ID, not by position (two runs a fraction of a second apart
    # share a ``started_at`` second on SQLite - see the sibling incremental
    # test's note).
    runs = client.get(_url(company_id, "/runs"), headers=_auth(client)).json()["data"]
    latest = next(r for r in runs if r["id"] == second["runId"])
    assert latest["rowsScanned"] == 0


def test_run_requires_sync_run_and_404s_cross_tenant(client, session_factory, rig):
    company_id, _sql_id = rig
    db = session_factory()
    _other_tenant(db)
    theirs = _company(db, tenant_id=OTHER_TENANT, database_name="THEIRS3")
    _limited_user(db, ["autocount.companies.read"], "norun@example.com")
    db.close()
    limited = _auth(client, "norun@example.com", "limited1234")
    assert client.post(_url(company_id, "/run"), headers=limited).status_code == 403
    assert client.post(
        _url(theirs.id, "/run"), headers=_auth(client)
    ).status_code == 404


# ── GET .../etl-task/runs (AC-22-17) ────────────────────────────────────────


def test_runs_are_newest_first_paginated_and_capped(client, rig, consumer):
    company_id, _sql_id = rig
    _activated(client, company_id)
    client.post(_url(company_id, "/run"), headers=_auth(client))
    client.post(_url(company_id, "/run"), headers=_auth(client))

    body = client.get(
        _url(company_id, "/runs?page=0&page_size=1"), headers=_auth(client)
    ).json()
    assert body["total"] == 2
    assert len(body["data"]) == 1
    # An all-rows fetch is refused rather than silently served.
    assert client.get(
        _url(company_id, "/runs?page_size=500"), headers=_auth(client)
    ).status_code == 422


def test_runs_requires_sync_read_and_404s_cross_tenant(client, session_factory, rig):
    company_id, _sql_id = rig
    db = session_factory()
    _other_tenant(db)
    theirs = _company(db, tenant_id=OTHER_TENANT, database_name="THEIRS4")
    _limited_user(db, ["autocount.companies.read"], "noruns@example.com")
    db.close()
    limited = _auth(client, "noruns@example.com", "limited1234")
    assert client.get(_url(company_id, "/runs"), headers=limited).status_code == 403
    assert client.get(_url(theirs.id, "/runs"), headers=_auth(client)).status_code == 404


def test_an_unknown_entity_is_a_404_not_a_500(client, rig):
    company_id, _sql_id = rig
    response = client.get(
        f"/autocount/companies/{company_id}/entities/unicorn/etl-task/runs",
        headers=_auth(client),
    )
    assert response.status_code == 404


# ── the review gate survives a source switch (found in LIVE verify) ─────────


def _parked_review_batch(db, company_id: str, entity_type: str = ENTITY_CUSTOMER) -> str:
    """An OLD API-path batch left in ``needs_review`` with a staged row - the
    exact residue an entity carries when it is switched to a DB task."""
    from app.models.background_job import JOB_NEEDS_REVIEW

    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID,
        type="autocount_sync",
        status=JOB_NEEDS_REVIEW,
        payload_json={"companyId": company_id, "entityType": entity_type},
    )
    db.add(job)
    db.flush()
    db.add(
        AcStagedRecord(
            tenant_id=DEFAULT_TENANT_ID,
            company_id=company_id,
            entity_type=entity_type,
            job_id=job.id,
            source_ref=f"{DB_NAME}:LEGACY-1",
            canonical_json={"source_ref": f"{DB_NAME}:LEGACY-1", "code": "LEGACY-1"},
            status=STAGED,
        )
    )
    db.commit()
    return job.id


def test_a_parked_review_batch_does_NOT_block_running_the_db_task(
    client, session_factory, rig, consumer
):
    """``needs_review`` is non-terminal but NOT executing - it is parked on a
    human, possibly forever. Treating it as "a run is in flight" let four old
    API-path batches refuse every run of the DB task that replaced them (found
    against live data)."""
    company_id, _sql_id = rig
    db = session_factory()
    _parked_review_batch(db, company_id)
    db.close()

    _activated(client, company_id)
    assert client.post(_url(company_id, "/run"), headers=_auth(client)).status_code == 200


def test_auto_push_NEVER_delivers_a_record_still_awaiting_review(
    client, session_factory, rig, consumer
):
    """The review gate must survive a source switch. Auto-push looks at the
    ENTITY's undelivered rows (so a retryable re-pushes next run), and without
    this guard that sweep would deliver an old API-path batch a human still
    owns - the gate bypassed by switching source."""
    company_id, _sql_id = rig
    db = session_factory()
    _parked_review_batch(db, company_id)
    db.close()

    _activated(client, company_id)
    client.post(_url(company_id, "/run"), headers=_auth(client))

    db = session_factory()
    legacy = (
        db.query(AcStagedRecord)
        .filter(AcStagedRecord.source_ref == f"{DB_NAME}:LEGACY-1")
        .one()
    )
    assert legacy.status == STAGED  # untouched, still the human's to decide
    # …while the DB task's own rows DID deliver on the same run.
    delivered = (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.entity_type == ENTITY_CUSTOMER,
            AcStagedRecord.status == STAGED_PUSHED,
        )
        .count()
    )
    assert delivered == 2
    db.close()
    refs = [
        r["source_ref"]
        for call in consumer.requests
        if call["params"] == {}
        for r in call["json"].get("records", [])
    ]
    assert f"{DB_NAME}:LEGACY-1" not in refs


def test_a_RUNNING_job_still_blocks_a_manual_run(client, session_factory, rig, consumer):
    """The guard that matters is unchanged: two workers on one (company,
    entity) would double-push the same staged rows."""
    from app.models.background_job import JOB_RUNNING

    company_id, _sql_id = rig
    _activated(client, company_id)
    db = session_factory()
    db.add(
        BackgroundJob(
            tenant_id=DEFAULT_TENANT_ID,
            type="autocount_sync",
            status=JOB_RUNNING,
            payload_json={"companyId": company_id, "entityType": ENTITY_CUSTOMER},
        )
    )
    db.commit()
    db.close()

    response = client.post(_url(company_id, "/run"), headers=_auth(client))
    assert response.status_code == 409
    assert "still going" in str(response.json()).lower()


def test_a_failed_verdict_is_QUARANTINED_while_retryable_carries_over(
    client, session_factory, rig, consumer
):
    """The two failure verdicts need OPPOSITE handling on an unattended push.

    Found live: Sorento rejected a customer whose code was already linked to
    another source. Re-offering a ``failed`` record on every run re-fails it
    forever and pins the task's health signal permanently red - so it is
    quarantined (D13's "FAILED is never pushable"), while a ``retryable``
    record still carries over to the next run.
    """
    company_id, _sql_id = rig
    _activated(client, company_id)

    def mixed(body):
        records = body.get("records") or []
        out = []
        for index, record in enumerate(records):
            out.append(
                {
                    "source_ref": record["source_ref"],
                    "outcome": "failed" if index == 0 else "retryable",
                    "errors": {"code": "already linked to another source"},
                }
            )
        return httpx.Response(
            200,
            json={
                "summary": {
                    "total": len(records), "created": 0, "updated": 0,
                    "failed": 1, "retryable": max(len(records) - 1, 0),
                },
                "records": out,
            },
        )

    consumer.responder = mixed
    client.post(_url(company_id, "/run"), headers=_auth(client))

    db = session_factory()
    rows = {
        row.source_ref: row.status
        for row in db.query(AcStagedRecord)
        .filter(AcStagedRecord.entity_type == ENTITY_CUSTOMER)
        .all()
    }
    db.close()
    assert sorted(rows.values()) == ["FAILED", "STAGED"]

    # S2 review SHOULD-FIX 10: a quarantined push failure must be VISIBLE on
    # the run row, not just buried in the job result JSON - it folds into
    # failedCount (0 documents failed to MAP, 1 record failed to PUSH).
    runs = client.get(_url(company_id, "/runs"), headers=_auth(client)).json()["data"]
    assert runs[0]["failedCount"] == 1

    # The quarantined one is NOT re-offered; the retryable one is.
    consumer.responder = Consumer.created
    consumer.requests.clear()
    client.post(_url(company_id, "/run"), headers=_auth(client))
    offered = [
        r["source_ref"]
        for call in consumer.requests
        if call["params"] == {}
        for r in call["json"].get("records", [])
    ]
    db = session_factory()
    quarantined = (
        db.query(AcStagedRecord)
        .filter(AcStagedRecord.status == "FAILED")
        .one()
    )
    db.close()
    assert quarantined.source_ref not in offered
