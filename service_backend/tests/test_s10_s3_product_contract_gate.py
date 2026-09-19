"""Sprint-5/10 S3 - product contract gate: AC-10-69.

RED before the coder: ``CompanyService`` has no ``contract_gate`` method and
``sinks_sorento`` has no ``PRODUCT_CODE_WINS_CONTRACT_VERSION`` today - every
import/attribute access below fails plainly.

ASSUMED NAMES (generalised from the EXISTING brand gate,
``services/company_service.py:818-872`` / ``sinks_sorento.
BRAND_REQUIRED_CONTRACT_VERSION`` - read before writing this file):

* ``modules.autocount.sinks_sorento.PRODUCT_CODE_WINS_CONTRACT_VERSION = 2.4``.
* ``CompanyService.contract_gate(tenant_id, company, entity_type) ->
  Optional[Dict[str, Any]]`` - the GENERALISED replacement AC-10-69 itself
  names ("the existing brandContractGate field... folded into it"). Unlike
  ``brand_contract_gate``, this does NOT early-return ``None`` for a
  non-Sorento company when ``entity_type == ENTITY_PRODUCT`` - AC-10-69's own
  third bullet requires a banner with ``version: None`` even with NO Sorento
  connection at all ("the gateway genuinely cannot see the consumer's
  contract... nothing is blocked"). For ``ENTITY_BRAND`` the method's
  behaviour is BYTE-IDENTICAL to today's ``brand_contract_gate`` (pinned by a
  regression test below) - only ``product`` gets the new no-connection
  branch.
* ``EtlService.activate_task`` gains a NEW refusal, PUSH-mode + ``product``
  + a Sorento-sunk company only: below contract 2.4, raise ``EtlStateError``
  naming the required version (409, matching the anchor-code gate's own
  shape immediately above it in that method). PULL mode and a non-Sorento
  company are NEVER blocked by this gate - banner-only (not exercised by an
  ``activate_task`` call in this backend suite; the banner itself is a wire/
  FE concern this file does not touch).

NOTE ON THE WIRE FIELD (flagged, not silently assumed): AC-10-69 says the
existing ``brandContractGate``/``brandContractBanner`` fold into ONE generic
``contractGate`` field on the task view - but
``service_frontend/types/autocount.ts`` still declares ONLY
``brandContractGate`` (unchanged on this branch). This file tests the
BACKEND SERVICE method only (``CompanyService.contract_gate``), never a wire
field name, so it does not take a position on whether/how the FE type
renames - see the ambiguity in the final report.

Kill-test notes are per section below.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.masters import ENTITY_BRAND, ENTITY_PRODUCT
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    SINK_IMPL_LOGGING,
    SINK_IMPL_SORENTO,
    AcCompany,
    AcEntityConfig,
)
from modules.autocount.services.company_service import CompanyService
from modules.autocount.services.etl_service import EtlService, EtlStateError

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _connection(db, provider, config, credentials=None):
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider=provider,
        type="erp" if provider != "sorento" else "consumer",
        name=f"{provider} conn", config_json=config,
        credentials_json=encrypt_secret(credentials or {}), is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, *, sink_impl=SINK_IMPL_LOGGING, sink_connection_id=None, sorento_company_code=None):
    api = _connection(db, "autocount", {"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"})
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api.id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True,
        sink_impl=sink_impl, sink_connection_id=sink_connection_id,
        sorento_company_code=sorento_company_code,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _http_raw(connection_id):
    return {
        "sourceImpl": "autocount_http", "connectionId": connection_id, "path": "/itembypage",
        "keyFields": ["ItemCode"], "watermarkField": "LastModified", "comparedFields": [],
        "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
        "reconcileHours": None, "reconcileAt": "02:00", "lookups": [],
    }


def _stamp_previewed(db, company_id, entity_type=ENTITY_PRODUCT):
    from modules.autocount.repositories import EntityConfigRepository

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company_id, entity_type)
    config.last_preview_at = NOW
    config.result_columns = ["ItemCode", "Description"]
    db.commit()


# ── the version constant + generic gate shape ───────────────────────────────


def test_product_code_wins_contract_version_is_2_4():
    from modules.autocount.sinks_sorento import PRODUCT_CODE_WINS_CONTRACT_VERSION

    assert PRODUCT_CODE_WINS_CONTRACT_VERSION == 2.4


def test_contract_gate_returns_none_for_a_product_company_at_or_above_2_4(db, monkeypatch):
    sorento = _connection(db, "sorento", {"baseUrl": "https://sorento.example.com"}, {"apiKey": "k"})
    company = _company(
        db, sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento.id, sorento_company_code="SRT",
    )

    class _Contract:
        version = 2.4
        entities = ["products"]

    monkeypatch.setattr(
        "modules.autocount.sinks_sorento.SorentoSink.fetch_contract_detail",
        lambda self: _Contract(),
    )
    gate = CompanyService(db).contract_gate(DEFAULT_TENANT_ID, company, ENTITY_PRODUCT)
    assert gate is None


def test_contract_gate_names_the_shortfall_for_a_product_company_below_2_4(db, monkeypatch):
    sorento = _connection(db, "sorento", {"baseUrl": "https://sorento.example.com"}, {"apiKey": "k"})
    company = _company(
        db, sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento.id, sorento_company_code="SRT",
    )

    class _Contract:
        version = 2.3
        entities = ["suppliers", "customers", "products"]

    monkeypatch.setattr(
        "modules.autocount.sinks_sorento.SorentoSink.fetch_contract_detail",
        lambda self: _Contract(),
    )
    gate = CompanyService(db).contract_gate(DEFAULT_TENANT_ID, company, ENTITY_PRODUCT)
    assert gate == {"entity": ENTITY_PRODUCT, "version": 2.3, "requiredVersion": 2.4}


def test_contract_gate_reads_version_null_for_a_pull_only_company_on_the_logging_sink(db):
    """AC-10-69 third bullet: NO Sorento sink connection at all - the gateway
    genuinely cannot see the consumer's contract, so this is a banner with
    ``version: null``, never a guess and never an exception."""
    company = _company(db, sink_impl=SINK_IMPL_LOGGING)

    gate = CompanyService(db).contract_gate(DEFAULT_TENANT_ID, company, ENTITY_PRODUCT)
    assert gate == {"entity": ENTITY_PRODUCT, "version": None, "requiredVersion": 2.4}


def test_contract_gate_brand_behaviour_is_unchanged_regression_control(db):
    """CONTROL: the generalisation must not touch ``brand``'s own existing
    contract - a logging-sink company still reads ``None`` (nothing to warn
    about) exactly as ``brand_contract_gate`` does today, proving the new
    no-connection branch above is entity-specific to ``product``, not a
    blanket behaviour change."""
    company = _company(db, sink_impl=SINK_IMPL_LOGGING)

    gate = CompanyService(db).contract_gate(DEFAULT_TENANT_ID, company, ENTITY_BRAND)
    assert gate is None


# ── activation refusal (push mode + Sorento sink + below 2.4) ───────────────


def test_activating_a_product_push_task_is_refused_below_contract_2_4(db, monkeypatch):
    sorento = _connection(db, "sorento", {"baseUrl": "https://sorento.example.com"}, {"apiKey": "k"})
    company = _company(
        db, sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento.id, sorento_company_code="SRT",
    )
    api = _connection(db, "autocount", {"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"})
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(api.id))
    _stamp_previewed(db, company.id)
    monkeypatch.setattr(
        CompanyService, "contract_gate",
        lambda self, tenant_id, company, entity_type: {
            "entity": entity_type, "version": 2.3, "requiredVersion": 2.4,
        },
    )

    with pytest.raises(EtlStateError) as exc:
        EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert "2.4" in str(exc.value)


def test_activating_a_product_push_task_succeeds_at_contract_2_4_control(db, monkeypatch):
    sorento = _connection(db, "sorento", {"baseUrl": "https://sorento.example.com"}, {"apiKey": "k"})
    company = _company(
        db, sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento.id, sorento_company_code="SRT",
    )
    api = _connection(db, "autocount", {"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"})
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(api.id))
    _stamp_previewed(db, company.id)
    monkeypatch.setattr(
        CompanyService, "contract_gate", lambda self, tenant_id, company, entity_type: None,
    )

    view = EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert view.etl_status == ETL_STATUS_ACTIVE


def test_activating_a_product_pull_task_is_never_refused_by_the_contract_gate(db, monkeypatch):
    """PULL mode gets the banner only (never blocked) even below 2.4 -
    nothing lands on the consumer until ITS OWN Confirm."""
    company = _company(db, sink_impl=SINK_IMPL_LOGGING, sorento_company_code="SRT")
    api = _connection(db, "autocount", {"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"})
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(api.id))
    _stamp_previewed(db, company.id)
    EtlService(db).set_delivery_mode(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, "pull")
    monkeypatch.setattr(
        CompanyService, "contract_gate",
        lambda self, tenant_id, company, entity_type: {
            "entity": entity_type, "version": None, "requiredVersion": 2.4,
        },
    )

    view = EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert view.etl_status == ETL_STATUS_ACTIVE


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_contract_gate_names_the_shortfall_for_a_product_company_below_2_4
#   dies if the coder copies the BRAND gate's fallback-to-logging-sink
#   behaviour for product instead of refusing activation (AC-10-69's own
#   "unlike the brand gate there is no safe logging-sink fallback").
# * test_activating_a_product_pull_task_is_never_refused_by_the_contract_gate
#   dies if the new activate-time check is not scoped to PUSH mode only.
# * test_contract_gate_brand_behaviour_is_unchanged_regression_control dies
#   if the no-Sorento-connection banner branch is added for EVERY entity
#   instead of ``product`` only, silently changing brand's own contract.
