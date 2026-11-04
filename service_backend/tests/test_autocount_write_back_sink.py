"""Plan 57 S5 (RED): `replaces_line_ref` on the Sorento sink (AC-57-50..52, plan 5.5).

Contract (plan 5.5): ``CanonicalPurchaseOrderLine`` / ``CanonicalShippingOrderLine`` /
``CanonicalSalesOrderLine`` gain optional ``replaces_line_ref`` (``{db}:{DocKey}:{DtlKey}``
of the deleted row). It is a FALLBACK field and an OMIT_WHEN_EMPTY field, and is sent only
when the consumer's ADVERTISED contract is >= ``REPLACES_LINE_REF_CONTRACT_VERSION =
ContractVersion(2, 12)`` (Sorento ingest uses ``extra="forbid"``). The advertised version
reaches a document line through ``sink_payload(contract_version=, advertised_contract=)``
(the keyword the linked documents already use); ``None`` = unknown = omitted.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.documents import (
    CanonicalPurchaseOrderLine,
    CanonicalSalesOrderLine,
    CanonicalShippingOrderLine,
)
from modules.autocount.sinks_sorento import ContractVersion, SorentoSink
from modules.autocount.write_back.doc_mapping import map_wrapper_document
from tests.test_autocount_write_back_operations import DEL_PO, PUT_PO, OpHarness, World  # noqa: F401
from tests.test_autocount_write_back_operations import db, h, w  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

REF = "AED_TEST:7001:700101"
LINE_MODELS = [CanonicalPurchaseOrderLine, CanonicalShippingOrderLine, CanonicalSalesOrderLine]
V212 = ContractVersion(2, 12)


def _line(model, **over):
    fields = dict(source_ref="AED_TEST:7001:1", product_ref="AED_TEST:P1", qty_ordered=Decimal("1"),
                  product_code="ITEM-1")
    fields.update(over)
    return model(**fields)


# ---- the constant and the model field ---------------------------------------------------

def test_ac_57_50_contract_constant_is_2_12_as_a_contract_version():
    from modules.autocount import sinks_sorento

    const = sinks_sorento.REPLACES_LINE_REF_CONTRACT_VERSION
    assert isinstance(const, ContractVersion) and (const.major, const.minor) == (2, 12)


@pytest.mark.parametrize("model", LINE_MODELS)
def test_ac_57_50_line_models_declare_optional_replaces_line_ref(model):
    assert "replaces_line_ref" in model.model_fields
    assert _line(model).replaces_line_ref is None
    assert "replaces_line_ref" in model.FALLBACK_FIELDS
    assert "replaces_line_ref" in model.OMIT_WHEN_EMPTY_FIELDS
    assert "replaces_line_ref" not in model.SINK_FIELDS  # never sent below contract 2


# ---- the gate ------------------------------------------------------------------------------

@pytest.mark.parametrize("model", LINE_MODELS)
def test_ac_57_50_sent_only_when_advertised_contract_is_2_12_or_more(model):
    line = _line(model, replaces_line_ref=REF)
    assert line.sink_payload(contract_version=2, advertised_contract=V212)["replaces_line_ref"] == REF
    assert line.sink_payload(contract_version=2, advertised_contract=ContractVersion(2, 13))["replaces_line_ref"] == REF
    assert line.sink_payload(contract_version=2, advertised_contract=ContractVersion(3, 0))["replaces_line_ref"] == REF


@pytest.mark.parametrize("model", LINE_MODELS)
@pytest.mark.parametrize("advertised", [None, ContractVersion(2, 11), ContractVersion(2, 2), 2.1, 2.0])
def test_ac_57_50_omitted_below_2_12_or_unknown(model, advertised):
    line = _line(model, replaces_line_ref=REF)
    assert "replaces_line_ref" not in line.sink_payload(contract_version=2, advertised_contract=advertised)


@pytest.mark.parametrize("model", LINE_MODELS)
def test_ac_57_50_omitted_for_a_v1_connection_even_when_advertised_high(model):
    line = _line(model, replaces_line_ref=REF)
    assert "replaces_line_ref" not in line.sink_payload(contract_version=1, advertised_contract=V212)


def test_ac_57_50_ten_is_not_two_dot_one_a_2_10_advertisement_does_not_pass():
    line = _line(CanonicalPurchaseOrderLine, replaces_line_ref=REF)
    assert "replaces_line_ref" not in line.sink_payload(contract_version=2, advertised_contract=ContractVersion(2, 10))


@pytest.mark.parametrize("model", LINE_MODELS)
@pytest.mark.parametrize("empty", [None, ""])
def test_ac_57_50_absent_when_empty_never_null(model, empty):
    line = _line(model, replaces_line_ref=empty)
    assert "replaces_line_ref" not in line.sink_payload(contract_version=2, advertised_contract=V212)


def test_ac_57_50_existing_payload_unchanged_when_the_field_is_unset():
    line = _line(CanonicalPurchaseOrderLine)
    with_gate = line.sink_payload(contract_version=2, advertised_contract=V212)
    without = line.sink_payload(contract_version=2)
    assert with_gate == without


# ---- wire projection through the real sink ---------------------------------------------------

def _po_record(h, w):
    doc = h.vendor.find("PO", 7001)
    _entity, rec = map_wrapper_document(h.db, tenant_id=DEFAULT_TENANT_ID, company=h.company, doc=doc, kind="PO")
    rec.lines[0].replaces_line_ref = REF
    return rec


@pytest.mark.parametrize("advertised,expect", [(V212, True), (ContractVersion(2, 11), False), (None, False)])
def test_ac_57_50_sorento_sink_projects_the_field_by_advertised_contract(h, w, advertised, expect):
    sink = SorentoSink(base_url="http://x", api_key="k", entity_type="purchase_order",
                       company_code="SOR", contract_version=2)
    sink.advertised_contract_version = advertised
    wire = sink._to_records([_po_record(h, w)])[0]["lines"]
    assert [("replaces_line_ref" in line) for line in wire] == [expect, False, False, False]
    if expect:
        assert wire[0]["replaces_line_ref"] == REF


# ---- operation to push --------------------------------------------------------------------------

def _pushed(h):
    return [r for r in h.sink_calls if hasattr(r, "lines")]


def test_ac_57_50_link_row_push_carries_old_ref_on_the_new_line_only(h, w):
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "done", res.error_code
    (old_key, new_key), = res.replaced_lines
    pushed = _pushed(h)
    assert pushed, "the read-back document must go out through the sink"
    rec = pushed[-1]
    by_dtl = {line.source_ref.rsplit(":", 1)[-1]: line for line in rec.lines}
    assert by_dtl[str(new_key)].replaces_line_ref == f"AED_TEST:7001:{old_key}"
    others = [line for key, line in by_dtl.items() if key != str(new_key)]
    assert len(others) == 3 and all(line.replaces_line_ref is None for line in others)
    wire = rec.sink_payload(contract_version=2, advertised_contract=V212)["lines"]
    assert sum("replaces_line_ref" in line for line in wire) == 1
    old_wire = rec.sink_payload(contract_version=2, advertised_contract=ContractVersion(2, 11))["lines"]
    assert not any("replaces_line_ref" in line for line in old_wire)


def test_ac_57_50_unlink_and_spo_operations_carry_the_ref_too(h, w):
    res = h.run("unlink_row", w.params["unlink_row"])
    (old_key, new_key), = res.replaced_lines
    line = next(l for l in _pushed(h)[-1].lines if l.source_ref.endswith(f":{new_key}"))
    assert line.replaces_line_ref == f"AED_TEST:7001:{old_key}"
    h.sink_calls.clear()
    res = h.run("spo_relink_row", w.params["spo_relink_row"], key="idem-2")
    (old_key, new_key), = res.replaced_lines
    rec = _pushed(h)[-1]
    line = next(l for l in rec.lines if l.source_ref.endswith(f":{new_key}"))
    assert rec.source_ref == "AED_TEST:7003" and line.replaces_line_ref == f"AED_TEST:7003:{old_key}"


def test_ac_57_50_a_later_ordinary_edit_does_not_repeat_the_old_ref(h, w):
    h.run("link_row", w.params["link_row"])
    h.sink_calls.clear()
    res = h.edit("PO", 7001, {"Remark1": "later"})
    assert res.outcome == "done", res.error_code
    rec = _pushed(h)[-1]
    assert all(line.replaces_line_ref is None for line in rec.lines)


def test_ac_57_50_recovery_re_added_line_carries_the_ref_of_the_deleted_row(h, w):
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "add failed")
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "recovered"
    (old_key, new_key), = res.replaced_lines
    line = next(l for l in _pushed(h)[-1].lines if l.source_ref.endswith(f":{new_key}"))
    assert line.replaces_line_ref == f"AED_TEST:7001:{old_key}"


def test_ac_57_50_a_refused_operation_pushes_nothing(h):
    world = World(h)  # delete flag off
    res = h.run("link_row", world.params["link_row"])
    assert res.outcome == "refused"
    assert _pushed(h) == []


def test_ac_57_52_quotation_is_never_pushed_by_any_primitive(h):
    created = h.create("QT")
    assert created.outcome == "done"
    from datetime import date

    h.edit("QT", created.doc_key, {"Remark1": "x"})
    h.service().add_line(**h.args("QT", doc_key=created.doc_key, line={
        "ItemCode": "Z", "UOM": "UNIT", "Qty": 1, "UnitPrice": 1.0, "Location": "HQ"}, doc_date=date(2026, 11, 4)))
    assert h.sink_calls == []
