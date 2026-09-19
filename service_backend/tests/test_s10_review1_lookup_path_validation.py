"""Sprint-5/10 S1 review round 1 (Opus reviewer) - BLOCKER 1: a lookup
``path`` never passed ``validate_http_path`` at several surfaces, and
save-time lookup validation was skipped ENTIRELY on a never-previewed task
(``if lookups and existing_result_columns is not None``). The reviewer
proved live: a lookup path ``/../db2/itembypage`` was actually FETCHED
(reads the other book), and a never-previewed task persisted 9 lookups with
a bad alias, an empty ``on`` and an empty ``fields``.

Fix (this file pins all four surfaces):
  (a) ``validate_lookups`` runs its STRUCTURAL rules (path, alias regex, the
      5-cap, empty ``on``/``fields``, a duplicate alias, a forward
      reference) UNCONDITIONALLY - only the "local is known" / "collides
      with a REAL source column" checks stay skipped pre-preview.
  (b) ``EtlService.preview_http``/``preview_http_columns`` validate every
      lookup / the probe path BEFORE any outbound request.
  (c) ``HttpApiSource`` refuses (at run time) a lookup whose saved ``path``
      fails ``validate_http_path`` - defence in depth for a row saved
      BEFORE this fix (or edited directly in the DB).
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.http_source.errors import HttpSourceError
from modules.autocount.http_source.lookups import MAX_LOOKUPS, validate_lookups
from modules.autocount.http_source.source import HttpApiSource
from modules.autocount.models import AcCompany, AcEntityConfig
from modules.autocount.services.company_service import CompanyService
from modules.autocount.services.etl_service import EtlService, EtlValidationError
from modules.autocount.sources import SourceContext, Watermark

DB_NAME = "MOCHA"
BASE_URL = "https://hapi.sorento.cc.cd/api/db2"

_BAD_PATH_LOOKUP = {
    "path": "/../db2/itembypage",
    "as": "uom",
    "on": [{"local": "ItemCode", "remote": "ItemCode"}],
    "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
}


# ── (a) validate_lookups runs structurally with source_columns=None ─────────


def test_bad_path_rejected_even_when_never_previewed():
    errors = validate_lookups([_BAD_PATH_LOOKUP], None)
    assert "lookups[0].path" in errors, errors


def test_over_max_lookups_rejected_even_when_never_previewed():
    specs: List[Dict[str, Any]] = [
        {
            "path": "/itembypage", "as": f"l{i}",
            "on": [{"local": "ItemCode", "remote": "ItemCode"}],
            "fields": [{"remote": "Description", "as": f"alias{i}"}],
        }
        for i in range(MAX_LOOKUPS + 1)
    ]
    errors = validate_lookups(specs, None)
    assert "lookups" in errors, errors


def test_bad_alias_rejected_even_when_never_previewed():
    spec = {
        "path": "/itemuombypage", "as": "not a valid name",
        "on": [{"local": "ItemCode", "remote": "ItemCode"}],
        "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
    }
    errors = validate_lookups([spec], None)
    assert "lookups[0].as" in errors, errors


def test_empty_on_rejected_even_when_never_previewed():
    spec = {
        "path": "/itemuombypage", "as": "uom", "on": [],
        "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
    }
    errors = validate_lookups([spec], None)
    assert "lookups[0].on" in errors, errors


def test_empty_fields_rejected_even_when_never_previewed():
    spec = {
        "path": "/itemuombypage", "as": "uom",
        "on": [{"local": "ItemCode", "remote": "ItemCode"}], "fields": [],
    }
    errors = validate_lookups([spec], None)
    assert "lookups[0].fields" in errors, errors


# ── (b) preview + preview-columns validate BEFORE any outbound request ──────


@pytest.fixture
def headers(client):
    response = client.post(
        "/auth/login", json={"email": "demo@example.com", "password": "demo1234"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _open_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Mocha REST",
        config_json={"baseUrl": BASE_URL, "auth": "none"}, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    db.expunge(conn)
    return conn


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _exploding_transport() -> httpx.Client:
    """A request reaching this at ALL proves the code failed to validate
    BEFORE going outbound - the reviewer's exact live finding."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected outbound request to {request.url}")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_preview_rejects_a_bad_lookup_path_before_any_request(client, headers, db):
    from app.main import app
    from modules.autocount.http_client import get_http_transport

    conn = _open_connection(db)
    app.dependency_overrides[get_http_transport] = lambda: _exploding_transport()
    try:
        response = client.post(
            "/autocount/http/preview",
            json={
                "connectionId": conn.id, "path": "/itembypage",
                "lookups": [_BAD_PATH_LOOKUP],
            },
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)
    assert response.status_code == 422, response.text
    field_errors = response.json()["detail"]["fieldErrors"]
    assert "lookups[0].path" in field_errors, field_errors


