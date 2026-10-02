"""Sprint-5/08 S2 - open (no-auth) company onboarding (AC-08-06/07/08).

RED before the coder: ``CompanyService.create_from_open_connection`` does not
exist yet (``services/company_service.py``, read 2026-09-12); ``create()``
dispatches ONLY on ``conn.provider`` (``sql_database`` vs ``autocount``), never
on ``auth_mode`` - an open (no-auth) ``autocount`` connection falls through to
the vendor-login path today. ``source_kind()`` returns only ``'api'``/``'db'``.

Tests call the SERVICE directly for the new create path (precise, avoids the
``CompanyCreate`` wire schema gap - ``refPrefix`` is not on that schema yet,
a coder TODO noted in the test report) and hit the real ``POST
/autocount/companies`` route once to pin the end-to-end dispatch gap.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.models.tenant import Tenant
from app.secrets import encrypt_secret
from modules.autocount.models import AcCompany
from modules.autocount.services.company_service import (
    CompanyNotApiBacked,
    CompanyService,
)

try:
    from modules.autocount.services.company_service import (
        ConnectionValidationError,
        SOURCE_KIND_HTTP,
    )
except ImportError:  # pragma: no cover - expected until the coder adds it
    from modules.autocount.services.company_service import ConnectionValidationError

    SOURCE_KIND_HTTP = "http"

OTHER_TENANT = "tenant-other-open-company"
BASE_URL = "https://hapi.sorento.cc.cd/api/db2"


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
                slug="other-co-open-company",
                name="Other Co",
                status_id=default_tenant.status_id,
            )
        )
        db.commit()


def _open_connection(
    db, *, base_url: str = BASE_URL, tenant_id: str = DEFAULT_TENANT_ID, name: str = "Mocha REST"
) -> Connection:
    conn = Connection(
        tenant_id=tenant_id,
        provider="autocount",
        type="erp",
        name=name,
        config_json={"baseUrl": base_url, "auth": "none"},
        credentials_json=None,
        is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    db.expunge(conn)
    return conn


def _basic_connection(db, *, tenant_id: str = DEFAULT_TENANT_ID) -> Connection:
    conn = Connection(
        tenant_id=tenant_id,
        provider="autocount",
        type="erp",
        name="AutoCount API",
        config_json={"baseUrl": "https://ac.example.com", "auth": "basic", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}),
        is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    db.expunge(conn)
    return conn


def _sql_connection(db, *, tenant_id: str = DEFAULT_TENANT_ID) -> Connection:
    conn = Connection(
        tenant_id=tenant_id,
        provider="sql_database",
        type="erp",
        name="AutoCount DB",
        config_json={"dbType": "postgresql", "database": "AED_2024"},
        credentials_json=encrypt_secret({"password": "x"}),
        is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    db.expunge(conn)
    return conn


def _transport(rows: Optional[List[Dict[str, Any]]] = None, *, status: int = 200) -> httpx.Client:
    body = rows if rows is not None else [{"Location": "A1"}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body if status == 200 else None)

    return httpx.Client(transport=httpx.MockTransport(handler))


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


# ── AC-08-06: create_from_open_connection happy path + probe failures ────────


def test_create_open_company_happy(db):
    conn = _open_connection(db)
    company = CompanyService(db).create_from_open_connection(
        DEFAULT_TENANT_ID, conn, name="Mocha", ref_prefix="MOCHA", transport=_transport()
    )
    assert company.connection_id == conn.id
    assert company.database_name == "MOCHA"
    assert company.name == "Mocha"


def test_create_open_company_probe_fails_422_connectionId(db):
    conn = _open_connection(db)
    with pytest.raises(ConnectionValidationError):
        CompanyService(db).create_from_open_connection(
            DEFAULT_TENANT_ID, conn, name="Mocha", ref_prefix="MOCHA",
            transport=_transport(status=500),
        )
    assert db.query(AcCompany).count() == 0


def test_create_open_company_probe_non_array_body_422(db):
    conn = _open_connection(db)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"not": "array"})

    with pytest.raises(ConnectionValidationError):
        CompanyService(db).create_from_open_connection(
            DEFAULT_TENANT_ID, conn, name="Mocha", ref_prefix="MOCHA",
            transport=httpx.Client(transport=httpx.MockTransport(handler)),
        )


def test_second_company_same_open_connection_409(db):
    conn = _open_connection(db)
    CompanyService(db).create_from_open_connection(
        DEFAULT_TENANT_ID, conn, name="Mocha", ref_prefix="MOCHA", transport=_transport()
    )
    from modules.autocount.services.company_service import CompanyAlreadyExists

    with pytest.raises(CompanyAlreadyExists):
        CompanyService(db).create_from_open_connection(
            DEFAULT_TENANT_ID, conn, name="Mocha Again", ref_prefix="MOCHA2",
            transport=_transport(),
        )


def test_no_seed_company_defaults_on_open_company(db):
    """AC-08-06: mirrors the DB branch (D13) - NO ac_entity_config/
    ac_field_mapping rows are seeded for an open company."""
    from modules.autocount.models import AcEntityConfig, AcFieldMapping

    conn = _open_connection(db)
    company = CompanyService(db).create_from_open_connection(
        DEFAULT_TENANT_ID, conn, name="Mocha", ref_prefix="MOCHA", transport=_transport()
    )
    assert db.query(AcEntityConfig).filter(AcEntityConfig.company_id == company.id).count() == 0
    assert db.query(AcFieldMapping).filter(AcFieldMapping.company_id == company.id).count() == 0


# ── AC-08-07: ref prefix normalisation + validation ───────────────────────────


def test_ref_prefix_required_422_blank(db):
    conn = _open_connection(db)
    with pytest.raises(ConnectionValidationError):
        CompanyService(db).create_from_open_connection(
            DEFAULT_TENANT_ID, conn, name="Mocha", ref_prefix="  ", transport=_transport()
        )


def test_ref_prefix_normalised_trim_and_upper(db):
    conn = _open_connection(db)
    company = CompanyService(db).create_from_open_connection(
        DEFAULT_TENANT_ID, conn, name="Mocha", ref_prefix="  mocha  ", transport=_transport()
    )
    assert company.database_name == "MOCHA"


@pytest.mark.parametrize("bad_prefix", ["M", "A-B", "X" * 33, "HAS SPACE"])
def test_ref_prefix_regex_422(db, bad_prefix):
    conn = _open_connection(db)
    with pytest.raises(ConnectionValidationError):
        CompanyService(db).create_from_open_connection(
            DEFAULT_TENANT_ID, conn, name="Mocha", ref_prefix=bad_prefix, transport=_transport()
        )


def test_ref_prefix_duplicate_409_names_holder(db):
    conn_a = _open_connection(db, name="Mocha REST A")
    CompanyService(db).create_from_open_connection(
        DEFAULT_TENANT_ID, conn_a, name="Mocha", ref_prefix="MOCHA", transport=_transport()
    )
    conn_b = _open_connection(db, name="Mocha REST B")
    from modules.autocount.services.company_service import CompanyAlreadyExists

    with pytest.raises(CompanyAlreadyExists) as exc:
        CompanyService(db).create_from_open_connection(
            DEFAULT_TENANT_ID, conn_b, name="Mocha Two", ref_prefix="MOCHA", transport=_transport()
        )
    assert "MOCHA" in exc.value.message


def test_ref_prefix_duplicate_race_forced_integrity_error_409(db, monkeypatch):
    """S13 (sprint-5/08 review round 1) - the ``get_by_database_name``
    pre-check closes the COMMON race window, but two concurrent creates for
    the same prefix can both pass it; only the DB's own unique constraint
    catches THAT. Forced here by making the pre-check lie (simulating the
    race) while a real holder already exists - the ``IntegrityError`` from
    the unique index must still surface as a clean 409, never a raw 500."""
    from modules.autocount.services.company_service import CompanyAlreadyExists

    conn_a = _open_connection(db, name="Mocha REST A")
    CompanyService(db).create_from_open_connection(
        DEFAULT_TENANT_ID, conn_a, name="Mocha", ref_prefix="MOCHA", transport=_transport()
    )
    conn_b = _open_connection(db, name="Mocha REST B")
    service = CompanyService(db)
    monkeypatch.setattr(service.companies, "get_by_database_name", lambda *a, **k: None)
    with pytest.raises(CompanyAlreadyExists) as exc:
        service.create_from_open_connection(
            DEFAULT_TENANT_ID, conn_b, name="Mocha Two", ref_prefix="MOCHA", transport=_transport()
        )
    assert "MOCHA" in exc.value.message


def test_ref_prefix_not_applicable_on_basic_connection_422(db):
    """A ref prefix is ignored (422 'not applicable') when the connection is
    vendor (basic) or sql_database - `create()` is expected to reject a
    ref_prefix argument on a non-open connection rather than silently accept
    it.

    S8 (sprint-5/08 review round 1) - was ``pytest.raises(Exception)``,
    which passes for ANY exception (a typo'd attribute, an unrelated crash)
    just as happily as the real validation error; now pins the actual
    error class AND the ``refPrefix`` field error, matching every other
    ``ConnectionValidationError`` assertion in this module."""
    conn = _basic_connection(db)
    service = CompanyService(db)
    with pytest.raises(ConnectionValidationError) as exc:
        service.create(DEFAULT_TENANT_ID, conn.id, name="X", ref_prefix="NOTAPPLICABLE")
    assert exc.value.field_errors == {
        "refPrefix": "A reference prefix only applies to a no-auth API connection."
    }


def test_ref_prefix_not_applicable_on_sql_connection_422(db):
    conn = _sql_connection(db)
    service = CompanyService(db)
    with pytest.raises(ConnectionValidationError) as exc:
        service.create(DEFAULT_TENANT_ID, conn.id, name="X", ref_prefix="NOTAPPLICABLE")
    assert exc.value.field_errors == {
        "refPrefix": "A reference prefix only applies to a no-auth API connection."
    }


# ── AC-08-08: source_kind + guards ─────────────────────────────────────────────


def test_source_kind_http_for_open_connection(db):
    conn = _open_connection(db)
    company = CompanyService(db).create_from_open_connection(
        DEFAULT_TENANT_ID, conn, name="Mocha", ref_prefix="MOCHA", transport=_transport()
    )
    assert CompanyService(db).source_kind_for(DEFAULT_TENANT_ID, company) == SOURCE_KIND_HTTP


def test_client_for_open_company_raises_company_not_api_backed(db):
    conn = _open_connection(db)
    company = CompanyService(db).create_from_open_connection(
        DEFAULT_TENANT_ID, conn, name="Mocha", ref_prefix="MOCHA", transport=_transport()
    )
    with pytest.raises(CompanyNotApiBacked):
        CompanyService(db).client_for(DEFAULT_TENANT_ID, company)


def test_update_entity_config_autocount_read_on_open_company_422(db):
    from modules.autocount.canonical.masters import ENTITY_CUSTOMER
    from modules.autocount.models import AcEntityConfig, SYNC_MODE_MANUAL

    conn = _open_connection(db)
    company = CompanyService(db).create_from_open_connection(
        DEFAULT_TENANT_ID, conn, name="Mocha", ref_prefix="MOCHA", transport=_transport()
    )
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID,
            company_id=company.id,
            entity_type=ENTITY_CUSTOMER,
            sync_mode=SYNC_MODE_MANUAL,
            source_impl="sql_db",
        )
    )
    db.commit()
    with pytest.raises(CompanyNotApiBacked):
        CompanyService(db).update_entity_config(
            DEFAULT_TENANT_ID, company.id, ENTITY_CUSTOMER, source_impl="autocount_read"
        )


# ── router: create() must dispatch an open connection here, not the vendor path ─


def test_router_create_dispatches_open_connection_without_a_vendor_login(client, headers, db, monkeypatch):
    """End-to-end pin (AC-08-06): posting an open (no-auth) connection through
    `POST /autocount/companies` must never attempt a real vendor login - it is
    expected to succeed via `create_from_open_connection` once wired. RED
    today: `create()` only branches on `conn.provider`, so a no-auth
    `autocount` connection falls into the vendor-login flow and 422s (or
    worse, tries a real network call) instead of succeeding."""
    import modules.autocount.services.company_service as company_module

    login_attempts: List[Any] = []

    class FakeFailingClient:
        def login(self):
            login_attempts.append(True)
            from modules.autocount.client import AutoCountAuthError

            raise AutoCountAuthError("no credentials")

        def close(self):
            pass

    monkeypatch.setattr(
        company_module, "client_from_connection", lambda *_a, **_k: FakeFailingClient()
    )
    conn = _open_connection(db)
    # B4 (sprint-5/08 review round 1): the reachability probe itself is a
    # REAL network call unless the router's ``get_http_transport``
    # dependency is overridden - this test used to reach
    # ``hapi.sorento.cc.cd`` for the exact reason it exists (proving the
    # router-level dispatch), which is precisely what must never happen in
    # the suite.
    from app.main import app
    from modules.autocount.http_client import get_http_transport

    app.dependency_overrides[get_http_transport] = lambda: _transport(
        [{"Location": "A1"}]
    )
    try:
        response = client.post(
            "/autocount/companies",
            json={"connectionId": conn.id, "name": "Mocha", "refPrefix": "MOCHA"},
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)
    assert response.status_code == 201, response.text
    assert response.json()["sourceKind"] == SOURCE_KIND_HTTP
    assert not login_attempts, "an open connection must never sign in to the vendor API"
