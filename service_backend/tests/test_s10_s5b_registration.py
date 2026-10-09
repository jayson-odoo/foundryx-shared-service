"""Sprint-5/10 S5b - Group E registration: AC-10-39, AC-10-15 (as it applies
to ``stock_balance``).

Plan 13 S0 (2026-09-25) INVERTS three tests below on purpose
(``test_no_sorento_entity_path_entry``,
``test_constructing_a_sorento_sink_for_stock_balance_raises``,
``test_sorento_does_not_report_supporting_stock_balance_at_all`` -
originally lines 235/240/250, cited verbatim in
`documentation/plans/sprint-5/13-autocount-stock-push-acceptance-criteria.md`
"Verified baseline"). Plan 10's S5b deliberately left stock PULL-ONLY (no
``_ENTITY_PATH`` entry, ``sorento_supports_entity`` unconditionally ``False``)
- plan 13 (BL-SS-207) gives it the SAME push path every other pull-capable
entity has, contract-gated at 2.5 exactly like ``brand`` is at 2.3. These
three inversions are the ONLY deliberate assertion reversals in this file
(AC-13-71); every other test above keeps pinning plan 10's own behaviour
unchanged.

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


# N1 (review round 5) - imported from the REAL preset rather than a local
# copy, so a preset edit (e.g. dropping `listRows`) fails a registration
# test too instead of silently drifting from what actually ships.
from modules.autocount.presets import STOCK_BALANCE_HTTP_PRESET  # noqa: E402

ITEM_LOOKUP, ITEM_UOM_LOOKUP = STOCK_BALANCE_HTTP_PRESET.lookups
STOCK_COMBINE = STOCK_BALANCE_HTTP_PRESET.combine


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


def test_sorento_entity_path_stock_balance_is_stock_balances():
    """INVERTED for plan 13 (AC-13-01): stock now has an ingest path, exactly
    like every other push-capable entity - ``_ENTITY_PATH[ENTITY_STOCK_BALANCE]
    == "stock_balances"``."""
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.sinks_sorento import _ENTITY_PATH

    assert ENTITY_STOCK_BALANCE in _ENTITY_PATH
    assert _ENTITY_PATH[ENTITY_STOCK_BALANCE] == "stock_balances"


def test_constructing_a_sorento_sink_for_stock_balance_succeeds():
    """INVERTED for plan 13 (AC-13-01): a ``SorentoSink`` for stock now
    constructs cleanly (the ``_ENTITY_PATH`` entry above is what makes
    construction possible at all - ``SorentoSink.__init__`` raises
    ``SorentoSinkError`` for any entity absent from the map)."""
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.sinks_sorento import SorentoSink

    sink = SorentoSink(
        base_url="https://example.invalid", api_key="k", entity_type=ENTITY_STOCK_BALANCE,
    )
    assert sink.entity_type == ENTITY_STOCK_BALANCE


def test_sorento_supports_stock_balance_is_contract_gated_like_brand():
    """INVERTED for plan 13 (AC-13-02): stock is CONTRACT-GATED exactly like
    ``brand`` (2.3) is - here at ``STOCK_BALANCES_CONTRACT_VERSION = 2.5`` -
    never an unconditional ``False``. The plain 1-arg call (no contract
    kwargs, the shape every OTHER non-gated entity uses) still reads as
    "not yet provable" -> ``False``, same posture as brand below 2.3."""
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.sinks_sorento import sorento_supports_entity

    assert sorento_supports_entity(ENTITY_STOCK_BALANCE) is False
    assert (
        sorento_supports_entity(
            ENTITY_STOCK_BALANCE, contract_version=2.4, contract_entities=["stock_balances"]
        )
        is False
    )
    assert (
        sorento_supports_entity(
            ENTITY_STOCK_BALANCE, contract_version=2.5, contract_entities=["suppliers"]
        )
        is False
    )
    assert (
        sorento_supports_entity(
            ENTITY_STOCK_BALANCE, contract_version=2.5, contract_entities=["stock_balances"]
        )
        is True
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
    """Plan 13 S0 (2026-09-25) - the ONE sanctioned edit to this file
    (coder brief defect 3): once contract 2.5 opens the gate, stock ALSO
    needs a READY, unexpired snapshot to seed its baseline from (D9,
    AC-13-31) - this rig now provides one so the assertion under test
    (contract-gated switch succeeds) is not masked by the newer
    ``no_snapshot`` refusal plan 13 adds on top of plan 10's own gate."""
    import uuid
    from datetime import timedelta

    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.models import (
        DELIVERY_MODE_PUSH,
        PULL_SNAPSHOT_STATUS_READY,
        SINK_IMPL_SORENTO,
        AcPullSnapshot,
        AcPullSnapshotRow,
    )
    from modules.autocount.repositories import PullSnapshotRepository
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

    now = datetime.now(timezone.utc)
    snapshot = AcPullSnapshot(
        id=str(uuid.uuid4()), tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
        entity_type=ENTITY_STOCK_BALANCE, company_code=company.sorento_company_code,
        status=PULL_SNAPSHOT_STATUS_READY, record_count=1, complete=True,
        extracted_at=now, expires_at=now + timedelta(hours=24),
    )
    snapshot_repo = PullSnapshotRepository(db)
    snapshot_repo.add(snapshot)
    snapshot_repo.insert_row(
        AcPullSnapshotRow(
            tenant_id=DEFAULT_TENANT_ID, snapshot_id=snapshot.id, row_index=0,
            company_id=company.id, source_ref="AED_X:A1|MBS",
            payload_json={"source_ref": "AED_X:A1|MBS", "qty": 1},
        )
    )
    db.commit()

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


