"""Sprint-5/10 S1 review round 2 (Opus reviewer) - two mandatory save-path
fixes on ``EtlService._validate_http_config``.

FIX 1 - AC-10-06 was still false on the REAL save path. The default
``comparedFields`` (operator left it blank) was computed from the RAW
``existing_result_columns`` only, so a previewed-then-saved task PERSISTS
an explicit list missing the alias; at run time that non-empty stored list
narrows the effective compared set back down and an enrich-only price
change reports ``updated_count == 0``. Round 1's own test missed this
because its fixture wrote ``comparedFields: []`` directly, never going
through a real save.

FIX 1b - the same family, one level deeper: once a default list is
PERSISTED, a client that round-trips it unchanged makes every LATER save
treat it as "explicit", so adding a lookup afterwards never gets its alias
into the compared set either - exactly the live shape of the plan-08
product tasks. Rule: if the incoming ``comparedFields`` equals what the
PREVIOUS default would have been (previous effective columns minus the
PREVIOUS key fields, order-insensitive), treat it as still "default" and
recompute fresh; a genuinely customised list (different from the previous
default) wins untouched, with `compared_columns_for`'s own
configured-intersect-available silently pruning a name no longer in the
effective set (the same behaviour an unknown configured column already
had - never a 422).

FIX 2 - the round-1b "pre-fix row" tolerance (``stored_raw_columns``) was
built from the INCOMING lookups, which let a BRAND-NEW lookup's own alias
strip itself out of the tolerance and reopen AC-10-01's save-time collision
check: a new lookup aliased the same as a genuine STORED raw column saved
clean. Fixed by building the tolerance from the task's EXISTING STORED
lookups only.
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT, ENTITY_WAREHOUSE
from modules.autocount.models import AcCompany, AcEntityConfig, RUN_MODE_RECONCILE, SOURCE_IMPL_AUTOCOUNT_HTTP
from modules.autocount.services.company_service import CompanyService
from modules.autocount.services.etl_service import EtlService, EtlValidationError
from modules.autocount.sources import SourceContext, Watermark

from modules.autocount.http_source.source import HttpApiSource

DB_NAME = "MOCHA"
BASE_URL = "https://hapi.sorento.cc.cd/api/db2"


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
        config_json={"baseUrl": BASE_URL, "auth": "none"}, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _multi_transport(pages_by_path: Dict[str, Any]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        match = next((p for p in pages_by_path if request.url.path.endswith(p)), None)
        if match is None:
            return httpx.Response(404, text=f"no fixture for {request.url.path}")
        return httpx.Response(200, json=pages_by_path[match])

    return httpx.Client(transport=httpx.MockTransport(handler))


def _transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _envelope(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"TotalCount": len(rows), "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": rows}


# ── FIX 1: AC-10-06 through a REAL preview -> save -> run ───────────────────


def _product_http_raw(**overrides: Any) -> Dict[str, Any]:
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


def test_default_compared_fields_persists_the_lookup_alias_on_a_real_save(db):
    conn = _open_connection(db)
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=DB_NAME,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    service = EtlService(db)

    # 1) First clean save - seeds the preset's ItemUOM lookup, but the task
    #    has never been previewed yet (no result_columns).
    service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _product_http_raw(connectionId=conn.id)
    )
    seeded = service.configs.get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    seeded_lookups = seeded.source_config["lookups"]
    assert seeded_lookups, "the preset's ItemUOM lookup must have seeded"

    # 2) Preview WITH the seeded lookup (what the editor's Test button
    #    would send) - stamps RAW-ONLY result_columns (review round 1b).
    main_row = {
        "ItemCode": "SRT-01", "Description": "WIDGET", "BaseUOM": "UNIT",
        "IsActive": "T", "LastModified": "2026-08-01T09:00:00",
    }
    transport = _multi_transport({
        "/itembypage": _envelope([main_row]),
        "/itemuombypage": _envelope([{"ItemCode": "SRT-01", "UOM": "UNIT", "Price": 10.0}]),
    })
    service.preview_http(
        DEFAULT_TENANT_ID, conn.id, "/itembypage", lookups=seeded_lookups,
        company_id=company.id, entity_type=ENTITY_PRODUCT, transport=transport,
    )

    # 3) Save again - comparedFields left at its DEFAULT (empty on the
    #    wire). The persisted default must include "BaseUOMPrice".
    saved = service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        _product_http_raw(connectionId=conn.id),
    )
    assert "BaseUOMPrice" in saved.source_config["comparedFields"], saved.source_config

    # 4) Prove it at RUN TIME too: a second run where ONLY the enriched
    #    Price changed must register as `updated`, using the SAVED config
    #    (never a hand-built one) - the actual bug.
    config = service.configs.get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    ctx = SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )

    def make_pages(price: float):
        return {
            "/itembypage": _envelope([main_row]),
            "/itemuombypage": _envelope(
                [{"ItemCode": "SRT-01", "UOM": "UNIT", "Price": price}]
            ),
        }

    first = HttpApiSource(
        ctx, entity_type=ENTITY_PRODUCT, mode=RUN_MODE_RECONCILE,
        transport=_multi_transport(make_pages(10.0)),
    )
    result1 = first.fetch_changes(Watermark())
    assert result1.added_count == 1

    second = HttpApiSource(
        ctx, entity_type=ENTITY_PRODUCT, mode=RUN_MODE_RECONCILE,
        transport=_multi_transport(make_pages(20.0)),
    )
    result2 = second.fetch_changes(Watermark())
    assert result2.added_count == 0
    assert result2.updated_count == 1, (
        "the SAVED comparedFields must include the alias, or an "
        "enrich-only price change is invisible at run time"
    )


# ── FIX 1b: "was the incoming comparedFields still the old default?" ────────


def _wh_http_raw(**overrides: Any) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "sourceImpl": SOURCE_IMPL_AUTOCOUNT_HTTP,
        "connectionId": None,
        "path": "/location",
        "keyFields": ["Location"],
        "watermarkField": None,
        "comparedFields": [],
        "distinctOf": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileHours": None,
        "reconcileAt": "02:00",
    }
    raw.update(overrides)
    return raw


SUPPLIER_LOOKUP = {
    "path": "/creditorbypage", "as": "supplier",
    "on": [{"local": "Location", "remote": "Location"}],
    "fields": [{"remote": "Name", "as": "SupplierName"}],
}

_WH_MAIN_PAGE = _envelope(
    [{"Location": "MAIN", "Description": "Main Store", "IsActive": "T"}]
)
_WH_LOOKUP_PAGE = _envelope([{"Location": "MAIN", "Name": "Acme Supplies"}])


@pytest.fixture
def wh_rig(db):
    conn = _open_connection(db)
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=DB_NAME,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    service = EtlService(db)
    # Establish the task with NO lookup and a genuine PREVIEW, so
    # result_columns is stamped raw = ["Location", "Description", "IsActive"].
    service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, _wh_http_raw(connectionId=conn.id)
    )
    service.preview_http(
        DEFAULT_TENANT_ID, conn.id, "/location",
        company_id=company.id, entity_type=ENTITY_WAREHOUSE,
        transport=_multi_transport({"/location": _WH_MAIN_PAGE}),
    )
    return service, company, conn


def test_fix1b_default_list_recomputes_when_a_lookup_is_added(wh_rig):
    """(a) The client round-trips the OLD persisted DEFAULT unchanged
    (["Description"], no lookup existed yet) alongside a brand-new lookup -
    the save must recognise "still default" and recompute against the NEW
    effective columns, picking up the alias."""
    service, company, conn = wh_rig

    # First save (still no lookup): default comparedFields bakes to
    # ["Description"] (raw minus the "Location" key).
    saved1 = service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, _wh_http_raw(connectionId=conn.id)
    )
    previous_default = set(saved1.source_config["comparedFields"])
    assert previous_default == {"Description", "IsActive"}, previous_default

    # Preview WITH the new lookup - stamps raw-only again (unchanged raw
    # columns; the alias is never stored).
    service.preview_http(
        DEFAULT_TENANT_ID, conn.id, "/location", lookups=[SUPPLIER_LOOKUP],
        company_id=company.id, entity_type=ENTITY_WAREHOUSE,
        transport=_multi_transport({"/location": _WH_MAIN_PAGE, "/creditorbypage": _WH_LOOKUP_PAGE}),
    )

    # Save WITH the lookup, round-tripping the OLD default list unchanged.
    saved2 = service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE,
        _wh_http_raw(connectionId=conn.id, lookups=[SUPPLIER_LOOKUP], comparedFields=sorted(previous_default)),
    )
    assert set(saved2.source_config["comparedFields"]) == {"Description", "IsActive", "SupplierName"}, (
        saved2.source_config["comparedFields"]
    )


def test_fix1b_customised_list_is_never_auto_extended_with_a_new_alias(wh_rig):
    """(b) An EXPLICITLY customised list (a strict subset of the default)
    must NOT gain the new alias automatically when a lookup is added and
    the same customisation is round-tripped."""
    service, company, conn = wh_rig

    # Customise comparedFields to just ["Description"] - NOT equal to the
    # default {"Description", "IsActive"}.
    service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE,
        _wh_http_raw(connectionId=conn.id, comparedFields=["Description"]),
    )

    service.preview_http(
        DEFAULT_TENANT_ID, conn.id, "/location", lookups=[SUPPLIER_LOOKUP],
        company_id=company.id, entity_type=ENTITY_WAREHOUSE,
        transport=_multi_transport({"/location": _WH_MAIN_PAGE, "/creditorbypage": _WH_LOOKUP_PAGE}),
    )

    saved = service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE,
        _wh_http_raw(connectionId=conn.id, lookups=[SUPPLIER_LOOKUP], comparedFields=["Description"]),
    )
    assert saved.source_config["comparedFields"] == ["Description"], (
        "an explicit customisation must never be silently widened"
    )


def test_fix1b_removing_the_lookup_drops_the_alias_from_a_default_list(wh_rig):
    """(c) The mirror of (a): a DEFAULT list (baked WITH the alias) that is
    round-tripped unchanged when the lookup is REMOVED must drop the
    alias, recomputed fresh against the columns that remain."""
    service, company, conn = wh_rig

    service.preview_http(
        DEFAULT_TENANT_ID, conn.id, "/location", lookups=[SUPPLIER_LOOKUP],
        company_id=company.id, entity_type=ENTITY_WAREHOUSE,
        transport=_multi_transport({"/location": _WH_MAIN_PAGE, "/creditorbypage": _WH_LOOKUP_PAGE}),
    )
    saved_with_lookup = service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE,
        _wh_http_raw(connectionId=conn.id, lookups=[SUPPLIER_LOOKUP]),
    )
    default_with_alias = set(saved_with_lookup.source_config["comparedFields"])
    assert default_with_alias == {"Description", "IsActive", "SupplierName"}, default_with_alias

    # Remove the lookup, round-tripping the OLD (alias-carrying) default.
    saved_after_removal = service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE,
        _wh_http_raw(connectionId=conn.id, lookups=[], comparedFields=sorted(default_with_alias)),
    )
    assert set(saved_after_removal.source_config["comparedFields"]) == {"Description", "IsActive"}, (
        saved_after_removal.source_config["comparedFields"]
    )


def test_fix1b_removing_the_lookup_prunes_a_customised_lists_dead_alias_only(wh_rig):
    """(d) A CUSTOMISED list (different from the default, but includes the
    alias) survives the lookup's removal except for the now-dead alias
    being pruned - consistent with how an unknown configured column has
    always been silently dropped."""
    service, company, conn = wh_rig

    service.preview_http(
        DEFAULT_TENANT_ID, conn.id, "/location", lookups=[SUPPLIER_LOOKUP],
        company_id=company.id, entity_type=ENTITY_WAREHOUSE,
        transport=_multi_transport({"/location": _WH_MAIN_PAGE, "/creditorbypage": _WH_LOOKUP_PAGE}),
    )
    # Customised: ["Description", "SupplierName"] - deliberately NOT the
    # full default ({"Description", "IsActive", "SupplierName"}, missing
    # "IsActive").
    service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE,
        _wh_http_raw(
            connectionId=conn.id, lookups=[SUPPLIER_LOOKUP],
            comparedFields=["Description", "SupplierName"],
        ),
    )

    saved = service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE,
        _wh_http_raw(connectionId=conn.id, lookups=[], comparedFields=["Description", "SupplierName"]),
    )
    assert saved.source_config["comparedFields"] == ["Description"], (
        "the dead alias must be pruned; 'IsActive' must NOT appear (never "
        "picked) and the customisation must not be treated as default"
    )


# ── FIX 2: the pre-fix-row tolerance must use EXISTING lookups only ─────────


def test_fix2_a_new_lookup_aliased_the_same_as_a_real_stored_column_422s(db):
    conn = _open_connection(db)
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=DB_NAME,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    service = EtlService(db)

    # Establish the task with NO lookups and a genuine preview, so
    # result_columns genuinely (not tolerantly) contains "Description".
    service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, _wh_http_raw(connectionId=conn.id)
    )
    service.preview_http(
        DEFAULT_TENANT_ID, conn.id, "/location",
        company_id=company.id, entity_type=ENTITY_WAREHOUSE,
        transport=_multi_transport({"/location": _WH_MAIN_PAGE}),
    )

    poisoned_lookup = {
        "path": "/creditorbypage", "as": "poison",
        "on": [{"local": "Location", "remote": "Location"}],
        "fields": [{"remote": "Name", "as": "Description"}],
    }
    with pytest.raises(EtlValidationError) as exc:
        service.update_task(
            DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE,
            _wh_http_raw(connectionId=conn.id, lookups=[poisoned_lookup]),
        )
    assert "lookups[0].fields[0].as" in exc.value.field_errors, exc.value.field_errors


def test_fix2_pre_fix_row_tolerance_for_an_unchanged_lookup_still_works(db):
    """Control (must stay green): a task whose STORED lookup's own alias
    reappears in a pre-round-1b-style stale `result_columns` (simulated by
    writing the row directly, bypassing preview) must still save cleanly
    on an ordinary re-save - the tolerance is keyed on EXISTING lookups,
    and here the lookup is unchanged (existing == incoming)."""
    conn = _open_connection(db)
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=DB_NAME,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    service = EtlService(db)

    lookup = {
        "path": "/creditorbypage", "as": "supplier",
        "on": [{"local": "Location", "remote": "Location"}],
        "fields": [{"remote": "Name", "as": "SupplierName"}],
    }
    service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE,
        _wh_http_raw(connectionId=conn.id, lookups=[lookup]),
    )
    config = service.configs.get(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE)
    # Simulate a PRE-round-1b stale row: the old preview merged the alias
    # straight into result_columns.
    config.result_columns = ["Location", "Description", "SupplierName"]
    db.commit()

    saved = service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE,
        _wh_http_raw(connectionId=conn.id, lookups=[lookup]),
    )
    assert saved.source_config["lookups"] == [lookup]
