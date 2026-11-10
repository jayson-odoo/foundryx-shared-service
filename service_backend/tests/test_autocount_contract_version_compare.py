"""BL-SS-289 - CRM contract versions compare as (major, minor) integers.

CRM #1770 advertises ``"version": "2.10"``. Parsed as a float that is 2.1,
which is below every 2.x gate (2.3 .. 2.9) and would shut the brand, stock,
doc-feed, branch, linked-document and consignment gates the moment the CRM
answers 2.10. ``ContractVersion`` keeps the minor as an integer.
"""

import httpx
import pytest

from modules.autocount.sinks_sorento import (
    CONTRACT_GATED_ENTITIES,
    ContractVersion,
    SorentoSink,
    sorento_supports_entity,
)


def _sink(version_body):
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"version": version_body, "entities": ["brands", "delivery_orders"]})

    return SorentoSink(
        base_url="https://crm.example.test", api_key="k", entity_type="brand",
        transport=httpx.MockTransport(handle),
    )


@pytest.mark.parametrize(
    "text,major,minor",
    [("2.10", 2, 10), ("2.9", 2, 9), ("2.10.3", 2, 10), ("3", 3, 0), (" 2.7 ", 2, 7)],
)
def test_parse_keeps_minor_as_integer(text, major, minor):
    v = ContractVersion.parse(text)
    assert (v.major, v.minor) == (major, minor)
    assert str(v) == f"{major}.{minor}"


@pytest.mark.parametrize("bad", ["", "x", "2.x", None, True, "²", "2.²", "١٢", "٢.١٠", "9" * 5000, -3, "-2", "2.", 1e16])
def test_parse_rejects_non_versions(bad):
    assert ContractVersion.parse(bad) is None


def test_2_10_is_above_every_2_x_float_threshold():
    v = ContractVersion.parse("2.10")
    for threshold in (2.3, 2.4, 2.5, 2.7, 2.8, 2.9):
        assert v >= threshold
        assert threshold <= v
        assert not (v < threshold)
    assert v > ContractVersion(2, 9)
    assert v != 2.1
    assert ContractVersion(2, 1) == 2.1
    assert ContractVersion(2, 0) == 2


def test_compares_against_int_major():
    assert ContractVersion(2, 10) > 2
    assert ContractVersion(2, 0) >= 2
    assert not (ContractVersion(2, 10) > 3)


def test_fetch_contract_detail_parses_2_10_string():
    info = _sink("2.10").fetch_contract_detail()
    assert info is not None
    assert (info.version.major, info.version.minor) == (2, 10)


def test_fetch_contract_detail_numeric_body_unchanged():
    info = _sink(2.7).fetch_contract_detail()
    assert info.version == 2.7
    assert (info.version.major, info.version.minor) == (2, 7)


def test_every_existing_gate_stays_open_on_2_10():
    """Every gate up to 2.10 opens on a 2.10 CRM; plan 37's `item_class`
    (2.11) is the first gate above it and stays shut."""
    v = ContractVersion.parse("2.10")
    for entity_type, (required, name) in CONTRACT_GATED_ENTITIES.items():
        assert sorento_supports_entity(
            entity_type, contract_version=v, contract_entities=[name]
        ) is (v >= required), entity_type
    assert not sorento_supports_entity(
        "item_class", contract_version=v, contract_entities=["item_classes"]
    )


def test_equal_values_hash_equally():
    """Review N1: a version equal to a plain float/int finds it as a dict key."""
    assert {2.7: "x"}[ContractVersion(2, 7)] == "x"
    assert hash(ContractVersion(2, 0)) == hash(2)
    assert ContractVersion(2, 10) != 2.1
