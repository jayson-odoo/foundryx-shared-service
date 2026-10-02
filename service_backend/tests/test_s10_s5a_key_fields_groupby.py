"""Sprint-5/10 S5a - AC-10-80 (R11): "Output key and the push path" - when a
task carries a ``combine`` step its KEY FIELDS are DERIVED from
``combine.groupBy``, never separately typed, and changing the group-by on
an ACTIVE task demotes it to draft (mirroring AC-08-28's existing
config-change-demotes-to-draft rule, extended here to combine).

RED before the coder: ``EtlService._validate_http_config`` today has no
``combine`` branch at all - a raw payload's ``combine`` key is silently
DROPPED (never copied into ``clean``, exactly like any other unknown key
per that method's own "a stray key is simply not copied, never a 422"
contract) and ``keyFields`` is taken LITERALLY from the client
unconditionally. So every test below fails on a plain, real assertion
(the saved ``source_config`` has no ``combine`` key / ``keyFields`` is
whatever the client sent, not the groupBy), never an ImportError.

ASSUMED wiring (the AC states the OUTCOME - "key fields are the groupBy
columns... the Source tab's key picker becomes read-only chips" - not the
internal mechanics; this file only pins the OBSERVABLE save-time contract,
robust to whatever internal shape the coder picks):

* ``raw["combine"]`` round-trips through ``EtlService.update_task`` the SAME
  way ``raw["lookups"]`` already does: omitted (``None``) keeps whatever is
  currently stored; an explicit dict (including ``{}``) replaces it.
* When the clean, validated ``combine`` carries a non-empty ``groupBy``, the
  SAVED ``source_config["keyFields"]`` equals ``combine["groupBy"]``
  EXACTLY - the client's own ``keyFields`` (even a non-empty, plausible-
  looking one) is ignored/overridden, and the "choose at least one key
  field" / "not in the last preview" rules do not apply to it (a combine
  groupBy column is typically a COMPUTED alias that can never appear in
  ``result_columns``).
* A ``combine`` that fails ``validate_combine`` surfaces through
  ``EtlService.update_task`` as an ``EtlValidationError`` whose
  ``field_errors`` carries the SAME ``combine.<part>[i].<field>`` keys
  ``validate_combine`` itself would have produced.
* Saving a NEW ``combine`` whose ``groupBy`` differs from the currently
  ACTIVE task's demotes it to ``draft`` (``ETL_STATUS_DRAFT``) - the
  existing AC-08-28 identity-change rule, extended to combine's own
  identity-bearing field.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    ETL_STATUS_DRAFT,
    SOURCE_IMPL_AUTOCOUNT_HTTP,
    AcCompany,
)
from modules.autocount.services.etl_service import EtlService, EtlValidationError

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


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
        company_name="Mocha", name="Mocha", is_active=True,
        sorento_company_code="MOCHA",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _combine(group_by=("item_code", "location_code")) -> Dict[str, Any]:
    computed = [
        {"alias": "item_code", "formula": "trim(ItemCode)"},
        {"alias": "location_code", "formula": "trim(Location)"},
    ]
    return {
        "computed": [c for c in computed if c["alias"] in group_by],
        "require": [],
        "measure": group_by[0],
        "groupBy": list(group_by),
        "measures": [{"source": group_by[0], "op": "count", "alias": "n"}],
        "carry": [],
        "round": [],
        "drop": [],
    }


def _http_raw(**overrides: Any) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "sourceImpl": SOURCE_IMPL_AUTOCOUNT_HTTP,
        "connectionId": None,
        "path": "/itembatchbalqtybypage",
        "keyFields": ["ItemCode"],  # deliberately WRONG when combine is set
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


def _stamp_previewed(db, company_id: str) -> None:
    from modules.autocount.repositories import EntityConfigRepository

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company_id, ENTITY_PRODUCT)
    config.last_preview_at = NOW
    # sprint-5/10 S5a follow-up (fixture defect, coordinator ruling) -
    # ENTITY_PRODUCT auto-seeds the PRODUCT_HTTP_PRESET's own ItemUOM lookup
    # (``on[].local == "BaseUOM"``), so a re-save must find "BaseUOM" among
    # the previously-stamped result columns or it 422s on
    # ``lookups[0].on[1].local`` before this test's own combine assertion
    # ever runs - the SAME gotcha ``test_autocount_http_lifecycle.py``'s own
    # ``_stamp_previewed`` documents and stamps for.
    config.result_columns = ["ItemCode", "UOM", "Location", "BalQty", "BaseUOM"]
    db.commit()


# ── AC-10-80: key fields are DERIVED from groupBy, never separately typed ──


def test_saving_a_combine_task_derives_key_fields_from_group_by(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    raw = _http_raw(connectionId=conn.id, keyFields=[], combine=_combine())
    view = EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, raw)
    assert view.source_config["keyFields"] == ["item_code", "location_code"], view.source_config


def test_an_explicit_wrong_key_fields_is_overridden_by_group_by(db):
    """The Source tab's key picker becomes READ-ONLY chips - even a
    plausible-looking client-submitted ``keyFields`` must be ignored in
    favour of the derived value."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    raw = _http_raw(
        connectionId=conn.id, keyFields=["ItemCode", "Location"], combine=_combine()
    )
    view = EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, raw)
    assert view.source_config["keyFields"] == ["item_code", "location_code"], view.source_config


def test_invalid_combine_surfaces_as_a_named_422(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    bad_combine = _combine()
    bad_combine["groupBy"] = []  # AC-10-76: empty groupBy is invalid
    raw = _http_raw(connectionId=conn.id, keyFields=[], combine=bad_combine)
    with pytest.raises(EtlValidationError) as exc_info:
        EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, raw)
    assert "combine.groupBy" in exc_info.value.field_errors, exc_info.value.field_errors


# ── AC-10-80: changing group-by on an ACTIVE task demotes it to draft ──────


def test_changing_group_by_on_an_active_task_demotes_it_to_draft(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    raw = _http_raw(connectionId=conn.id, keyFields=[], combine=_combine(("item_code",)))
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, raw)
    _stamp_previewed(db, company.id)
    view = EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert view.etl_status == ETL_STATUS_ACTIVE

    raw2 = _http_raw(
        connectionId=conn.id, keyFields=[],
        combine=_combine(("item_code", "location_code")),
    )
    updated = EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, raw2)
    assert updated.etl_status == ETL_STATUS_DRAFT, (
        "changing combine.groupBy changes the task's identity (AC-10-80) - "
        "it must demote an ACTIVE task to draft, mirroring AC-08-28"
    )
    assert updated.source_config["keyFields"] == ["item_code", "location_code"]


def test_saving_the_same_group_by_again_does_not_demote_an_active_task(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    raw = _http_raw(connectionId=conn.id, keyFields=[], combine=_combine(("item_code",)))
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, raw)
    _stamp_previewed(db, company.id)
    EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)

    raw_again = _http_raw(
        connectionId=conn.id, keyFields=[], combine=_combine(("item_code",))
    )
    updated = EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, raw_again)
    assert updated.etl_status == ETL_STATUS_ACTIVE
