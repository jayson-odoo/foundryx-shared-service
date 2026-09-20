"""Sprint-5/10 S5b - the stock reducer's observable behaviour through the
FULL pull-snapshot build job: AC-10-42, 43, 44, 45, 46, 68.

RED before the coder for TWO layered reasons:

* ``ENTITY_STOCK_BALANCE``/``CanonicalStockBalance`` do not exist yet -
  every test below fails at collection with a plain ``ImportError``.
* Once they exist, ``sync._run_pull_snapshot`` still has NO branch that
  merges ``FetchResult.combine_metadata`` (the generic
  ``{excludedRows, excludedCount, dropped, roundedCount}`` shape S5a's
  ``HttpApiSource``/``apply_combine`` already produce) onto the snapshot's
  own ``metadata_json`` - today the handler's only entity-specific branch is
  ``if entity_type == ENTITY_PRODUCT: metadata.update(_product_price_counters(...))``
  (verified by reading ``sync.py`` before writing this file), and the
  per-record ``excluded_rows`` list it DOES build only ever comes from
  ``mapped.record is None`` (a MAPPING failure) - a combine-stage exclusion
  (stock's own ``uom_rate_unresolved``/``computed_error``) never reaches it
  at all. So every assertion on ``snapshot.metadata_json``'s
  ``excludedCount``/``excludedRows`` below is a plain, real assertion
  failure once collection succeeds - never an ImportError.

The 9-row fixture (bal endpoint) is DELIBERATELY the same shape
``test_s10_s5a_preview_funnel.py``'s own ``_funnel_rows()``/``STOCK_COMBINE``
already pins at the reducer layer (9 in, 2 excluded, 4 groups, "zero" drops
1, "negative" drops 1 listed, 1 rounded, 2 out) - rebuilt here to go through
REAL lookup endpoints (item/itemuom) instead of pre-merged columns, so the
SAME numbers additionally prove the lookup-then-combine-then-map pipeline
end to end. One addition over the S5a fixture: the two combine-stage
exclusions are engineered to hit BOTH of ``apply_combine``'s two distinct
exclusion paths (a genuine finding while designing this fixture, not
previously documented in the plan) - see the note above
``test_the_two_combine_stage_exclusions_use_different_reasons``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    "path": "/itembypage",
    "as": "item",
    "on": [{"local": "ItemCode", "remote": "ItemCode"}],
    "fields": [
        {"remote": "BaseUOM", "as": "ItemBaseUOM"},
        {"remote": "Description", "as": "ItemDescription"},
    ],
}
ITEM_UOM_LOOKUP = {
    "path": "/itemuombypage",
    "as": "uom",
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
    """Lane rule: no test in this file may touch the network."""
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


DEFAULT_MAPPING_ROWS = [
    _row("item_code", "item_code", required=True),
    _row("location_code", "location_code", required=True),
    _row("ItemDescription", "item_description"),
    _row("ItemBaseUOM", "uom_code"),
    _row("qty", "qty", "int"),
]


def _stock_task(db, company, connection_id, *, mapping_rows=None):
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
    for i, row in enumerate(DEFAULT_MAPPING_ROWS if mapping_rows is None else mapping_rows):
        db.add(
            AcFieldMapping(
                tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
                entity_type=ENTITY_STOCK_BALANCE, scope="header", sort_order=i, **row,
            )
        )
    db.commit()
    db.refresh(config)
    return config


def _envelope(rows: List[Dict[str, Any]], *, total_count=None) -> Dict[str, Any]:
    return {
        "TotalCount": total_count if total_count is not None else len(rows),
        "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": rows,
    }


def _multi_transport(pages_by_path: Dict[str, Dict[str, Any]]) -> httpx.Client:
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


def _bal_row(**kw: Any) -> Dict[str, Any]:
    base = {"ItemCode": "X", "UOM": "UNIT", "Location": "L", "BatchNo": "", "BalQty": 1}
    base.update(kw)
    return base


# The 9-row scenario (AC-10-42/43/44/45/68), reproducing
# test_s10_s5a_preview_funnel.py's own verified funnel numbers (9 in, 2
# excluded, 4 groups, zero drops 1, negative drops 1 listed, 1 rounded, 2
# out) but through REAL /itembypage + /itemuombypage lookups instead of
# pre-merged columns. Locations deliberately include one AutoCount-inactive
# code (PRJ-ACT, a live stock-bearing example the UAC names) and one absent
# from Sorento entirely (BRW-VAR) - AC-10-68 pins that BOTH are delivered/
# excluded on quantity grounds alone, never filtered by location.
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
    # Every item's BASE-UOM row is present (the live-shaped fact AC-10-40's
    # probe note relies on: "every item has a row whose UOM equals its
    # BaseUOM") PLUS the box conversions - except SRT-05's BOX row, which is
    # deliberately ABSENT (a genuine lookup miss).
    rows = []
    for code in ("SRT-01", "SRT-02", "SRT-03", "SRT-04", "SRT-05", "SRT-06"):
        rows.append({"ItemCode": code, "UOM": "UNIT", "Rate": 1.0})
    rows.append({"ItemCode": "SRT-01", "UOM": "BOX", "Rate": 5.0})
    rows.append({"ItemCode": "SRT-04", "UOM": "BOX", "Rate": 0.0})  # explicit zero rate
    # SRT-05 BOX: no row at all.
    rows.append({"ItemCode": "SRT-06", "UOM": "BOX", "Rate": 0.5})
    return rows


def _scenario_transport(*, bal_total_count=None):
    return _multi_transport(
        {
            "/itembatchbalqtybypage": _envelope(_bal_rows(), total_count=bal_total_count),
            "/itembypage": _envelope(_item_rows()),
            "/itemuombypage": _envelope(_uom_rows()),
        }
    )


def _build(db, company):
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.services.pull_service import PullService

    return PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, requested_via="operator", now=NOW,
    )


# ── AC-10-42/45: only nonzero positive pairs survive, with the agreed shape ─


def test_only_nonzero_positive_pairs_survive_with_the_agreed_row_shape(db, monkeypatch):
    from modules.autocount.models import AcPullSnapshotRow

    conn = _connection(db)
    company = _company(db, conn.id)
    _stock_task(db, company, conn.id)
    _patch_transport(monkeypatch, _scenario_transport())

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.status == "ready", snapshot.error
    assert snapshot.record_count == 2, snapshot.record_count
    rows = (
        db.query(AcPullSnapshotRow)
        .filter(AcPullSnapshotRow.snapshot_id == snapshot.id)
        .order_by(AcPullSnapshotRow.row_index)
        .all()
    )
    by_key = {(r.payload_json["item_code"], r.payload_json["location_code"]): r for r in rows}
    assert set(by_key) == {("SRT-01", "MAIN"), ("SRT-06", "LOC4")}, by_key

    main = by_key[("SRT-01", "MAIN")]
    assert main.payload_json == {
        "source_ref": f"{REF_PREFIX}:SRT-01|MAIN",
        "item_code": "SRT-01", "item_description": "Item SRT-01",
        "location_code": "MAIN", "uom_code": "UNIT", "qty": 20,
    }, main.payload_json
    assert main.source_ref == f"{REF_PREFIX}:SRT-01|MAIN"

    rounded = by_key[("SRT-06", "LOC4")]
    assert rounded.payload_json["qty"] == 4, rounded.payload_json  # 3.5 half-up


# ── AC-10-44: complete stays TRUE despite combine-stage exclusions ─────────


def test_complete_stays_true_with_combine_stage_exclusions(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _stock_task(db, company, conn.id)
    _patch_transport(monkeypatch, _scenario_transport())

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.status == "ready"
    assert snapshot.complete is True, (
        "an exclusion is a data problem, not a truncated walk (R6/AC-10-44) - "
        "the main walk AND both lookups were fully verified here"
    )


# ── AC-10-44/45/65/66 wiring gap: combine-stage exclusions must reach the
# snapshot's own excludedRows/excludedCount, not just per-record mapping
# failures ───────────────────────────────────────────────────────────────


def test_combine_stage_exclusions_reach_the_snapshot_header(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _stock_task(db, company, conn.id)
    _patch_transport(monkeypatch, _scenario_transport())

    snapshot = _build(db, company)
    db.refresh(snapshot)

    meta = snapshot.metadata_json
    assert meta.get("excludedCount") == 2, meta
    assert len(meta.get("excludedRows") or []) == 2, meta


def test_the_two_combine_stage_exclusions_use_different_reasons(db, monkeypatch):
    """A genuine finding while building this fixture, PROVEN by running it
    against a scratch implementation before this test was finalised
    (documented in the file docstring and the tester's final report):
    ``apply_combine``'s stock preset has THREE formulas that name
    ``UomRate`` (the computed ``base_qty`` column's own FALSE branch, and
    the ``require`` rule) - so a row whose lookup genuinely MISSED (SRT-05:
    no itemuombypage row at all for (SRT-05, BOX)) fails to even PARSE at
    the very first place ``UomRate`` is referenced, which is the COMPUTED
    stage, not the require stage - reason ``"computed_error"``, never
    ``"require_error"``. Only a row whose lookup MATCHED with a real,
    resolvable (if unusable) rate - SRT-04's explicit ``Rate: 0.0`` - reaches
    the require rule at all and is excluded with ITS declared reason,
    ``"uom_rate_unresolved"``. An entity-profile map or a consumer reading
    raw reason strings must expect ``computed_error`` for a genuine lookup
    miss, not only the one reason AC-10-41's require rule names."""
    conn = _connection(db)
    company = _company(db, conn.id)
    _stock_task(db, company, conn.id)
    _patch_transport(monkeypatch, _scenario_transport())

    snapshot = _build(db, company)
    db.refresh(snapshot)

    reasons = {row.get("reason") for row in (snapshot.metadata_json.get("excludedRows") or [])}
    assert reasons == {"uom_rate_unresolved", "computed_error"}, reasons


# ── AC-10-68: no location allow-list, no active filter, no item filter ─────


def test_inactive_and_unknown_locations_are_processed_untouched_no_filter(db, monkeypatch):
    """``PRJ-ACT`` (inactive in AutoCount) and ``BRW-VAR`` (absent from
    Sorento entirely) are both fed through the SAME quantity-only cut as
    every other row - excluded here because of their RATE, never their
    location. A location allow-list would have dropped them silently with a
    different (or no) reason; this fixture proves neither location name is
    ever consulted."""
    conn = _connection(db)
    company = _company(db, conn.id)
    _stock_task(db, company, conn.id)
    _patch_transport(monkeypatch, _scenario_transport())

    snapshot = _build(db, company)
    db.refresh(snapshot)

    excluded_locations = {
        row.get("location_code") for row in (snapshot.metadata_json.get("excludedRows") or [])
    }
    assert excluded_locations == {"PRJ-ACT", "BRW-VAR"}, excluded_locations


# ── AC-10-45: a short walk yields complete=false ────────────────────────────


def test_complete_is_false_when_the_main_walk_is_short_of_total_count(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _stock_task(db, company, conn.id)
    _patch_transport(monkeypatch, _scenario_transport(bal_total_count=999))

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.status == "ready"  # a completeness mismatch never fails the build
    assert snapshot.complete is False


# ── AC-10-46: the zero-row guard applies to stock exactly like product ─────


def test_a_zero_row_stock_build_after_a_nonzero_ready_snapshot_fails_empty_extract(db, monkeypatch):
    from modules.autocount.services.pull_service import SnapshotService

    conn = _connection(db)
    company = _company(db, conn.id)
    _stock_task(db, company, conn.id)

    previous = SnapshotService(db).create_building(
        DEFAULT_TENANT_ID, company.id, "stock_balance",
        company_code=company.sorento_company_code, requested_via="operator",
    )
    SnapshotService(db).stamp_ready(
        DEFAULT_TENANT_ID, previous, record_count=2, complete=True,
        content_hash="a" * 64, metadata={},
        extracted_at=NOW - timedelta(hours=1), expires_at=NOW + timedelta(hours=23),
    )
    _patch_transport(
        monkeypatch,
        _multi_transport({
            "/itembatchbalqtybypage": _envelope([]),
            "/itembypage": _envelope([]),
            "/itemuombypage": _envelope([]),
        }),
    )

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.status == "failed"
    assert snapshot.error_code == "EMPTY_EXTRACT"


def test_a_genuinely_first_zero_row_stock_build_is_allowed_control(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _stock_task(db, company, conn.id)
    _patch_transport(
        monkeypatch,
        _multi_transport({
            "/itembatchbalqtybypage": _envelope([]),
            "/itembypage": _envelope([]),
            "/itemuombypage": _envelope([]),
        }),
    )

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.status == "ready"
    assert snapshot.record_count == 0


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_only_nonzero_positive_pairs_survive_with_the_agreed_row_shape dies
#   if a location trim regression reintroduces 'MBS ' as a SEPARATE pair from
#   'MBS', or if the round-half-up rule is skipped (3.5 would deliver as 3 or
#   error).
# * test_combine_stage_exclusions_reach_the_snapshot_header dies today
#   (before the coder's fix): `_run_pull_snapshot` never reads
#   `result.combine_metadata` at all, so `excludedCount` stays 0.
# * test_inactive_and_unknown_locations_are_processed_untouched_no_filter
#   dies if a location allow-list/active-flag check is ever added on this
#   side - the exact regression R7/AC-10-68 forbids.
# * test_complete_is_false_when_the_main_walk_is_short_of_total_count is the
#   CONTROL proving `complete` is computed, never hardcoded True for stock.
