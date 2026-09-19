"""Sprint-5/10 S1 review round 1b - the blocker-2(iii) carve-out from round
1 (``lookups.py``'s ``previously_saved_lookups``/preset-registry exemption)
still 422s the flow it exists to serve (R9's whole point - operator-authored
GENERAL lookups): a BRAND-NEW lookup, previewed once (which stamps its own
alias into ``result_columns``, AC-10-05), then SAVED for the first time.

Flow that breaks: operator adds a lookup with a fresh alias (``SupplierName``,
unrelated to any preset and never saved before) -> Tests it (the SAME
``/autocount/http/preview`` call the editor's Test button makes, WITH the
task's ``companyId``/``entityType`` so the stamp lands, exactly per AC-10-05)
-> Saves. At save, ``SupplierName`` is now in the task's stamped
``result_columns`` (the preview just put it there), it was never PREVIOUSLY
saved, and it is not a REGISTERED preset's own alias - the round-1 carve-out
has no way to explain it, so the save 422s "already a source column" on the
alias the operator just legitimately added.

Round 1's own pinned test (``test_s10_review1_alias_collision.py::
test_save_time_still_exempts_a_previously_saved_lookups_own_alias``) only
covers the RE-save of an ALREADY-saved lookup - never the FIRST save of a
brand-new one, which is this file's whole point.
"""
from __future__ import annotations

from typing import Any, Dict

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_WAREHOUSE
from modules.autocount.models import AcCompany, SOURCE_IMPL_AUTOCOUNT_HTTP
from modules.autocount.services.etl_service import EtlService, EtlValidationError

DB_NAME = "MOCHA"
BASE_URL = "https://hapi.sorento.cc.cd/api/db2"

SUPPLIER_LOOKUP = {
    "path": "/creditorbypage", "as": "supplier",
    "on": [{"local": "Location", "remote": "Location"}],
    "fields": [{"remote": "Name", "as": "SupplierName"}],
}
SECOND_LOOKUP = {
    "path": "/itemgroup", "as": "grouping",
    "on": [{"local": "Location", "remote": "Location"}],
    "fields": [{"remote": "Description", "as": "GroupLabel"}],
}


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


def _open_company(db, conn) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=DB_NAME,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _http_raw(**overrides: Any) -> Dict[str, Any]:
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


def _multi_transport(pages_by_path: Dict[str, Dict[str, Any]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        match = next((p for p in pages_by_path if request.url.path.endswith(p)), None)
        if match is None:
            return httpx.Response(404, text=f"no fixture for {request.url.path}")
        return httpx.Response(200, json=pages_by_path[match])

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_brand_new_lookup_previewed_then_saved_succeeds(db):
    conn = _open_connection(db)
    company = _open_company(db, conn)
    service = EtlService(db)

    # 1) Establish the task with NO lookups yet (the operator's task exists,
    #    ordinary base config - warehouse carries no preset lookups at all,
    #    so nothing pre-seeds one).
    service.update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, _http_raw(connectionId=conn.id))

    # 2) The operator adds SUPPLIER_LOOKUP in the editor and clicks Test -
    #    the SAME /autocount/http/preview call, WITH companyId/entityType so
    #    the stamp lands (AC-10-05) - this is what puts "SupplierName" into
    #    the task's stamped result_columns.
    transport = _multi_transport({
        "/location": {
            "TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1,
            "Data": [{"Location": "MAIN", "Description": "Main Store"}],
        },
        "/creditorbypage": {
            "TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1,
            "Data": [{"Location": "MAIN", "Name": "Acme Supplies"}],
        },
    })
    result, task_view = service.preview_http(
        DEFAULT_TENANT_ID, conn.id, "/location", lookups=[SUPPLIER_LOOKUP],
        company_id=company.id, entity_type=ENTITY_WAREHOUSE, transport=transport,
    )
    assert "SupplierName" in result.columns, result.columns
    assert task_view is not None
    assert "SupplierName" in task_view.result_columns, task_view.result_columns

    # 3) The operator saves - this is the flow blocker 2(iii) exists to
    #    serve (R9: general, operator-authored lookups) and must succeed.
    saved = service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE,
        _http_raw(connectionId=conn.id, lookups=[SUPPLIER_LOOKUP]),
    )
    assert saved.source_config.get("lookups") == [SUPPLIER_LOOKUP]


def test_a_second_brand_new_lookup_previewed_then_saved_also_succeeds(db):
    """The mirror case: after the FIRST new lookup is saved, a SECOND
    brand-new lookup (previewed with the task, stamping ITS OWN alias too)
    must also save cleanly - not just the very first one."""
    conn = _open_connection(db)
    company = _open_company(db, conn)
    service = EtlService(db)

    service.update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, _http_raw(connectionId=conn.id))

    transport1 = _multi_transport({
        "/location": {
            "TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1,
            "Data": [{"Location": "MAIN", "Description": "Main Store"}],
        },
        "/creditorbypage": {
            "TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1,
            "Data": [{"Location": "MAIN", "Name": "Acme Supplies"}],
        },
    })
    service.preview_http(
        DEFAULT_TENANT_ID, conn.id, "/location", lookups=[SUPPLIER_LOOKUP],
        company_id=company.id, entity_type=ENTITY_WAREHOUSE, transport=transport1,
    )
    service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE,
        _http_raw(connectionId=conn.id, lookups=[SUPPLIER_LOOKUP]),
    )

    # Now add a SECOND, also brand-new lookup alongside the first.
    both_lookups = [SUPPLIER_LOOKUP, SECOND_LOOKUP]
    transport2 = _multi_transport({
        "/location": {
            "TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1,
            "Data": [{"Location": "MAIN", "Description": "Main Store"}],
        },
        "/creditorbypage": {
            "TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1,
            "Data": [{"Location": "MAIN", "Name": "Acme Supplies"}],
        },
        "/itemgroup": {
            "TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1,
            "Data": [{"Location": "MAIN", "Description": "Grouping label"}],
        },
    })
    result, task_view = service.preview_http(
        DEFAULT_TENANT_ID, conn.id, "/location", lookups=both_lookups,
        company_id=company.id, entity_type=ENTITY_WAREHOUSE, transport=transport2,
    )
    assert "GroupLabel" in result.columns, result.columns

    saved = service.update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE,
        _http_raw(connectionId=conn.id, lookups=both_lookups),
    )
    assert saved.source_config.get("lookups") == both_lookups
