"""Sprint-5/08 S4 - the ``brand`` entity: canonical shape, Sorento push path,
contract gate, 429 handling (AC-08-31..33, 35).

RED before the coder: ``modules/autocount/canonical/masters.py`` (read
2026-09-12) declares NO ``ENTITY_BRAND``/``CanonicalBrand`` at all - this
whole file fails COLLECTION with ImportError until S4 lands.
``sinks_sorento._ENTITY_PATH`` has no ``'brand'`` entry either, so
``SorentoSink(entity_type="brand", ...)`` raises ``SorentoSinkError`` at
construction TODAY - pinned explicitly in
``test_sorento_entity_path_brand_is_brands``/``test_sink_429_...`` below so a
coder who adds the entity to ``ENTITY_PROFILES`` but forgets ``_ENTITY_PATH``
still sees a named failure.

Design assumption pinned for the coder (AC-08-33): ``sorento_supports_entity``
is extended with an optional keyword so the plain 2-arg membership check used
by every OTHER entity is untouched (`sorento_supports_entity(entity_type)`
stays byte-identical for non-brand callers). This file calls it as
``sorento_supports_entity("brand", contract_entities=..., contract_version=...)``
- a coder who names the kwargs differently will see a clean ``TypeError``
naming the mismatch, not a silent pass.
"""
from __future__ import annotations

from typing import List

import httpx
import pytest
from pydantic import ValidationError

from modules.autocount.canonical.masters import CanonicalBrand, ENTITY_BRAND
from modules.autocount.mapping import ENTITY_PROFILES
from modules.autocount.services.etl_service import ETL_ENTITY_TYPES
from modules.autocount.sinks import SINK_LOGGING, sink_for
from modules.autocount.sinks_sorento import (
    SorentoSink,
    SorentoSinkError,
    sorento_supports_entity,
)


# ── AC-08-31: entity registration + canonical shape ───────────────────────────


def test_entity_brand_registered_in_profiles_and_etl_entity_types():
    assert ENTITY_BRAND == "brand"
    assert ENTITY_BRAND in ENTITY_PROFILES
    assert ENTITY_BRAND in ETL_ENTITY_TYPES


def test_canonical_brand_fields_and_sink_fields():
    record = CanonicalBrand(
        source_ref="MOCHA:SORENTO", code="SORENTO", name="Sorento", description="d", is_active=True,
    )
    payload = record.sink_payload()
    assert set(payload) <= {"source_ref", "source_doc_no", "code", "name", "description", "is_active"}
    assert payload["code"] == "SORENTO"


def test_code_over_50_chars_rejected():
    with pytest.raises(ValidationError):
        CanonicalBrand(source_ref="MOCHA:X", code="X" * 51, name="ok")


def test_name_over_150_chars_rejected():
    with pytest.raises(ValidationError):
        CanonicalBrand(source_ref="MOCHA:X", code="OK", name="Y" * 151)


# ── AC-08-32: Sorento entity path + dependent-entity retryable tolerance ─────


def test_sorento_entity_path_brand_is_brands():
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"summary": {"created": 1}, "records": [{"source_ref": "MOCHA:S", "outcome": "created"}]})

    sink = SorentoSink(
        base_url="https://sorento.example.com", api_key="k", entity_type=ENTITY_BRAND,
        transport=httpx.MockTransport(handler),
    )
    record = CanonicalBrand(source_ref="MOCHA:SORENTO", code="SORENTO", name="Sorento")
    sink.write_batch([record], request_id="req-1")
    assert any("/ingest/brands" in str(c.url) for c in calls)


def test_logging_sink_handles_brand_with_no_change():
    from modules.autocount.sinks import LoggingSink  # noqa: F401 - existence check

    sink = sink_for(SINK_LOGGING)
    record = CanonicalBrand(source_ref="MOCHA:SORENTO", code="SORENTO", name="Sorento")
    result = sink.write(record, request_id="req-1")
    assert result.delivered is False
    assert result.sink == SINK_LOGGING


# ── AC-08-33: contract gate (2.2 = logging fallback, 2.3 = real push) ────────


def test_supports_brand_false_on_2_2_contract():
    assert sorento_supports_entity(
        ENTITY_BRAND, contract_version=2.2, contract_entities=["suppliers", "customers"]
    ) is False


def test_supports_brand_true_on_2_3_with_brands_entity():
    assert sorento_supports_entity(
        ENTITY_BRAND, contract_version=2.3, contract_entities=["suppliers", "brands"]
    ) is True


def test_supports_brand_false_when_entity_missing_even_at_2_3():
    assert sorento_supports_entity(
        ENTITY_BRAND, contract_version=2.3, contract_entities=["suppliers"]
    ) is False


