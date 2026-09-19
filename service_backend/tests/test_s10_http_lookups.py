"""Sprint-5/10 S1 - AC-10-02/03/06/54/60(a): ``HttpApiSource`` merging
operator-configured ``lookups`` onto every source row (R9), pinned at the
HIGHEST STABLE SEAM the plan gives for this: ``HttpApiSource.fetch_changes``'s
own output (``FetchResult.records[i].raw``), never an invented private
``lookups.py`` function signature (``build_index``/``apply`` are named in the
plan's files list with no fixed signature - deliberately not tested directly
here so the coder is free to shape them however is convenient internally).

RED before the coder: ``HttpApiSource.__init__`` today reads a fixed set of
``source_config`` keys (``path``/``keyFields``/``watermarkField``/
``distinctOf``/``comparedFields``/``connectionId``) and silently IGNORES an
unknown ``lookups`` key - so every test below that expects a merged alias
column fails on a plain, real assertion (the alias is simply never there),
never an ImportError. That is the "missing feature" RED reason the brief
allows.

Mirrors ``test_autocount_http_source.py``'s own fixtures byte-for-byte
(``_open_connection``/``_company``/``_config``/``_ctx``/``_transport``) so
the coder sees ONE house style for this seam, not two.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig, AcRowHash
from modules.autocount.repositories import RowHashRepository
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark

from modules.autocount.http_source.source import HttpApiSource
from modules.autocount.http_source.errors import HttpSourceError

DB_NAME = "MOCHA"
BASE_URL = "https://hapi.sorento.cc.cd/api/db2"

ITEM_UOM_LOOKUP = {
    "path": "/itemuombypage",
    "as": "uom",
    "on": [
        {"local": "ItemCode", "remote": "ItemCode"},
        {"local": "BaseUOM", "remote": "UOM", "match": "casefold_trim"},
    ],
    "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
}


def _open_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Mocha REST",
        config_json={"baseUrl": BASE_URL, "auth": "none"}, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name=DB_NAME,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _config(
    db, company, *, entity_type=ENTITY_PRODUCT, connection_id: str, path="/itembypage",
    key_fields=("ItemCode",), watermark_field: Optional[str] = "LastModified",
    compared_fields=(), lookups=None,
) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
        source_impl="autocount_http",
        source_config={
            "connectionId": connection_id,
            "path": path,
            "keyFields": list(key_fields),
            "watermarkField": watermark_field,
            "comparedFields": list(compared_fields),
            "distinctOf": None,
            "incrementalMinutes": 15,
            "reconcileMode": "dailyAt",
            "reconcileAt": "02:00",
            "lookups": lookups or [],
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _ctx(db, company, config) -> SourceContext:
    return SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )


def _transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def rig(session_factory):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    yield db, company, conn
    db.close()


def _envelope(rows: List[Dict[str, Any]], *, page: int = 1, page_size: int = 1000, total_pages: int = 1) -> Dict[str, Any]:
    return {
        "TotalCount": len(rows), "Page": page, "PageSize": page_size,
        "TotalPages": total_pages, "Data": rows,
    }


def _multi_handler(pages_by_path: Dict[str, List[Dict[str, Any]]], calls: List[httpx.Request]):
    """``pages_by_path``: endpoint path -> list of PAGE ENVELOPES (already
    shaped with Page/TotalPages/Data). A request past the last configured
    page for its path answers an empty terminal page."""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        # ``request.url.path`` carries the connection's base path too
        # (e.g. ``/api/db2/itembypage``) - match by SUFFIX against the
        # configured (relative) endpoint path, never an exact string.
        path = next(p for p in pages_by_path if request.url.path.endswith(p))
        pages = pages_by_path[path]
        page_num = int(request.url.params.get("page", "1"))
        if page_num - 1 < len(pages):
            body = pages[page_num - 1]
        else:
            last = pages[-1]
            body = {**last, "Page": page_num, "Data": []}
        return httpx.Response(200, json=body)

    return handler


def _item(code: str, *, base_uom: str = "UNIT", last_modified="2026-08-01T09:00:00") -> Dict[str, Any]:
    return {
        "ItemCode": code, "Description": code, "BaseUOM": base_uom,
        "LastModified": last_modified, "IsActive": "T",
    }


# ── AC-10-02: merge, miss-is-absent, casefold_trim ───────────────────────────


def test_lookup_merges_matching_alias_onto_row(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id, lookups=[ITEM_UOM_LOOKUP])
    calls: List[httpx.Request] = []
    pages_by_path = {
        "/itembypage": [_envelope([_item("SRT-01")])],
        "/itemuombypage": [
            _envelope([{"ItemCode": "SRT-01", "UOM": "unit", "Rate": 1.0, "Price": 63.0}])
        ],
    }
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_multi_handler(pages_by_path, calls)),
    )
    result = source.fetch_changes(Watermark())
    assert len(result.records) == 1
    assert result.records[0].raw.get("BaseUOMPrice") == 63.0


def test_lookup_miss_leaves_alias_absent_never_none(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id, lookups=[ITEM_UOM_LOOKUP])
    calls: List[httpx.Request] = []
    pages_by_path = {
        "/itembypage": [_envelope([_item("SRT-01"), _item("SRT-02", base_uom="EA")])],
        "/itemuombypage": [
            _envelope([{"ItemCode": "SRT-01", "UOM": "UNIT", "Rate": 1.0, "Price": 63.0}])
        ],
    }
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_multi_handler(pages_by_path, calls)),
    )
    result = source.fetch_changes(Watermark())
    by_code = {r.raw["ItemCode"]: r.raw for r in result.records}
    assert "BaseUOMPrice" in by_code["SRT-01"]
    assert "BaseUOMPrice" not in by_code["SRT-02"], (
        "a miss must OMIT the alias key entirely, never set it to None "
        f"(got {by_code['SRT-02']!r})"
    )


def test_junk_uom_row_never_matches(rig):
    """Live dirt (UAC "Live wrapper facts"): some ItemUOM rows carry
    ``UOM: ""`` - they must never satisfy a join, casefold_trim or not."""
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id, lookups=[ITEM_UOM_LOOKUP])
    calls: List[httpx.Request] = []
    pages_by_path = {
        "/itembypage": [_envelope([_item("SRT-03", base_uom="EA")])],
        "/itemuombypage": [
            _envelope([{"ItemCode": "SRT-03", "UOM": "", "Rate": 1.0, "Price": 99.0}])
        ],
    }
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_multi_handler(pages_by_path, calls)),
    )
    result = source.fetch_changes(Watermark())
    assert "BaseUOMPrice" not in result.records[0].raw


def test_casefold_trim_matches_unit_vs_UNIT(rig):
    """Live dirt: a UOM ``'unit'`` where the item's BaseUOM is ``'UNIT'``."""
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id, lookups=[ITEM_UOM_LOOKUP])
    calls: List[httpx.Request] = []
    pages_by_path = {
        "/itembypage": [_envelope([_item("SRT-04", base_uom="UNIT")])],
        "/itemuombypage": [
            _envelope([{"ItemCode": "SRT-04", "UOM": "unit", "Rate": 1.0, "Price": 10.0}])
        ],
    }
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_multi_handler(pages_by_path, calls)),
    )
    result = source.fetch_changes(Watermark())
    assert result.records[0].raw.get("BaseUOMPrice") == 10.0