def test_preview_columns_rejects_a_bad_path_before_any_request(client, headers, db):
    from app.main import app
    from modules.autocount.http_client import get_http_transport

    conn = _open_connection(db)
    app.dependency_overrides[get_http_transport] = lambda: _exploding_transport()
    try:
        response = client.post(
            "/autocount/http/preview-columns",
            json={"connectionId": conn.id, "path": "/../db2/itembypage"},
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)
    assert response.status_code == 422, response.text
    assert "path" in response.json()["detail"]["fieldErrors"]


# ── (a continued) save on a never-previewed task ─────────────────────────────


def _http_raw(**overrides: Any) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "sourceImpl": "autocount_http",
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


def test_save_on_never_previewed_task_rejects_bad_path_empty_on_and_fields(db):
    """The reviewer's exact live finding: a never-previewed task's save
    persisted 9 lookups with a bad alias, an empty ``on`` and an empty
    ``fields`` - none of that must ever reach the database."""
    conn = _open_connection(db)
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=DB_NAME,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)

    broken_lookups = [
        _BAD_PATH_LOOKUP,
        {"path": "/itemuombypage", "as": "empty_on", "on": [], "fields": [{"remote": "Price", "as": "X"}]},
        {"path": "/itemuombypage", "as": "empty_fields", "on": [{"local": "ItemCode", "remote": "ItemCode"}], "fields": []},
    ]
    with pytest.raises(EtlValidationError) as exc:
        EtlService(db).update_task(
            DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
            _http_raw(connectionId=conn.id, lookups=broken_lookups),
        )
    field_errors = exc.value.field_errors
    assert "lookups[0].path" in field_errors, field_errors
    assert "lookups[1].on" in field_errors, field_errors
    assert "lookups[2].fields" in field_errors, field_errors

    from modules.autocount.repositories import EntityConfigRepository

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert config is None, "nothing must ever be persisted for a rejected save"


# ── (c) defence in depth: the source refuses to WALK a bad saved path ───────


def test_source_refuses_to_walk_a_lookup_whose_saved_path_is_invalid(db):
    """A row saved BEFORE this fix (or edited directly) must never be
    walked - the bad path is refused before a single request reaches it."""
    conn = _open_connection(db)
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=DB_NAME,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.flush()
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http",
        source_config={
            "connectionId": conn.id, "path": "/itembypage", "keyFields": ["ItemCode"],
            "watermarkField": "LastModified", "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": [_BAD_PATH_LOOKUP],
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)

    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                  "Data": [{"ItemCode": "SRT-01", "LastModified": "2026-08-01T09:00:00"}]},
        )

    ctx = SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )
    source = HttpApiSource(
        ctx, entity_type=ENTITY_PRODUCT,
        transport=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(HttpSourceError):
        source.fetch_changes(Watermark())
    # The main path itself is fine and would have been walked; the ONLY
    # request that may legitimately reach the handler is the main path's -
    # the lookup's bad path must never be requested at all.
    for call in calls:
        assert ".." not in str(call.url), f"the bad lookup path was requested: {call.url}"
