"""The Sorento connection's ``sorentoContractVersion`` gets a UI field.

Today the key exists only as a hand-set connection-config value (plan-02 test
report friction note): ``sorento_sink_from_connection`` reads
``int(config.get("sorentoContractVersion") or 1)`` and at 1 every PO/SO/SPO
``FALLBACK_FIELDS`` (``supplier_code``/``supplier_name``/``agent_code``, line
``product_code`` ...) is withheld - which is why a production Sorento cannot
back-create suppliers. The provider's ``fields()`` must expose it as a select
(mirroring ``smtp_provider``'s ``security`` select) so the operator opts in
from the edit form; an existing connection with no key stays at 1 (no
backfill); ``test()`` refuses a version Sorento's own ``/contract`` endpoint
says it cannot take (foolproof: never save what the consumer rejects).
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from modules.autocount.sinks_sorento import sorento_sink_from_connection
from modules.autocount.sorento_provider import SorentoProvider
from tests.test_integrations import _create, _demo_headers

CONTRACT_PATH = "/api/v1/external/contract"

EXPECTED_FIELD = {
    "key": "sorentoContractVersion",
    "label": "Contract version",
    "type": "select",
    "required": True,
    "defaultValue": "2",
    "options": [
        {"value": "1", "label": "1 (legacy)"},
        {"value": "2", "label": "2"},
    ],
}

SORENTO_PAYLOAD = {
    "provider": "sorento",
    "name": "Sorento",
    "config": {"baseUrl": "http://sorento.test"},
    "credentials": {"apiKey": "sk_test"},
}


def _by_key(fields: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {f["key"]: f for f in fields}


# ── (1) the form field ──────────────────────────────────────────────────────


def test_fields_expose_the_contract_version_as_a_select_after_base_url():
    fields = SorentoProvider().fields()
    assert [f["key"] for f in fields] == ["baseUrl", "sorentoContractVersion", "apiKey"]
    assert _by_key(fields)["sorentoContractVersion"] == EXPECTED_FIELD


def test_the_contract_version_field_is_displayable_config_not_a_secret():
    field = _by_key(SorentoProvider().fields())["sorentoContractVersion"]
    assert field.get("secret") is not True


# ── (2) the stored string reaches the sink as an int; absent stays 1 ───────


def test_a_stored_string_version_yields_an_int_contract_version_on_the_sink():
    sink = sorento_sink_from_connection(
        {"baseUrl": "http://sorento.test", "sorentoContractVersion": "2"},
        {"apiKey": "k"}, entity_type="supplier", company_code="C1",
    )
    assert sink.contract_version == 2


def test_a_connection_with_no_version_key_stays_on_contract_1():
    """Existing tenants are unchanged - no backfill; the operator opts in from
    the edit form."""
    sink = sorento_sink_from_connection(
        {"baseUrl": "http://sorento.test"},
        {"apiKey": "k"}, entity_type="supplier", company_code="C1",
    )
    assert sink.contract_version == 1


def test_a_stored_dotted_version_yields_its_major_on_the_sink():
    """``"2.0"`` is major 2 - the factory must parse a version, never
    ``int()`` the raw string (ValueError on the dotted form)."""
    sink = sorento_sink_from_connection(
        {"baseUrl": "http://sorento.test", "sorentoContractVersion": "2.0"},
        {"apiKey": "k"}, entity_type="supplier", company_code="C1",
    )
    assert sink.contract_version == 2


def test_an_unparseable_stored_version_falls_back_to_1_without_raising():
    sink = sorento_sink_from_connection(
        {"baseUrl": "http://sorento.test", "sorentoContractVersion": "abc"},
        {"apiKey": "k"}, entity_type="supplier", company_code="C1",
    )
    assert sink.contract_version == 1


def test_fetch_contract_parses_a_dotted_advertised_version_to_its_major():
    """The only pre-existing ``fetch_contract`` case serves the int ``2``
    (test_autocount_document_mapping); a 2.1 Sorento answers ``"2.1"``."""
    from modules.autocount.sinks_sorento import SorentoSink

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"version": "2.1"})
    )
    sink = SorentoSink(
        base_url="http://sorento.test", api_key="k", entity_type="supplier",
        transport=transport,
    )
    assert sink.fetch_contract() == 2


# ── (3) the edit form's partial PATCH keeps baseUrl ─────────────────────────


def test_patching_only_the_contract_version_keeps_base_url(client):
    h = _demo_headers(client)
    created = _create(client, h, SORENTO_PAYLOAD)
    res = client.patch(
        f"/integrations/connections/{created['id']}",
        json={"config": {"sorentoContractVersion": "2"}},
        headers=h,
    )
    assert res.status_code == 200, res.text
    cfg = res.json()["config"]
    assert cfg["sorentoContractVersion"] == "2"
    assert cfg["baseUrl"] == "http://sorento.test"


# ── (4) test() checks the chosen version against Sorento's advertised one ──


def _sorento(advertised: Any, seen: Dict[str, Any]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == CONTRACT_PATH:
            seen["contract_method"] = request.method
            seen["contract_x_api_key"] = request.headers.get("X-API-Key")
            return httpx.Response(200, json={"version": advertised})
        return httpx.Response(200, json={"items": []})

    return httpx.MockTransport(handler)


def _test(config: Dict[str, Any], advertised: Any, seen: Dict[str, Any] | None = None):
    return SorentoProvider().test(
        config, {"apiKey": "sk_live"}, transport=_sorento(advertised, seen if seen is not None else {})
    )


def test_test_gets_the_contract_endpoint_with_the_api_key():
    seen: Dict[str, Any] = {}
    result = _test({"baseUrl": "http://sorento.test", "sorentoContractVersion": "2"}, 2, seen)
    assert result.ok is True, result.message
    assert seen.get("contract_method") == "GET"
    assert seen.get("contract_x_api_key") == "sk_live"


def test_test_refuses_a_chosen_major_above_the_advertised_major_naming_both():
    result = _test({"baseUrl": "http://sorento.test", "sorentoContractVersion": "2"}, 1)
    assert result.ok is False
    assert "2" in result.message and "1" in result.message
    assert "contract" in result.message.lower()


def test_test_passes_when_advertised_2_1_and_chosen_2():
    """The pass must be a VERIFIED pass (review B1): the message names the
    advertised ``2.1``, never the advisory "could not be verified" wording an
    unparseable advertised version would fall back to - that path also says
    ok=True and would let a bad parser hide behind this test."""
    result = _test({"baseUrl": "http://sorento.test", "sorentoContractVersion": "2"}, "2.1")
    assert result.ok is True, result.message
    assert "2.1" in result.message
    assert "could not be verified" not in result.message


def test_test_passes_when_the_chosen_version_is_below_the_advertised_one():
    """A newer Sorento still takes an older payload - only a version the
    consumer cannot take is refused (the mismatch stays advisory elsewhere)."""
    result = _test({"baseUrl": "http://sorento.test", "sorentoContractVersion": "1"}, 2)
    assert result.ok is True, result.message


def test_test_treats_a_missing_version_key_as_1():
    result = _test({"baseUrl": "http://sorento.test"}, 1)
    assert result.ok is True, result.message