def test_exact_match_mode_is_case_sensitive(rig):
    """The default ``match: exact`` must NOT casefold - only an explicit
    ``casefold_trim`` join pair does."""
    db, company, conn = rig
    lookup = {
        "path": "/itemuombypage", "as": "uom",
        "on": [{"local": "ItemCode", "remote": "ItemCode"}],
        "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
    }
    config = _config(db, company, connection_id=conn.id, lookups=[lookup])
    calls: List[httpx.Request] = []
    pages_by_path = {
        "/itembypage": [_envelope([{**_item("srt-05"), "ItemCode": "srt-05"}])],
        "/itemuombypage": [
            _envelope([{"ItemCode": "SRT-05", "UOM": "UNIT", "Rate": 1.0, "Price": 5.0}])
        ],
    }
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_multi_handler(pages_by_path, calls)),
    )
    result = source.fetch_changes(Watermark())
    assert "BaseUOMPrice" not in result.records[0].raw, (
        "exact match on ItemCode must be case-sensitive: 'srt-05' != 'SRT-05'"
    )


# ── AC-10-02: multi-hop ordered evaluation ───────────────────────────────────


def test_multi_hop_second_lookup_joins_on_first_lookups_alias(rig):
    """The stock-shaped chain from plan section 2.2: balance row -> item
    BaseUOM (lookup 1) -> ItemUOM Rate keyed off the FIRST lookup's own
    alias (lookup 2)."""
    db, company, conn = rig
    lookups = [
        {
            "path": "/itembypage", "as": "item",
            "on": [{"local": "ItemCode", "remote": "ItemCode"}],
            "fields": [{"remote": "BaseUOM", "as": "ItemBaseUOM"}],
        },
        {
            "path": "/itemuombypage", "as": "uom",
            "on": [
                {"local": "ItemCode", "remote": "ItemCode"},
                {"local": "ItemBaseUOM", "remote": "UOM", "match": "casefold_trim"},
            ],
            "fields": [{"remote": "Rate", "as": "UomRate"}],
        },
    ]
    config = _config(
        db, company, connection_id=conn.id, path="/itembatchbalqtybypage",
        key_fields=("ItemCode", "Location"), watermark_field=None, lookups=lookups,
    )
    calls: List[httpx.Request] = []
    pages_by_path = {
        "/itembatchbalqtybypage": [
            _envelope([{"ItemCode": "SRT-01", "UOM": "unit", "Location": "MAIN", "BalQty": 10}])
        ],
        "/itembypage": [_envelope([{"ItemCode": "SRT-01", "BaseUOM": "UNIT"}])],
        "/itemuombypage": [
            _envelope([{"ItemCode": "SRT-01", "UOM": "UNIT", "Rate": 2.5}])
        ],
    }
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_multi_handler(pages_by_path, calls)),
    )
    result = source.fetch_changes(Watermark())
    raw = result.records[0].raw
    assert raw.get("ItemBaseUOM") == "UNIT"
    assert raw.get("UomRate") == 2.5


