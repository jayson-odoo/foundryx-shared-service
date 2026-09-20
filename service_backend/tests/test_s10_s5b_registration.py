"""Sprint-5/10 S5b - Group E registration: AC-10-39, AC-10-15 (as it applies
to ``stock_balance``).

RED before the coder: ``modules.autocount.canonical.masters`` declares no
``ENTITY_STOCK_BALANCE``/``CanonicalStockBalance`` at all today (grepped
2026-09-20 - only ``pull_gateway_service.py``'s wire-name map and
``etl_service.py``'s own forward-looking comment mention the string
``"stock_balance"``) - every test below fails at collection with a plain
``ImportError``.

ASSUMED NAMES (from the plan's own files list section 3 + AC-10-39/15):

* ``modules.autocount.canonical.masters.ENTITY_STOCK_BALANCE = "stock_balance"``
  and ``CanonicalStockBalance`` (fields ``item_code``, ``item_description``,
  ``location_code``, ``uom_code``, ``qty`` int ``ge=0``) - landing beside the
  other masters in that file for the SAME no-import-cycle reason the file's
  own module docstring gives for the plan-22 S4 fan-out five.
* Registered in ``modules.autocount.mapping.ENTITY_PROFILES``,
  ``modules.autocount.services.etl_service.ETL_ENTITY_TYPES``,
  ``modules.autocount.presets.HTTP_PRESETS``/``HTTP_ENTITY_TYPES`` and
  ``modules.autocount.mapping_catalog.SORENTO_FIELDS``.
* NO ``modules.autocount.sinks_sorento._ENTITY_PATH`` entry - constructing a
  ``SorentoSink`` for it raises the EXISTING ``SorentoSinkError`` ("No
  Sorento ingest path for canonical entity ...") unchanged, since that guard
  already fires for any entity absent from the map (verified: today it does
  for a made-up string; once ``ENTITY_STOCK_BALANCE`` exists as a real
  constant, the SAME guard must keep firing for it as long as the coder never
  adds an entry - pinned here so a future path addition is a deliberate,
  reviewed act, not an accident).
* ``ENTITY_STOCK_BALANCE`` joins
  ``modules.autocount.services.etl_service.PULL_CAPABLE_ENTITY_TYPES`` (today
  only ``(ENTITY_PRODUCT,)``) and a freshly-saved stock task is created in
  PULL mode - never the column's own ``push`` default (AC-10-15's "Its tasks
  are created in `pull` mode").
* ``EtlService.set_delivery_mode`` refuses a PUSH switch for
  ``stock_balance`` with a 422 naming both the entity and the required
  contract version (AC-10-15: "the SAME `fetch_contract_detail` ->
  `sorento_supports_entity` probe AC-10-69 generalises" -
  ``STOCK_BALANCES_CONTRACT_VERSION = 2.5``), and allows it once a probed
  Sorento contract reports ``>= 2.5`` with ``"stock_balances"`` advertised -
  pinned at the PUBLIC ``set_delivery_mode`` seam only, deliberately agnostic
  to which private helper the coder threads the probe through (AC-10-69's own
  ``CompanyService.contract_gate``, or a stock-specific twin) - the plan
  states the OUTCOME, not the internal wiring.

Kill-test notes are per section below.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network. See
    ``test_s10_s3_delivery_mode.py``'s copy of this fixture for the full
    rationale (coordinator finding 2026-09-20)."""
    import httpx

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
STOCK_COMBINE = {
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


def _http_raw(connection_id):
    return {
        "sourceImpl": "autocount_http",
        "connectionId": connection_id,
        "path": "/itembatchbalqtybypage",
        "keyFields": [],
        "watermarkField": None,
        "comparedFields": [],
        "distinctOf": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileHours": None,
        "reconcileAt": "02:00",
        "lookups": [ITEM_LOOKUP, ITEM_UOM_LOOKUP],
        "combine": STOCK_COMBINE,
    }


def _open_connection(db, *, name="db1 REST") -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name=name,
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id, *, sink_impl=None, sink_connection_id=None):
    from modules.autocount.models import AcCompany, SINK_IMPL_LOGGING

    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
        sink_impl=sink_impl or SINK_IMPL_LOGGING, sink_connection_id=sink_connection_id,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


