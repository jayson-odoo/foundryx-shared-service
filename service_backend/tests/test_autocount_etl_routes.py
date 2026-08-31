"""AutoCount direct-DB ETL, slice S1 - the HTTP surface (plan 22 §2.3/2.4).

The five endpoints the phase-1 frontend contract pins
(``service_frontend/services/autocount-service.ts``):

    GET  /autocount/sql/connections
    GET  /autocount/sql/connections/{id}/schema[?refresh=true]
    POST /autocount/sql/preview
    GET  /autocount/companies/{id}/entities/{entityType}/etl-task
    PUT  /autocount/companies/{id}/entities/{entityType}/etl-task

Every route: happy path + permission 403 + cross-tenant 404 (AC-22-29), the
guard's 422-before-source (AC-22-03), sanitised 400/502 (AC-22-30) and the
task-config validation matrix (AC-22-11).

No network: each SQL connection row is bound to an in-process SQLite engine
through the runtime's ``put_engine`` seam, so the routes exercise the REAL
introspection/preview code against a real (throwaway) database.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.models.connection import Connection
from app.models.tenant import Tenant
from app.repositories.permission_repository import PermissionRepository
from app.secrets import encrypt_secret
from app.security import hash_password
from modules.autocount.models import AcCompany, AcEntityConfig
from modules.autocount.services.company_service import CompanyService
from modules.autocount.services.etl_service import (
    ETL_ENTITY_TYPES,
    validate_source_config,
)
from modules.autocount.sql_source.runtime import RUNTIME

PASSWORD = "S3cret!Pa55"
OTHER_TENANT = "tenant-other"


def _auth(client, email="demo@example.com", password="demo1234") -> Dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _limited_user(db, keys: List[str], email: str = "limited@example.com") -> None:
    """A default-tenant user holding ONLY the given permission keys."""
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
                slug="other-co-etl",
                name="Other Co",
                status_id=default_tenant.status_id,
            )
        )
        db.commit()


def _sqlite_engine() -> sa.engine.Engine:
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE debtor (acc_no TEXT PRIMARY KEY, company_name TEXT, "
            "balance NUMERIC, last_modified TIMESTAMP, is_active INTEGER)"
        )
        for i in range(120):
            conn.exec_driver_sql(
                "INSERT INTO debtor VALUES (?, ?, ?, ?, ?)",
                (f"3000/A{i:03d}", f"Company {i}", 12.5 * i, f"2026-08-{1 + (i % 28):02d} 09:00:00", 1),
            )
    return engine


def _sql_connection(
    db,
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
    name: str = "AutoCount SQL",
    db_type: str = "mssql",
    engine: sa.engine.Engine | None = None,
) -> Connection:
    conn = Connection(
        tenant_id=tenant_id,
        provider="sql_database",
        type="erp",
        name=name,
        config_json={
            "dbType": db_type,
            "host": "db.example.com",
            "port": "1433",
            "database": "AED_2024",
            "username": "readonly",
        },
        credentials_json=encrypt_secret({"password": PASSWORD}),
        is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    db.expunge(conn)  # usable after the session closes
    RUNTIME.put_engine(conn.id, engine or _sqlite_engine())
    return conn


def _autocount_connection(db, tenant_id: str = DEFAULT_TENANT_ID) -> Connection:
    conn = Connection(
        tenant_id=tenant_id,
        provider="autocount",
        type="erp",
        name="AutoCount API",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}),
        is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    db.expunge(conn)
    return conn


def _company(db, tenant_id: str = DEFAULT_TENANT_ID, database_name: str = "AED_2024") -> AcCompany:
    conn = _autocount_connection(db, tenant_id)
    company = AcCompany(
        tenant_id=tenant_id,
        connection_id=conn.id,
        database_name=database_name,
        company_name="AED Sdn Bhd",
        name="AED Sdn Bhd",
        is_active=True,
    )
    db.add(company)
    db.flush()
    CompanyService(db).seed_company_defaults(tenant_id, company.id)
    db.commit()
    db.refresh(company)
    db.expunge(company)
    return company


def _config(**overrides) -> Dict[str, object]:
    base = {
        "connectionId": None,
        "query": "",
        "lineQuery": None,
        "keyColumns": [],
        "watermarkColumn": None,
        "comparedColumns": [],
        "fromDate": None,
        # Plan 22 S5 - documents-only, always present (None for a non-document
        # entity, exactly like `lineQuery`/`fromDate` above).
        "docDateColumn": None,
        "lineKeyColumn": None,
        "lineProductColumn": None,
        "lineWarehouseColumn": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileHours": None,
        "reconcileAt": "02:00",
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _clean_runtime():
    yield
    RUNTIME.dispose_all()


# ── GET /autocount/sql/connections ───────────────────────────────────────────


def test_list_sql_connections_is_tenant_and_provider_scoped(client, session_factory):
    db = session_factory()
    _other_tenant(db)
    mine = _sql_connection(db, name="Mine", db_type="postgresql")
    _autocount_connection(db)  # same tenant, wrong provider - never listed
    _sql_connection(db, tenant_id=OTHER_TENANT, name="Theirs")  # other tenant
    db.close()

    response = client.get("/autocount/sql/connections", headers=_auth(client))
    assert response.status_code == 200, response.text
    body = response.json()
    assert [c["id"] for c in body] == [mine.id]
    assert body[0] == {
        "id": mine.id,
        "name": "Mine",
        "dialect": "postgresql",
        "database": "AED_2024",
    }


def test_list_sql_connections_requires_manage(client, session_factory):
    db = session_factory()
    _limited_user(db, ["autocount.companies.read"])
    db.close()
    headers = _auth(client, "limited@example.com", "limited1234")
    assert client.get("/autocount/sql/connections", headers=headers).status_code == 403


# ── GET /autocount/sql/connections/{id}/schema ───────────────────────────────


def test_schema_returns_the_introspected_tree(client, session_factory):
    db = session_factory()
    conn = _sql_connection(db)
    db.close()

    response = client.get(f"/autocount/sql/connections/{conn.id}/schema", headers=_auth(client))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["connectionId"] == conn.id
    assert body["dialect"] == "mssql"
    assert body["database"] == "AED_2024"
    assert body["introspectedAt"].endswith("Z")
    schemas = {s["name"]: s for s in body["schemas"]}
    assert "main" in schemas
    tables = {t["name"]: t for t in schemas["main"]["tables"]}
    assert "debtor" in tables
    assert {c["name"] for c in tables["debtor"]["columns"]} == {
        "acc_no",
        "company_name",
        "balance",
        "last_modified",
        "is_active",
    }
    assert all(isinstance(c["type"], str) and c["type"] for c in tables["debtor"]["columns"])


def test_schema_is_cached_per_connection_until_refreshed(client, session_factory, monkeypatch):
    import modules.autocount.services.etl_service as etl_module

    db = session_factory()
    conn = _sql_connection(db)
    db.close()
    calls = {"n": 0}
    real = etl_module.introspect_schema

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(etl_module, "introspect_schema", counting)
    headers = _auth(client)
    url = f"/autocount/sql/connections/{conn.id}/schema"
    assert client.get(url, headers=headers).status_code == 200
    assert client.get(url, headers=headers).status_code == 200
    assert calls["n"] == 1
    assert client.get(url + "?refresh=true", headers=headers).status_code == 200
    assert calls["n"] == 2


def test_schema_404s_for_another_tenants_or_a_non_sql_connection(client, session_factory):
    db = session_factory()
    _other_tenant(db)
    theirs = _sql_connection(db, tenant_id=OTHER_TENANT)
    api_conn = _autocount_connection(db)
    db.close()
    headers = _auth(client)
    assert client.get(f"/autocount/sql/connections/{theirs.id}/schema", headers=headers).status_code == 404
    assert client.get(f"/autocount/sql/connections/{api_conn.id}/schema", headers=headers).status_code == 404
    assert client.get("/autocount/sql/connections/nope/schema", headers=headers).status_code == 404


def test_schema_connect_failure_is_a_sanitised_502(client, session_factory):
    db = session_factory()
    # A real (never-connected) engine to a closed port: refused immediately.
    dead = sa.create_engine(
        f"postgresql+psycopg2://ro:{PASSWORD}@127.0.0.1:1/nope",
        connect_args={"connect_timeout": 2},
    )
    conn = _sql_connection(db, engine=dead)
    db.close()
    response = client.get(f"/autocount/sql/connections/{conn.id}/schema", headers=_auth(client))
    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert PASSWORD not in detail
    assert "://" not in detail
    assert detail.startswith("Could not connect to the database")


def test_schema_requires_manage(client, session_factory):
    db = session_factory()
    conn = _sql_connection(db)
    _limited_user(db, ["autocount.companies.read"])
    db.close()
    headers = _auth(client, "limited@example.com", "limited1234")
    assert client.get(f"/autocount/sql/connections/{conn.id}/schema", headers=headers).status_code == 403


# ── POST /autocount/sql/preview ──────────────────────────────────────────────


def test_preview_returns_capped_rows_columns_and_types(client, session_factory):
    db = session_factory()
    conn = _sql_connection(db)
    db.close()
    response = client.post(
        "/autocount/sql/preview",
        json={"connectionId": conn.id, "query": "SELECT acc_no, balance, last_modified FROM debtor ORDER BY acc_no"},
        headers=_auth(client),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [c["name"] for c in body["columns"]] == ["acc_no", "balance", "last_modified"]
    assert body["rowCount"] == 100
    assert body["truncated"] is True
    assert len(body["rows"]) == 100
    assert body["rows"][0]["acc_no"] == "3000/A000"
    assert isinstance(body["durationMs"], int)


def test_preview_rejects_non_select_with_422_before_the_source(client, session_factory, monkeypatch):
    db = session_factory()
    engine = _sqlite_engine()
    conn = _sql_connection(db, engine=engine)
    db.close()
    touched = {"n": 0}
    real_connect = engine.connect

    def counting(*a, **kw):
        touched["n"] += 1
        return real_connect(*a, **kw)

    monkeypatch.setattr(engine, "connect", counting)
    for bad in ("DELETE FROM debtor", "SELECT 1; DROP TABLE debtor", "", "SELECT * INTO x FROM debtor"):
        response = client.post(
            "/autocount/sql/preview",
            json={"connectionId": conn.id, "query": bad},
            headers=_auth(client),
        )
        assert response.status_code == 422, (bad, response.text)
    assert touched["n"] == 0


def test_preview_query_failure_is_a_sanitised_400(client, session_factory):
    db = session_factory()
    conn = _sql_connection(db)
    db.close()
    response = client.post(
        "/autocount/sql/preview",
        json={"connectionId": conn.id, "query": "SELECT * FROM no_such_table"},
        headers=_auth(client),
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "no_such_table" in detail
    assert "[SQL:" not in detail
    assert PASSWORD not in detail


def test_preview_404s_cross_tenant_and_requires_manage(client, session_factory):
    db = session_factory()
    _other_tenant(db)
    theirs = _sql_connection(db, tenant_id=OTHER_TENANT)
    mine = _sql_connection(db)
    _limited_user(db, ["autocount.companies.read"])
    db.close()
    body = {"connectionId": theirs.id, "query": "SELECT 1"}
    assert client.post("/autocount/sql/preview", json=body, headers=_auth(client)).status_code == 404
    limited = _auth(client, "limited@example.com", "limited1234")
    assert (
        client.post("/autocount/sql/preview", json={"connectionId": mine.id, "query": "SELECT 1"}, headers=limited).status_code
        == 403
    )


# ── GET/PUT .../etl-task ─────────────────────────────────────────────────────


def test_get_etl_task_returns_draft_defaults_for_a_configured_entity(client, session_factory):
    db = session_factory()
    company = _company(db)
    db.close()
    response = client.get(
        f"/autocount/companies/{company.id}/entities/customer/etl-task", headers=_auth(client)
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "companyId": company.id,
        "entityType": "customer",
        "etlStatus": "draft",
        "activatedAt": None,
        "sourceConfig": _config(),
        # Read-only task state (plan 22 S2) - all empty on a never-saved task.
        "resultColumns": [],
        "lastPreviewAt": None,
        "lastRunAt": None,
        "lastRunError": None,
        "lastRunErrorCode": None,
        # Schedule (plan 22 S3) - NULL until the task is activated.
        "nextIncrementalAt": None,
        "nextReconcileAt": None,
    }


def test_get_etl_task_returns_document_defaults_for_a_never_configured_entity(client, session_factory):
    """``sales_order`` has no ``ac_entity_config`` row yet - the editor IS the
    create surface, so it gets a draft (from-date = today, a line query slot)."""
    db = session_factory()
    company = _company(db)
    db.close()
    response = client.get(
        f"/autocount/companies/{company.id}/entities/sales_order/etl-task", headers=_auth(client)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["etlStatus"] == "draft"
    assert body["sourceConfig"]["fromDate"] == date.today().isoformat()
    assert body["sourceConfig"]["lineQuery"] == ""
    assert "sales_order" in ETL_ENTITY_TYPES


def test_get_etl_task_404s_unknown_entity_cross_tenant_and_reads_with_read_perm(client, session_factory):
    db = session_factory()
    _other_tenant(db)
    mine = _company(db)
    theirs = _company(db, tenant_id=OTHER_TENANT, database_name="THEIRS")
    _limited_user(db, ["autocount.companies.read"])
    db.close()
    headers = _auth(client)
    assert client.get(f"/autocount/companies/{mine.id}/entities/not_a_thing/etl-task", headers=headers).status_code == 404
    assert client.get(f"/autocount/companies/{theirs.id}/entities/customer/etl-task", headers=headers).status_code == 404
    limited = _auth(client, "limited@example.com", "limited1234")
    assert client.get(f"/autocount/companies/{mine.id}/entities/customer/etl-task", headers=limited).status_code == 200


def test_put_etl_task_saves_and_round_trips(client, session_factory):
    db = session_factory()
    company = _company(db)
    conn = _sql_connection(db, db_type="postgresql")
    db.close()
    headers = _auth(client)
    url = f"/autocount/companies/{company.id}/entities/customer/etl-task"
    body = {
        "sourceConfig": _config(
            connectionId=conn.id,
            query="SELECT acc_no, company_name, balance, last_modified FROM debtor;",
            keyColumns=["acc_no"],
            # SQLite hands a TIMESTAMP back as text, so the orderable watermark
            # in this throwaway source is the numeric column.
            watermarkColumn="balance",
            comparedColumns=["company_name", "last_modified"],
            incrementalMinutes=5,
        )
    }
    response = client.put(url, json=body, headers=headers)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["etlStatus"] == "draft"
    cfg = saved["sourceConfig"]
    assert cfg["connectionId"] == conn.id
    # Stored without the tolerated trailing terminator.
    assert cfg["query"] == "SELECT acc_no, company_name, balance, last_modified FROM debtor"
    assert cfg["keyColumns"] == ["acc_no"]
    assert cfg["watermarkColumn"] == "balance"
    assert cfg["comparedColumns"] == ["company_name", "last_modified"]
    assert cfg["incrementalMinutes"] == 5

    again = client.get(url, headers=headers)
    assert again.status_code == 200
    assert again.json() == saved

    # Persisted on the anchor row, never a new table (Q13).
    db = session_factory()
    row = (
        db.query(AcEntityConfig)
        .filter_by(tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type="customer")
        .one()
    )
    assert row.source_config["keyColumns"] == ["acc_no"]
    assert row.etl_status == "draft"
    db.close()


def test_put_etl_task_creates_the_anchor_row_for_a_new_entity(client, session_factory):
    db = session_factory()
    company = _company(db)
    conn = _sql_connection(db)
    db.close()
    url = f"/autocount/companies/{company.id}/entities/sales_order/etl-task"
    body = {
        "sourceConfig": _config(
            connectionId=conn.id,
            query="SELECT acc_no AS doc_key, balance, last_modified FROM debtor",
            lineQuery=(
                "SELECT acc_no, company_name AS item_code FROM debtor "
                "WHERE acc_no = :doc_key"
            ),
            keyColumns=["doc_key"],
            watermarkColumn="balance",
            fromDate="2026-01-01",
            docDateColumn="last_modified",
            lineKeyColumn="acc_no",
            lineProductColumn="item_code",
        )
    }
    response = client.put(url, json=body, headers=_auth(client))
    assert response.status_code == 200, response.text
    assert response.json()["sourceConfig"]["fromDate"] == "2026-01-01"
    db = session_factory()
    row = (
        db.query(AcEntityConfig)
        .filter_by(tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type="sales_order")
        .one()
    )
    # A row that exists ONLY for the DB path carries the DB source impl.
    assert row.source_impl == "sql_db"
    db.close()


def test_put_etl_task_allows_an_empty_draft(client, session_factory):
    db = session_factory()
    company = _company(db)
    db.close()
    url = f"/autocount/companies/{company.id}/entities/customer/etl-task"
    response = client.put(url, json={"sourceConfig": _config()}, headers=_auth(client))
    assert response.status_code == 200, response.text


def _put(client, company, body, entity="customer"):
    return client.put(
        f"/autocount/companies/{company.id}/entities/{entity}/etl-task",
        json={"sourceConfig": body},
        headers=_auth(client),
    )


def test_put_etl_task_422_matrix_names_the_field(client, session_factory):
    db = session_factory()
    _other_tenant(db)
    company = _company(db)
    conn = _sql_connection(db)
    theirs = _sql_connection(db, tenant_id=OTHER_TENANT)
    db.close()
    good = "SELECT acc_no, company_name, balance, last_modified FROM debtor"

    def errors(body, entity="customer") -> Dict[str, str]:
        response = _put(client, company, body, entity)
        assert response.status_code == 422, response.text
        return response.json()["detail"]["fieldErrors"]

    # a query needs its connection
    assert "connectionId" in errors(_config(query=good))
    # a connection that is not this tenant's / does not exist
    assert "connectionId" in errors(_config(connectionId=theirs.id, query=good))
    assert "connectionId" in errors(_config(connectionId="nope", query=good))
    # non-SELECT never stored, even as a draft
    assert "query" in errors(_config(connectionId=conn.id, query="DELETE FROM debtor"))
    # a query the source rejects (sanitised)
    q = errors(_config(connectionId=conn.id, query="SELECT * FROM missing_table"))
    assert "query" in q and "[SQL:" not in q["query"] and PASSWORD not in q["query"]
    # columns must exist in the preview result
    assert "keyColumns" in errors(_config(connectionId=conn.id, query=good, keyColumns=["nope"]))
    assert "watermarkColumn" in errors(_config(connectionId=conn.id, query=good, watermarkColumn="nope"))
    assert "comparedColumns" in errors(_config(connectionId=conn.id, query=good, comparedColumns=["acc_no", "nope"]))
    # watermark must be orderable (a text column is not)
    assert "watermarkColumn" in errors(_config(connectionId=conn.id, query=good, watermarkColumn="company_name"))
    # column picks without a query cannot be validated
    assert "query" in errors(_config(keyColumns=["acc_no"]))
    # intervals
    assert "incrementalMinutes" in errors(_config(incrementalMinutes=0))
    assert "incrementalMinutes" in errors(
        _config(connectionId=conn.id, query=good, watermarkColumn="last_modified", incrementalMinutes=0)
    )
    # no watermark → 15 minute floor
    assert "incrementalMinutes" in errors(_config(incrementalMinutes=5))
    assert "reconcileMode" in errors(_config(reconcileMode="weekly"))
    assert "reconcileHours" in errors(_config(reconcileMode="interval", reconcileHours=None))
    assert "reconcileHours" in errors(_config(reconcileMode="interval", reconcileHours=0))
    assert "reconcileAt" in errors(_config(reconcileMode="dailyAt", reconcileAt="25:00"))
    assert "reconcileAt" in errors(_config(reconcileMode="dailyAt", reconcileAt=None))
    # documents need a from-date; a line query is guarded too
    assert "fromDate" in errors(_config(fromDate=None), entity="sales_order")
    assert "fromDate" in errors(_config(fromDate="31/12/2026"), entity="sales_order")
    assert "lineQuery" in errors(
        _config(fromDate="2026-01-01", lineQuery="DELETE FROM x"), entity="sales_order"
    )


def test_put_etl_task_422s_when_the_incremental_wrap_cannot_run(client, session_factory, monkeypatch):
    """S2 review BLOCKER 2: the exact runtime statement shape (the derived-
    table wrap around the watermark column ``SqlDbSource`` will execute on
    every real run) is probed ONCE at save time - a query the target
    database rejects there (MSSQL 8155 unnamed columns, duplicate column
    names, ...) must be a 422 on THIS field, not a run-time surprise the
    first time the task actually fires. No real MSSQL driver runs in this
    suite, so the probe itself is stubbed to fail (simulating the DB's own
    rejection) - what is under test is the WIRING: ``update_task`` actually
    calls it and turns whatever it raises into a named field error, never a
    500, and never persists the rejected config."""
    import modules.autocount.services.etl_service as etl_service_module

    def _boom(self, engine, secrets, query, watermark_column):
        raise RuntimeError("The multi-part identifier could not be bound.")

    monkeypatch.setattr(etl_service_module.EtlService, "_probe_incremental_wrap", _boom)

    db = session_factory()
    company = _company(db)
    conn = _sql_connection(db, db_type="postgresql")
    before = (
        db.query(AcEntityConfig)
        .filter_by(tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type="customer")
        .one()
    )
    assert before.source_impl == "autocount_read"  # the seeded default
    db.close()

    good = "SELECT acc_no, company_name, balance, last_modified FROM debtor"
    response = _put(
        client, company, _config(connectionId=conn.id, query=good, watermarkColumn="balance")
    )
    assert response.status_code == 422, response.text
    errors = response.json()["detail"]["fieldErrors"]
    assert "watermarkColumn" in errors
    assert "cannot be run incrementally" in errors["watermarkColumn"]

    # Nothing was saved - a rejected probe must not persist a task that is
    # guaranteed to fail on its very first run.
    db = session_factory()
    after = (
        db.query(AcEntityConfig)
        .filter_by(tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type="customer")
        .one()
    )
    assert after.source_impl == "autocount_read"
    db.close()


def test_put_etl_task_probes_the_wrap_only_when_a_watermark_column_is_set(
    client, session_factory, monkeypatch
):
    """No watermark column = no incremental fetch = nothing to probe - the
    probe must not run (and so cannot spuriously 422) on a full-extract-only
    task."""
    import modules.autocount.services.etl_service as etl_service_module

    calls: List[str] = []

    def _boom(self, engine, secrets, query, watermark_column):
        calls.append(watermark_column)
        raise RuntimeError("must not be called")

    monkeypatch.setattr(etl_service_module.EtlService, "_probe_incremental_wrap", _boom)

    db = session_factory()
    company = _company(db)
    conn = _sql_connection(db, db_type="postgresql")
    db.close()
    good = "SELECT acc_no, company_name, balance, last_modified FROM debtor"
    response = _put(client, company, _config(connectionId=conn.id, query=good))
    assert response.status_code == 200, response.text
    assert calls == []


def test_put_etl_task_422s_when_the_connection_database_does_not_match_the_company(
    client, session_factory
):
    """S2 review SHOULD-FIX 6: nothing stopped a task from pointing at a SQL
    connection whose ``database`` config is a DIFFERENT database than the
    company's own ``database_name`` - a silent cross-company overwrite path
    (foolproof-UI: 422 always, no confirm-and-proceed escape hatch)."""
    db = session_factory()
    company = _company(db, database_name="AED_2024")
    wrong_db = _sql_connection(db, db_type="postgresql")
    wrong_db_conn = db.get(Connection, wrong_db.id)
    wrong_db_conn.config_json = {**wrong_db_conn.config_json, "database": "OTHER_2025"}
    db.commit()
    db.close()

    good = "SELECT acc_no, company_name, balance, last_modified FROM debtor"
    response = _put(client, company, _config(connectionId=wrong_db.id, query=good))
    assert response.status_code == 422, response.text
    errors = response.json()["detail"]["fieldErrors"]
    assert "connectionId" in errors
    assert "AED_2024" in errors["connectionId"]

    # Nothing was saved.
    db = session_factory()
    row = (
        db.query(AcEntityConfig)
        .filter_by(tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type="customer")
        .one()
    )
    assert row.source_impl == "autocount_read"
    db.close()


def test_put_etl_task_allows_a_connection_whose_database_matches_the_company(
    client, session_factory
):
    db = session_factory()
    company = _company(db, database_name="AED_2024")
    conn = _sql_connection(db, db_type="postgresql")  # config database = AED_2024
    db.close()

    good = "SELECT acc_no, company_name, balance, last_modified FROM debtor"
    response = _put(client, company, _config(connectionId=conn.id, query=good))
    assert response.status_code == 200, response.text


def test_put_etl_task_requires_manage_and_404s_cross_tenant(client, session_factory):
    db = session_factory()
    _other_tenant(db)
    mine = _company(db)
    theirs = _company(db, tenant_id=OTHER_TENANT, database_name="THEIRS")
    _limited_user(db, ["autocount.companies.read"])
    db.close()
    body = {"sourceConfig": _config()}
    assert (
        client.put(f"/autocount/companies/{theirs.id}/entities/customer/etl-task", json=body, headers=_auth(client)).status_code
        == 404
    )
    limited = _auth(client, "limited@example.com", "limited1234")
    assert (
        client.put(f"/autocount/companies/{mine.id}/entities/customer/etl-task", json=body, headers=limited).status_code
        == 403
    )


def test_validation_defaults_compared_columns_to_all_minus_keys_semantics():
    """Pure validator: an empty comparedColumns is stored empty (= "all minus
    keys" at run time), non-document entities drop document-only fields, and a
    non-document task never carries a from-date/line query."""
    columns = {"acc_no": "string", "name": "string", "last_modified": "datetime"}
    clean, errors = validate_source_config(
        "customer",
        _config(
            connectionId="c", query="SELECT 1", keyColumns=["acc_no"],
            fromDate="2026-01-01", lineQuery="SELECT 2", watermarkColumn="last_modified",
            incrementalMinutes=1,
        ),
        columns,
    )
    assert errors == {}
    assert clean["comparedColumns"] == []
    assert clean["fromDate"] is None
    assert clean["lineQuery"] is None
    assert clean["incrementalMinutes"] == 1


def test_backfill_etl_defaults_is_idempotent(session_factory):
    from modules.autocount.backfill import backfill_etl_defaults, default_schema

    db = session_factory()
    _company(db)
    schema = default_schema(db.get_bind())
    assert backfill_etl_defaults(db, schema=schema) >= 0
    assert backfill_etl_defaults(db, schema=schema) == 0
    db.close()
