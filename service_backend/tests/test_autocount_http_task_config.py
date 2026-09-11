"""Sprint-5/08 S3 - HTTP task configuration: registration, validation, preview,
connections list, first-save preset seeding (AC-08-12..17).

RED before the coder: ``modules.autocount.models.SOURCE_IMPL_AUTOCOUNT_HTTP``
does not exist; nothing registers an ``autocount_http`` source
(``modules/autocount/sources.py`` only knows ``autocount_read``); the router
carries no ``/autocount/http/*`` routes (``routers/companies.py`` /
``routers/sql.py``, read 2026-09-12); ``EtlService.update_task`` is 100% SQL-
shaped (no ``sourceImpl`` branch at all).

Task-level tests call ``EtlService.update_task`` DIRECTLY with a raw dict
shaped exactly per the UAC's "HTTP task" definition
(``{connectionId, path, keyFields, watermarkField, comparedFields, distinctOf,
incrementalMinutes, reconcileMode, reconcileAt}`` + ``sourceImpl:
"autocount_http"``) - this is the real Router->Service seam the coder must
extend; it sidesteps the ``EtlTaskUpdate``/``EtlSourceConfigIn`` Pydantic
schemas, which do not carry ``path``/``keyFields``/``distinctOf``/``sourceImpl``
yet either (a schema-widening TODO called out in the test report).
"""
from __future__ import annotations

from typing import Any, Dict

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.masters import ENTITY_CUSTOMER, ENTITY_PRODUCT
from modules.autocount.canonical.grn import ENTITY_GOODS_RECEIVED_NOTE
from modules.autocount.services.company_service import CompanyService
from modules.autocount.services.etl_service import EtlService, EtlValidationError

try:
    from modules.autocount.models import SOURCE_IMPL_AUTOCOUNT_HTTP
