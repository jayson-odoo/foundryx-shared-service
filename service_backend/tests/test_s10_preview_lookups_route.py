"""Sprint-5/10 S1 - AC-10-05: ``POST /autocount/http/preview`` accepts a
task's ``lookups``, and the companion ``POST /autocount/http/preview-
columns`` probe.

RED before the coder:
  - ``POST /autocount/http/preview-columns`` does not exist as a route at
    all yet (``modules/autocount/routers/http.py`` only mounts
    ``/connections`` and ``/preview``) - a 404, the "missing feature" RED
    reason the brief allows.
  - ``HttpPreviewRequest`` (``modules/autocount/schemas.py``) has no
    ``lookups`` field - pydantic silently DROPS an unknown JSON key rather
    than 422ing (no ``extra="forbid"`` on ``ApiModel``), so posting
    ``lookups`` today is accepted but has NO EFFECT: the alias column never
    appears in the response, a real, named mismatch.

Assumed wire shape (not fixed by the plan beyond "returns the alias columns
alongside the source columns plus a per-lookup {alias, matched, missed}
count"): the per-lookup counts land under a NEW top-level ``lookups`` key on
``HttpPreviewResponse`` (list of ``{alias, matched, missed}``), camelCase,
mirroring the `columns`/`rows` siblings already on that response. This is an
ASSUMPTION the coder should confirm rather than silently rename - the
per-lookup dict's OWN keys (`alias`/`matched`/`missed`) are the load-bearing
part (an AC-10-09 FE consumes them by name), the outer wrapper key less so.
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.services.company_service import CompanyService

ITEM_UOM_LOOKUP = {
    "path": "/itemuombypage",
    "as": "uom",
    "on": [
        {"local": "ItemCode", "remote": "ItemCode"},
        {"local": "BaseUOM", "remote": "UOM", "match": "casefold_trim"},
    ],
    "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
}


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
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db2", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    db.expunge(conn)
    return conn


def _multi_transport(pages_by_path: Dict[str, Dict[str, Any]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        # ``request.url.path`` carries the connection's base path too
        # (e.g. ``/api/db2/itembypage``) - match by SUFFIX, never exact.
        match = next((p for p in pages_by_path if request.url.path.endswith(p)), None)
        if match is None:
            return httpx.Response(404, text=f"no fixture for {request.url.path}")
        status, body = pages_by_path[match]
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


# ── the companion preview-columns probe ──────────────────────────────────────


def test_preview_columns_route_returns_first_page_column_names(client, headers, db):
    from app.main import app
    from modules.autocount.http_client import get_http_transport

    conn = _open_connection(db)
    app.dependency_overrides[get_http_transport] = lambda: _multi_transport({
        "/itemuombypage": (200, {
            "TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1,
            "Data": [{"ItemCode": "A1", "UOM": "UNIT", "Rate": 1.0, "Price": 10.0}],
        }),
    })
    try:
        response = client.post(
            "/autocount/http/preview-columns",
            json={"connectionId": conn.id, "path": "/itemuombypage"},
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)
    assert response.status_code == 200, response.text
    columns = set(response.json()["columns"])
    assert columns == {"ItemCode", "UOM", "Rate", "Price"}, columns


def test_preview_columns_route_applies_the_same_path_rules(client, headers, db):
    conn = _open_connection(db)
    response = client.post(
        "/autocount/http/preview-columns",
        json={"connectionId": conn.id, "path": "../escape"},
        headers=headers,
    )
    assert response.status_code == 422, response.text
    assert "path" in response.json()["detail"]["fieldErrors"]


def test_preview_columns_route_requires_auth(client, db):
    conn = _open_connection(db)
    response = client.post(
        "/autocount/http/preview-columns",
        json={"connectionId": conn.id, "path": "/itemuombypage"},
    )
    assert response.status_code in (401, 403)


# ── `/preview` accepting `lookups` ───────────────────────────────────────────


def test_preview_with_lookups_returns_alias_columns_and_per_lookup_counts(client, headers, db):
    from app.main import app
    from modules.autocount.http_client import get_http_transport

    conn = _open_connection(db)
    app.dependency_overrides[get_http_transport] = lambda: _multi_transport({
        "/itembypage": (200, {
            "TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1,
            "Data": [{"ItemCode": "SRT-01", "BaseUOM": "UNIT", "Description": "WIDGET"}],
        }),
        "/itemuombypage": (200, {
            "TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1,
            "Data": [{"ItemCode": "SRT-01", "UOM": "unit", "Rate": 1.0, "Price": 63.0}],
        }),
    })
    try:
        response = client.post(
            "/autocount/http/preview",
            json={"connectionId": conn.id, "path": "/itembypage", "lookups": [ITEM_UOM_LOOKUP]},
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)
    assert response.status_code == 200, response.text
    body = response.json()
    column_names = {c["name"] for c in body["columns"]}
    assert "BaseUOMPrice" in column_names, column_names
    row_values = [r.get("BaseUOMPrice") for r in body["rows"]]
    assert row_values == [63.0], body["rows"]
    lookup_counts = body.get("lookups")
    assert lookup_counts, "expected per-lookup {alias, matched, missed} counts on the response"
    entry = lookup_counts[0]
    assert entry["alias"] == "uom"
    assert entry["matched"] == 1
    assert entry["missed"] == 0


def test_preview_lookup_endpoint_failure_is_a_422_naming_the_lookup_path(client, headers, db):
    from app.main import app
    from modules.autocount.http_client import get_http_transport

    conn = _open_connection(db)
    app.dependency_overrides[get_http_transport] = lambda: _multi_transport({
        "/itembypage": (200, {
            "TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1,
            "Data": [{"ItemCode": "SRT-01", "BaseUOM": "UNIT"}],
        }),
        "/itemuombypage": (500, {"error": "boom"}),
    })
    try:
        response = client.post(
            "/autocount/http/preview",
            json={"connectionId": conn.id, "path": "/itembypage", "lookups": [ITEM_UOM_LOOKUP]},
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_http_transport, None)
    assert response.status_code == 422, response.text
    field_errors = response.json()["detail"]["fieldErrors"]
    assert "lookups[0].path" in field_errors, field_errors
    assert "/itemuombypage" in field_errors["lookups[0].path"]


# KILL TEST (for the reviewer): revert `/preview` to ignore `lookups`
# entirely (drop the branch that walks them) -
# ``test_preview_with_lookups_returns_alias_columns_and_per_lookup_counts``
# flips red on `column_names`; the pre-existing `test_preview_http_paged`
# (test_autocount_http_task_config.py) stays green either way, proving a
# plain preview with no lookups is unaffected by the new branch.