# ── S3 (review round 5, AC-10-40/41/84): "the owner configures nothing" ────


def _bare_stock_http_raw(connection_id):
    """A genuinely bare add-entity request: no `combine`, no manual
    `keyFields` - exactly what the owner submits when they add the entity
    and configure nothing at all."""
    raw = dict(_http_raw(connection_id))
    raw.pop("combine", None)
    raw["keyFields"] = []
    return raw


def test_adding_a_fresh_stock_entity_seeds_combine_and_derives_key_fields(db):
    """S3 - a bare add-entity request 422ed before this fix (no combine, no
    manual keyFields -> "Choose at least one key field."); it must instead
    seed `source_config.combine` from the preset and derive `keyFields`
    from ITS `groupBy` (AC-10-80), saving cleanly."""
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.models import DELIVERY_MODE_PULL
    from modules.autocount.services.etl_service import EtlService

    conn = _open_connection(db)
    company = _company(db, conn.id)

    view = EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, _bare_stock_http_raw(conn.id)
    )

    assert view.source_config["combine"] == STOCK_COMBINE, view.source_config["combine"]
    assert view.source_config["keyFields"] == ["item_code", "location_code"]

    config = EtlService(db).configs.get(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    assert config.delivery_mode == DELIVERY_MODE_PULL


def _bare_product_http_raw(connection_id):
    return {
        "sourceImpl": "autocount_http",
        "connectionId": connection_id,
        "path": "/itembypage",
        "keyFields": ["ItemCode"],
        "watermarkField": None,
        "comparedFields": [],
        "distinctOf": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileHours": None,
        "reconcileAt": "02:00",
        "lookups": [],
    }


def test_adding_a_fresh_product_entity_is_unaffected_by_the_combine_seed(db):
    """S3 CONTROL - `product`'s own HTTP preset carries no `combine`
    (only stock's does today), so this save is byte-identical to before
    the fix: its own manually-picked `keyFields` win, `combine` stays
    unset."""
    from modules.autocount.canonical.masters import ENTITY_PRODUCT
    from modules.autocount.services.etl_service import EtlService

    conn = _open_connection(db)
    company = _company(db, conn.id)

    view = EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _bare_product_http_raw(conn.id)
    )
    assert view.source_config.get("combine") is None
    assert view.source_config["keyFields"] == ["ItemCode"]


# ── N3 (review round 5, AC-10-15): activate re-checks the push gate too ────


def _activatable_stock_config(db, company_id, connection_id):
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.services.etl_service import EtlService

    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company_id, ENTITY_STOCK_BALANCE, _http_raw(connection_id)
    )
    config = EtlService(db).configs.get(DEFAULT_TENANT_ID, company_id, ENTITY_STOCK_BALANCE)
    # Mirrors a real "Test" having already succeeded (AC-22-18's own
    # activation precondition) - `update_task` itself always clears these.
    config.last_preview_at = NOW
    config.last_preview_failed_count = 0
    db.commit()
    return config


