"""Sprint-5/10 S5b - the entity-profile map (AC-10-81, R11) as it applies to
``stock_balance``, plus the per-entity exclusion semantics split (AC-10-65,
AC-10-66).

RED before the coder for the SAME two layered reasons
``test_s10_s5b_reducer_behaviour.py`` documents: the entity import fails
first; once it exists, ``sync._run_pull_snapshot`` has no map at all from
the generic ``{excludedRows, excludedCount, dropped, roundedCount}`` shape
(``http_source/combine.py``'s own already-shipped output) onto the agreed
Sorento wire names (``zeroPairs``, ``negativePairs``, ``negativePairList``,
``fractionalPairs``, ``excludedNonzeroCount``) - every assertion below on
``snapshot.metadata_json`` is a plain, real assertion failure.

**A discrepancy worth flagging rather than papering over** (see the tester's
final report): the plan's Appendix A3 worked example shows a stock
``excludedRows`` entry carrying a ``"uom"`` key
(``{"item_code": "SRT-99", "location_code": "HQ", "uom": "ctn", "qty": 0,
"reason": "uom_rate_unresolved"}``), but the ALREADY-SHIPPED, ALREADY-GREEN
generic exclusion shape AC-10-77 pins (``combine.py``'s own
``apply_combine``, S5a) captures ONLY the ``groupBy`` columns plus the raw
DESIGNATED MEASURE value plus ``reason`` for a require-stage exclusion -
literally no mechanism carries a THIRD, non-group-by, non-measure raw
column like ``uom`` along for the ride. This file therefore pins AC-10-81's
own precise, unambiguous declarative-map TEXT (quoted in full below) rather
than attempting a literal byte-for-byte JSON compare against Appendix A3's
example, which is unreachable without extending the require-rule shape
(e.g. an optional ``capture`` list) - a genuine open question for the
planner/coder, not a decision this test file should make unilaterally.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection

DB_NAME = "AED_SORENTO"
REF_PREFIX = "AED_SORENTO"
BASE_URL = "https://hapi.sorento.cc.cd/api/db1"
NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)

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
        config_json={"baseUrl": BASE_URL, "auth": "none"}, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str):
    from modules.autocount.models import AcCompany

    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name=DB_NAME,
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _row(source_path, canonical_field, transform="string", *, required=False):
    return dict(
        source_path=source_path, canonical_field=canonical_field, transform=transform,
        is_required=required, formula=None,
    )


def _stock_task(db, company, connection_id):
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.models import AcEntityConfig, AcFieldMapping, DELIVERY_MODE_PULL, ETL_STATUS_ACTIVE

    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_STOCK_BALANCE,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE,
        delivery_mode=DELIVERY_MODE_PULL,
        source_config={
            "connectionId": connection_id, "path": "/itembatchbalqtybypage",
            "keyFields": ["item_code", "location_code"], "watermarkField": None,
            "comparedFields": [], "distinctOf": None, "incrementalMinutes": 15,
            "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": [ITEM_LOOKUP, ITEM_UOM_LOOKUP], "combine": STOCK_COMBINE,
        },
        last_preview_at=NOW,
        result_columns=["ItemCode", "UOM", "Location", "BatchNo", "BalQty"],
    )
    db.add(config)
    db.commit()
    for i, row in enumerate([
        _row("item_code", "item_code", required=True),
        _row("location_code", "location_code", required=True),
        _row("ItemDescription", "item_description"),
        _row("ItemBaseUOM", "uom_code"),
        _row("qty", "qty", "int"),
    ]):
        db.add(
            AcFieldMapping(
                tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
                entity_type=ENTITY_STOCK_BALANCE, scope="header", sort_order=i, **row,
            )
        )
    db.commit()
    db.refresh(config)
    return config


def _bal_row(**kw: Any) -> Dict[str, Any]:
    base = {"ItemCode": "X", "UOM": "UNIT", "Location": "L", "BatchNo": "", "BalQty": 1}
    base.update(kw)
    return base


def _bal_rows() -> List[Dict[str, Any]]:
    return [
        _bal_row(ItemCode="SRT-01", UOM="UNIT", Location="MAIN", BalQty=10),
        _bal_row(ItemCode="SRT-01", UOM="BOX", Location="MAIN", BalQty=2),
        _bal_row(ItemCode="SRT-02", UOM="UNIT", Location="MBS ", BalQty=5),
        _bal_row(ItemCode="SRT-02", UOM="UNIT", Location="MBS", BalQty=-8),
        _bal_row(ItemCode="SRT-03", UOM="UNIT", Location="LOC1", BalQty=0),
        _bal_row(ItemCode="SRT-04", UOM="BOX", Location="PRJ-ACT", BalQty=3),
        _bal_row(ItemCode="SRT-05", UOM="BOX", Location="BRW-VAR", BalQty=4),
        _bal_row(ItemCode="SRT-06", UOM="UNIT", Location="LOC4", BalQty=3),
        _bal_row(ItemCode="SRT-06", UOM="BOX", Location="LOC4", BalQty=1),
    ]


def _item_rows() -> List[Dict[str, Any]]:
    return [
        {"ItemCode": code, "BaseUOM": "UNIT", "Description": f"Item {code}"}
        for code in ("SRT-01", "SRT-02", "SRT-03", "SRT-04", "SRT-05", "SRT-06")
    ]


def _uom_rows() -> List[Dict[str, Any]]:
    rows = [
        {"ItemCode": code, "UOM": "UNIT", "Rate": 1.0}
        for code in ("SRT-01", "SRT-02", "SRT-03", "SRT-04", "SRT-05", "SRT-06")
    ]
    rows.append({"ItemCode": "SRT-01", "UOM": "BOX", "Rate": 5.0})
    rows.append({"ItemCode": "SRT-04", "UOM": "BOX", "Rate": 0.0})
    rows.append({"ItemCode": "SRT-06", "UOM": "BOX", "Rate": 0.5})
    return rows


def _envelope(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"TotalCount": len(rows), "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": rows}


def _scenario_transport() -> httpx.Client:
    pages_by_path = {
        "/itembatchbalqtybypage": _envelope(_bal_rows()),
        "/itembypage": _envelope(_item_rows()),
        "/itemuombypage": _envelope(_uom_rows()),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = next(p for p in pages_by_path if request.url.path.endswith(p))
        return httpx.Response(200, json=pages_by_path[path])

    return httpx.Client(transport=httpx.MockTransport(handler))


def _patch_transport(monkeypatch, transport: httpx.Client) -> None:
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=transport),
    )


def _build_stock_snapshot(db, monkeypatch):
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.services.pull_service import PullService

    conn = _connection(db)
    company = _company(db, conn.id)
    _stock_task(db, company, conn.id)
    _patch_transport(monkeypatch, _scenario_transport())
    snapshot = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, requested_via="operator", now=NOW,
    )
    db.refresh(snapshot)
    return snapshot


# ── AC-10-81: the declarative map, quoted verbatim from the UAC ────────────
#
#   zeroPairs          <- dropped["zero"].count
#   negativePairs      <- dropped["negative"].count
#   negativePairList   <- dropped["negative"].rows
#   fractionalPairs    <- roundedCount
#   excludedNonzeroCount <- excludedRows where measure != 0
#   excludedRows / excludedCount pass through unchanged


def test_stock_header_serialises_the_agreed_wire_names_from_generic_metadata(db, monkeypatch):
    snapshot = _build_stock_snapshot(db, monkeypatch)
    meta = snapshot.metadata_json

    assert meta.get("zeroPairs") == 1, meta
    assert meta.get("negativePairs") == 1, meta
    assert meta.get("negativePairList") == [
        {"item_code": "SRT-02", "location_code": "MBS", "qty": -3}
    ], meta.get("negativePairList")
    assert meta.get("fractionalPairs") == 1, meta
    assert meta.get("excludedCount") == 2, meta
    # AC-10-66: the DESIGNATED MEASURE is the COMPUTED "base_qty" column, not
    # the raw "BalQty" - a genuine finding (see
    # test_s10_s5b_reducer_behaviour.py's own docstring on the two distinct
    # exclusion reasons). SRT-04's rate resolved to a REAL 0.0, so its OWN
    # computed base_qty is ALSO 0.0 (3 * 0.0) - correctly NOT counted as
    # "nonzero" (omitting a row that already contributes zero is never a
    # silent-zeroing risk; Appendix A3's own worked example shows exactly
    # this shape: {"qty": 0, "reason": "uom_rate_unresolved"}). SRT-05's rate
    # is UNRESOLVABLE (a computed_error, measure reported as None, never a
    # guessed number) - "None != 0" fail-closed COUNTS it, since an unknown
    # quantity is never provably safe to drop. So exactly ONE of the two
    # exclusions is nonzero here.
    assert meta.get("excludedNonzeroCount") == 1, meta
    assert "truncated" not in meta, meta


def test_the_negative_pair_list_row_shape_is_item_code_location_code_qty_only(db, monkeypatch):
    """AC-10-42's own quoted shape: ``{item_code, location_code, qty}`` -
    never a fourth key (no ``uom``, no ``reason``) - this is a DROP-stage
    listed row, structurally different from an EXCLUDED row."""
    snapshot = _build_stock_snapshot(db, monkeypatch)
    negative_pair_list = snapshot.metadata_json.get("negativePairList") or []
    assert len(negative_pair_list) == 1
    assert set(negative_pair_list[0].keys()) == {"item_code", "location_code", "qty"}


def test_the_operator_and_gateway_headers_both_project_the_stock_keys(db, monkeypatch):
    """The two ALREADY-SHIPPED header projections (``pull_service.
    snapshot_header``, ``pull_gateway_service.gateway_snapshot_header``)
    already pass through any of the agreed stock keys present in
    ``metadata_json`` (verified by reading both functions before writing
    this test) - so once the entity-profile map lands, BOTH surfaces pick
    it up for free. This test is the end-to-end proof of that, not a new
    requirement on either function."""
    from modules.autocount.services.pull_gateway_service import gateway_snapshot_header
    from modules.autocount.services.pull_service import snapshot_header

    snapshot = _build_stock_snapshot(db, monkeypatch)

    operator_header = snapshot_header(snapshot)
    gateway_header = gateway_snapshot_header(snapshot)
    for header in (operator_header, gateway_header):
        assert header["zeroPairs"] == 1, header
        assert header["negativePairs"] == 1, header
        assert header["fractionalPairs"] == 1, header
        assert header["excludedNonzeroCount"] == 1, header
    # Both headers must serialise cleanly (no Decimal/None-shaped surprise).
    json.dumps(operator_header, default=str)
    json.dumps(gateway_header, default=str)


# ── AC-10-65: exclusion semantics differ by entity, never the header shape ─


def test_a_product_snapshot_with_exclusions_never_carries_stock_only_keys(db, monkeypatch):
    """CONTROL (AC-10-65): a PRODUCT snapshot with an exclusion is
    ``ready``, ``complete: true``, and carries NONE of the stock-only wire
    names - the entity-profile map is per-entity, never a blanket merge."""
    from modules.autocount.canonical.masters import ENTITY_PRODUCT
    from modules.autocount.models import AcEntityConfig, AcFieldMapping, DELIVERY_MODE_PULL, ETL_STATUS_ACTIVE
    from modules.autocount.services.pull_service import PullService

    conn = _connection(db)
    company = _company(db, conn.id)
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE,
        delivery_mode=DELIVERY_MODE_PULL,
        source_config={
            "connectionId": conn.id, "path": "/itembypage", "keyFields": ["ItemCode"],
            "watermarkField": None, "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": [],
        },
        last_preview_at=NOW, result_columns=["ItemCode", "Description"],
    )
    db.add(config)
    db.commit()
    db.add(
        AcFieldMapping(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            scope="header", sort_order=0, source_path="ItemCode", canonical_field="code",
            transform="string", is_required=True,
        )
    )
    db.add(
        AcFieldMapping(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            scope="header", sort_order=1, source_path="Description", canonical_field="name",
            transform="string", is_required=True,
        )
    )
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "TotalCount": 2, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                "Data": [
                    {"ItemCode": "GOOD", "Description": "A good item"},
                    {"ItemCode": "BLANK", "Description": ""},
                ],
            },
        )

    _patch_transport(monkeypatch, httpx.Client(transport=httpx.MockTransport(handler)))
    snapshot = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=NOW,
    )
    db.refresh(snapshot)

    assert snapshot.status == "ready"
    assert snapshot.complete is True
    meta = snapshot.metadata_json
    assert meta.get("excludedCount") == 1
    for stock_only_key in (
        "zeroPairs", "negativePairs", "negativePairList", "fractionalPairs",
        "excludedNonzeroCount",
    ):
        assert stock_only_key not in meta, (stock_only_key, meta)


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_stock_header_serialises_the_agreed_wire_names_from_generic_metadata
#   dies today (before the coder's fix) on every assertion - none of these
#   keys are written by `_run_pull_snapshot` for any entity but `product`.
# * test_a_product_snapshot_with_exclusions_never_carries_stock_only_keys
#   dies if the coder wires the entity-profile map as an UNCONDITIONAL merge
#   (every entity gets zeroPairs etc.) instead of a per-entity map keyed by
#   `entity_type == ENTITY_STOCK_BALANCE`.
# * test_the_operator_and_gateway_headers_both_project_the_stock_keys dies if
#   the coder writes the stock keys somewhere OTHER than
#   `AcPullSnapshot.metadata_json` (e.g. a parallel column) that the two
#   EXISTING header projections never read.
