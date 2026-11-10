"""AutoCount SO `UDFNote` -> Sorento `po_ref` (lane SS-PO-REF).

Partner of sorento-crm PR #1528 (`CanonicalSalesOrder.po_ref`, max 255,
`sorento_crm_backend/app/schemas/canonical_documents.py:269`). RED tests
written before the implementation.
"""
from __future__ import annotations

import pytest

from modules.autocount.canonical.documents import (
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
    CanonicalPurchaseOrder,
    CanonicalSalesOrder,
    CanonicalShippingOrder,
)
from modules.autocount.mapping import (
    SCOPE_HEADER,
    SCOPE_LINE,
    MappingEngine,
    MappingRow,
    build_mapping_rows_for_run,
    flat_profile,
)
from modules.autocount.mapping_catalog import accepted_field_names
from modules.autocount.presets import SO_PRESET, PresetField, plan_rows


def _so(**overrides) -> CanonicalSalesOrder:
    fields = dict(source_ref="AED:SO:1", so_number="SO-00001", status="open")
    fields.update(overrides)
    return CanonicalSalesOrder(**fields)


def test_canonical_sales_order_declares_po_ref_like_sorento():
    field = CanonicalSalesOrder.model_fields.get("po_ref")
    assert field is not None, "CanonicalSalesOrder has no `po_ref` field"
    assert field.default is None
    assert any(getattr(m, "max_length", None) == 255 for m in field.metadata), field.metadata
    assert "po_ref" in CanonicalSalesOrder.FALLBACK_FIELDS
    assert "po_ref" in CanonicalSalesOrder.OMIT_WHEN_EMPTY_FIELDS


def test_po_ref_over_255_is_rejected():
    with pytest.raises(ValueError):
        _so(po_ref="x" * 256)


def test_v2_payload_carries_po_ref_verbatim():
    payload = _so(po_ref="PO-4500 123", ref="ACME TOWER").sink_payload(contract_version=2)
    assert payload["po_ref"] == "PO-4500 123"
    assert payload["ref"] == "ACME TOWER"


@pytest.mark.parametrize("value", [None, ""])
def test_v2_payload_omits_an_empty_po_ref(value):
    assert "po_ref" not in _so(po_ref=value).sink_payload(contract_version=2)


def test_v1_payload_never_carries_po_ref():
    assert "po_ref" not in _so(po_ref="PO-1").sink_payload(contract_version=1)


@pytest.mark.parametrize("version", [1, 2])
def test_po_and_spo_never_carry_po_ref(version):
    assert "po_ref" not in CanonicalPurchaseOrder.model_fields
    assert "po_ref" not in CanonicalShippingOrder.model_fields
    po = CanonicalPurchaseOrder(
        source_ref="AED:PO:5", po_number="PO-5", status="open", supplier_code="400-J001",
    )
    spo = CanonicalShippingOrder(
        source_ref="AED:PO:7", spo_number="SPO-7", status="open", supplier_code="400-J001",
    )
    assert "po_ref" not in po.sink_payload(contract_version=version)
    assert "po_ref" not in spo.sink_payload(contract_version=version)


def test_mapping_catalog_offers_po_ref_for_sales_order_only():
    assert "po_ref" in accepted_field_names(ENTITY_SALES_ORDER)
    assert "po_ref" not in accepted_field_names(ENTITY_PURCHASE_ORDER)
    assert "po_ref" not in accepted_field_names(ENTITY_SHIPPING_ORDER)


def test_so_preset_header_maps_udfnote_to_po_ref():
    rows = [f for f in SO_PRESET.header if f.canonical_field == "po_ref"]
    assert rows == [PresetField("UDFNote", "po_ref", "string")], rows
    assert rows[0].required is False
    # `Ref -> ref` (the Project label feed) is untouched.
    assert [f for f in SO_PRESET.header if f.canonical_field == "ref"] == [
        PresetField("Ref", "ref", "string")
    ]


def test_preset_po_ref_row_seeds_disabled_when_the_query_lacks_udfnote():
    """The shared preset query never selects a per-company UDF column
    (SQL pack section 4b), so a task whose result columns lack `UDFNote`
    gets the row DISABLED, never a row that maps a missing column."""
    planned = plan_rows(
        SO_PRESET.header, ["DocKey", "DocNo", "Ref"],
        entity_type=ENTITY_SALES_ORDER, scope=SCOPE_HEADER,
    )
    po_ref = [p for p in planned if p.spec.canonical_field == "po_ref"]
    assert len(po_ref) == 1 and po_ref[0].is_enabled is False
    planned = plan_rows(
        SO_PRESET.header, ["DocKey", "DocNo", "Ref", "UDFNote"],
        entity_type=ENTITY_SALES_ORDER, scope=SCOPE_HEADER,
    )
    po_ref = [p for p in planned if p.spec.canonical_field == "po_ref"]
    assert len(po_ref) == 1 and po_ref[0].is_enabled is True


def test_map_document_end_to_end_udfnote_to_po_ref():
    rows = build_mapping_rows_for_run(
        ENTITY_SALES_ORDER,
        [
            MappingRow("DocKey", "source_ref", "string", SCOPE_HEADER),
            MappingRow("DocNo", "so_number", "string", SCOPE_HEADER),
            MappingRow("Status", "status", "string", SCOPE_HEADER),
            MappingRow("UDFNote", "po_ref", "string", SCOPE_HEADER),
            MappingRow("DtlKey", "source_ref", "string", SCOPE_LINE, is_required=True),
            MappingRow("ItemAutoKey", "product_ref", "ref_product", SCOPE_LINE, is_required=True),
            MappingRow("Qty", "qty_ordered", "decimal", SCOPE_LINE, is_required=True),
        ],
        is_sql_db_source=True, source_config={},
    )
    engine = MappingEngine(
        rows, entity_type=ENTITY_SALES_ORDER,
        profile=flat_profile(ENTITY_SALES_ORDER, ["DocKey"]), database_name="AED_X",
    )
    mapped = engine.map_document({
        "DocKey": "D1", "DocNo": "SO-1", "Status": "open", "UDFNote": "PO-4500 123",
        "_lines": [{"DtlKey": "L1", "ItemAutoKey": "P1", "Qty": "10"}],
    })
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.po_ref == "PO-4500 123"
    assert mapped.record.sink_payload(contract_version=2)["po_ref"] == "PO-4500 123"
