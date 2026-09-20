"""Sprint-5/10 S1 review round 1 (Opus reviewer) - BLOCKER 2: a lookup's
alias carve-out let a lookup OVERWRITE a REAL source column.
``fields:[{remote:"Price", as:"Description"}]`` with source columns
containing ``Description`` validated clean and ``merge_onto_rows`` replaced
the real value - the reviewer's exact live finding, pinned here at all
three surfaces:

  (i) PREVIEW - it holds the raw main-endpoint columns BEFORE merging; an
      alias (a lookup's own ``as`` or any ``fields[].as``) equal to a raw
      main column is an unconditional 422, no carve-out.
  (ii) RUN TIME - ``merge_onto_rows`` must NEVER overwrite a key already
       present on the raw row (a real column, or an earlier lookup's own
       alias) - it raises, and the source fails the whole run loudly
       (``HttpSourceError``, fail-before-state) rather than deliver a
       poisoned value.
  (iii) SAVE - the carve-out is tightened to what is PROVABLE: only aliases
        of the task's PREVIOUSLY SAVED lookups, or of THIS call's lookups
        that also appear in the saved set or a REGISTERED preset. A
        brand-new alias that happens to equal a real column is a 422.
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.http_source.errors import HttpSourceError
from modules.autocount.http_source.lookups import validate_lookups
from modules.autocount.http_source.source import HttpApiSource
from modules.autocount.models import AcCompany, AcEntityConfig
from modules.autocount.services.company_service import CompanyService
from modules.autocount.services.etl_service import EtlService, EtlValidationError
from modules.autocount.sources import SourceContext, Watermark

DB_NAME = "MOCHA"
BASE_URL = "https://hapi.sorento.cc.cd/api/db2"

# The reviewer's exact exploit: alias "Description" is NOT a join key for
# this lookup and is NOT a preset alias anywhere - a fresh, unrelated name
# that happens to collide with a genuine raw column.
_POISONED_LOOKUP = {
    "path": "/itemuombypage", "as": "poison",
    "on": [{"local": "ItemCode", "remote": "ItemCode"}],
    "fields": [{"remote": "Price", "as": "Description"}],
}


# ── (iii) SAVE: a brand-new alias colliding with a REAL column is a 422 ─────


def test_save_time_fresh_alias_colliding_with_a_real_column_rejected():
    source_columns = ["ItemCode", "Description", "Desc2", "BaseUOM", "LastModified"]
    errors = validate_lookups([_POISONED_LOOKUP], source_columns)
    assert "lookups[0].fields[0].as" in errors, errors


def test_save_time_still_exempts_a_previously_saved_lookups_own_alias():
    """The re-save flow must not regress. Superseded by review round 1b's
    ruling: raw-only storage means ``validate_lookups`` no longer accepts a
    ``previously_saved_lookups`` carve-out at all (removed - see
    ``lookups.py``'s own docstring) - the caller (``EtlService.
    _validate_http_config``) is instead responsible for passing a
    TOLERANT, ALIAS-STRIPPED raw column set (``lookups.stored_raw_columns``),
    so an already-saved lookup's own alias reappearing in a pre-fix row's
    stored ``result_columns`` is never treated as a genuine collision. This
    pins that stripping directly, mirroring the real save-time call."""
    from modules.autocount.http_source.lookups import stored_raw_columns

    lookup = {
        "path": "/itemuombypage", "as": "uom",
        "on": [{"local": "ItemCode", "remote": "ItemCode"}],
        "fields": [{"remote": "Price", "as": "MyOwnAlias"}],
    }
    # A pre-round-1b row's stored result_columns may still literally carry
    # the alias (the OLD preview merged it in) - the tolerance strips it.
    stale_stored_columns = ["ItemCode", "Description", "MyOwnAlias"]
    tolerant_columns = stored_raw_columns(stale_stored_columns, [lookup])
    assert tolerant_columns == ["ItemCode", "Description"], tolerant_columns

    errors = validate_lookups([lookup], tolerant_columns)
    assert errors == {}, errors


# ── (i) PREVIEW: unconditional, no carve-out ────────────────────────────────


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


def _multi_transport(pages_by_path: Dict[str, Dict[str, Any]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        match = next((p for p in pages_by_path if request.url.path.endswith(p)), None)
        if match is None:
            return httpx.Response(404, text=f"no fixture for {request.url.path}")
        status, body = pages_by_path[match]
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_preview_rejects_an_alias_equal_to_a_raw_main_column(client, headers, db):
    from app.main import app
    from modules.autocount.http_client import get_http_transport

    conn = _open_connection(db)
    app.dependency_overrides[get_http_transport] = lambda: _multi_transport({
        "/itembypage": (200, {
            "TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1,
            "Data": [{"ItemCode": "SRT-01", "Description": "WIDGET"}],
        }),
        "/itemuombypage": (200, {
            "TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1,
            "Data": [{"ItemCode": "SRT-01", "Price": 7.5}],
        }),
    })
    try:
        response = client.post(
            "/autocount/http/preview",
            json={
                "connectionId": conn.id, "path": "/itembypage",
                "lookups": [_POISONED_LOOKUP],
            },
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)
    assert response.status_code == 422, response.text
    field_errors = response.json()["detail"]["fieldErrors"]
    assert "lookups[0].fields[0].as" in field_errors, field_errors


# ── (ii) RUN TIME: never silently overwrite; fail the whole run ─────────────


def _config(db, company, connection_id: str, lookups) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http",
        source_config={
            "connectionId": connection_id, "path": "/itembypage", "keyFields": ["ItemCode"],
            "watermarkField": "LastModified", "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": lookups,
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def test_run_time_alias_colliding_with_a_real_column_fails_the_whole_run_never_delivers(db):
    conn = _open_connection(db)
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=DB_NAME,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    # Bypasses the save-time gate on purpose - a row saved before this fix,
    # or a lookup whose alias only started colliding after a LATER schema
    # change on the vendor side.
    config = _config(db, company, conn.id, [_POISONED_LOOKUP])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/itemuombypage"):
            return httpx.Response(
                200,
                json={"TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                      "Data": [{"ItemCode": "SRT-01", "Price": 7.5}]},
            )
        return httpx.Response(
            200,
            json={"TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                  "Data": [{"ItemCode": "SRT-01", "Description": "WIDGET",
                            "LastModified": "2026-08-01T09:00:00"}]},
        )

    ctx = SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )
    source = HttpApiSource(
        ctx, entity_type=ENTITY_PRODUCT,
        transport=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(HttpSourceError) as exc:
        source.fetch_changes(Watermark())
    assert "Description" in exc.value.message, exc.value.message
    # NEVER "7.5" (the poisoned overwrite) reaching anywhere staged/pushed -
    # the run raised before any FetchResult was even built.


def test_run_time_second_lookup_overwriting_first_lookups_alias_fails_the_run(db):
    """Same rule, the OTHER collision source named in the blocker: an alias
    doing double duty because a LATER lookup reuses an EARLIER lookup's own
    alias name."""
    conn = _open_connection(db)
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=DB_NAME,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    lookups = [
        {
            "path": "/itembypage2", "as": "first",
            "on": [{"local": "ItemCode", "remote": "ItemCode"}],
            "fields": [{"remote": "BaseUOM", "as": "SharedAlias"}],
        },
        {
            "path": "/itemuombypage", "as": "second",
            "on": [{"local": "ItemCode", "remote": "ItemCode"}],
            "fields": [{"remote": "Price", "as": "SharedAlias"}],
        },
    ]
    config = _config(db, company, conn.id, lookups)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/itemuombypage"):
            body = {"ItemCode": "SRT-01", "Price": 7.5}
        elif request.url.path.endswith("/itembypage2"):
            body = {"ItemCode": "SRT-01", "BaseUOM": "UNIT"}
        else:
            body = {"ItemCode": "SRT-01", "LastModified": "2026-08-01T09:00:00"}
        return httpx.Response(
            200, json={"TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": [body]}
        )

    ctx = SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )
    source = HttpApiSource(
        ctx, entity_type=ENTITY_PRODUCT,
        transport=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(HttpSourceError) as exc:
        source.fetch_changes(Watermark())
    assert "SharedAlias" in exc.value.message, exc.value.message
