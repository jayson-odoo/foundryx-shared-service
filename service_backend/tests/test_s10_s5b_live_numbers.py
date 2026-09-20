"""Sprint-5/10 S5b - AC-10-84: the stock preset reproduces the LIVE db1
numbers end to end, with no operator configuration, driven directly off the
recorded wrapper pages (never a live network call - the lane's own
"no network in tests" rule).

RED before the coder: ``ENTITY_STOCK_BALANCE``/``CanonicalStockBalance`` do
not exist yet, so this file fails at collection with a plain ``ImportError``
exactly like its four siblings.

**Ground truth, independently computed and cross-checked against the UAC's
own probe notes before this file was written** (not asserted on faith - run
via ``modules.autocount.http_source.combine.apply_combine`` directly against
every recorded page, see the tester's final report for the exact numbers):
68,612 raw balance rows walked, 0 excluded (every (ItemCode, UOM) pair the
balance table names has a matching ``/itemuombypage`` rate row in THIS
recorded capture - the plan's "5 known rate-unresolved rows" narrative does
not reproduce against this exact fixture; flagged, not silently
overridden), 68,597 total (item, location) pairs, 56,422 zero, 42 negative
(all listed), 0 fractional, 12,133 positive pairs delivered. The 68,597/
56,422/12,175(=12,133+42) intermediate figures match the UAC's own
"Aggregated to (item, location)" paragraph exactly; ``12,133``/``42``/``0``
are the SAME three numbers AC-10-84's own text names.

Kept to ONE test function (module-scoped page load) per the brief's own
"keep the test fast: load pages once per module" instruction - the
``apply_combine`` pass over 68,612 raw dicts is pure Python and takes on the
order of 10 seconds; there is nothing to gain from repeating it.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection

PROBE_DIR = (
    "/private/tmp/claude-501/-Users-tehjayson-Documents-foundryx-foundryx-shared-service/"
    "50d47831-315e-4257-9732-fe1acb44c646/scratchpad/probe"
)

BAL_PAGES = 69
ITEM_PAGES = 12
ITEM_UOM_PAGES = 12

_skip_reason = None
if not os.path.isdir(PROBE_DIR):
    _skip_reason = f"recorded db1 probe directory not found at {PROBE_DIR}"
else:
    _missing = [
        name
        for prefix, count in (("bal", BAL_PAGES), ("itembypage", ITEM_PAGES), ("itemuombypage", ITEM_UOM_PAGES))
        for name in (f"{prefix}-{i}.json" for i in range(1, count + 1))
        if not os.path.isfile(os.path.join(PROBE_DIR, name))
    ]
    if _missing:
        _skip_reason = (
            f"recorded db1 probe directory is missing {len(_missing)} expected page(s), "
            f"e.g. {_missing[0]} - cannot prove AC-10-84 against a partial capture"
        )

pytestmark = pytest.mark.skipif(_skip_reason is not None, reason=_skip_reason or "")

ITEM_LOOKUP = {
    "path": "/itembypage", "as": "item",
    "on": [{"local": "ItemCode", "remote": "ItemCode"}],
    "fields": [
        {"remote": "BaseUOM", "as": "ItemBaseUOM"},
        {"remote": "Description", "as": "ItemDescription"},
    ],
}
ITEM_UOM_LOOKUP = {
    "path": "/itemuombypage", "as": "uom",
    "on": [
        {"local": "ItemCode", "remote": "ItemCode"},
        {"local": "UOM", "remote": "UOM", "match": "casefold_trim"},
    ],
    "fields": [{"remote": "Rate", "as": "UomRate"}],
}
STOCK_COMBINE: Dict[str, Any] = {
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
    "require": [
        {
            "name": "uom_rate",
            "formula": (
                "lower(trim(UOM)) == lower(trim(ItemBaseUOM)) or "
                "number(default(UomRate, 0)) > 0"
            ),
            "reason": "uom_rate_unresolved",
        }
    ],
    "measure": "base_qty",
    "groupBy": ["item_code", "location_code"],
    "measures": [{"source": "base_qty", "op": "sum", "alias": "qty"}],
    "carry": ["ItemDescription", "ItemBaseUOM"],
    "round": [{"measure": "qty", "mode": "half_up", "dp": 0}],
    "drop": [
        {"name": "zero", "formula": "qty == 0"},
        {"name": "negative", "formula": "qty < 0", "listRows": True},
    ],
}


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    real_send = httpx.Client.send
    real_async_send = httpx.AsyncClient.send

    def guarded_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return real_send(self, request, *args, **kwargs)

    async def guarded_async_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return await real_async_send(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", guarded_send)
    monkeypatch.setattr(httpx.AsyncClient, "send", guarded_async_send)


@pytest.fixture(scope="module")
def probe_pages() -> Dict[str, List[Dict[str, Any]]]:
    """Loaded ONCE for the whole module (brief's own instruction)."""
    if _skip_reason is not None:
        return {}

    def _load(prefix: str, count: int) -> List[Dict[str, Any]]:
        pages = []
        for i in range(1, count + 1):
            with open(os.path.join(PROBE_DIR, f"{prefix}-{i}.json"), encoding="utf-8") as fh:
                pages.append(json.load(fh))
        return pages

    return {
        "/itembatchbalqtybypage": _load("bal", BAL_PAGES),
        "/itembypage": _load("itembypage", ITEM_PAGES),
        "/itemuombypage": _load("itemuombypage", ITEM_UOM_PAGES),
    }


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str):
    from modules.autocount.models import AcCompany

    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _recorded_pages_handler(probe_pages: Dict[str, List[Dict[str, Any]]]):
    """Routes by path suffix and serves the recorded page for the requested
    ``page`` number - the file's own ``Page``/``TotalCount``/``TotalPages``
    are the LIVE wrapper's own echoed values, untouched."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = next(p for p in probe_pages if request.url.path.endswith(p))
        pages = probe_pages[path]
        page_num = int(request.url.params.get("page", "1"))
        index = min(max(page_num, 1), len(pages)) - 1
        return httpx.Response(200, json=pages[index])

    return handler


def test_the_stock_preset_reproduces_the_live_db1_numbers_end_to_end(db, probe_pages):
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.models import AcEntityConfig
    from modules.autocount.services.company_service import CompanyService
    from modules.autocount.sources import SourceContext, Watermark
    from modules.autocount.http_source.source import HttpApiSource

    conn = _connection(db)
    company = _company(db, conn.id)
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_STOCK_BALANCE,
        source_impl="autocount_http",
        source_config={
            "connectionId": conn.id, "path": "/itembatchbalqtybypage",
            "keyFields": ["item_code", "location_code"], "watermarkField": None,
            "comparedFields": [], "distinctOf": None, "incrementalMinutes": 15,
            "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": [ITEM_LOOKUP, ITEM_UOM_LOOKUP], "combine": STOCK_COMBINE,
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)

    ctx = SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )
    transport = httpx.Client(transport=httpx.MockTransport(_recorded_pages_handler(probe_pages)))
    source = HttpApiSource(ctx, entity_type=ENTITY_STOCK_BALANCE, transport=transport)

    result = source.fetch_changes(Watermark())

    # rows in -> rows out (AC-10-84's own two headline numbers).
    assert result.rows_scanned == 68612, result.rows_scanned
    assert len(result.records) == 12133, len(result.records)

    meta = result.combine_metadata
    assert meta is not None
    assert meta["roundedCount"] == 0, meta["roundedCount"]
    assert meta["dropped"]["negative"]["count"] == 42, meta["dropped"]["negative"]
    assert len(meta["dropped"]["negative"].get("rows", [])) == 42, meta["dropped"]["negative"]
    # "roughly 56,400" per the plan's own words - pinned exactly here since
    # this run is 100% reproducible against a FIXED recorded capture (never
    # a live, drifting endpoint).
    assert meta["dropped"]["zero"]["count"] == 56422, meta["dropped"]["zero"]["count"]
    # See the file docstring: this recorded capture resolves EVERY
    # (ItemCode, UOM) pair the balance table names, so excludedCount is 0
    # here - not the "5 known rate-unresolved rows" the plan's prose
    # describes from an earlier/different probe. Every other number above
    # matches the plan's own stated live figures exactly.
    assert meta["excludedCount"] == 0, meta["excludedCount"]

    # Every delivered row is a genuinely positive integer quantity.
    for record in result.records:
        assert int(record.raw["qty"]) > 0, record.raw


# ── kill test ────────────────────────────────────────────────────────────
#
# test_the_stock_preset_reproduces_the_live_db1_numbers_end_to_end dies on
# the FIRST assertion if the coder's combine engine (or the preset's own
# formulas) diverge from the already-shipped, already-GREEN S5a reducer in
# any way that changes counts at this scale - a wrong casefold/trim, a
# dropped require rule, or a rounding-mode slip would all show up as a
# numeric mismatch here, not a silent pass.