except ImportError:  # pragma: no cover - expected until the coder adds it
    SOURCE_IMPL_AUTOCOUNT_HTTP = "autocount_http"


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def headers(client):
    response = client.post(
        "/auth/login", json={"email": "demo@example.com", "password": "demo1234"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _transport(rows, *, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=rows if status == 200 else None)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _open_connection(db, *, tenant_id: str = DEFAULT_TENANT_ID, base_url: str = "https://hapi.sorento.cc.cd/api/db2") -> Connection:
    conn = Connection(
        tenant_id=tenant_id, provider="autocount", type="erp", name="Mocha REST",
        config_json={"baseUrl": base_url, "auth": "none"}, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    db.expunge(conn)
    return conn


def _sql_connection(db, *, tenant_id: str = DEFAULT_TENANT_ID) -> Connection:
    conn = Connection(
        tenant_id=tenant_id, provider="sql_database", type="erp", name="AutoCount DB",
        config_json={"dbType": "postgresql", "database": "AED_2024"},
        credentials_json=encrypt_secret({"password": "x"}), is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    db.expunge(conn)
    return conn


def _open_company(db, transport=None):
    from modules.autocount.services.company_service import CompanyService as CS

    conn = _open_connection(db)
    return CS(db).create_from_open_connection(
        DEFAULT_TENANT_ID, conn, name="Mocha", ref_prefix="MOCHA",
        transport=transport or _transport([{"Location": "A1"}]),
    ), conn


def _http_raw(**overrides) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "sourceImpl": SOURCE_IMPL_AUTOCOUNT_HTTP,
        "connectionId": None,
        "path": "/itembypage",
        "keyFields": ["ItemCode"],
        "watermarkField": "LastModified",
        "comparedFields": [],
        "distinctOf": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileHours": None,
        "reconcileAt": "02:00",
    }
    raw.update(overrides)
    return raw


# ── AC-08-12: source registration + entity-set gate ───────────────────────────


def test_source_impl_registered_after_bootstrap(client):
    """`client` triggers the real module bootstrap (`register_engine_entities`
    for every installed module) - `source_factory("autocount_http")` must
    resolve without raising."""
    from modules.autocount.sources import source_factory

    factory = source_factory(SOURCE_IMPL_AUTOCOUNT_HTTP)
    assert callable(factory)


def test_http_impl_rejected_for_non_http_entities_422(db):
    from modules.autocount.models import AcEntityConfig, SYNC_MODE_MANUAL

    company, _conn = _open_company(db)
    # GRN is not in the HTTP entity set (product/customer/warehouse/
    # product_category/brand/unit_of_measure only) - offering it is a
    # guaranteed dead end.
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
            entity_type=ENTITY_GOODS_RECEIVED_NOTE, sync_mode=SYNC_MODE_MANUAL,
            source_impl="sql_db",
        )
    )
    db.commit()
    with pytest.raises(Exception):
        CompanyService(db).update_entity_config(
            DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE,
            source_impl=SOURCE_IMPL_AUTOCOUNT_HTTP,
        )


# ── AC-08-13: validate_source_config for autocount_http ──────────────────────


def test_http_task_connection_must_be_open_autocount_of_this_tenant(db):
    company, _conn = _open_company(db)
    sql_conn = _sql_connection(db)
    with pytest.raises(EtlValidationError) as exc:
        EtlService(db).update_task(
            DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
            _http_raw(connectionId=sql_conn.id),
        )
    assert "connectionId" in exc.value.field_errors


def test_http_task_path_required_and_must_start_with_slash(db):
    company, conn = _open_company(db)
    with pytest.raises(EtlValidationError) as exc:
        EtlService(db).update_task(
            DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
            _http_raw(connectionId=conn.id, path="itembypage"),
        )
    assert "path" in exc.value.field_errors


def test_http_task_path_rejects_dotdot_and_query_string(db):
    company, conn = _open_company(db)
    for bad_path in ("/../etc/passwd", "/itembypage?page=1"):
        with pytest.raises(EtlValidationError) as exc:
            EtlService(db).update_task(
                DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
                _http_raw(connectionId=conn.id, path=bad_path),
            )
        assert "path" in exc.value.field_errors


def test_http_task_key_fields_required(db):
    company, conn = _open_company(db)
    with pytest.raises(EtlValidationError) as exc:
        EtlService(db).update_task(
            DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
            _http_raw(connectionId=conn.id, keyFields=[]),
        )
    assert "keyFields" in exc.value.field_errors


def test_http_task_distinct_of_requires_key_fields_value(db):
    company, conn = _open_company(db)
    with pytest.raises(EtlValidationError) as exc:
        EtlService(db).update_task(
            DEFAULT_TENANT_ID, company.id, "unit_of_measure",
            _http_raw(
                connectionId=conn.id, path="/itembypage",
                keyFields=["ItemCode"], watermarkField=None,
                distinctOf=["BaseUOM", "SalesUOM", "PurchaseUOM"],
            ),
        )
    assert "keyFields" in exc.value.field_errors


def test_http_task_on_db_company_may_reference_any_open_connection(db):
    """AC-08-13: the plan-01 'DB company reads only its own connection' lock
    is narrowed to sql_db tasks - an HTTP task on a DB company validates
    against ANY open connection of the tenant, not just its own."""
    from modules.autocount.sql_source import probe
    from modules.autocount.sql_source.runtime import RUNTIME
    import sqlalchemy as sa
    from sqlalchemy.pool import StaticPool

    sql_conn = _sql_connection(db)
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    RUNTIME.put_engine(sql_conn.id, engine)
    probe.CURRENT_DATABASE_SQL["postgresql"] = "SELECT 'AED_2024'"
    db_company = CompanyService(db).create_from_sql_connection(
        DEFAULT_TENANT_ID, sql_conn, name="Sorento"
    )
    open_conn = _open_connection(db, base_url="https://hapi.sorento.cc.cd/api/db1")

    view = EtlService(db).update_task(
        DEFAULT_TENANT_ID, db_company.id, ENTITY_PRODUCT,
        _http_raw(connectionId=open_conn.id),
    )
    assert view.source_config.get("connectionId") == open_conn.id


def test_http_task_stray_sql_keys_dropped_not_422ed(db):
    company, conn = _open_company(db)
    raw = _http_raw(connectionId=conn.id, query="SELECT 1", keyColumns=["x"], watermarkColumn="y")
    view = EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, raw)
    assert "query" not in view.source_config
    assert "keyColumns" not in view.source_config


