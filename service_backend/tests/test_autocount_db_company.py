"""DB-only company onboarding (plan sprint-5/01, AC-01-01..11 / AC-01-22).

A company born from a ``sql_database`` connection: identity = the connection's
``config.database`` verified by a live current-database probe, no vendor API
call, no API-shaped seeds, ``sourceKind`` derived on the wire, every vendor
path refusing it cleanly, and the task editor's ``connectionId`` locked to the
company connection.

The probe runs against an in-process SQLite engine bound through
``RUNTIME.put_engine``; the per-dialect statement maps are monkeypatched per
case so the SAME helper answers "match", "mismatch" and "the table is gone".
The connect-failure case binds a real driver at a closed port - no socket ever
answers, so it is deterministic offline.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.models.integration_activity import IntegrationActivity
from app.models.tenant import Tenant
from app.secrets import encrypt_secret
from modules.autocount.canonical.grn import ENTITY_GOODS_RECEIVED_NOTE
from modules.autocount.canonical.masters import ENTITY_CUSTOMER, ENTITY_SUPPLIER
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    ETL_STATUS_DRAFT,
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)
from modules.autocount.services.company_service import (
    SEEDED_ENTITIES,
    CompanyNotApiBacked,
    CompanyService,
    ConnectionNotFound,
)
from modules.autocount.sql_source import probe
from modules.autocount.sql_source.runtime import RUNTIME

PASSWORD = "S3cret!Pa55"
DB_NAME = "AED_2024"
OTHER_TENANT = "tenant-other-db-company"

QUERY = "SELECT acc_no, company_name, email, last_modified FROM debtor"
TASK_BODY: Dict[str, Any] = {
    "query": QUERY,
    "keyColumns": ["acc_no"],
    # No watermark: SQLite reports every column as a string, and the lock
    # under test is on ``connectionId`` - 15 minutes meets the mark-less floor.
    "watermarkColumn": None,
    "comparedColumns": [],
    "incrementalMinutes": 15,
    "reconcileMode": "dailyAt",
    "reconcileAt": "02:00",
}


# ── fixtures ─────────────────────────────────────────────────────────────────


def _auth(client, email="demo@example.com", password="demo1234") -> Dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _other_tenant(db) -> None:
    if db.get(Tenant, OTHER_TENANT) is None:
        default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(
            Tenant(
                id=OTHER_TENANT,
                slug="other-co-db-company",
                name="Other Co",
                status_id=default_tenant.status_id,
            )
        )
        db.commit()


def _source_engine() -> sa.engine.Engine:
    """The probe target AND a task-preview target (one ``debtor`` table)."""
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE debtor (acc_no TEXT PRIMARY KEY, company_name TEXT, "
            "email TEXT, last_modified DATETIME)"
        )
        conn.exec_driver_sql(
            "INSERT INTO debtor VALUES ('300-A001', 'Acme', 'a@x.com', '2026-08-01 09:00:00')"
        )
    return engine


def _connection(
    db, provider: str, config, credentials, *, tenant_id=DEFAULT_TENANT_ID, name=None
) -> Connection:
    conn = Connection(
        tenant_id=tenant_id,
        provider=provider,
        type="erp" if provider != "sorento" else "consumer",
        name=name or f"{provider} conn",
        config_json=config,
        credentials_json=encrypt_secret(credentials),
        is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    db.expunge(conn)
    return conn


def _sql_connection(
    db, *, database: str = DB_NAME, tenant_id=DEFAULT_TENANT_ID, name=None
) -> Connection:
    return _connection(
        db,
        "sql_database",
        {
            "dbType": "postgresql",
            "host": "db.example.com",
            "port": "5432",
            "database": database,
            "username": "readonly",
        },
        {"password": PASSWORD},
        tenant_id=tenant_id,
        name=name,
    )


def _bind_probe(
    monkeypatch,
    conn: Connection,
    *,
    current: Optional[str] = DB_NAME,
    profile: Optional[str] = None,
    profile_sql: Optional[str] = None,
    engine: Optional[sa.engine.Engine] = None,
) -> sa.engine.Engine:
    """Bind an in-process engine to ``conn`` and script the probe answers.

    ``current`` = what the current-database probe returns (None = the probe
    statement itself fails); ``profile`` = the profile-name answer (None =
    no statement for this dialect, i.e. "not readable"); ``profile_sql``
    overrides the profile statement outright (a table that is absent).
    """
    engine = engine or _source_engine()
    RUNTIME.put_engine(conn.id, engine)
    monkeypatch.setattr(
        probe,
        "CURRENT_DATABASE_SQL",
        {
            "postgresql": (
                f"SELECT '{current}'" if current is not None else "SELECT * FROM no_such_table"
            )
        },
    )
    if profile_sql is not None:
        monkeypatch.setattr(probe, "PROFILE_NAME_SQL", {"postgresql": profile_sql})
    elif profile is not None:
        monkeypatch.setattr(probe, "PROFILE_NAME_SQL", {"postgresql": f"SELECT '{profile}'"})
    else:
        monkeypatch.setattr(probe, "PROFILE_NAME_SQL", {})
    return engine


def _api_company(db, *, tenant_id=DEFAULT_TENANT_ID, database_name=DB_NAME) -> AcCompany:
    """An API-kind company exactly as plan 13 births it (seeded)."""
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
    db.expunge(company)
    return company


def _create(client, headers, conn: Connection, *, name: str = ""):
    return client.post(
        "/autocount/companies",
        json={"connectionId": conn.id, "name": name},
        headers=headers,
    )


def _db_company(client, headers, db, monkeypatch, *, database=DB_NAME, **probe_kwargs):
    """A DB company created THROUGH the route (the only birth path)."""
    conn = _sql_connection(db, database=database)
    engine = _bind_probe(monkeypatch, conn, current=database, **probe_kwargs)
    response = _create(client, headers, conn)
    assert response.status_code == 201, response.text
    return response.json(), conn, engine


def _config_rows(db, company_id: str) -> List[AcEntityConfig]:
    return (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == DEFAULT_TENANT_ID,
            AcEntityConfig.company_id == company_id,
        )
        .all()
    )


def _add_config(db, company_id: str, entity_type: str, *, status=ETL_STATUS_DRAFT, enabled=True):
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID,
            company_id=company_id,
            entity_type=entity_type,
            source_impl=SOURCE_IMPL_SQL_DB,
            enabled=enabled,
            etl_status=status,
        )
    )
    db.commit()


@pytest.fixture(autouse=True)
def _clean_runtime():
    yield
    RUNTIME.dispose_all()


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def headers(client):
    return _auth(client)


# ── Group A: create a DB company ──────────────────────────────────────────────


def test_create_from_a_sql_connection_derives_identity_from_the_config_database(
    client, headers, db, monkeypatch
):
    """AC-01-01/02: identity = ``config.database`` (trimmed), no vendor call,
    verified by the live probe; ``sourceKind='db'`` on the created item."""
    conn = _sql_connection(db, database=f"  {DB_NAME}  ")
    _bind_probe(monkeypatch, conn, current=DB_NAME)

    response = _create(client, headers, conn)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["databaseName"] == DB_NAME
    assert body["connectionId"] == conn.id
    assert body["sourceKind"] == "db"
    assert body["companyName"] == ""  # no profile statement for this dialect
    assert body["name"] == DB_NAME  # label falls back to the database
    assert body["documentPrerequisites"] == []


def test_the_operator_label_is_kept_when_given(client, headers, db, monkeypatch):
    conn = _sql_connection(db)
    _bind_probe(monkeypatch, conn)
    response = _create(client, headers, conn, name="  Sorento Trading  ")
    assert response.status_code == 201, response.text
    assert response.json()["name"] == "Sorento Trading"


def test_a_probe_mismatch_is_a_422_on_connectionId_and_creates_nothing(
    client, headers, db, monkeypatch
):
    """AC-01-02: the login lands on a different database than the connection
    names - a per-field 422 the picker renders inline; NOTHING is created."""
    conn = _sql_connection(db)
    _bind_probe(monkeypatch, conn, current="OTHER_DB")

    response = _create(client, headers, conn)

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["fieldErrors"]["connectionId"] == (
        f"This login lands on 'OTHER_DB', but the connection names '{DB_NAME}'."
    )
    assert db.query(AcCompany).filter(AcCompany.tenant_id == DEFAULT_TENANT_ID).count() == 0


def test_a_connect_failure_is_a_422_with_a_sanitized_message(client, headers, db, monkeypatch):
    """AC-01-02: a real driver bound at a closed port - the runtime's sanitized
    message lands on ``connectionId``; never the password, never a DSN."""
    conn = _sql_connection(db)
    dead = sa.create_engine(
        f"postgresql+psycopg2://readonly:{PASSWORD}@127.0.0.1:1/{DB_NAME}",
        connect_args={"connect_timeout": 1},
    )
    _bind_probe(monkeypatch, conn, engine=dead)

    response = _create(client, headers, conn)

    assert response.status_code == 422, response.text
    message = response.json()["detail"]["fieldErrors"]["connectionId"]
    assert message
    assert PASSWORD not in message
    assert "://" not in message
    assert db.query(AcCompany).count() == 0


def test_a_failing_probe_statement_is_a_422_not_a_500(client, headers, db, monkeypatch):
    conn = _sql_connection(db)
    _bind_probe(monkeypatch, conn, current=None)  # the statement itself errors
    response = _create(client, headers, conn)
    assert response.status_code == 422, response.text
    assert "connectionId" in response.json()["detail"]["fieldErrors"]
    assert db.query(AcCompany).count() == 0


def test_the_profile_company_name_is_read_when_available(client, headers, db, monkeypatch):
    """AC-01-03: ``dbo.Profile`` readable → ``company_name`` + the default label."""
    body, _conn, _engine = _db_company(client, headers, db, monkeypatch, profile="Acme Sdn Bhd")
    assert body["companyName"] == "Acme Sdn Bhd"
    assert body["name"] == "Acme Sdn Bhd"


def test_an_absent_profile_table_leaves_company_name_blank_and_still_creates(
    client, headers, db, monkeypatch
):
    """AC-01-03: the table is missing on this database - silent, blank, 201."""
    body, _conn, _engine = _db_company(
        client, headers, db, monkeypatch, profile_sql="SELECT CompanyName FROM Profile"
    )
    assert body["companyName"] == ""
    assert body["name"] == DB_NAME


def test_the_same_database_held_by_an_api_company_is_a_409(client, headers, db, monkeypatch):
    """AC-01-04: one company per database across BOTH kinds."""
    _api_company(db, database_name=DB_NAME)
    conn = _sql_connection(db)
    _bind_probe(monkeypatch, conn)

    response = _create(client, headers, conn)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == f"'{DB_NAME}' is already connected as company 'AED'."
    assert db.query(AcCompany).count() == 1


def test_a_sql_connection_already_bound_to_a_company_is_a_409(client, headers, db, monkeypatch):
    """AC-01-04: ``get_by_connection`` guards the SQL provider too."""
    body, conn, _engine = _db_company(client, headers, db, monkeypatch)
    response = _create(client, headers, conn)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == (
        f"'{DB_NAME}' is already connected as company '{body['name']}'."
    )


def test_a_db_company_seeds_no_entity_configs_or_mappings(client, headers, db, monkeypatch):
    """AC-01-05: NO ``ac_entity_config``/``ac_field_mapping`` rows; the API
    path still seeds exactly ``SEEDED_ENTITIES`` (regression pin)."""
    body, _conn, _engine = _db_company(client, headers, db, monkeypatch)
    assert _config_rows(db, body["id"]) == []
    assert (
        db.query(AcFieldMapping).filter(AcFieldMapping.company_id == body["id"]).count() == 0
    )

    api = _api_company(db, database_name="AED_OTHER")
    assert {row.entity_type for row in _config_rows(db, api.id)} == set(SEEDED_ENTITIES)
    assert db.query(AcFieldMapping).filter(AcFieldMapping.company_id == api.id).count() > 0


def test_create_records_a_discover_company_activity_row(client, headers, db, monkeypatch):
    """AC-01-06: the same ``discover company`` channel the API path writes."""
    body, _conn, _engine = _db_company(client, headers, db, monkeypatch, profile="Acme Sdn Bhd")
    rows = (
        db.query(IntegrationActivity)
        .filter(
            IntegrationActivity.tenant_id == DEFAULT_TENANT_ID,
            IntegrationActivity.operation == "discover company",
        )
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].external_ref == DB_NAME
    response = rows[0].response_summary_json
    # ``record_activity`` masks the payload (``companyName`` is redacted on
    # this channel exactly as the API path's row is) - pin the shape.
    assert set(response) == {"databaseName", "companyName", "source"}
    assert response["databaseName"] == DB_NAME
    assert response["source"] == "sql_database"


def test_a_probe_mismatch_records_an_error_activity_row(client, headers, db, monkeypatch):
    conn = _sql_connection(db)
    _bind_probe(monkeypatch, conn, current="OTHER_DB")
    assert _create(client, headers, conn).status_code == 422
    row = (
        db.query(IntegrationActivity)
        .filter(IntegrationActivity.operation == "discover company")
        .one()
    )
    assert row.status == "error"
    assert row.external_ref == conn.id
    assert "OTHER_DB" in (row.error_message or "")


def test_another_provider_or_another_tenants_connection_is_a_uniform_404(
    client, headers, db, monkeypatch
):
    """AC-01-01: neither a Sorento connection nor a foreign tenant's SQL
    connection ever resolves - the SAME message, no row revealed."""
    sorento = _connection(db, "sorento", {"baseUrl": "https://s.example.com"}, {"apiKey": "k"})
    _other_tenant(db)
    foreign = _sql_connection(db, tenant_id=OTHER_TENANT)
    _bind_probe(monkeypatch, foreign)

    for conn in (sorento, foreign):
        response = _create(client, headers, conn)
        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "That connection was not found."
    assert db.query(AcCompany).count() == 0


def test_an_autocount_connection_still_runs_the_api_flow(client, headers, db, monkeypatch):
    """AC-01-01 regression pin: an ``autocount`` connection signs in and seeds."""
    from datetime import datetime, timezone

    import modules.autocount.services.company_service as company_module
    from modules.autocount.client import Session as VendorSession

    class FakeClient:
        calls: List[Any] = []

        def login(self):
            return VendorSession(
                jwt_token="jwt",
                token="guid",
                database_name="AED_VSOFT",
                company_name="AED Vsoft Sdn Bhd",
                issued_at=datetime.now(timezone.utc),
            )

        def close(self):
            pass

    monkeypatch.setattr(
        company_module, "client_from_connection", lambda *_a, **_k: FakeClient()
    )
    monkeypatch.setattr(company_module, "record_client_calls", lambda *_a, **_k: None)
    api = _connection(
        db,
        "autocount",
        {"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        {"appId": "app-1", "password": "secret"},
    )

    response = _create(client, headers, api)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["databaseName"] == "AED_VSOFT"
    assert body["companyName"] == "AED Vsoft Sdn Bhd"
    assert body["sourceKind"] == "api"
    assert {row.entity_type for row in _config_rows(db, body["id"])} == set(SEEDED_ENTITIES)


def test_create_requires_companies_manage(client, db, monkeypatch):
    """The EXISTING ``autocount.companies.manage`` gates create - no new key."""
    conn = _sql_connection(db)
    _bind_probe(monkeypatch, conn)
    response = client.post("/autocount/companies", json={"connectionId": conn.id, "name": ""})
    assert response.status_code == 401


# ── Group B: provider-aware wiring ───────────────────────────────────────────


def test_source_kind_is_derived_on_list_and_detail(client, headers, db, monkeypatch):
    """AC-01-07: ``sourceKind`` from the connection's provider, list + detail."""
    api = _api_company(db, database_name="AED_API")
    body, _conn, _engine = _db_company(client, headers, db, monkeypatch)

    listed = client.get("/autocount/companies", headers=headers)
    assert listed.status_code == 200, listed.text
    kinds = {row["id"]: row["sourceKind"] for row in listed.json()["data"]}
    assert kinds == {api.id: "api", body["id"]: "db"}
    assert all(row["documentPrerequisites"] == [] for row in listed.json()["data"])

    for company_id, kind in kinds.items():
        detail = client.get(f"/autocount/companies/{company_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["company"]["sourceKind"] == kind


def test_the_list_resolves_connections_in_one_batched_query(
    client, headers, db, session_factory, monkeypatch
):
    """AC-01-07: the statement count for the list does NOT grow with the
    number of companies (one ``IN`` query, never one per row)."""
    engine = session_factory().get_bind()
    counter: Dict[str, int] = {"n": 0}

    def _count(*_args, **_kwargs):
        counter["n"] += 1

    sa.event.listen(engine, "before_cursor_execute", _count)
    try:
        _api_company(db, database_name="AED_1")
        counter["n"] = 0
        assert client.get("/autocount/companies", headers=headers).status_code == 200
        with_one = counter["n"]

        for n in range(2, 6):
            if n % 2:
                _api_company(db, database_name=f"AED_{n}")
            else:
                _db_company(client, headers, db, monkeypatch, database=f"AED_{n}")
        counter["n"] = 0
        response = client.get("/autocount/companies", headers=headers)
        assert response.status_code == 200
        assert response.json()["total"] == 5
        with_five = counter["n"]
    finally:
        sa.event.remove(engine, "before_cursor_execute", _count)

    assert with_five == with_one, (with_one, with_five)


def test_a_deleted_connection_reports_api_and_never_500s(client, headers, db, monkeypatch):
    """AC-01-07: a company whose connection row is gone stays readable."""
    body, conn, _engine = _db_company(client, headers, db, monkeypatch)
    db.query(Connection).filter(Connection.id == conn.id).delete()
    db.commit()

    listed = client.get("/autocount/companies", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"][0]["sourceKind"] == "api"

    detail = client.get(f"/autocount/companies/{body['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["company"]["sourceKind"] == "api"


def test_client_for_refuses_a_db_company_with_a_named_error(client, headers, db, monkeypatch):
    """AC-01-08: the vendor client is never built for a DB company - a
    ``CompanyNotApiBacked`` (409), NEVER ``ConnectionNotFound``."""
    body, _conn, _engine = _db_company(client, headers, db, monkeypatch)
    service = CompanyService(db)
    company = service.get(DEFAULT_TENANT_ID, body["id"])

    with pytest.raises(CompanyNotApiBacked) as excinfo:
        service.client_for(DEFAULT_TENANT_ID, company)
    assert not isinstance(excinfo.value, ConnectionNotFound)
    assert excinfo.value.message == (
        "This company is connected by database; the AutoCount API is not available."
    )


def test_switching_an_entity_to_autocount_read_on_a_db_company_is_a_409(
    client, headers, db, monkeypatch
):
    """AC-01-08: ``sourceImpl='autocount_read'`` has nowhere to read from."""
    body, _conn, _engine = _db_company(client, headers, db, monkeypatch)
    _add_config(db, body["id"], ENTITY_CUSTOMER)

    response = client.patch(
        f"/autocount/companies/{body['id']}/entities/{ENTITY_CUSTOMER}",
        json={"sourceImpl": "autocount_read"},
        headers=headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == (
        "This company is connected by database; the AutoCount API is not available."
    )
    row = _config_rows(db, body["id"])[0]
    db.refresh(row)
    assert row.source_impl == SOURCE_IMPL_SQL_DB


@pytest.mark.parametrize("entity_type", [ENTITY_CUSTOMER, ENTITY_SUPPLIER])
def test_an_omitted_task_connection_is_filled_and_the_row_is_born_sql_db(
    client, headers, db, monkeypatch, entity_type
):
    """AC-01-09 + AC-01-10: no ``connectionId`` → the company connection; the
    first save for customer/supplier births the row ``sql_db``."""
    body, conn, _engine = _db_company(client, headers, db, monkeypatch)

    response = client.put(
        f"/autocount/companies/{body['id']}/entities/{entity_type}/etl-task",
        json={"sourceConfig": TASK_BODY},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["sourceConfig"]["connectionId"] == conn.id
    assert response.json()["resultColumns"] == ["acc_no", "company_name", "email", "last_modified"]
    rows = _config_rows(db, body["id"])
    assert [row.entity_type for row in rows] == [entity_type]
    assert rows[0].source_impl == SOURCE_IMPL_SQL_DB
    assert rows[0].source_config["connectionId"] == conn.id


def test_a_different_connection_on_a_db_company_is_a_422(client, headers, db, monkeypatch):
    """AC-01-09: a DB company reads ONLY from its own connection."""
    body, _conn, engine = _db_company(client, headers, db, monkeypatch)
    other = _sql_connection(db, database=DB_NAME, name="another sql conn")
    RUNTIME.put_engine(other.id, engine)

    response = client.put(
        f"/autocount/companies/{body['id']}/entities/{ENTITY_CUSTOMER}/etl-task",
        json={"sourceConfig": {**TASK_BODY, "connectionId": other.id}},
        headers=headers,
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["fieldErrors"]["connectionId"] == (
        "A database company reads only from its own connection."
    )
    assert _config_rows(db, body["id"]) == []


def test_an_api_company_keeps_the_free_picker(client, headers, db, monkeypatch):
    """AC-01-09 regression pin: an API company may pick ANY tenant SQL
    connection for its database, and an omitted one stays an error."""
    api = _api_company(db, database_name=DB_NAME)
    sql = _sql_connection(db)
    RUNTIME.put_engine(sql.id, _source_engine())

    picked = client.put(
        f"/autocount/companies/{api.id}/entities/{ENTITY_CUSTOMER}/etl-task",
        json={"sourceConfig": {**TASK_BODY, "connectionId": sql.id}},
        headers=headers,
    )
    assert picked.status_code == 200, picked.text
    assert picked.json()["sourceConfig"]["connectionId"] == sql.id

    omitted = client.put(
        f"/autocount/companies/{api.id}/entities/{ENTITY_CUSTOMER}/etl-task",
        json={"sourceConfig": TASK_BODY},
        headers=headers,
    )
    assert omitted.status_code == 422, omitted.text
    assert omitted.json()["detail"]["fieldErrors"]["connectionId"] == (
        "Choose the connection this query runs on."
    )


def test_goods_received_note_is_not_available_on_a_db_company(client, headers, db, monkeypatch):
    """AC-01-10: GRN has no Sorento path and an API-only envelope."""
    body, _conn, _engine = _db_company(client, headers, db, monkeypatch)
    response = client.put(
        f"/autocount/companies/{body['id']}/entities/{ENTITY_GOODS_RECEIVED_NOTE}/etl-task",
        json={"sourceConfig": TASK_BODY},
        headers=headers,
    )
    assert response.status_code == 422, response.text
    assert "not available on a database company" in response.json()["detail"]
    assert _config_rows(db, body["id"]) == []


# ── AC-01-11: documentPrerequisites matrix ───────────────────────────────────


def _prerequisites(client, headers, company_id: str):
    response = client.get(f"/autocount/companies/{company_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["company"]["documentPrerequisites"]


def test_document_prerequisites_are_empty_without_a_document_entity(
    client, headers, db, monkeypatch
):
    body, _conn, _engine = _db_company(client, headers, db, monkeypatch)
    _add_config(db, body["id"], ENTITY_CUSTOMER, status=ETL_STATUS_ACTIVE)
    assert _prerequisites(client, headers, body["id"]) == []


def test_document_prerequisites_report_missing_masters(client, headers, db, monkeypatch):
    body, _conn, _engine = _db_company(client, headers, db, monkeypatch)
    _add_config(db, body["id"], "sales_order")
    assert _prerequisites(client, headers, body["id"]) == [
        {"entityType": "sales_order", "missing": ["customer", "product"], "inactive": []}
    ]


def test_document_prerequisites_report_inactive_masters(client, headers, db, monkeypatch):
    """A draft task and a disabled row both count as inactive."""
    body, _conn, _engine = _db_company(client, headers, db, monkeypatch)
    _add_config(db, body["id"], "purchase_order", status=ETL_STATUS_ACTIVE)
    _add_config(db, body["id"], ENTITY_SUPPLIER, status=ETL_STATUS_DRAFT)
    _add_config(db, body["id"], "product", status=ETL_STATUS_ACTIVE, enabled=False)
    assert _prerequisites(client, headers, body["id"]) == [
        {"entityType": "purchase_order", "missing": [], "inactive": ["supplier", "product"]}
    ]


def test_document_prerequisites_are_clear_when_all_masters_are_active(
    client, headers, db, monkeypatch
):
    body, _conn, _engine = _db_company(client, headers, db, monkeypatch)
    _add_config(db, body["id"], "sales_order", status=ETL_STATUS_ACTIVE)
    _add_config(db, body["id"], "purchase_order")
    _add_config(db, body["id"], ENTITY_CUSTOMER, status=ETL_STATUS_ACTIVE)
    _add_config(db, body["id"], "product", status=ETL_STATUS_ACTIVE)
    # One entry per CONFIGURED document entity, in the company's stored
    # entity order (``entity_type`` asc) - an all-active document still lists,
    # with both arrays empty (the card decides to render nothing).
    assert _prerequisites(client, headers, body["id"]) == [
        {"entityType": "purchase_order", "missing": ["supplier"], "inactive": []},
        {"entityType": "sales_order", "missing": [], "inactive": []},
    ]


def test_document_prerequisites_apply_to_an_api_company_too(client, headers, db):
    api = _api_company(db, database_name=DB_NAME)  # seeds customer + supplier (draft)
    _add_config(db, api.id, "sales_order")
    assert _prerequisites(client, headers, api.id) == [
        {"entityType": "sales_order", "missing": ["product"], "inactive": ["customer"]}
    ]
