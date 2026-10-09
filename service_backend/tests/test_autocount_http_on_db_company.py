"""fix/autocount-add-http-only-entity-on-db-company.

`stock_balance` has no `sql_db` variant (sprint-5/10 S5b, AC-10-39/D4) - the
open REST API is its ONLY source, on any company kind. `EtlService.update_task`
already dispatches an explicit `sourceImpl: "autocount_http"` payload to
`_update_http_task` BEFORE a single line of the "DB company reads only its
own connection" rule runs (AC-08-13), so a DB company can already save one -
this pins that it keeps working (the frontend fix just started OFFERING it,
`app/(protected)/autocount/components/autocount-meta.test.ts`).

It also pins the gap this fix closed server-side: the SAME entity with
`sourceImpl` omitted used to fall through to the SQL branch and save a blank,
un-queryable `sql_db` draft row with NO error at all - the new guard in
`EtlService.update_task` (mirroring the pre-existing GRN one) now refuses it,
naming the entity, exactly like GRN already does for "not available on a
database company" (`tests/test_autocount_db_company.py`).
"""
from __future__ import annotations

from typing import Any, Dict

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
from modules.autocount.services.company_service import AutocountServiceError, CompanyService
from modules.autocount.services.etl_service import EtlService
from modules.autocount.sql_source import probe
from modules.autocount.sql_source.runtime import RUNTIME

try:
    from modules.autocount.models import SOURCE_IMPL_AUTOCOUNT_HTTP
except ImportError:  # pragma: no cover
    SOURCE_IMPL_AUTOCOUNT_HTTP = "autocount_http"

DB_NAME = "AED_2024"


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _clean_runtime():
    yield
    RUNTIME.dispose_all()


def _open_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Mocha REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db2", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    db.expunge(conn)
    return conn


def _sql_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sql_database", type="erp", name="AutoCount DB",
        config_json={"dbType": "postgresql", "database": DB_NAME},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    db.expunge(conn)
    return conn


def _db_company(db, monkeypatch):
    """A DB company born straight through the service (mirrors
    `test_autocount_db_company.py::_db_company`, without the route round-trip
    - this suite is about the TASK route, not company creation)."""
    sql_conn = _sql_connection(db)
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    RUNTIME.put_engine(sql_conn.id, engine)
    monkeypatch.setattr(probe, "CURRENT_DATABASE_SQL", {"postgresql": f"SELECT '{DB_NAME}'"})
    monkeypatch.setattr(probe, "PROFILE_NAME_SQL", {})
    return CompanyService(db).create_from_sql_connection(DEFAULT_TENANT_ID, sql_conn, name="Mocha")


def _http_raw(connection_id: str, **overrides) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "sourceImpl": SOURCE_IMPL_AUTOCOUNT_HTTP,
        "connectionId": connection_id,
        "path": "/itembatchbalqtybypage",
        "keyFields": ["ItemCode", "Location"],
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


def test_db_company_can_create_a_stock_balance_task_via_the_open_api(db, monkeypatch):
    """The already-working half (AC-08-13): explicit `sourceImpl:
    "autocount_http"` dispatches to `_update_http_task` on ANY company kind,
    so a DB company can save a `stock_balance` task against any open
    connection of the tenant (never its own locked SQL connection - there is
    nothing to lock it to)."""
    company = _db_company(db, monkeypatch)
    open_conn = _open_connection(db)

    view = EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, _http_raw(open_conn.id)
    )

    assert view.source_impl == SOURCE_IMPL_AUTOCOUNT_HTTP
    assert view.source_config["connectionId"] == open_conn.id


def test_db_company_stock_balance_via_sql_path_is_refused_naming_the_entity(db, monkeypatch):
    """The gap this fix closed: the SAME entity with `sourceImpl` omitted
    (the SQL/database path) has no `sql_db` variant at all (D4) - it must
    422 naming the entity, mirroring the pre-existing GRN guard, never
    silently save a blank, un-queryable draft row."""
    company = _db_company(db, monkeypatch)

    raw = _http_raw(company.connection_id)
    raw.pop("sourceImpl")
    raw.update(query="SELECT ItemCode FROM stock_balance", keyColumns=["ItemCode"])

    with pytest.raises(AutocountServiceError) as exc:
        EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, raw)
    assert ENTITY_STOCK_BALANCE in str(exc.value)

    from modules.autocount.repositories import EntityConfigRepository

    assert EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE) is None