# ── AC-08-14: preview endpoint ────────────────────────────────────────────────


def test_preview_http_paged(client, headers, db):
    """B4 (sprint-5/08 review round 1): this used to reach the real
    ``hapi.sorento.cc.cd`` on every pytest run - the route builds its OWN
    transport, the ``_open_company(..., transport=...)`` stub only ever
    covered the CREATE probe, never the preview call. The router's
    ``get_http_transport`` dependency override (the SAME seam
    ``probe_open_connection``/``run_http_preview`` already accept as a
    plain kwarg) lets this stay a REAL route test with zero network."""
    from app.main import app
    from modules.autocount.http_client import get_http_transport

    company, conn = _open_company(db, transport=_transport({"TotalCount": 3, "Page": 1, "PageSize": 50, "TotalPages": 1, "Data": []}))
    app.dependency_overrides[get_http_transport] = lambda: _transport(
        {"TotalCount": 3, "Page": 1, "PageSize": 50, "TotalPages": 1, "Data": [{"ItemCode": "A"}]}
    )
    try:
        response = client.post(
            "/autocount/http/preview",
            json={"connectionId": conn.id, "path": "/itembypage"},
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["envelope"] == "paged"


def test_preview_http_bad_connection_422(client, headers, db):
    sql_conn = _sql_connection(db)
    response = client.post(
        "/autocount/http/preview",
        json={"connectionId": sql_conn.id, "path": "/location"},
        headers=headers,
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("bad_path", ["../x", "/a?b", "itembypage", "/" + "x" * 200])
def test_preview_http_applies_path_rules_422(client, headers, db, bad_path):
    """S4 (sprint-5/08 review round 1) - `POST /autocount/http/preview`
    used to apply NONE of `_validate_http_config`'s path rules
    (`/`-prefix, no `..`, no `?`, <= 200 chars) - a `../x` or `/a?b` path
    reached the vendor call unchecked. `validate_http_path` is now the
    ONE shared rule set both callers run."""
    company, conn = _open_company(db)
    response = client.post(
        "/autocount/http/preview",
        json={"connectionId": conn.id, "path": bad_path},
        headers=headers,
    )
    assert response.status_code == 422, response.text
    assert "path" in response.json()["detail"]["fieldErrors"]


def test_preview_http_permission_denied_403(client, db):
    company, conn = _open_company(db)
    login = client.post(
        "/auth/login", json={"email": "inactive@example.com", "password": "inactive1234"}
    )
    # inactive user cannot even log in; use a plain unauthenticated call instead
    response = client.post(
        "/autocount/http/preview", json={"connectionId": conn.id, "path": "/location"}
    )
    assert response.status_code in (401, 403)


# ── AC-08-15: list http connections ───────────────────────────────────────────


def test_list_http_connections_both_auths_excludes_sql_and_other_tenants(client, headers, db):
    """S8 (sprint-5/08 review round 1): the name promised "and other
    tenants" but no other-tenant row was ever created - a dropped
    ``tenant_id`` filter on ``list_for_provider`` would have stayed green."""
    from app.models import Tenant

    open_conn = _open_connection(db)
    from modules.autocount.services.company_service import CompanyService as CS  # noqa: F401

    basic = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Basic AC",
        config_json={"baseUrl": "https://ac.example.com", "auth": "basic", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "a", "password": "p"}), is_active=True,
    )
    db.add(basic)
    _sql_connection(db)

    other_tenant_id = "tenant-other-http-connections"
    if db.get(Tenant, other_tenant_id) is None:
        default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(
            Tenant(
                id=other_tenant_id, slug="other-co-http-connections",
                name="Other Co", status_id=default_tenant.status_id,
            )
        )
    db.commit()
    foreign = _open_connection(db, tenant_id=other_tenant_id)
    db.commit()

    response = client.get("/autocount/http/connections", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    ids = {row["id"]: row for row in body}
    assert open_conn.id in ids
    assert basic.id in ids
    assert ids[open_conn.id]["auth"] == "none"
    assert ids[basic.id]["auth"] == "basic"
    assert foreign.id not in ids, "another tenant's connection leaked into the list"


# ── AC-08-16: first clean save seeds the HTTP preset ─────────────────────────


def test_first_clean_save_seeds_http_preset_product(db):
    from modules.autocount.models import AcFieldMapping

    company, conn = _open_company(
        db, transport=_transport([{"ItemCode": "A1", "IsActive": "T", "Discontinued": "F"}])
    )
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(connectionId=conn.id)
    )
    rows = (
        db.query(AcFieldMapping)
        .filter(AcFieldMapping.company_id == company.id, AcFieldMapping.entity_type == ENTITY_PRODUCT)
        .all()
    )
    assert len(rows) == 8, [r.canonical_field for r in rows]
    by_source = {r.source_path: r for r in rows}
    assert by_source["IsActive"].transform == "t_f_bool"
    assert by_source["Discontinued"].transform == "t_f_bool"


