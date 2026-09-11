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
