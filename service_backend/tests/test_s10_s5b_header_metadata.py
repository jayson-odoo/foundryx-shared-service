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

**Resolved (S5b review round 5, S1)**: the discrepancy this file originally
flagged (the plan's Appendix A3 worked example showing a stock
``excludedRows`` entry with a ``"uom"``/``"qty"`` key no mechanism could
produce) was fixed by AMENDING Appendix A3 itself (405185bd) to match the
ALREADY-SHIPPED, ALREADY-GREEN generic exclusion shape ``combine.py``'s own
``apply_combine`` produces - ``{<groupBy cols>, measure, reason}`` for a
require-stage exclusion. Appendix A3 is now the SOURCE OF TRUTH the pin
below compares against byte for byte (ids/timestamps normalised) - a
renamed, added or dropped header key now fails this file directly, not just
AC-10-81's own declarative-map text (still quoted below as the map's own
spec, unchanged).
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

# N1 (review round 5) - imported from the REAL preset rather than a local
# copy, so a preset edit (e.g. dropping `listRows`) fails a header test too
# instead of silently drifting from what actually ships.
from modules.autocount.presets import STOCK_BALANCE_HTTP_PRESET  # noqa: E402

ITEM_LOOKUP, ITEM_UOM_LOOKUP = STOCK_BALANCE_HTTP_PRESET.lookups
STOCK_COMBINE: Dict[str, Any] = STOCK_BALANCE_HTTP_PRESET.combine


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


def test_the_gateway_header_is_byte_for_byte_appendix_a3s_amended_stock_example(db, monkeypatch):
    """S1 (review round 5) - the FULL, real ``gateway_snapshot_header`` dict
    compared key for key against Appendix A3's amended stock example (ids/
    timestamps/hash normalised to placeholders below), so an added, renamed
    or dropped header key fails HERE, not just via the individual-key
    assertions above. ``gateway_snapshot_header``'s own docstring is explicit
    that its shape IS Appendix A3 ("every key here is one Appendix A names
    for THIS status, and no other") - the operator route's
    ``pull_service.snapshot_header`` is a DIFFERENT, internal shape by
    design (``id``/``entityType``/``companyId``/``requestedVia``/
    ``createdAt`` - never claimed to match A3), so it gets its OWN full-dict
    pin below instead of a literal comparison against the same example."""
    from modules.autocount.services.pull_gateway_service import gateway_snapshot_header
    from modules.autocount.services.pull_service import snapshot_header

    snapshot = _build_stock_snapshot(db, monkeypatch)

    gateway_header = gateway_snapshot_header(snapshot)
    normalised = {
        **gateway_header,
        "snapshotId": "<snapshotId>",
        "extractedAt": "<timestamp>",
        "expiresAt": "<timestamp>",
        "contentHash": "<hash>",
    }
    assert normalised == {
        "snapshotId": "<snapshotId>",
        "entity": "stock_balances",
        "companyCode": "SRT",
        "status": "ready",
        "extractedAt": "<timestamp>",
        "expiresAt": "<timestamp>",
        "recordCount": 2,
        "complete": True,
        "contentHash": "<hash>",
        "sourcePageSize": 1000,
        "zeroPairs": 1,
        "negativePairs": 1,
        "fractionalPairs": 1,
        "excludedCount": 2,
        "excludedNonzeroCount": 1,
        "negativePairList": [{"item_code": "SRT-02", "location_code": "MBS", "qty": -3}],
        "excludedRows": [
            {
                "item_code": "SRT-04", "location_code": "PRJ-ACT",
                "measure": 0, "reason": "uom_rate_unresolved",
            },
            {
                "item_code": "SRT-05", "location_code": "BRW-VAR",
                "measure": None, "reason": "computed_error",
            },
        ],
    }, normalised
    # N2 (review round 5) - dict `==` treats `0.0 == 0`, so the comparison
    # above alone cannot catch a float slipping onto the wire where A3 pins
    # a plain int; pinned explicitly by TYPE.
    assert type(gateway_header["excludedRows"][0]["measure"]) is int, gateway_header

    # The operator route's OWN full shape, pinned separately (see docstring
    # above for why it is never compared against the SAME A3 example).
    operator_header = snapshot_header(snapshot)
    normalised_operator = {
        **operator_header,
        "id": "<snapshotId>",
        "companyId": "<companyId>",
        "createdAt": "<timestamp>",
        "extractedAt": "<timestamp>",
        "expiresAt": "<timestamp>",
        "contentHash": "<hash>",
    }
    assert normalised_operator == {
        "id": "<snapshotId>",
        "entityType": "stock_balance",
        "companyId": "<companyId>",
        "companyCode": "SRT",
        "status": "ready",
        "requestedVia": "operator",
        "createdAt": "<timestamp>",
        "extractedAt": "<timestamp>",
        "expiresAt": "<timestamp>",
        "recordCount": 2,
        "complete": True,
        "contentHash": "<hash>",
        "sourcePageSize": 1000,
        "excludedCount": 2,
        "excludedRows": [
            {
                "item_code": "SRT-04", "location_code": "PRJ-ACT",
                "measure": 0, "reason": "uom_rate_unresolved",
            },
            {
                "item_code": "SRT-05", "location_code": "BRW-VAR",
                "measure": None, "reason": "computed_error",
            },
        ],
        "zeroPairs": 1,
        "negativePairs": 1,
        "fractionalPairs": 1,
        "excludedNonzeroCount": 1,
        "negativePairList": [{"item_code": "SRT-02", "location_code": "MBS", "qty": -3}],
    }, normalised_operator


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