# ── AC-10-39: entity key + canonical shape ──────────────────────────────────


def test_entity_key_is_the_agreed_wire_string():
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE

    assert ENTITY_STOCK_BALANCE == "stock_balance"


def test_canonical_stock_balance_declares_the_agreed_fields_and_shape():
    from modules.autocount.canonical.masters import CanonicalStockBalance

    fields = CanonicalStockBalance.model_fields
    for name in ("item_code", "item_description", "location_code", "uom_code", "qty"):
        assert name in fields, sorted(fields)

    record = CanonicalStockBalance(
        source_ref="AED_SORENTO:X1|MAIN", item_code="X1", item_description="Widget",
        location_code="MAIN", uom_code="UNIT", qty=10,
    )
    payload = record.sink_payload()
    assert payload == {
        "source_ref": "AED_SORENTO:X1|MAIN", "item_code": "X1",
        "item_description": "Widget", "location_code": "MAIN", "uom_code": "UNIT",
        "qty": 10,
    }, payload


def test_qty_is_ge_zero():
    from modules.autocount.canonical.masters import CanonicalStockBalance

    with pytest.raises(ValidationError):
        CanonicalStockBalance(
            source_ref="AED_SORENTO:X1|MAIN", item_code="X1", item_description="Widget",
            location_code="MAIN", uom_code="UNIT", qty=-1,
        )


# ── registration in the four catalogs ───────────────────────────────────────


def test_registered_in_entity_profiles():
    from modules.autocount.canonical.masters import CanonicalStockBalance, ENTITY_STOCK_BALANCE
    from modules.autocount.mapping import ENTITY_PROFILES

    assert ENTITY_STOCK_BALANCE in ENTITY_PROFILES
    assert ENTITY_PROFILES[ENTITY_STOCK_BALANCE].record_model is CanonicalStockBalance


def test_registered_in_etl_entity_types():
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.services.etl_service import ETL_ENTITY_TYPES

    assert ENTITY_STOCK_BALANCE in ETL_ENTITY_TYPES


def test_registered_in_http_presets_and_entity_types():
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.presets import HTTP_ENTITY_TYPES, HTTP_PRESETS

    assert ENTITY_STOCK_BALANCE in HTTP_PRESETS
    assert ENTITY_STOCK_BALANCE in HTTP_ENTITY_TYPES


def test_registered_in_mapping_catalog_sorento_fields():
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.mapping_catalog import SORENTO_FIELDS

    field_names = {f.field for f in SORENTO_FIELDS.get(ENTITY_STOCK_BALANCE, ())}
    for name in ("item_code", "item_description", "location_code", "uom_code", "qty"):
        assert name in field_names, field_names
    # source_ref is minted, never a mappable target - masters.py's own rule,
    # extended here (AC-10-39's "registered ... beside their siblings").
    assert "source_ref" not in field_names


# ── no Sorento ingest path (pull-only rule, AC-10-15) ───────────────────────


def test_no_sorento_entity_path_entry():
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.sinks_sorento import _ENTITY_PATH

    assert ENTITY_STOCK_BALANCE not in _ENTITY_PATH


def test_constructing_a_sorento_sink_for_stock_balance_raises():
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.sinks_sorento import SorentoSink, SorentoSinkError

    with pytest.raises(SorentoSinkError, match="No Sorento ingest path"):
        SorentoSink(
            base_url="https://example.invalid", api_key="k", entity_type=ENTITY_STOCK_BALANCE,
        )


def test_sorento_does_not_report_supporting_stock_balance_at_all():
    """``sorento_supports_entity`` never claims the PUSH ingest route exists
    for stock, at any contract - it has no ``_ENTITY_PATH`` entry to gate.
    (The SEPARATE `set_delivery_mode` gate below is what actually governs
    whether an operator may flip the mode - a different question from "does
    Sorento have an ingest route".)"""
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.sinks_sorento import sorento_supports_entity

    assert sorento_supports_entity(ENTITY_STOCK_BALANCE) is False
    assert (
        sorento_supports_entity(
            ENTITY_STOCK_BALANCE, contract_version=99.0, contract_entities=["stock_balances"]
        )
        is False
    )