def _seed_ready_stock_snapshot(db, company_id, connection_id):
    """NOTE (plan 13 S2 coder, 2026-09-26) - a READY, unexpired snapshot is
    now ALSO a `pull -> push` prerequisite for stock (AC-13-31, D9), on
    top of this file's own pre-existing contract-version gate - every
    caller here that goes on to call `set_delivery_mode(push)` needs one,
    or that call now 422s `no_snapshot` before it ever reaches the
    contract-regression scenario this test exists to pin."""
    import uuid
    from datetime import timedelta

    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.models import PULL_SNAPSHOT_STATUS_READY, AcPullSnapshot, AcPullSnapshotRow
    from modules.autocount.repositories import PullSnapshotRepository

    now = datetime.now(timezone.utc)
    snapshot = AcPullSnapshot(
        id=str(uuid.uuid4()), tenant_id=DEFAULT_TENANT_ID, company_id=company_id,
        entity_type=ENTITY_STOCK_BALANCE, company_code="SRT",
        status=PULL_SNAPSHOT_STATUS_READY, record_count=1, complete=True,
        extracted_at=now, expires_at=now + timedelta(hours=24),
    )
    repo = PullSnapshotRepository(db)
    repo.add(snapshot)
    repo.insert_row(
        AcPullSnapshotRow(
            tenant_id=DEFAULT_TENANT_ID, snapshot_id=snapshot.id, row_index=0,
            company_id=company_id, source_ref="AED_X:A1|MBS",
            payload_json={"source_ref": "AED_X:A1|MBS", "qty": 1},
        )
    )
    db.commit()


def test_activating_a_stock_task_refuses_once_the_push_gate_regresses(db, monkeypatch):
    """N3 - a task SAVED in push mode while the gate was open (the
    consumer served 2.5) must be re-checked again on its way to `active`,
    not just on the `push` switch itself: the consumer's contract
    REGRESSES between the switch and activation here."""
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.models import DELIVERY_MODE_PUSH, SINK_IMPL_SORENTO
    from modules.autocount.services.etl_service import EtlService, EtlStateError

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
    _activatable_stock_config(db, company.id, conn.id)
    _seed_ready_stock_snapshot(db, company.id, conn.id)

    class _ContractOk:
        version = 2.5
        entities = ["products", "stock_balances"]

    monkeypatch.setattr(
        "modules.autocount.sinks_sorento.SorentoSink.fetch_contract_detail",
        lambda self: _ContractOk(),
    )
    EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PUSH
    )
    # `set_delivery_mode` re-fetched/committed its own `config` row - restamp
    # the activation preconditions on a FRESH instance.
    _activatable_stock_config(db, company.id, conn.id)

    class _ContractRegressed:
        version = 2.4
        entities = ["products"]

    monkeypatch.setattr(
        "modules.autocount.sinks_sorento.SorentoSink.fetch_contract_detail",
        lambda self: _ContractRegressed(),
    )

    with pytest.raises(EtlStateError) as exc_info:
        # A FRESH EtlService/CompanyService instance - review round 5's own
        # memoisation (N4) must never leak a stale result ACROSS instances,
        # only within one.
        EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    message = str(exc_info.value)
    assert "stock_balance" in message, message
    assert "2.5" in message, message


def test_activating_a_pull_mode_stock_task_never_probes_the_push_gate(db, monkeypatch):
    """N3 CONTROL - pull mode carries no push gate at all: activation must
    never even ATTEMPT the contract probe."""
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.services.etl_service import EtlService

    conn = _open_connection(db)
    company = _company(db, conn.id)
    _activatable_stock_config(db, company.id, conn.id)

    def _boom(self):
        raise AssertionError("the push gate must never probe a pull-mode task")

    monkeypatch.setattr(
        "modules.autocount.sinks_sorento.SorentoSink.fetch_contract_detail", _boom
    )
    view = EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    assert view.etl_status == "active"


# ── N4 (review round 5): a config fault is never the SAME refusal as an ────
# ── old contract, and the gate is memoised per service instance ───────────