# ── S2 (sprint-5/08 review round 1) - the gate has a REAL caller now ────────
#
# Before this fix ``fetch_contract`` returned ONLY the truncated MAJOR int
# (``contract_major`` floors "2.3" to 2), so ``contract_version >= 2.3`` could
# never be true even against a genuinely-2.3 consumer, and neither call site
# (`company_service.sink_for_company` / `sync_service.preview`) passed the
# gate kwargs at all - `sorento_supports_entity("brand")` (no kwargs)
# always answers False, so the gate could never OPEN.


def test_fetch_contract_detail_parses_full_version_and_entities():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"version": "2.3", "entities": ["suppliers", "brands"]})

    sink = SorentoSink(
        base_url="https://sorento.example.com", api_key="k", entity_type=ENTITY_BRAND,
        transport=httpx.MockTransport(handler),
    )
    detail = sink.fetch_contract_detail()
    assert detail is not None
    assert detail.version == 2.3
    assert detail.entities == ["suppliers", "brands"]


def test_fetch_contract_detail_none_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    sink = SorentoSink(
        base_url="https://sorento.example.com", api_key="k", entity_type=ENTITY_BRAND,
        transport=httpx.MockTransport(handler),
    )
    assert sink.fetch_contract_detail() is None


def test_fetch_contract_detail_parses_a_three_part_patch_version():
    """Nit (sprint-5/08 review round 2) - a bare ``float()`` rejects a
    three-part semver-style version string (``"2.3.1"``) outright, so a
    consumer advertising a patch version could never open the brand gate at
    all. Parse major.minor from the first two dot-separated ints instead."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"version": "2.3.1", "entities": ["brands"]})

    sink = SorentoSink(
        base_url="https://sorento.example.com", api_key="k", entity_type=ENTITY_BRAND,
        transport=httpx.MockTransport(handler),
    )
    detail = sink.fetch_contract_detail()
    assert detail is not None
    assert detail.version == 2.3


@pytest.fixture
def _brand_gate_rig(session_factory):
    from app.models import DEFAULT_TENANT_ID
    from app.models.connection import Connection
    from app.secrets import encrypt_secret
    from modules.autocount.models import AcCompany, SINK_IMPL_SORENTO

    db = session_factory()
    source_conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Vendor",
        config_json={"baseUrl": "https://ac.example.com", "auth": "basic"},
        credentials_json=encrypt_secret({"appId": "a", "password": "p"}), is_active=True,
    )
    sorento_conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sorento", type="erp", name="Sorento",
        config_json={"baseUrl": "https://sorento.example.com"},
        credentials_json=encrypt_secret({"apiKey": "k"}), is_active=True,
    )
    db.add_all([source_conn, sorento_conn])
    db.commit()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=source_conn.id,
        database_name="MOCHA", company_name="Mocha", name="Mocha", is_active=True,
        sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento_conn.id,
        sorento_company_code="MOCHA",
    )
    db.add(company)
    db.commit()
    yield db, company
    db.close()


def test_sink_for_company_brand_opens_on_2_3_with_brands_entity(monkeypatch, _brand_gate_rig):
    from app.models import DEFAULT_TENANT_ID
    from modules.autocount.services.company_service import CompanyService
    from modules.autocount.sinks_sorento import SorentoContractInfo

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.3, entities=["brands"]),
    )
    db, company = _brand_gate_rig
    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_BRAND)
    assert isinstance(sink, SorentoSink)
    assert hasattr(sink, "dry_run")


def test_sink_for_company_brand_falls_back_to_logging_on_2_2_contract(monkeypatch, _brand_gate_rig):
    from app.models import DEFAULT_TENANT_ID
    from modules.autocount.services.company_service import CompanyService
    from modules.autocount.sinks_sorento import SorentoContractInfo

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.2, entities=["suppliers", "customers"]),
    )
    db, company = _brand_gate_rig
    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_BRAND)
    assert sink.name == SINK_LOGGING


# ── S5 (sprint-5/08 review round 1 follow-up, AC-08-33/AC-08-20 S5) ─────────
# `EtlService.get_task`/`_task_view` surface the SAME live contract gate on
# the READ path (`EtlTaskView.brand_contract_gate`), not only at push time -
# the Review & Activate banner must be there the moment the tab opens,
# never only after the operator clicks Preview/Run.


def test_get_task_brand_contract_gate_populated_on_2_2_contract(monkeypatch, _brand_gate_rig):
    from app.models import DEFAULT_TENANT_ID
    from modules.autocount.services.etl_service import EtlService
    from modules.autocount.sinks_sorento import SorentoContractInfo

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.2, entities=["suppliers", "customers"]),
    )
    db, company = _brand_gate_rig
    view = EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, ENTITY_BRAND)
    assert view.brand_contract_gate == {"version": 2.2, "requiredVersion": 2.3}


def test_get_task_brand_contract_gate_none_once_2_3_advertises_brands(monkeypatch, _brand_gate_rig):
    from app.models import DEFAULT_TENANT_ID
    from modules.autocount.services.etl_service import EtlService
    from modules.autocount.sinks_sorento import SorentoContractInfo

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.3, entities=["brands"]),
    )
    db, company = _brand_gate_rig
    view = EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, ENTITY_BRAND)
    assert view.brand_contract_gate is None


def test_get_task_brand_contract_gate_none_for_a_non_brand_entity(monkeypatch, _brand_gate_rig):
    from app.models import DEFAULT_TENANT_ID
    from modules.autocount.services.etl_service import EtlService
    from modules.autocount.sinks_sorento import SorentoContractInfo

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.2, entities=["suppliers"]),
    )
    db, company = _brand_gate_rig
    view = EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, "product")
    assert view.brand_contract_gate is None


# ── SF-1 (sprint-5/08 review round 2) - the READ-path probe must not share the
# push path's 300s ``autocount_sink_timeout_seconds`` budget, and must not
# re-hit the network on every call within the same request. ──────────────────


def test_brand_contract_gate_probe_uses_its_own_short_timeout_not_the_push_budget(
    monkeypatch, _brand_gate_rig
):
    import modules.autocount.services.company_service as company_module
    from app.models import DEFAULT_TENANT_ID
    from modules.autocount.services.company_service import CompanyService

    captured: dict = {}
    real = company_module.sorento_sink_from_connection

    def spy(config, credentials, *, entity_type, company_code=None, transport=None, **kw):
        captured.update(kw)
        return real(
            config, credentials, entity_type=entity_type, company_code=company_code,
            transport=transport, **kw,
        )

    monkeypatch.setattr(company_module, "sorento_sink_from_connection", spy)
    monkeypatch.setattr(SorentoSink, "fetch_contract_detail", lambda self: None)
    db, company = _brand_gate_rig
    CompanyService(db).brand_contract_gate(DEFAULT_TENANT_ID, company)
    assert "timeout" in captured, "the read-path probe must pass its own timeout override"
    assert captured["timeout"] != 300  # never the 300s push budget (app/config.py:360)
    assert captured["timeout"] <= 10


def test_brand_contract_gate_memoises_the_probe_per_service_instance(monkeypatch, _brand_gate_rig):
    from app.models import DEFAULT_TENANT_ID
    from modules.autocount.services.company_service import CompanyService
    from modules.autocount.sinks_sorento import SorentoContractInfo

    calls = {"n": 0}

    def counted(self):
        calls["n"] += 1
        return SorentoContractInfo(version=2.2, entities=["suppliers"])

    monkeypatch.setattr(SorentoSink, "fetch_contract_detail", counted)
    db, company = _brand_gate_rig
    service = CompanyService(db)
    first = service.brand_contract_gate(DEFAULT_TENANT_ID, company)
    second = service.brand_contract_gate(DEFAULT_TENANT_ID, company)
    assert first == second == {"version": 2.2, "requiredVersion": 2.3}
    assert calls["n"] == 1, "the probe must be memoised per service instance/request"


def test_brand_contract_gate_raising_probe_yields_none_never_raises(monkeypatch, _brand_gate_rig):
    from app.models import DEFAULT_TENANT_ID
    from modules.autocount.services.company_service import CompanyService

    def boom(self):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(SorentoSink, "fetch_contract_detail", boom)
    db, company = _brand_gate_rig
    result = CompanyService(db).brand_contract_gate(DEFAULT_TENANT_ID, company)
    assert result is None


# ── AC-08-35: 429 mid-batch sleeps Retry-After capped at 60s, once, retries ──


def test_sink_429_mid_batch_sleeps_retry_after_capped_once_and_retries(monkeypatch):
    import modules.autocount.sinks_sorento as sinks_sorento_module

    sleeps: List[float] = []
    monkeypatch.setattr(sinks_sorento_module.time, "sleep", lambda s: sleeps.append(s))

    attempts: List[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": "9999"}, json={"message": "slow down"})
        return httpx.Response(
            200, json={"summary": {"created": 1}, "records": [{"source_ref": "MOCHA:SORENTO", "outcome": "created"}]}
        )

    sink = SorentoSink(
        base_url="https://sorento.example.com", api_key="k", entity_type=ENTITY_BRAND,
        transport=httpx.MockTransport(handler),
    )
    record = CanonicalBrand(source_ref="MOCHA:SORENTO", code="SORENTO", name="Sorento")
    results = sink.write_batch([record], request_id="req-1")

    assert len(attempts) == 2  # one 429, one retry that succeeded
    assert sleeps == [60]  # capped, slept exactly once
    assert results[0].outcome == "created"