# ── AC-10-15: pull-capable, created in pull mode, push refused ─────────────


def test_stock_balance_joins_the_pull_capable_set():
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.services.etl_service import PULL_CAPABLE_ENTITY_TYPES

    assert ENTITY_STOCK_BALANCE in PULL_CAPABLE_ENTITY_TYPES


def test_a_freshly_saved_stock_task_is_created_in_pull_mode(db):
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.models import DELIVERY_MODE_PULL
    from modules.autocount.services.etl_service import EtlService

    conn = _open_connection(db)
    company = _company(db, conn.id)

    view = EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, _http_raw(conn.id)
    )
    assert view.source_config["keyFields"] == ["item_code", "location_code"]

    config = EtlService(db).configs.get(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    assert config.delivery_mode == DELIVERY_MODE_PULL, (
        "AC-10-15: a stock_balance task must be created in pull mode - never "
        "the AcEntityConfig column's own 'push' server_default"
    )


def test_switching_a_stock_task_to_push_is_refused_naming_entity_and_version(db):
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.models import DELIVERY_MODE_PUSH
    from modules.autocount.services.etl_service import EtlService, EtlValidationError

    conn = _open_connection(db)
    # A logging-sink company: Sorento's contract genuinely CANNOT be probed -
    # "never guess a contract we cannot see" (D20) means this must refuse,
    # not silently allow, exactly the fail-closed default AC-10-15 implies.
    company = _company(db, conn.id)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, _http_raw(conn.id))

    with pytest.raises(EtlValidationError) as exc_info:
        EtlService(db).set_delivery_mode(
            DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PUSH
        )
    message = " ".join(exc_info.value.field_errors.values())
    assert "stock_balance" in message, message
    assert "2.5" in message, message


def test_switching_a_stock_task_to_push_is_allowed_once_the_contract_reports_2_5(db, monkeypatch):
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.models import DELIVERY_MODE_PUSH, SINK_IMPL_SORENTO
    from modules.autocount.services.etl_service import EtlService

    conn = _open_connection(db)
    sorento = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sorento", type="consumer", name="sorento conn",
        config_json={"baseUrl": "https://sorento.example.com"},
        credentials_json=encrypt_secret({"apiKey": "k"}), is_active=True,
    )
    db.add(sorento)
    db.commit()
    db.refresh(sorento)
    company = _company(db, conn.id, sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento.id)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, _http_raw(conn.id))

    class _Contract:
        version = 2.5
        entities = ["products", "stock_balances"]

    monkeypatch.setattr(
        "modules.autocount.sinks_sorento.SorentoSink.fetch_contract_detail",
        lambda self: _Contract(),
    )

    view = EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PUSH
    )
    assert view.delivery_mode == DELIVERY_MODE_PUSH


def test_switching_a_stock_task_to_pull_is_always_allowed_control(db):
    """CONTROL: pull needs no contract at all - only the pull-capable
    membership + a consumer company code, both already satisfied here."""
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.models import DELIVERY_MODE_PULL
    from modules.autocount.services.etl_service import EtlService

    conn = _open_connection(db)
    company = _company(db, conn.id)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, _http_raw(conn.id))

    view = EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PULL
    )
    assert view.etl_status is not None  # the call succeeded without raising


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_constructing_a_sorento_sink_for_stock_balance_raises dies the moment
#   anyone adds a "stock_balances" entry to `_ENTITY_PATH` without also
#   updating `test_no_sorento_entity_path_entry` - the pull-only rule's whole
#   enforcement mechanism is "the map has no entry", so this is the guard
#   that would catch an accidental path addition.
# * test_switching_a_stock_task_to_push_is_refused_naming_entity_and_version
#   dies if the coder reuses the GENERIC "entity outside pull-capable set"
#   422 (which never mentions "2.5") instead of the contract-specific one -
#   proving the refusal is version-aware, not just membership-aware.
# * test_switching_a_stock_task_to_push_is_allowed_once_the_contract_reports_2_5
#   dies if the refusal is unconditional (a hardcoded "stock never pushes"
#   forever rule) rather than the contract GATE the plan calls for.