# ── review round 5 (B1/S2): a MAPPING-stage exclusion must count too ───────


def _stock_task_no_negative_drop(db, company, connection_id):
    """Same task/mapping shape as ``_stock_task`` above, but the combine's
    OWN ``negative`` drop rule is removed on purpose - so a group whose
    combined quantity is negative SURVIVES combine intact and reaches the
    mapping stage instead, where ``CanonicalStockBalance.qty``'s own
    ``ge=0`` constraint rejects it (a genuine MAPPING-stage exclusion, never
    a combine-stage one) - the exact class of row B1 names."""
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.models import AcEntityConfig, AcFieldMapping, DELIVERY_MODE_PULL, ETL_STATUS_ACTIVE

    combine_no_negative_drop = {**STOCK_COMBINE, "drop": [STOCK_COMBINE["drop"][0]]}
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_STOCK_BALANCE,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE,
        delivery_mode=DELIVERY_MODE_PULL,
        source_config={
            "connectionId": connection_id, "path": "/itembatchbalqtybypage",
            "keyFields": ["item_code", "location_code"], "watermarkField": None,
            "comparedFields": [], "distinctOf": None, "incrementalMinutes": 15,
            "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": [ITEM_LOOKUP, ITEM_UOM_LOOKUP], "combine": combine_no_negative_drop,
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


def _build_stock_snapshot_with_negative_mapping_exclusion(db, monkeypatch):
    """One (item, location) pair whose COMBINED quantity is negative
    (-8, PoC per B1) and whose ONLY exclusion is this mapping-stage one -
    no other row in the fixture is excluded at any stage, so
    ``excludedCount``/``excludedNonzeroCount`` isolate exactly this case."""
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.services.pull_service import PullService

    conn = _connection(db)
    company = _company(db, conn.id)
    _stock_task_no_negative_drop(db, company, conn.id)
    rows = [_bal_row(ItemCode="SRT-02", UOM="UNIT", Location="MBS", BalQty=-8)]
    transport_pages = {
        "/itembatchbalqtybypage": _envelope(rows),
        "/itembypage": _envelope([{"ItemCode": "SRT-02", "BaseUOM": "UNIT", "Description": "Item SRT-02"}]),
        "/itemuombypage": _envelope([{"ItemCode": "SRT-02", "UOM": "UNIT", "Rate": 1.0}]),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = next(p for p in transport_pages if request.url.path.endswith(p))
        return httpx.Response(200, json=transport_pages[path])

    _patch_transport(monkeypatch, httpx.Client(transport=httpx.MockTransport(handler)))
    snapshot = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, requested_via="operator", now=NOW,
    )
    db.refresh(snapshot)
    return snapshot


def test_a_mapping_stage_exclusion_counts_toward_excluded_nonzero_count(db, monkeypatch):
    """B1 (review round 5, AC-10-65/66) - a real stock pair excluded at the
    MAPPING stage (never the combine stage) must still be reachable through
    `excludedNonzeroCount`, the ONE number the consumer's Confirm guard
    reads - before the fix this row never reached
    `apply_pull_metadata_map` at all (only `result.combine_metadata`'s own
    combine-stage-only `excludedRows` did), so `excludedNonzeroCount`
    under-reported and the consumer's import would have zeroed this pair."""
    from modules.autocount.services.pull_gateway_service import gateway_snapshot_header
    from modules.autocount.services.pull_service import snapshot_header

    snapshot = _build_stock_snapshot_with_negative_mapping_exclusion(db, monkeypatch)
    meta = snapshot.metadata_json

    assert meta.get("excludedCount") == 1, meta
    assert meta.get("excludedNonzeroCount") == 1, meta

    operator_header = snapshot_header(snapshot)
    gateway_header = gateway_snapshot_header(snapshot)
    for header in (operator_header, gateway_header):
        assert header["excludedCount"] == 1, header
        assert header["excludedNonzeroCount"] == 1, header


def test_the_mapping_stage_exclusion_entry_uses_the_combine_carrying_shape(db, monkeypatch):
    """S2 (review round 5, coordinator ruling 2026-09-20) - ONE
    `excludedRows` shape for a combine-carrying task: this mapping-stage
    exclusion carries `{item_code, location_code, measure, reason,
    message}`, NEVER the generic `{source_ref, code, reason, message}`
    shape a task with no combine step keeps - `measure` reads off the
    combine's own grouped `qty` alias (the `measures[]` entry whose
    `source` is the designated `base_qty` column), fail-closed to `None`
    when unresolvable, never a raw pre-group column that does not survive
    grouping."""
    snapshot = _build_stock_snapshot_with_negative_mapping_exclusion(db, monkeypatch)
    excluded_rows = snapshot.metadata_json.get("excludedRows") or []
    assert len(excluded_rows) == 1, excluded_rows
    entry = excluded_rows[0]
    assert entry == {
        "item_code": "SRT-02", "location_code": "MBS",
        "measure": -8, "reason": "mapping_failed",
        "message": entry.get("message"),
    }, entry
    assert entry["message"], entry
    assert set(entry.keys()) == {"item_code", "location_code", "measure", "reason", "message"}
    assert "source_ref" not in entry, entry
    assert "code" not in entry, entry


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
# * test_the_gateway_header_is_byte_for_byte_appendix_a3s_amended_stock_example
#   dies on ANY added, renamed or dropped key in either header projection -
#   not just the stock-only subset the earlier tests check.
# * test_a_mapping_stage_exclusion_counts_toward_excluded_nonzero_count dies
#   if `apply_pull_metadata_map` is fed `result.combine_metadata` directly
#   (the pre-fix B1 bug) instead of the MERGED `excluded_rows` list -
#   `excludedNonzeroCount` reports 0 instead of 1.
# * test_the_mapping_stage_exclusion_entry_uses_the_combine_carrying_shape
#   dies if `_excluded_row_entry` keeps building the generic
#   `{source_ref, code, reason, message}` shape for a combine-carrying task
#   instead of normalising through `excluded_row_for_mapping_failure`.