def test_stock_push_gate_reports_a_distinct_message_for_a_config_fault(db, monkeypatch):
    """A decrypt/config fault (a rotated FERNET_KEY, here simulated
    directly) refuses with a message naming the CONNECTION, never "needs
    contract 2.5" - conflating the two would send an operator with a fine,
    merely-outdated Sorento contract off to fix a connection that is not
    broken."""
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.models import DELIVERY_MODE_PUSH, SINK_IMPL_SORENTO
    from modules.autocount.services.etl_service import EtlService, EtlValidationError

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

    from cryptography.fernet import InvalidToken

    def _raise_invalid_token(_token):
        raise InvalidToken()

    monkeypatch.setattr(
        "modules.autocount.services.company_service.decrypt_secret", _raise_invalid_token
    )

    with pytest.raises(EtlValidationError) as exc_info:
        EtlService(db).set_delivery_mode(
            DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PUSH
        )
    message = exc_info.value.field_errors["deliveryMode"]
    assert "connection" in message.lower(), message
    assert "2.5" not in message, message


def test_stock_push_gate_reports_the_2_5_message_for_a_genuinely_old_contract(db, monkeypatch):
    """CONTROL - a REACHABLE consumer on a contract below 2.5 keeps the
    original "needs contract 2.5" message, distinct from a config fault."""
    from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
    from modules.autocount.models import DELIVERY_MODE_PUSH, SINK_IMPL_SORENTO
    from modules.autocount.services.etl_service import EtlService, EtlValidationError

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

    class _OldContract:
        version = 2.4
        entities = ["products"]

    monkeypatch.setattr(
        "modules.autocount.sinks_sorento.SorentoSink.fetch_contract_detail",
        lambda self: _OldContract(),
    )

    with pytest.raises(EtlValidationError) as exc_info:
        EtlService(db).set_delivery_mode(
            DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PUSH
        )
    message = exc_info.value.field_errors["deliveryMode"]
    assert "2.5" in message, message
    assert "connection" not in message.lower(), message


def test_stock_push_gate_is_memoised_per_service_instance(db, monkeypatch):
    """N4 - the SAME mechanism `contract_gate` already gets: a SECOND read
    on the SAME `CompanyService` instance never re-probes the network."""
    from modules.autocount.models import SINK_IMPL_SORENTO
    from modules.autocount.services.company_service import CompanyService

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

    calls = {"count": 0}

    class _ContractOk:
        version = 2.5
        entities = ["products", "stock_balances"]

    def _fetch(self):
        calls["count"] += 1
        return _ContractOk()

    monkeypatch.setattr(
        "modules.autocount.sinks_sorento.SorentoSink.fetch_contract_detail", _fetch
    )
    service = CompanyService(db)
    first = service.stock_push_gate_error(DEFAULT_TENANT_ID, company)
    second = service.stock_push_gate_error(DEFAULT_TENANT_ID, company)
    assert first == second
    assert calls["count"] == 1, calls


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
# * test_adding_a_fresh_stock_entity_seeds_combine_and_derives_key_fields dies
#   with a "Choose at least one key field." 422 if the coder seeds `combine`
#   only AFTER validation (mirroring the lookups seed's own post-save spot)
#   instead of before it.
# * test_adding_a_fresh_product_entity_is_unaffected_by_the_combine_seed dies
#   if the seed is wired unconditionally (every entity gets a combine) rather
#   than reading it off THAT entity's own `HTTP_PRESETS` entry.
# * test_activating_a_stock_task_refuses_once_the_push_gate_regresses dies if
#   `activate_task` never re-checks the gate at all (a push task set up while
#   the gate was open sails through activation regardless of the consumer's
#   CURRENT contract).
# * test_activating_a_pull_mode_stock_task_never_probes_the_push_gate dies if
#   the new activate-time check is not gated on `delivery_mode == 'push'`.
# * test_stock_push_gate_reports_a_distinct_message_for_a_config_fault dies if
#   the coder keeps the original bare `except Exception` (every fault reports
#   the SAME "needs contract 2.5" message).
# * test_stock_push_gate_is_memoised_per_service_instance dies if
#   `stock_push_gate_error` still probes the network on every call.
