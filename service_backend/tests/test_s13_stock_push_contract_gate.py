"""Plan 13 S0 - Group A (sink registration/contract) + Group D (the flip's
own gate), the ``pushGate`` half. RED before the coder.

Verified baseline (2026-09-25, same facts the plan's own "Verified baseline"
section cites): ``sinks_sorento._ENTITY_PATH`` carries NO ``stock_balance``
entry (`sinks_sorento.py:94-113`), so ``sorento_supports_entity`` answers
``False`` at ANY contract and ``sink_for_company`` routes stock straight to
the logging sink regardless of the live probe (`company_service.py:859`).
``EtlTaskView`` (a plain ``@dataclass``, `etl_service.py:280-330`) has no
``push_gate`` field at all - reading ``view.push_gate`` raises
``AttributeError`` until S3 adds it. Every test below is expected to fail
for exactly one of those two reasons (a stale/absent registration, or a
missing dataclass field) - never at collection.

Pins: AC-13-01, AC-13-02, AC-13-06, AC-13-30, AC-13-31.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_RUNNING, BackgroundJob
from app.secrets import encrypt_secret
from modules.autocount.canonical.masters import (
    ENTITY_BRAND,
    ENTITY_PRODUCT,
    ENTITY_STOCK_BALANCE,
)
from modules.autocount.models import (
    STAGED,
    AcStagedRecord,
    SINK_IMPL_LOGGING,
    SINK_IMPL_SORENTO,
)
from modules.autocount.sinks import SINK_LOGGING
from modules.autocount.sinks_sorento import (
    SorentoContractInfo,
    SorentoSink,
    STOCK_BALANCES_CONTRACT_VERSION,
    sorento_supported_entities_label,
    sorento_supports_entity,
)
from modules.autocount.sync import AUTOCOUNT_SYNC

# Reuse the plan-10 stock registration rig (real AcCompany/AcEntityConfig
# helpers, real HTTP task config) rather than a second hand-rolled copy.
from tests.test_s10_s5b_registration import _company, _http_raw, _open_connection

NOW = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)


# ── AC-13-02: contract-gated membership table (stock beside brand) ─────────


def test_stock_membership_is_contract_gated_like_brand_byte_identical():
    """The SAME gate function, brand's own behaviour untouched: every
    ``sorento_supports_entity`` call this file's sibling ``test_autocount_
    brand.py`` makes must still answer exactly as it does today."""
    assert sorento_supports_entity(ENTITY_BRAND, contract_version=2.2, contract_entities=["suppliers"]) is False
    assert sorento_supports_entity(ENTITY_BRAND, contract_version=2.3, contract_entities=["brands"]) is True
    # And stock now answers the SAME SHAPE of question at its own version.
    assert sorento_supports_entity(
        ENTITY_STOCK_BALANCE, contract_version=2.4, contract_entities=["stock_balances"]
    ) is False
    assert sorento_supports_entity(
        ENTITY_STOCK_BALANCE,
        contract_version=STOCK_BALANCES_CONTRACT_VERSION,
        contract_entities=["stock_balances"],
    ) is True


def test_supported_entities_label_excludes_every_gated_entity():
    """AC-13-02 - the operator-facing label never claims a contract-gated
    entity Sorento may not actually accept yet, for BOTH gated entities.

    NOTE - this one is a forward guard, not currently red: today ``stock``
    has no ``_ENTITY_PATH`` entry at all, so it is trivially absent from the
    label for the WRONG reason (never mapped, not "gated"). It exists here
    so a coder who adds the `_ENTITY_PATH` entry (AC-13-01) but forgets to
    generalise the label's ``entity_type != ENTITY_BRAND`` exclusion
    (`sinks_sorento.py:232`) sees this go red DURING that change, not after."""
    label = sorento_supported_entities_label()
    assert "brand" not in label
    assert "stock balance" not in label
    # Un-gated entities stay named.
    assert "product" in label


# ── AC-13-06: sink_for_company opens/falls back on the LIVE contract ───────


@pytest.fixture
def _stock_gate_rig(session_factory):
    from app.models.connection import Connection

    db = session_factory()
    source_conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Vendor",
        config_json={"baseUrl": "https://ac.example.com", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    sorento_conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sorento", type="erp", name="Sorento",
        config_json={"baseUrl": "https://sorento.example.com"},
        credentials_json=encrypt_secret({"apiKey": "k"}), is_active=True,
    )
    db.add_all([source_conn, sorento_conn])
    db.commit()
    company = _company(
        db, source_conn.id, sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento_conn.id,
    )
    yield db, company
    db.close()


def test_sink_for_company_stock_opens_on_2_5_with_stock_balances(monkeypatch, _stock_gate_rig):
    from modules.autocount.services.company_service import CompanyService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.5, entities=["products", "stock_balances"]),
    )
    db, company = _stock_gate_rig
    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_STOCK_BALANCE)
    assert isinstance(sink, SorentoSink), (
        f"expected a live SorentoSink once the contract is 2.5 with stock_balances "
        f"advertised, got {sink.name!r}"
    )


def test_sink_for_company_stock_falls_back_to_logging_below_2_5(monkeypatch, _stock_gate_rig):
    from modules.autocount.services.company_service import CompanyService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.4, entities=["products"]),
    )
    db, company = _stock_gate_rig
    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_STOCK_BALANCE)
    assert sink.name == SINK_LOGGING


# ── AC-13-06: auto_push refuses CONTRACT_GATE, never PUSHED ────────────────


def _staged_row(db, company_id, *, ref="AED_SORENTO:X|MBS") -> AcStagedRecord:
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC, status=JOB_RUNNING,
        payload_json={"companyId": company_id, "entityType": ENTITY_STOCK_BALANCE},
    )
    db.add(job)
    db.commit()
    row = AcStagedRecord(
        tenant_id=DEFAULT_TENANT_ID, company_id=company_id, entity_type=ENTITY_STOCK_BALANCE,
        job_id=job.id, source_ref=ref, doc_no=None,
        raw_json={"item_code": "X", "location_code": "MBS", "qty": 1},
        canonical_json={"item_code": "X", "location_code": "MBS", "qty": 1},
        status=STAGED,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, job


def test_auto_push_refuses_contract_gate_and_leaves_rows_staged(monkeypatch, _stock_gate_rig):
    """AC-13-06 - a Sorento-sink company whose stock contract gate is SHUT
    must never deliver through brand's logging-sink fallback (that would
    mark rows PUSHED while nothing landed, and changed-only staging would
    then never re-offer them): ``auto_push`` refuses with
    ``errorCode == 'CONTRACT_GATE'`` and every row stays STAGED."""
    from modules.autocount.services.sync_service import SyncService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.4, entities=["products"]),
    )
    db, company = _stock_gate_rig
    row, job = _staged_row(db, company.id)

    summary = SyncService(db).auto_push(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, job_id=job.id
    )
    assert summary.get("errorCode") == "CONTRACT_GATE", summary
    db.refresh(row)
    assert row.status == STAGED


# ── AC-13-30: pushGate on the task view ─────────────────────────────────────


@pytest.fixture
def _stock_task_rig(session_factory):
    # NOTE (plan 13 S2 coder, 2026-09-26) - this fixture originally built its
    # company with `sink_impl=SINK_IMPL_SORENTO` and NO `sink_connection_id`
    # at all, which makes `CompanyService.stock_push_gate_error` refuse via
    # its own "no consumer connection configured" early-out
    # (`{"version": None, "requiredVersion": ...}`, no probe) REGARDLESS of
    # any `fetch_contract_detail` monkeypatch a test below applies - so
    # `test_push_gate_carries_contract_gate_when_shut`'s and
    # `test_push_gate_names_no_snapshot_once_contract_opens_with_no_snapshot`'s
    # monkeypatched contract could never be reached, and their own asserted
    # `{"version": 2.4, ...}` / an OPEN gate could never be produced. Wired a
    # real Sorento connection the SAME way this file's own `_stock_gate_rig`
    # (above) already does, so the probe this fixture's tests exist to pin
    # actually runs. No assertion in any test using this fixture changed.
    from app.models.connection import Connection

    db = session_factory()
    conn = _open_connection(db)
    sorento_conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sorento", type="erp", name="Sorento",
        config_json={"baseUrl": "https://sorento.example.com"},
        credentials_json=encrypt_secret({"apiKey": "k"}), is_active=True,
    )
    db.add(sorento_conn)
    db.commit()
    db.refresh(sorento_conn)
    company = _company(
        db, conn.id, sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento_conn.id,
    )
    from modules.autocount.services.etl_service import EtlService

    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, _http_raw(conn.id)
    )
    yield db, company
    db.close()


def test_push_gate_null_for_non_stock_entity_always(_stock_task_rig):
    from modules.autocount.services.etl_service import EtlService

    db, company = _stock_task_rig
    view = EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert view.push_gate is None


def test_push_gate_carries_contract_gate_when_shut(monkeypatch, _stock_task_rig):
    from modules.autocount.services.etl_service import EtlService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.4, entities=["products"]),
    )
    db, company = _stock_task_rig
    view = EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    assert view.push_gate == {"version": 2.4, "requiredVersion": STOCK_BALANCES_CONTRACT_VERSION}


def test_push_gate_names_no_snapshot_once_contract_opens_with_no_snapshot(
    monkeypatch, _stock_task_rig
):
    """AC-13-30/31 - contract passes but the task (created in `pull`) holds
    no READY, unexpired snapshot yet: `pushGate` must name `no_snapshot`,
    never `None` (which would let the Schedule tab offer Push with nothing
    to seed from)."""
    from modules.autocount.services.etl_service import EtlService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.5, entities=["products", "stock_balances"]),
    )
    db, company = _stock_task_rig
    view = EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    assert view.push_gate == {"reason": "no_snapshot"}


# ── AC-13-31: set_delivery_mode's no_snapshot refusal + ordering ───────────


def test_set_delivery_mode_refuses_no_snapshot_once_contract_is_open(
    monkeypatch, _stock_task_rig
):
    from modules.autocount.models import DELIVERY_MODE_PUSH
    from modules.autocount.services.etl_service import EtlService, EtlValidationError

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.5, entities=["products", "stock_balances"]),
    )
    db, company = _stock_task_rig
    with pytest.raises(EtlValidationError) as exc_info:
        EtlService(db).set_delivery_mode(
            DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PUSH
        )
    message = " ".join(exc_info.value.field_errors.values())
    assert "snapshot" in message.lower(), message


def test_set_delivery_mode_checks_contract_before_snapshot(monkeypatch, _stock_task_rig):
    """Ordering (AC-13-31): with BOTH prerequisites missing (contract shut
    AND no snapshot), the refusal names the CONTRACT reason, never the
    snapshot one - the operator fixes the more fundamental blocker first."""
    from modules.autocount.models import DELIVERY_MODE_PUSH
    from modules.autocount.services.etl_service import EtlService, EtlValidationError

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.4, entities=["products"]),
    )
    db, company = _stock_task_rig
    with pytest.raises(EtlValidationError) as exc_info:
        EtlService(db).set_delivery_mode(
            DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PUSH
        )
    message = " ".join(exc_info.value.field_errors.values())
    assert "2.5" in message, message
    assert "snapshot" not in message.lower(), message
