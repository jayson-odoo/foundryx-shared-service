"""Sprint-5/10 S5a - the combine step's own reduce hook inside
``HttpApiSource.fetch_changes`` (plan Files section: "http_source/source.py
(ordered lookup + reduce hooks in fetch_changes, no other behaviour
change)"). Pinned at the HIGHEST STABLE SEAM the plan gives for this
(``FetchResult`` itself), mirroring ``test_s10_http_lookups.py``'s own
philosophy exactly: no invented private ``combine.py`` runtime-primitive
signature is exercised through the source (that is
``test_s10_s5a_combine_apply.py``'s job) - only the observable seam a
caller of ``fetch_changes`` actually sees.

RED before the coder, for TWO different reasons pinned per test:

* the CONTROL test (no ``combine`` configured) already passes today - it is
  the byte-identical-output guarantee the plan promises, not a new
  behaviour; kept here as a regression trip-wire, not a red test.
* every other test expects ``HttpApiSource`` to actually REDUCE rows and to
  populate a new ``FetchResult`` field - ``HttpApiSource.__init__`` today
  reads a fixed key set from ``source_config`` and silently ignores an
  unknown ``combine`` key entirely, so these fail on a plain, real
  assertion (the row count never shrinks, the new field is never set),
  never an ImportError - the same "missing feature" RED reason
  ``test_s10_http_lookups.py`` documents for lookups.

ASSUMED addition to ``sources.FetchResult`` (mirroring the EXISTING
``lookup_verification: Dict[str, LookupVerification]`` field, added for the
analogous "generic per-run metadata a pull snapshot build needs" purpose):

    combine_metadata: Optional[Dict[str, Any]] = None

``None`` when the task carries no ``combine`` step (every existing/control
call site, byte-identical); AC-10-81's own generic shape
(``{excludedRows, excludedCount, dropped, roundedCount}``) when it does.

Reduce-hook ORDER (plan section 2.3 / Files list: "lookups first, then
combine"): ``HttpApiSource._apply_lookups`` merges aliases onto every row,
THEN the combine step reduces the (now-enriched) row set, both strictly
BEFORE ``_dedupe``/hashing/mapping (AC-10-80: "De-duplication, source_ref
minting and row_hash all run on the COMBINED rows").
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark

from modules.autocount.http_source.source import HttpApiSource

DB_NAME = "MOCHA"
BASE_URL = "https://hapi.sorento.cc.cd/api/db2"

SIMPLE_COMBINE: Dict[str, Any] = {
    "computed": [],
    "require": [],
    "measure": "v",
    "groupBy": ["g"],
    "measures": [{"source": "v", "op": "sum", "alias": "total"}],
    "carry": [],
    "round": [],
    "drop": [],
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
    db, company, *, entity_type=ENTITY_PRODUCT, connection_id: str, path="/rows",
    key_fields=("g",), watermark_field: Optional[str] = None,
    lookups=None, combine=None,
) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
        source_impl="autocount_http",
        source_config={
            "connectionId": connection_id,
            "path": path,
            "keyFields": list(key_fields),
            "watermarkField": watermark_field,
            "comparedFields": [],
            "distinctOf": None,
            "incrementalMinutes": 15,
            "reconcileMode": "dailyAt",
            "reconcileAt": "02:00",
            "lookups": lookups or [],
            "combine": combine,
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


def _envelope(rows: List[Dict[str, Any]], *, page: int = 1, total_pages: int = 1) -> Dict[str, Any]:
    return {
        "TotalCount": len(rows), "Page": page, "PageSize": 1000,
        "TotalPages": total_pages, "Data": rows,
    }


def _multi_handler(pages_by_path: Dict[str, List[Dict[str, Any]]]):
    def handler(request: httpx.Request) -> httpx.Response:
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


# ── control: no combine configured -> output is byte-identical ─────────────


def test_no_combine_leaves_fetch_changes_output_unchanged(rig):
    db, company, conn = rig
    config = _config(
        db, company, connection_id=conn.id, path="/itembypage",
        key_fields=("ItemCode",), combine=None,
    )
    pages_by_path = {"/itembypage": [_envelope([{"ItemCode": "A1"}, {"ItemCode": "A2"}])]}
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_multi_handler(pages_by_path)),
    )
    result = source.fetch_changes(Watermark())
    assert len(result.records) == 2
    assert {r.raw["ItemCode"] for r in result.records} == {"A1", "A2"}
    assert result.combine_metadata is None


# ── combine configured, no lookups ──────────────────────────────────────────


def test_combine_reduces_rows_at_the_fetch_changes_seam(rig):
    db, company, conn = rig
    config = _config(
        db, company, connection_id=conn.id, path="/rows",
        key_fields=("g",), combine=SIMPLE_COMBINE,
    )
    pages_by_path = {
        "/rows": [_envelope([
            {"g": "A", "v": 3}, {"g": "A", "v": 5}, {"g": "B", "v": 2},
        ])],
    }
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_multi_handler(pages_by_path)),
    )
    result = source.fetch_changes(Watermark())
    by_group = {r.raw["g"]: r.raw for r in result.records}
    assert set(by_group) == {"A", "B"}
    assert by_group["A"]["total"] == 8
    assert by_group["B"]["total"] == 2


def test_combine_metadata_carries_the_generic_shape(rig):
    db, company, conn = rig
    combine = {
        **SIMPLE_COMBINE,
        "drop": [{"name": "small", "formula": "total < 3"}],
    }
    config = _config(
        db, company, connection_id=conn.id, path="/rows",
        key_fields=("g",), combine=combine,
    )
    pages_by_path = {
        "/rows": [_envelope([{"g": "A", "v": 1}, {"g": "B", "v": 9}])],
    }
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_multi_handler(pages_by_path)),
    )
    result = source.fetch_changes(Watermark())
    assert result.combine_metadata is not None
    assert set(result.combine_metadata.keys()) == {
        "excludedRows", "excludedCount", "dropped", "roundedCount"
    }
    assert result.combine_metadata["dropped"]["small"]["count"] == 1
    assert {r.raw["g"] for r in result.records} == {"B"}


# ── reduce hook order: lookups first, then combine (plan section 2.3) ──────


def test_combine_runs_after_lookups_and_may_reference_a_lookup_alias(rig):
    db, company, conn = rig
    lookup = {
        "path": "/itembypage", "as": "item",
        "on": [{"local": "ItemCode", "remote": "ItemCode"}],
        "fields": [{"remote": "BaseUOM", "as": "ItemBaseUOM"}],
    }
    combine = {
        "computed": [
            {"alias": "priced", "formula": "if(ItemBaseUOM == \"UNIT\", 1, 0)"},
        ],
        "require": [],
        "measure": "priced",
        "groupBy": ["ItemCode"],
        "measures": [{"source": "priced", "op": "sum", "alias": "priced_total"}],
        "carry": [],
        "round": [],
        "drop": [],
    }
    config = _config(
        db, company, connection_id=conn.id, path="/itembatchbalqtybypage",
        key_fields=("ItemCode",), lookups=[lookup], combine=combine,
    )
    pages_by_path = {
        "/itembatchbalqtybypage": [_envelope([{"ItemCode": "SRT-01", "Location": "MAIN"}])],
        "/itembypage": [_envelope([{"ItemCode": "SRT-01", "BaseUOM": "UNIT"}])],
    }
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_multi_handler(pages_by_path)),
    )
    result = source.fetch_changes(Watermark())
    assert len(result.records) == 1
    assert result.records[0].raw["priced_total"] == 1, (
        "combine's computed column must see the lookup-merged 'ItemBaseUOM' "
        "alias - the reduce hook runs AFTER lookups, not before"
    )