def test_lookup_endpoint_uses_the_same_paged_walker(rig):
    """AC-10-02: "walks each lookup endpoint ONCE per run with the SAME
    page walker (echoed Page/TotalPages trusted...)" - a 2-page lookup
    response must be fully indexed, not just its first page."""
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id, lookups=[ITEM_UOM_LOOKUP])
    calls: List[httpx.Request] = []
    pages_by_path = {
        "/itembypage": [_envelope([_item("SRT-06"), _item("SRT-07")])],
        "/itemuombypage": [
            {"TotalCount": 2, "Page": 1, "PageSize": 1, "TotalPages": 2,
             "Data": [{"ItemCode": "SRT-06", "UOM": "UNIT", "Rate": 1.0, "Price": 11.0}]},
            {"TotalCount": 2, "Page": 2, "PageSize": 1, "TotalPages": 2,
             "Data": [{"ItemCode": "SRT-07", "UOM": "UNIT", "Rate": 1.0, "Price": 22.0}]},
        ],
    }
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_multi_handler(pages_by_path, calls)),
    )
    result = source.fetch_changes(Watermark())
    by_code = {r.raw["ItemCode"]: r.raw for r in result.records}
    assert by_code["SRT-06"]["BaseUOMPrice"] == 11.0
    assert by_code["SRT-07"]["BaseUOMPrice"] == 22.0
    lookup_calls = [c for c in calls if c.url.path.endswith("/itemuombypage")]
    assert len(lookup_calls) == 2, "the lookup endpoint must be walked to completion, not just page 1"


# ── AC-10-03: miss counted (one warning), endpoint failure fails the run ─────


