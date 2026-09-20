"""Sprint-5/10 S5a (AC-10-76/80, R11) - the coder's OWN test, pinning the
``combine`` field's round-trip contract through ``EtlService.update_task``
(the brief's explicit "own test for this" ask, mirrored on
``test_s10_s5a_key_fields_groupby.py``'s own fixtures).

Uses ``ENTITY_WAREHOUSE`` rather than ``ENTITY_PRODUCT``: the product HTTP
preset ships a PRE-FILLED ``ItemUOM`` lookup (``on[].local == "BaseUOM"``,
sprint-5/10 S1) that a minimal, made-up ``result_columns`` stub (as this
file's own fixtures use) would collide with on a second save - a documented
gotcha (see ``test_autocount_http_lifecycle.py``'s own comment on its
``BaseUOM``-inclusive stub). ``warehouse`` carries no preset lookups at all,
so it isolates the ``combine`` round-trip from that unrelated interaction.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_WAREHOUSE
from modules.autocount.models import AcCompany
from modules.autocount.services.etl_service import EtlService

COMBINE: Dict[str, Any] = {
    "computed": [],
    "require": [],
    "measure": "Code",
    "groupBy": ["Code"],
    "measures": [{"source": "Code", "op": "count", "alias": "n"}],
    "carry": [],
    "round": [],
    "drop": [],
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
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db2", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="MOCHA",
        company_name="Mocha", name="Mocha", is_active=True, sorento_company_code="MOCHA",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _raw(**overrides: Any) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "sourceImpl": "autocount_http",
        "connectionId": None,
        "path": "/warehousebypage",
        "keyFields": ["Code"],
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


def test_omitting_combine_key_keeps_the_previously_saved_combine(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    raw = _raw(connectionId=conn.id, keyFields=[], combine=COMBINE)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw)

    # A second save that never mentions "combine" at all (a client that
    # does not round-trip the field) must not silently wipe it - the SAME
    # contract `lookups` already has.
    raw_again = _raw(connectionId=conn.id, watermarkField="LastModified")
    assert "combine" not in raw_again
    view = EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw_again)

    assert view.source_config["combine"] == COMBINE
    assert view.source_config["keyFields"] == ["Code"]


def test_an_explicit_combine_replaces_the_previously_saved_one(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    raw = _raw(connectionId=conn.id, keyFields=[], combine=COMBINE)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw)

    other_combine = {**COMBINE, "groupBy": ["Name"], "measure": "Name",
                      "measures": [{"source": "Name", "op": "count", "alias": "n"}]}
    raw_again = _raw(connectionId=conn.id, keyFields=[], combine=other_combine)
    view = EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw_again)

    assert view.source_config["combine"] == other_combine
    assert view.source_config["keyFields"] == ["Name"]
