"""Sprint-5/10 confirm round 2 - the Source tab's alias self-collision, closed
at the WIRE instead of by an FE subtraction heuristic, plus the preset-combine
seed narrowed to task CREATION.

Two RED reasons before the coder:

1. ``POST /autocount/http/preview`` reports ``columns`` = the raw source
   columns UNION every lookup alias the REQUEST carried (``preview.py``'s own
   merge), and ``preCombineColumns`` additionally folds in the combine's
   computed aliases. Neither is a raw-column list, and the response carries no
   raw-column list at all - so the Lookups editor had nothing truthful to run
   AC-10-01/AC-10-09's "an alias may not equal a source column" check against.
   ``run_http_preview`` already computes the pre-lookup set
   (``HttpPreviewResult.raw_columns``); it is simply never put on the wire.
   This file pins a NEW ``rawColumns`` field: ALWAYS present, never an alias,
   never a computed alias.

2. ``EtlService._update_http_task`` seeds ``source_config.combine`` from the
   entity's HTTP preset whenever the ``combine`` KEY is absent from both the
   stored config and the wire (confirm round 1, B-2). A plan-08 HTTP row saved
   before ``combine`` existed carries no such key, so a BARE save of that
   pre-existing row seeds the preset behind the operator's back - rewriting
   ``keyFields`` and demoting an ACTIVE task to draft. Creation (``config is
   None``) is the only moment "the owner configured nothing" can be true; an
   existing row's own ``db``/``api`` -> http switch is seeded by the FE.

Plus the AC-10-01 nit: a lookup alias equal to a combine computed alias is the
COMBINE's error to report (``combine.computed[i].alias``), never the Lookups
editor's "already a source column".
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
from modules.autocount.services.company_service import CompanyService

# The main endpoint's RAW columns - the ONLY thing `rawColumns` may ever be.
RAW_ROWS: List[Dict[str, Any]] = [
    {"ItemCode": "SRT-01", "UOM": "UNIT", "Location": "MAIN", "BalQty": 10},
    {"ItemCode": "SRT-01", "UOM": "BOX", "Location": "MAIN", "BalQty": 2},
]
RAW_COLUMNS = ["ItemCode", "UOM", "Location", "BalQty"]

ITEM_LOOKUP = {
    "path": "/itembypage",
    "as": "item",
    "on": [{"local": "ItemCode", "remote": "ItemCode"}],
    "fields": [
        {"remote": "BaseUOM", "as": "ItemBaseUOM"},
        {"remote": "Description", "as": "ItemDescription"},
    ],
}
UOM_LOOKUP = {
    "path": "/itemuombypage",
    "as": "uom",
    "on": [
        {"local": "ItemCode", "remote": "ItemCode"},
        {"local": "UOM", "remote": "UOM", "match": "casefold_trim"},
    ],
    "fields": [{"remote": "Rate", "as": "UomRate"}],
}

COMBINE: Dict[str, Any] = {
    "computed": [
        {"alias": "item_code", "formula": "trim(ItemCode)"},
        {"alias": "location_code", "formula": "trim(Location)"},
        {
            "alias": "base_qty",
            "formula": (
                "if(lower(trim(UOM)) == lower(trim(ItemBaseUOM)), "
                "number(BalQty), number(BalQty) * number(UomRate))"
            ),
        },
    ],
    "require": [],
    "measure": "base_qty",
    "groupBy": ["item_code", "location_code"],
    "measures": [{"source": "base_qty", "op": "sum", "alias": "qty"}],
    "carry": ["ItemDescription"],
    "round": [],
    "drop": [],
}


@pytest.fixture
def headers(client):
    response = client.post(
        "/auth/login", json={"email": "demo@example.com", "password": "demo1234"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


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


def _multi_transport(pages_by_path: Dict[str, Any]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        match = next((p for p in pages_by_path if request.url.path.endswith(p)), None)
        if match is None:
            return httpx.Response(404, text=f"no fixture for {request.url.path}")
        return httpx.Response(200, json=pages_by_path[match])

    return httpx.Client(transport=httpx.MockTransport(handler))


def _paged(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "TotalCount": len(rows), "Page": 1, "PageSize": 50, "TotalPages": 1, "Data": rows,
    }


def _preview(client, headers, db, **body: Any):
    from app.main import app
    from modules.autocount.http_client import get_http_transport

    conn = _open_connection(db)
    app.dependency_overrides[get_http_transport] = lambda: _multi_transport({
        "/itembatchbalqtybypage": _paged(RAW_ROWS),
        "/itembypage": _paged([
            {"ItemCode": "SRT-01", "BaseUOM": "UNIT", "Description": "Widget"},
        ]),
        "/itemuombypage": _paged([
            {"ItemCode": "SRT-01", "UOM": "UNIT", "Rate": 1.0},
            {"ItemCode": "SRT-01", "UOM": "BOX", "Rate": 5.0},
        ]),
    })
    payload = {"connectionId": conn.id, "path": "/itembatchbalqtybypage", **body}
    try:
        return client.post("/autocount/http/preview", json=payload, headers=headers)
    finally:
        app.dependency_overrides.pop(get_http_transport, None)


# ── B1 (AC-10-01/AC-10-09): rawColumns on the preview wire ──────────────────


def test_preview_reports_raw_columns_only_never_a_lookup_or_computed_alias(
    client, headers, db
):
    """Two lookups AND a combine on one request: ``rawColumns`` stays the
    walked endpoint's own columns, while ``columns`` (the COMBINED shape) and
    ``preCombineColumns`` (raw + lookup + computed) keep their existing
    meanings untouched."""
    response = _preview(client, headers, db, lookups=[ITEM_LOOKUP, UOM_LOOKUP], combine=COMBINE)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["rawColumns"] == RAW_COLUMNS, body["rawColumns"]
    # Not a single alias leaks into it.
    for alias in ("ItemBaseUOM", "ItemDescription", "UomRate", "item_code",
                  "location_code", "base_qty", "qty"):
        assert alias not in body["rawColumns"], (alias, body["rawColumns"])

    # Unchanged siblings: `columns` = the post-group shape, `preCombineColumns`
    # = raw + lookup aliases + computed aliases.
    assert {c["name"] for c in body["columns"]} == {
        "item_code", "location_code", "ItemDescription", "qty"
    }, body["columns"]
    assert set(body["preCombineColumns"]) == set(RAW_COLUMNS) | {
        "ItemBaseUOM", "ItemDescription", "UomRate", "item_code", "location_code", "base_qty"
    }, body["preCombineColumns"]


def test_raw_columns_present_on_a_plain_preview_with_no_lookups_and_no_combine(
    client, headers, db
):
    """ALWAYS present (the FE falls back to an EMPTY set, never to
    ``columns``), so a lookup-free, combine-free Test must carry it too."""
    response = _preview(client, headers, db)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rawColumns"] == RAW_COLUMNS, body["rawColumns"]
    assert [c["name"] for c in body["columns"]] == RAW_COLUMNS, body["columns"]
    assert body.get("preCombineColumns") is None, body


def test_raw_columns_excludes_lookup_aliases_on_a_lookup_only_preview(client, headers, db):
    """The exact repro: the merged ``columns`` carries every alias the REQUEST
    named (that is what makes the grid useful), so only ``rawColumns`` can tell
    the Lookups editor which names are genuinely taken."""
    response = _preview(client, headers, db, lookups=[ITEM_LOOKUP, UOM_LOOKUP])
    assert response.status_code == 200, response.text
    body = response.json()
    merged = [c["name"] for c in body["columns"]]
    assert "ItemBaseUOM" in merged and "UomRate" in merged, merged
    assert body["rawColumns"] == RAW_COLUMNS, body["rawColumns"]


# ── item 4 nit (AC-10-01): an alias clashing with a COMPUTED alias is the ───
# ── combine's own 422, keyed to combine.computed[i].alias ───────────────────


def test_a_lookup_alias_equal_to_a_computed_alias_422s_on_the_combine_path(db):
    """Never "already a source column" - a computed alias is not a source
    column, and the save-time gate already keys this to the combine."""
    from modules.autocount.services.etl_service import EtlService, EtlValidationError

    conn = _open_connection(db)
    company = CompanyService(db).create_from_open_connection(
        DEFAULT_TENANT_ID, conn, name="Mocha", ref_prefix="MOCHA",
        transport=_multi_transport({"/location": _paged([{"Location": "A1"}])}),
    )
    raw = {
        "sourceImpl": "autocount_http",
        "connectionId": conn.id,
        "path": "/itembatchbalqtybypage",
        "keyFields": [],
        "watermarkField": None,
        "comparedFields": [],
        "distinctOf": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileHours": None,
        "reconcileAt": "02:00",
        # The lookup's alias IS the combine's first computed alias.
        "lookups": [{
            "path": "/itembypage",
            "as": "item",
            "on": [{"local": "ItemCode", "remote": "ItemCode"}],
            "fields": [{"remote": "BaseUOM", "as": "item_code"}],
        }],
        "combine": COMBINE,
    }
    with pytest.raises(EtlValidationError) as excinfo:
        EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, raw)
    assert excinfo.value.field_errors.get("combine.computed[0].alias") == (
        "'item_code' is already used by a lookup."
    ), excinfo.value.field_errors


# ── item 3: the preset-combine seed fires on CREATION only ──────────────────


def test_bare_save_of_a_preexisting_http_row_without_a_combine_key_is_never_seeded(
    client, headers, db
):
    """The reviewer's probe: a plan-08 HTTP row predates ``combine`` entirely,
    so its stored ``source_config`` has no such key. A bare save (the wire
    omits ``combine`` too) must leave it alone - seeding there rewrote
    ``keyFields`` from the preset's ``groupBy`` and demoted an ACTIVE task to
    draft, with the operator having changed nothing."""
    from modules.autocount.models import AcEntityConfig, ETL_STATUS_ACTIVE

    conn = _open_connection(db)
    company = CompanyService(db).create_from_open_connection(
        DEFAULT_TENANT_ID, conn, name="Mocha", ref_prefix="MOCHA",
        transport=_multi_transport({"/location": _paged([{"Location": "A1"}])}),
    )

    def _raw(**over: Any) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "sourceImpl": "autocount_http",
            "connectionId": conn.id,
            "path": "/itembatchbalqtybypage",
            "keyFields": ["ItemCode"],
            "watermarkField": None,
            "comparedFields": [],
            "distinctOf": None,
            "incrementalMinutes": 15,
            "reconcileMode": "dailyAt",
            "reconcileHours": None,
            "reconcileAt": "02:00",
        }
        base.update(over)
        return base

    first = client.put(
        f"/autocount/companies/{company.id}/entities/{ENTITY_STOCK_BALANCE}/etl-task",
        json={"sourceConfig": _raw(combine=None)},
        headers=headers,
    )
    assert first.status_code == 200, first.text

    # Rewind the row to its plan-08 shape: NO `combine` key at all, ACTIVE.
    row = (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == DEFAULT_TENANT_ID,
            AcEntityConfig.company_id == company.id,
            AcEntityConfig.entity_type == ENTITY_STOCK_BALANCE,
        )
        .one()
    )
    row.source_config = {
        k: v for k, v in dict(row.source_config).items() if k != "combine"
    }
    row.etl_status = ETL_STATUS_ACTIVE
    db.commit()

    bare = _raw()
    assert "combine" not in bare
    response = client.put(
        f"/autocount/companies/{company.id}/entities/{ENTITY_STOCK_BALANCE}/etl-task",
        json={"sourceConfig": bare},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sourceConfig"].get("combine") is None, body["sourceConfig"]
    assert body["sourceConfig"]["keyFields"] == ["ItemCode"], body["sourceConfig"]
    assert body["etlStatus"] == ETL_STATUS_ACTIVE, body["etlStatus"]