def test_enrich_miss_counted_once_with_named_activity_note(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id, lookups=[ITEM_UOM_LOOKUP])
    calls: List[httpx.Request] = []
    pages_by_path = {
        "/itembypage": [_envelope([_item("SRT-08"), _item("SRT-09", base_uom="EA")])],
        "/itemuombypage": [
            _envelope([{"ItemCode": "SRT-08", "UOM": "UNIT", "Rate": 1.0, "Price": 1.0}])
        ],
    }
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_multi_handler(pages_by_path, calls)),
    )
    result = source.fetch_changes(Watermark())
    assert len(result.records) == 2  # the run SUCCEEDS despite the miss
    activity = list(source.drain_activity())
    notes = [r for r in activity if r.method == "NOTE"]
    assert len(notes) == 1, activity
    message = notes[0].response["message"]
    assert "uom" in message
    assert "1" in message


def test_enrich_endpoint_failure_fails_the_run_before_any_state_touched(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id, lookups=[ITEM_UOM_LOOKUP])
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, {f"{DB_NAME}:SEED": "x" * 64}, seen_at=None
    )
    before_hash_count = db.query(AcRowHash).count()
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/itemuombypage"):
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=_envelope([_item("SRT-10")]))

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )
    with pytest.raises(HttpSourceError) as exc:
        source.fetch_changes(Watermark())
    assert "/itemuombypage" in exc.value.message
    assert db.query(AcRowHash).count() == before_hash_count


# ── AC-10-06: an enrich-only change is a genuine `updated` ───────────────────


def test_enrich_only_price_change_reports_updated_count_one(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id, lookups=[ITEM_UOM_LOOKUP])
    calls: List[httpx.Request] = []

    def make_pages(price: float) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "/itembypage": [_envelope([_item("SRT-11"), _item("SRT-12")])],
            "/itemuombypage": [
                _envelope([
                    {"ItemCode": "SRT-11", "UOM": "UNIT", "Rate": 1.0, "Price": price},
                    {"ItemCode": "SRT-12", "UOM": "UNIT", "Rate": 1.0, "Price": 5.0},
                ])
            ],
        }

    from modules.autocount.models import RUN_MODE_RECONCILE

    first = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, mode=RUN_MODE_RECONCILE,
        transport=_transport(_multi_handler(make_pages(63.0), calls)),
    )
    result1 = first.fetch_changes(Watermark())
    assert result1.added_count == 2

    second = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, mode=RUN_MODE_RECONCILE,
        transport=_transport(_multi_handler(make_pages(70.0), calls)),
    )
    result2 = second.fetch_changes(Watermark())
    assert result2.added_count == 0
    assert result2.updated_count == 1, "ONLY the enriched Price changed for SRT-11"


# ── AC-10-60(a): a trimmed key view is used for the JOIN, never written back ─


def test_trim_used_for_join_key_but_never_written_back_onto_the_row(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id, lookups=[ITEM_UOM_LOOKUP])
    calls: List[httpx.Request] = []
    pages_by_path = {
        "/itembypage": [
            _envelope([{**_item("SRT-13"), "ItemCode": " SRT-13 ", "BaseUOM": " UNIT "}])
        ],
        "/itemuombypage": [
            _envelope([{"ItemCode": "SRT-13", "UOM": "UNIT", "Rate": 1.0, "Price": 77.0}])
        ],
    }
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_multi_handler(pages_by_path, calls)),
    )
    result = source.fetch_changes(Watermark())
    raw = result.records[0].raw
    assert raw.get("BaseUOMPrice") == 77.0, "the join must match despite the whitespace dirt"
    assert raw.get("ItemCode") == " SRT-13 ", "the trim is a LOOKUP KEY only - never written back"
    assert raw.get("BaseUOM") == " UNIT "


# KILL TEST (for the reviewer): remove the `casefold_trim` branch in the
# coder's join-key comparison (fall back to a plain `==`) -
# ``test_casefold_trim_matches_unit_vs_UNIT`` and
# ``test_trim_used_for_join_key_but_never_written_back_onto_the_row`` both
# flip red; ``test_exact_match_mode_is_case_sensitive`` stays green either
# way (it never exercises that branch), proving the two modes are genuinely
# distinct code paths, not one lenient comparison always applied.
