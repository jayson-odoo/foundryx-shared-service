"""Sprint-5/10 S1 review round 1 (Opus reviewer) - BLOCKER 3: AC-10-06 was
false on a real task. ``compared_columns_for`` drops any column absent from
the stamped ``result_columns``; when the last preview ran WITHOUT lookups
(or before a lookup was added), ``BaseUOMPrice`` is not in the compared set
and an enrich-only price change silently reports ``updated_count == 0``.
The pre-existing test (``test_s10_http_lookups.py::
test_enrich_only_price_change_reports_updated_count_one_then_0_0_0``) passed
only because ``result_columns`` was empty there, hitting the NULL/empty
fallback branch by accident.

Fix: union every configured lookup alias (``fields[].as``) into the
comparable-column baseline before ``compared_columns_for`` runs - key
fields still excluded, and an operator's EXPLICIT ``comparedFields`` still
wins (unaffected, since it only ever NARROWS).

This file adds a case with ``result_columns`` stamped WITHOUT the alias -
the pre-existing test (``result_columns`` empty) is UNTOUCHED.
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig, RUN_MODE_RECONCILE
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark

from modules.autocount.http_source.source import HttpApiSource

DB_NAME = "MOCHA"
BASE_URL = "https://hapi.sorento.cc.cd/api/db2"

ITEM_UOM_LOOKUP = {
    "path": "/itemuombypage", "as": "uom",
    "on": [
        {"local": "ItemCode", "remote": "ItemCode"},
        {"local": "BaseUOM", "remote": "UOM", "match": "casefold_trim"},
    ],
    "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
}


@pytest.fixture
def rig(session_factory):
    db = session_factory()
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Mocha REST",
        config_json={"baseUrl": BASE_URL, "auth": "none"}, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=DB_NAME,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    yield db, company, conn
    db.close()


def _config(db, company, connection_id: str, *, result_columns: List[str]) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http",
        # STAMPED WITHOUT `BaseUOMPrice` - as if the last preview ran before
        # the lookup existed, or without lookups at all (this is the exact
        # gap blocker 3 closes: NEVER empty, so the old NULL fallback never
        # rescues it).
        result_columns=result_columns,
        source_config={
            "connectionId": connection_id, "path": "/itembypage", "keyFields": ["ItemCode"],
            "watermarkField": "LastModified", "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": [ITEM_UOM_LOOKUP],
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _envelope(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"TotalCount": len(rows), "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": rows}


def _item(code: str) -> Dict[str, Any]:
    return {"ItemCode": code, "Description": code, "BaseUOM": "UNIT",
            "LastModified": "2026-08-01T09:00:00", "IsActive": "T"}


def test_enrich_only_price_change_registers_as_updated_when_result_columns_predates_the_alias(rig):
    """AC-10-06, re-pinned: `result_columns` stamped WITHOUT `BaseUOMPrice`
    (a REAL, non-empty preview that simply predates the lookup) must not
    blind change detection to an enrich-only price change."""
    db, company, conn = rig
    # Exactly what a real `/itembypage`-only preview (no lookups run yet)
    # would have stamped - non-empty, deliberately missing the alias.
    stamped_columns = ["ItemCode", "Description", "BaseUOM", "IsActive", "LastModified"]
    config = _config(db, company, conn.id, result_columns=stamped_columns)

    def make_pages(price: float) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "/itembypage": [_envelope([_item("SRT-20")])],
            "/itemuombypage": [_envelope([{"ItemCode": "SRT-20", "UOM": "UNIT", "Rate": 1.0, "Price": price}])],
        }

    def handler_for(pages):
        def handler(request: httpx.Request) -> httpx.Response:
            path = next(p for p in pages if request.url.path.endswith(p))
            return httpx.Response(200, json=pages[path][0])
        return handler

    ctx = SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )
    first = HttpApiSource(
        ctx, entity_type=ENTITY_PRODUCT, mode=RUN_MODE_RECONCILE,
        transport=_transport(handler_for(make_pages(10.0))),
    )
    result1 = first.fetch_changes(Watermark())
    assert result1.added_count == 1

    second = HttpApiSource(
        ctx, entity_type=ENTITY_PRODUCT, mode=RUN_MODE_RECONCILE,
        transport=_transport(handler_for(make_pages(20.0))),
    )
    result2 = second.fetch_changes(Watermark())
    assert result2.added_count == 0
    assert result2.updated_count == 1, (
        "ONLY the enriched Price changed - `BaseUOMPrice` must be in the "
        "compared set even though `result_columns` never carried it"
    )


def test_compared_columns_includes_the_lookup_alias_when_stamped_without_it(rig):
    """The unit-level pin: `HttpApiSource.compared_columns` itself contains
    the alias even when `result_columns` was stamped without it."""
    db, company, conn = rig
    config = _config(
        db, company, conn.id,
        result_columns=["ItemCode", "Description", "BaseUOM", "IsActive", "LastModified"],
    )
    ctx = SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )
    source = HttpApiSource(ctx, entity_type=ENTITY_PRODUCT, transport=_transport(lambda r: httpx.Response(200, json=_envelope([]))))
    assert "BaseUOMPrice" in source.compared_columns


def test_operator_explicit_compared_fields_still_wins_and_excludes_the_alias(rig):
    """An operator's EXPLICIT `comparedFields` (narrower than "everything")
    must still be respected - blocker 3's union only ever WIDENS the
    baseline `compared_columns_for` narrows FROM, never forces the alias
    in when the operator deliberately left it out."""
    db, company, conn = rig
    config = _config(
        db, company, conn.id,
        result_columns=["ItemCode", "Description", "BaseUOM", "IsActive", "LastModified"],
    )
    config.source_config = {**config.source_config, "comparedFields": ["Description"]}
    db.commit()
    db.refresh(config)
    ctx = SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )
    source = HttpApiSource(ctx, entity_type=ENTITY_PRODUCT, transport=_transport(lambda r: httpx.Response(200, json=_envelope([]))))
    assert source.compared_columns == ["Description"]
    assert "BaseUOMPrice" not in source.compared_columns
