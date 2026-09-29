"""Shared builders for the sprint-5/14 (DO/GRN/branch HTTP source) red tests.

Not itself a test file (no `test_` prefix - the autouse network-block/DNS-stub
fixtures in `conftest.py` are scoped by FILENAME regex, and this helper is
imported BY `test_s14_*.py` files, which already match `s14_` after the D21
conftest edit). Mirrors the house convention `tests/meetings_helpers.py`
already sets for a shared-but-not-a-test module.

Every builder is tenant-scoped and mirrors an existing precedent exactly:
`_auth`/`_limited_user`/`_other_tenant` copy `tests/test_autocount_etl_routes.py`
byte-for-byte in spirit; `_company` copies `tests/test_autocount_scheduler.py`.
Fixture loading reads the JSON files committed at
`service_backend/tests/fixtures/s14_doc_feed/` (see that dir's own README for
provenance), resolved next to this file so the Docker image (no repo root)
can collect them.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import sqlalchemy as sa

from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.models.connection import Connection
from app.models.tenant import Tenant
from app.repositories.permission_repository import PermissionRepository
from app.secrets import encrypt_secret
from app.security import hash_password

OTHER_TENANT_ID = "tenant-s14-other"
PASSWORD = "S3cret!Pa55"

VENDOR_BASE_URL = "https://hapi.sorento.cc.cd/api/db1"
CRM_BASE_URL = "http://crm.example.test"
SORENTO_API_KEY = "sorento-doc-feed-test-key"
SORENTO_COMPANY_CODE = "SRT"
BOOK = "db1"

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "s14_doc_feed"


def load_fixture(name: str) -> Any:
    """Parse one committed JSON fixture (service_backend/tests/fixtures/s14_doc_feed/<name>)."""
    with open(_FIXTURES_DIR / name, "r", encoding="utf-8") as handle:
        return json.load(handle)


def auth_headers(client, email: str = "demo@example.com", password: str = "demo1234") -> Dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def limited_user(db, keys: List[str], email: str = "s14-limited@example.com") -> None:
    """A default-tenant user holding ONLY the given permission keys."""
    perms = PermissionRepository(db)
    role = Role(tenant_id=DEFAULT_TENANT_ID, name=f"S14 limited {email}", description="")
    role.permissions = [p for p in perms.list_all() if p.key in keys]
    db.add(role)
    db.flush()
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email=email,
        password=hash_password("limited1234"),
        name="S14 Limited",
        status=UserStatus.ACTIVE.value,
        email_verified_at=sa.func.now(),
    )
    user.roles = [role]
    db.add(user)
    db.commit()


def other_tenant(db) -> str:
    if db.get(Tenant, OTHER_TENANT_ID) is None:
        default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(
            Tenant(
                id=OTHER_TENANT_ID,
                slug="s14-other-co",
                name="S14 Other Co",
                status_id=default_tenant.status_id,
            )
        )
        db.commit()
    return OTHER_TENANT_ID


def autocount_connection(
    db,
    tenant_id: str = DEFAULT_TENANT_ID,
    *,
    base_url: str = VENDOR_BASE_URL,
    auth: str = "none",
    name: str = "db1 open API",
) -> Connection:
    """A tenant `autocount` open-REST connection (the vendor side)."""
    config: Dict[str, Any] = {"baseUrl": base_url, "auth": auth}
    credentials: Dict[str, Any] = {}
    if auth == "basic":
        config.update({"userId": "ADMIN"})
        credentials = {"appId": "app-1", "password": "secret"}
    conn = Connection(
        tenant_id=tenant_id,
        provider="autocount",
        type="erp",
        name=name,
        config_json=config,
        credentials_json=encrypt_secret(credentials),
        is_active=True,
    )
    db.add(conn)
    db.flush()
    return conn


def sorento_connection(
    db,
    tenant_id: str = DEFAULT_TENANT_ID,
    *,
    base_url: str = CRM_BASE_URL,
    api_key: str = SORENTO_API_KEY,
    name: str = "Sorento CRM",
) -> Connection:
    """A tenant `sorento` consumer connection (the CRM sink side)."""
    conn = Connection(
        tenant_id=tenant_id,
        provider="sorento",
        type="consumer",
        name=name,
        config_json={"baseUrl": base_url},
        credentials_json=encrypt_secret({"apiKey": api_key}),
        is_active=True,
    )
    db.add(conn)
    db.flush()
    return conn


def company(
    db,
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
    name: str = "S14 Doc Feed Co",
    database_name: Optional[str] = None,
    sink_connection: Optional[Connection] = None,
    sorento_company_code: Optional[str] = SORENTO_COMPANY_CODE,
    ac_connection: Optional[Connection] = None,
):
    """One `AcCompany` wired for the doc-feed lane: an `autocount` open API
    connection (vendor reads) plus (unless suppressed) a `sorento` consumer
    connection (the CRM sink) and company code - the "gate open" baseline
    every config/poll/sweep/backfill test starts from unless it is
    specifically testing an unwired company."""
    from modules.autocount.models import SINK_IMPL_LOGGING, SINK_IMPL_SORENTO, AcCompany
    from modules.autocount.services.company_service import CompanyService

    ac_conn = ac_connection or autocount_connection(db, tenant_id)
    db_name = database_name or f"S14DB_{ac_conn.id[-8:]}"
    rec = AcCompany(
        tenant_id=tenant_id,
        connection_id=ac_conn.id,
        database_name=db_name,
        company_name=name,
        name=name,
        is_active=True,
    )
    if sink_connection is not None:
        rec.sink_impl = SINK_IMPL_SORENTO
        rec.sink_connection_id = sink_connection.id
        rec.sorento_company_code = sorento_company_code
    else:
        rec.sink_impl = SINK_IMPL_LOGGING
    db.add(rec)
    db.flush()
    CompanyService(db).seed_company_defaults(tenant_id, rec.id)
    db.commit()
    db.refresh(rec)
    return rec


def wired_company(db, *, tenant_id: str = DEFAULT_TENANT_ID):
    """The full happy-path wiring: an eligible `autocount` connection + a
    `sorento` consumer connection + company code - what every poll/sweep/
    backfill test needs before it can even reach the gate check."""
    ac_conn = autocount_connection(db, tenant_id)
    crm_conn = sorento_connection(db, tenant_id)
    return company(db, tenant_id=tenant_id, sink_connection=crm_conn, ac_connection=ac_conn), ac_conn, crm_conn


class JsonRoute:
    """One routed response for `route_transport` below."""

    __slots__ = ("status_code", "json_body", "headers")

    def __init__(self, json_body: Any, *, status_code: int = 200, headers: Optional[Dict[str, str]] = None):
        self.status_code = status_code
        self.json_body = json_body
        self.headers = headers or {}


def route_transport(routes: Dict[str, Any]) -> httpx.MockTransport:
    """`httpx.MockTransport` keyed by exact request path (``request.url.path``,
    query string ignored - the caller's key is just the path, e.g.
    ``"/deliveryorderbyLastModified"`` or ``"/api/v1/external/contract"``).

    ``routes[path]`` is either a plain dict/list (200 JSON) or a `JsonRoute`
    (explicit status/headers, e.g. a 429 with ``Retry-After``) or a callable
    ``(request) -> httpx.Response`` for a path whose answer depends on the
    query string (e.g. paging by day). An unrouted path 404s loudly rather
    than silently 200ing - a test that forgot to route a call should fail
    with a clear KeyError-shaped message, not a false green.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        entry = routes.get(path)
        if entry is None:
            raise AssertionError(
                f"s14 test transport: no route for {request.method} {request.url} "
                f"(routed paths: {sorted(routes)})"
            )
        if callable(entry) and not isinstance(entry, JsonRoute):
            return entry(request)
        if isinstance(entry, JsonRoute):
            return httpx.Response(entry.status_code, json=entry.json_body, headers=entry.headers)
        return httpx.Response(200, json=entry)

    return httpx.MockTransport(handler)
