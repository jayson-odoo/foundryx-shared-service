"""INGEST-LINE-DROP-GUARD (SS side).

At Sorento contract 1 every document line loses ``product_code`` (and the
linkage refs), and since the CRM matches a line's product by CODE only, the CRM
drops every such line SILENTLY. Two guards:

1. A Sorento connection with NO stored ``sorentoContractVersion`` (or a value
   that is not a version) resolves to contract 2 - the floor every live CRM
   advertises - never to 1.
2. A sink explicitly set to contract 1 refuses to push (or dry-run) a document
   that carries lines, with a loud ``SorentoSinkError`` naming the fix, instead
   of stripping ``product_code`` off the wire.
"""
from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from modules.autocount.canonical.documents import (
    CanonicalArOutstanding,
    CanonicalArOutstandingDocument,
    CanonicalSalesOrder,
    CanonicalSalesOrderLine,
)
from modules.autocount.canonical.masters import CanonicalSupplier
from modules.autocount.sinks_sorento import (
    ENTITY_AR_OUTSTANDING,
    ENTITY_SALES_ORDER,
    ENTITY_SUPPLIER,
    SorentoSink,
    SorentoSinkError,
    sorento_sink_from_connection,
)
from modules.autocount.sorento_provider import SorentoProvider


def _so() -> CanonicalSalesOrder:
    return CanonicalSalesOrder(
        source_ref="db1:1", so_number="SO-1", status="open", customer_code="C001",
        lines=[
            CanonicalSalesOrderLine(
                source_ref="db1:1:10", product_ref="p1", qty_ordered=Decimal("1"),
                product_code="ITEM-A",
            )
        ],
    )


def _ok_transport(seen: list) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen.append(json.loads(request.content))
        return httpx.Response(
            200, json={"summary": {"total": 1, "created": 1}, "records": []}
        )

    return httpx.MockTransport(handle)


@pytest.mark.parametrize("stored", [None, "", "  ", "abc"])
def test_unset_contract_version_defaults_to_2(stored):
    config = {"baseUrl": "http://crm"}
    if stored is not None:
        config["sorentoContractVersion"] = stored
    sink = sorento_sink_from_connection(
        config, {"apiKey": "k" * 12}, entity_type=ENTITY_SALES_ORDER,
    )
    assert sink.contract_version == 2


@pytest.mark.parametrize("stored, expected", [("1", 1), ("2", 2), ("2.1", 2)])
def test_an_explicit_contract_version_is_honoured(stored, expected):
    sink = sorento_sink_from_connection(
        {"baseUrl": "http://crm", "sorentoContractVersion": stored},
        {"apiKey": "k" * 12}, entity_type=ENTITY_SALES_ORDER,
    )
    assert sink.contract_version == expected


def test_unset_connection_sends_product_code_on_every_line():
    seen: list = []
    sink = sorento_sink_from_connection(
        {"baseUrl": "http://crm"}, {"apiKey": "k" * 12},
        entity_type=ENTITY_SALES_ORDER, transport=_ok_transport(seen),
    )
    sink.write_batch([_so()], request_id="r1")
    line = seen[0]["records"][0]["lines"][0]
    assert line["product_code"] == "ITEM-A"


def test_contract_1_refuses_to_push_documents_with_lines():
    seen: list = []
    sink = SorentoSink(
        base_url="http://crm", api_key="k" * 12, entity_type=ENTITY_SALES_ORDER,
        transport=_ok_transport(seen), contract_version=1,
    )
    with pytest.raises(SorentoSinkError) as caught:
        sink.write_batch([_so()], request_id="r1")
    message = str(caught.value)
    assert "contract version 1" in message.lower()
    assert "product_code" in message
    assert "SO-1" in message or "db1:1" in message
    assert seen == [], "nothing may reach the CRM at contract 1"


def test_contract_1_refuses_a_document_dry_run_too():
    seen: list = []
    sink = SorentoSink(
        base_url="http://crm", api_key="k" * 12, entity_type=ENTITY_SALES_ORDER,
        transport=_ok_transport(seen), contract_version=1,
    )
    with pytest.raises(SorentoSinkError):
        sink.dry_run([_so()])
    assert seen == []


def test_contract_1_still_pushes_masters():
    seen: list = []
    sink = SorentoSink(
        base_url="http://crm", api_key="k" * 12, entity_type=ENTITY_SUPPLIER,
        transport=_ok_transport(seen), contract_version=1,
    )
    sink.write_batch(
        [CanonicalSupplier(source_ref="S1", code="S1", name="Supplier")],
        request_id="r1",
    )
    assert seen, "a master has no lines to drop; contract 1 stays allowed"


def test_contract_1_still_pushes_ar_outstanding():
    """AR outstanding's ``documents`` are not product lines: its wire shape
    never depended on the contract major, so nothing is stripped."""
    from datetime import datetime, timezone

    seen: list = []
    sink = SorentoSink(
        base_url="http://crm", api_key="k" * 12, entity_type=ENTITY_AR_OUTSTANDING,
        transport=_ok_transport(seen), contract_version=1,
    )
    record = CanonicalArOutstanding(
        source_ref="C001", customer_ref="C001", customer_code="C001",
        as_of=datetime(2026, 11, 4, tzinfo=timezone.utc),
        total_outstanding=Decimal("10"),
        lines=[CanonicalArOutstandingDocument(source_ref="db1:9", outstanding=Decimal("10"))],
    )
    sink.write_batch([record], request_id="r1")
    assert seen


def test_provider_test_treats_unset_version_as_2():
    """The connection Test must verify the version the sink will actually
    speak: unset = 2, so a CRM advertising 1.x fails the Test loudly."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/contract"):
            return httpx.Response(200, json={"version": "1.4"})
        return httpx.Response(200, json={"records": []})

    result = SorentoProvider().test(
        {"baseUrl": "http://crm"}, {"apiKey": "k" * 12},
        transport=httpx.MockTransport(handle),
    )
    assert result.ok is False
    assert "1.4" in result.message