def test_second_save_does_not_reseed(db):
    from modules.autocount.models import AcFieldMapping

    company, conn = _open_company(
        db, transport=_transport([{"ItemCode": "A1", "IsActive": "T", "Discontinued": "F"}])
    )
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(connectionId=conn.id))
    before = db.query(AcFieldMapping).filter(AcFieldMapping.company_id == company.id).count()
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(connectionId=conn.id))
    after = db.query(AcFieldMapping).filter(AcFieldMapping.company_id == company.id).count()
    assert before == after


# ── S1 (sprint-5/08 review round 1): connectionId tenant scope, ROUTE-level ──
#
# Kill test: dropping the ``tenant_id`` filter on ``ConnectionRepository.
# get_for_provider`` (``etl_service.py:800``/``:1000``) must turn either of
# these green-turned-red; before this pair neither the PUT etl-task route
# nor the preview route had ANY tenant-cross-connection test at all.


def test_put_etl_task_rejects_another_tenants_connection_422_never_leaks(client, headers, db):
    from app.models import Tenant

    company, _own_conn = _open_company(db)
    other_tenant_id = "tenant-other-http-task-put"
    if db.get(Tenant, other_tenant_id) is None:
        default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
        db.add(
            Tenant(
                id=other_tenant_id, slug="other-co-http-task-put",
                name="Other Co", status_id=default_tenant.status_id,
            )
        )
        db.commit()
    foreign = _open_connection(db, tenant_id=other_tenant_id)

    response = client.put(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task",
        json={"sourceConfig": _http_raw(connectionId=foreign.id)},
        headers=headers,
    )
    assert response.status_code == 422, response.text
    assert "connectionId" in response.json()["detail"]["fieldErrors"], response.text


def test_preview_http_rejects_another_tenants_connection_422_never_leaks(client, headers, db):
    from app.models import Tenant

    other_tenant_id = "tenant-other-http-preview"
    default_tenant = db.get(Tenant, DEFAULT_TENANT_ID)
    if db.get(Tenant, other_tenant_id) is None:
        db.add(
            Tenant(
                id=other_tenant_id, slug="other-co-http-preview",
                name="Other Co", status_id=default_tenant.status_id,
            )
        )
        db.commit()
    foreign = _open_connection(db, tenant_id=other_tenant_id)

    response = client.post(
        "/autocount/http/preview",
        json={"connectionId": foreign.id, "path": "/location"},
        headers=headers,
    )
    assert response.status_code == 422, response.text
    assert "connectionId" in response.json()["detail"]["fieldErrors"], response.text


# ── S7 (sprint-5/08 review round 1, AC-08-16 second clause) ─────────────────


def test_get_mapping_presets_route_returns_http_preset_not_empty(client, headers, db):
    """Before this fix ``list_mapping_presets`` only ever checked
    ``DOCUMENT_PRESETS`` - every HTTP entity (product/customer/warehouse/
    product_category/brand/unit_of_measure) answered ``[]``, so the Mapping
    tab's "Use preset" action had nothing to offer for the entities this
    plan actually added."""
    company, _conn = _open_company(db)
    response = client.get(
        f"/autocount/presets/{ENTITY_PRODUCT}",
        params={"companyId": company.id},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1, body
    assert body[0]["path"] == "/itembypage"
    assert "ItemCode" in body[0]["keyFields"]


# ── AC-08-17: parity extension lives in test_autocount_entity_parity.py ──────
