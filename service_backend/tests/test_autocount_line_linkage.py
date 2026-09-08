"""AutoCount document line linkage (PO/SPO line -> SO line, SPO line -> PO
line) - sprint-5/06 S1. Red tests written BEFORE the coder, against
`06-autocount-line-linkage-acceptance-criteria.md` Groups A, B, C
(AC-06-01..15).

Every name below is written to import cleanly even when the feature does not
exist yet: a not-yet-declared canonical field is read via
``model.model_fields.get(name)`` (None, never AttributeError); a not-yet-
declared transform is read via ``TRANSFORMS.get("string_list")``; a
not-yet-declared model (``FromSoExternal``) is read via
``getattr(documents_module, "FromSoExternal", None)``. A missing name fails
its OWN assertion (or an explicit ``pytest.fail`` naming what is missing),
never an import error for the whole module.

Some negative-space assertions (a field that must NEVER appear anywhere, e.g.
`CanonicalSalesOrderLine` gaining none of the linkage fields, or the header
scope refusing every line-only target) are already true today, before any
production code changes - the same style `test_autocount_spo_container_
number.py` used for `test_purchase_order_has_no_container_number_field`.
They stay green throughout and guard against a future regression rather than
proving the new feature exists; the report notes which tests these are.
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal

import pytest
import sqlalchemy as sa
from annotated_types import MaxLen
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool

import modules.autocount.canonical.documents as documents_module
from app.jobs.service import JobService
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE, JOB_NEEDS_REVIEW
from modules.autocount.canonical.documents import (
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
    CanonicalPurchaseOrderLine,
    CanonicalSalesOrderLine,
    CanonicalShippingOrderLine,
)
from modules.autocount.mapping import (
    SCOPE_HEADER,
    SCOPE_LINE,
    MappingEngine,
    MappingRow,
    TRANSFORMS,
    TransformError,
    flat_profile,
)
from modules.autocount.mapping_catalog import line_accepted_field_names, sorento_field_for
from modules.autocount.models import (
    RUN_MODE_MANUAL,
    RUN_MODE_RECONCILE,
    SOURCE_IMPL_SQL_DB,
    STAGED_OP_UPSERT,
    AcEntityConfig,
    AcFieldMapping,
    AcStagedRecord,
    AcSyncRun,
)
from modules.autocount.presets import (
    PO_PRESET,
    SO_PRESET,
    SPO_PRESET,
    PresetField,
    _PO_FINGERPRINT_QUERY,
    _PO_HEADER_QUERY,
    _PO_LINE_QUERY,
)
from modules.autocount.services.company_service import (
    AutocountServiceError,
    CompanyService,
    MappingWriteRow,
)
from modules.autocount.sql_source.runtime import RUNTIME
from modules.autocount.sync import AUTOCOUNT_SYNC
from tests.test_autocount_document_mapping import (
    _company,
    _document_config,
    _source_engine,
    _sql_connection,
)

DB = "AED_VSOFT"

# The eight canonical INPUT fields (Definitions section of the UAC) - never
# sent on the wire, only fed into engine minting.
INPUT_KEY_FIELDS = (
    "from_so_doc_key", "from_so_line_key",
    "from_so_external_doc_key", "from_so_external_line_key",
    "from_po_doc_key", "from_po_line_key",
)
INPUT_STR_FIELDS = ("from_so_external_db", "from_so_external_doc_no")
INPUT_FIELDS = INPUT_KEY_FIELDS + INPUT_STR_FIELDS

# The five WIRE fields (contract >= 2, FALLBACK_FIELDS gate).
WIRE_FIELDS = (
    "from_so_line_ref", "from_so_external", "from_so_numbers",
    "from_po_line_ref", "from_po_number",
)

DOCUMENT_LINE_MODELS = {
    ENTITY_PURCHASE_ORDER: CanonicalPurchaseOrderLine,
    ENTITY_SHIPPING_ORDER: CanonicalShippingOrderLine,
}


# ═══════════════════════════════════════════════════════════════════════════
# Group A - transform and canonical model (AC-06-01..04)
# ═══════════════════════════════════════════════════════════════════════════


def _string_list_fn():
    fn = TRANSFORMS.get("string_list")
    if fn is None:
        pytest.fail("mapping.TRANSFORMS has no 'string_list' transform yet (AC-06-01)")
    return fn


def test_string_list_splits_strips_drops_blanks_and_dedupes_preserving_first_occurrence():
    fn = _string_list_fn()
    assert fn("SO1, SO2,,SO1 ") == ["SO1", "SO2"]


@pytest.mark.parametrize("value", [None, ""])
def test_string_list_blank_passes_through_as_none(value):
    fn = _string_list_fn()
    assert fn(value) is None


def test_string_list_rejects_a_non_string_value_naming_it():
    fn = _string_list_fn()
    with pytest.raises(TransformError) as excinfo:
        fn(12345)
    assert "12345" in str(excinfo.value), str(excinfo.value)


def test_string_list_caps_at_50_entries_and_warns(caplog):
    fn = _string_list_fn()
    raw = ", ".join(f"SO{i}" for i in range(1, 60))  # 59 unique entries
    with caplog.at_level(logging.WARNING):
        result = fn(raw)
    assert result == [f"SO{i}" for i in range(1, 51)], result
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "no WARNING logged when the list was capped past 50 entries"


def test_string_list_rejects_an_entry_over_100_chars_after_strip():
    """Codex round finding 3 - `from_so_numbers`' own entries feed straight
    into `SO000012`-shaped doc numbers, which the contract caps at 100 chars
    each (the same cap `from_so_external_doc_no`/`from_po_number` carry). An
    over-cap entry must be a NAMED, per-field `TransformError` here - a
    Sorento 422 on the whole record is a worse failure mode than refusing
    the save. The cap is checked AFTER strip (leading/trailing whitespace
    does not count against it, same as every other length-checked field)."""
    fn = _string_list_fn()
    too_long = "S" * 101
    with pytest.raises(TransformError) as excinfo:
        fn(f"SO1, {too_long}")
    assert "100" in str(excinfo.value), str(excinfo.value)

    # Exactly 100 (after strip) is fine.
    exactly_100 = "S" * 100
    assert fn(f"  {exactly_100}  ") == [exactly_100]


def _field(model, name):
    field = model.model_fields.get(name)
    if field is None:
        pytest.fail(f"{model.__name__} has no '{name}' field yet (AC-06-02)")
    return field


def _assert_max_len(field, expected, *, model_name, field_name):
    assert any(isinstance(m, MaxLen) and m.max_length == expected for m in field.metadata), (
        f"{model_name}.{field_name} must carry max_length={expected} - metadata {field.metadata}"
    )


@pytest.mark.parametrize("model", [CanonicalPurchaseOrderLine, CanonicalShippingOrderLine])
def test_line_model_declares_the_eight_input_fields_optional_and_defaulting_none(model):
    for name in INPUT_KEY_FIELDS:
        field = _field(model, name)
        assert field.default is None, f"{model.__name__}.{name} must default to None"
    for name in INPUT_STR_FIELDS:
        field = _field(model, name)
        assert field.default is None
        _assert_max_len(field, 100, model_name=model.__name__, field_name=name)


@pytest.mark.parametrize("model", [CanonicalPurchaseOrderLine, CanonicalShippingOrderLine])
def test_line_model_declares_from_so_and_from_po_line_ref_as_optional_str_max_255(model):
    for name in ("from_so_line_ref", "from_po_line_ref"):
        field = _field(model, name)
        assert field.default is None
        _assert_max_len(field, 255, model_name=model.__name__, field_name=name)


@pytest.mark.parametrize("model", [CanonicalPurchaseOrderLine, CanonicalShippingOrderLine])
def test_line_model_declares_from_po_number_as_optional_str_max_100(model):
    field = _field(model, "from_po_number")
    assert field.default is None
    _assert_max_len(field, 100, model_name=model.__name__, field_name="from_po_number")


@pytest.mark.parametrize("model", [CanonicalPurchaseOrderLine, CanonicalShippingOrderLine])
def test_line_model_declares_from_so_external_as_an_optional_nested_model(model):
    _field(model, "from_so_external")
    ext_model = getattr(documents_module, "FromSoExternal", None)
    if ext_model is None:
        pytest.fail("canonical.documents has no FromSoExternal model yet (AC-06-02)")
    for name in ("db", "doc_key", "doc_no", "dtl_key"):
        assert name in ext_model.model_fields, f"FromSoExternal has no '{name}' field"


def test_from_so_external_db_is_a_required_non_blank_string_capped_at_100():
    """Codex round finding 2 - the engine only ever CONSTRUCTS a
    `FromSoExternal` when the mapped `from_so_external_db` resolved
    (`mapping.py`'s minting step); the "``db`` is set whenever the object
    exists" invariant this docstring already claims must actually be
    enforced by the model, or a future caller could mint `{"db": None}`
    onto the wire. `db` must be required (missing = ValidationError),
    non-blank (empty string = ValidationError) and capped at 100 chars
    like every other AutoCount code/name field."""
    ext_model = getattr(documents_module, "FromSoExternal", None)
    if ext_model is None:
        pytest.fail("canonical.documents has no FromSoExternal model yet (AC-06-02)")

    with pytest.raises(ValidationError):
        ext_model()
    with pytest.raises(ValidationError):
        ext_model(db="")
    with pytest.raises(ValidationError):
        ext_model(db="x" * 101)

    ok = ext_model(db="AED_VSOFT")
    assert ok.db == "AED_VSOFT"
    capped = ext_model(db="x" * 100)
    assert capped.db == "x" * 100


def test_sales_order_line_gains_none_of_the_linkage_fields():
    """Negative-space pin - already true today (guard against a future
    regression, not a red-before-implementation assertion)."""
    linkage = set(INPUT_FIELDS) | set(WIRE_FIELDS)
    present = linkage & set(CanonicalSalesOrderLine.model_fields)
    assert not present, f"CanonicalSalesOrderLine must not gain {sorted(present)}"


def _po_line_with_full_linkage(**overrides):
    fields = dict(
        source_ref=f"{DB}:D2:L1", product_ref=f"{DB}:P2", qty_ordered=Decimal("5"),
        product_code="ITEM-99",
        from_so_doc_key=45700100, from_so_line_key=45700148,
        from_so_external_db="AED_VSOFT", from_so_external_doc_key=12,
        from_so_external_doc_no="SO000012", from_so_external_line_key=99,
        from_po_doc_key=44909094, from_po_line_key=45021331,
        from_so_line_ref="AED_SORENTO:45700100:45700148",
        from_so_external={"db": "AED_VSOFT", "doc_key": 12, "doc_no": "SO000012", "dtl_key": 99},
        from_po_line_ref="AED_SORENTO:44909094:45021331",
        from_po_number="202606-S0018",
        from_so_numbers=["SO420374"],
    )
    fields.update(overrides)
    return CanonicalPurchaseOrderLine(**fields)


def test_v1_line_payload_omits_every_input_and_wire_field():
    line = _po_line_with_full_linkage()
    payload = line.sink_payload(contract_version=1)
    for name in INPUT_FIELDS + WIRE_FIELDS:
        assert name not in payload, f"{name} must not be sent at contract 1: {sorted(payload)}"


def test_v2_line_payload_carries_each_wire_field_when_set():
    line = _po_line_with_full_linkage()
    payload = line.sink_payload(contract_version=2)
    assert payload.get("from_so_line_ref") == "AED_SORENTO:45700100:45700148", payload
    assert payload.get("from_so_external") == {
        "db": "AED_VSOFT", "doc_key": 12, "doc_no": "SO000012", "dtl_key": 99,
    }, payload
    assert payload.get("from_so_numbers") == ["SO420374"], payload
    assert payload.get("from_po_line_ref") == "AED_SORENTO:44909094:45021331", payload
    assert payload.get("from_po_number") == "202606-S0018", payload


def test_v2_line_payload_never_carries_an_input_field():
    line = _po_line_with_full_linkage()
    payload = line.sink_payload(contract_version=2)
    for name in INPUT_FIELDS:
        assert name not in payload, f"input field {name} leaked onto the wire: {sorted(payload)}"


@pytest.mark.parametrize("name", WIRE_FIELDS)
def test_v2_line_payload_omits_a_wire_field_when_none_never_null(name):
    line = _po_line_with_full_linkage(**{name: None})
    payload = line.sink_payload(contract_version=2)
    assert name not in payload, f"{name} must be omitted, not null, when unset: {payload.get(name)!r}"


def test_v2_line_payload_omits_from_so_numbers_when_an_empty_list_never_empty_list():
    line = _po_line_with_full_linkage(from_so_numbers=[])
    payload = line.sink_payload(contract_version=2)
    assert "from_so_numbers" not in payload, payload.get("from_so_numbers")


def test_sales_order_line_payload_never_carries_any_linkage_field_at_any_version():
    """Negative-space pin - already true today."""
    line = CanonicalSalesOrderLine(source_ref="x:1", product_ref="x:P1", qty_ordered=Decimal("1"))
    for version in (1, 2, 3):
        payload = line.sink_payload(contract_version=version)
        for name in INPUT_FIELDS + WIRE_FIELDS:
            assert name not in payload, f"SO line must never carry {name}: {sorted(payload)}"


# ═══════════════════════════════════════════════════════════════════════════
# Group B - engine minting (AC-06-05..09)
# ═══════════════════════════════════════════════════════════════════════════

_HEADER_NUMBER_FIELD = {
    ENTITY_PURCHASE_ORDER: "po_number",
    ENTITY_SHIPPING_ORDER: "spo_number",
}
_REQUIRED_LINE_ROWS = [
    MappingRow("DtlKey", "source_ref", "string", SCOPE_LINE, is_required=True),
    MappingRow("ItemCode", "product_ref", "ref_product", SCOPE_LINE, is_required=True),
    MappingRow("Qty", "qty_ordered", "decimal", SCOPE_LINE, is_required=True),
]
_MISSING = object()


def _map_one_line(entity_type, extra_line_rows, raw_line_fields, *, database=DB):
    header_rows = [
        MappingRow("DocKey", "source_ref", "string", SCOPE_HEADER),
        MappingRow("DocNo", _HEADER_NUMBER_FIELD[entity_type], "string", SCOPE_HEADER),
        MappingRow("Status", "status", "string", SCOPE_HEADER),
    ]
    rows = header_rows + list(_REQUIRED_LINE_ROWS) + list(extra_line_rows)
    engine = MappingEngine(
        rows, entity_type=entity_type,
        profile=flat_profile(entity_type, ["DocKey"]), database_name=database,
    )
    raw = {
        "DocKey": "D1", "DocNo": "DOC-1", "Status": "open",
        "_lines": [{"DtlKey": "L1", "ItemCode": "P1", "Qty": "10", **raw_line_fields}],
    }
    mapped = engine.map_document(raw)
    assert mapped.ok, [e.message() for e in mapped.errors]
    [line] = mapped.record.lines
    assert line.source_ref == f"{database}:D1:L1", (
        "line ref composition must still run in the SAME per-line block as minting (AC-06-07)"
    )
    return line


@pytest.mark.parametrize("entity_type", [ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER])
def test_from_so_line_ref_is_minted_from_the_doc_key_and_line_key(entity_type):
    extra = [
        MappingRow("FromSODocKey", "from_so_doc_key", "int", SCOPE_LINE),
        MappingRow("FromSODtlKey", "from_so_line_key", "int", SCOPE_LINE),
    ]
    line = _map_one_line(
        entity_type, extra,
        {"FromSODocKey": "45700100", "FromSODtlKey": "45700148"},
        database="AED_SORENTO",
    )
    assert getattr(line, "from_so_line_ref", _MISSING) == "AED_SORENTO:45700100:45700148"


@pytest.mark.parametrize("entity_type", [ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER])
def test_from_so_line_ref_is_none_when_either_key_is_missing(entity_type):
    extra = [
        MappingRow("FromSODocKey", "from_so_doc_key", "int", SCOPE_LINE),
        MappingRow("FromSODtlKey", "from_so_line_key", "int", SCOPE_LINE),
    ]
    line = _map_one_line(
        entity_type, extra,
        {"FromSODocKey": "45700100", "FromSODtlKey": None},
        database="AED_SORENTO",
    )
    assert getattr(line, "from_so_line_ref", _MISSING) is None


@pytest.mark.parametrize("entity_type", [ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER])
def test_from_po_line_ref_is_minted_from_the_doc_key_and_line_key(entity_type):
    extra = [
        MappingRow("FromPODocKey", "from_po_doc_key", "int", SCOPE_LINE),
        MappingRow("FromPODtlKey", "from_po_line_key", "int", SCOPE_LINE),
    ]
    line = _map_one_line(
        entity_type, extra,
        {"FromPODocKey": "44909094", "FromPODtlKey": "45021331"},
        database="AED_SORENTO",
    )
    assert getattr(line, "from_po_line_ref", _MISSING) == "AED_SORENTO:44909094:45021331"


@pytest.mark.parametrize("entity_type", [ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER])
def test_from_po_line_ref_is_none_when_either_key_is_missing(entity_type):
    extra = [
        MappingRow("FromPODocKey", "from_po_doc_key", "int", SCOPE_LINE),
        MappingRow("FromPODtlKey", "from_po_line_key", "int", SCOPE_LINE),
    ]
    line = _map_one_line(
        entity_type, extra,
        {"FromPODocKey": None, "FromPODtlKey": "45021331"},
        database="AED_SORENTO",
    )
    assert getattr(line, "from_po_line_ref", _MISSING) is None


@pytest.mark.parametrize("entity_type", [ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER])
def test_from_so_external_is_minted_as_an_object_when_db_is_set(entity_type):
    extra = [
        MappingRow("ExtDb", "from_so_external_db", "string", SCOPE_LINE),
        MappingRow("ExtDocKey", "from_so_external_doc_key", "int", SCOPE_LINE),
        MappingRow("ExtDocNo", "from_so_external_doc_no", "string", SCOPE_LINE),
        MappingRow("ExtLineKey", "from_so_external_line_key", "int", SCOPE_LINE),
    ]
    line = _map_one_line(entity_type, extra, {
        "ExtDb": "AED_VSOFT", "ExtDocKey": "12", "ExtDocNo": "SO000012", "ExtLineKey": "99",
    })
    ext = getattr(line, "from_so_external", _MISSING)
    assert ext is not None and ext is not _MISSING, ext
    assert ext.db == "AED_VSOFT"
    assert ext.doc_key == 12
    assert ext.doc_no == "SO000012"
    assert ext.dtl_key == 99


@pytest.mark.parametrize("entity_type", [ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER])
def test_from_so_external_is_none_when_db_is_not_set_even_if_the_others_are(entity_type):
    extra = [
        MappingRow("ExtDb", "from_so_external_db", "string", SCOPE_LINE),
        MappingRow("ExtDocKey", "from_so_external_doc_key", "int", SCOPE_LINE),
        MappingRow("ExtDocNo", "from_so_external_doc_no", "string", SCOPE_LINE),
        MappingRow("ExtLineKey", "from_so_external_line_key", "int", SCOPE_LINE),
    ]
    line = _map_one_line(entity_type, extra, {
        "ExtDb": None, "ExtDocKey": "12", "ExtDocNo": "SO000012", "ExtLineKey": "99",
    })
    assert getattr(line, "from_so_external", _MISSING) is None


def _guard_task(session_factory, *, database, entity_type=ENTITY_PURCHASE_ORDER):
    db = session_factory()
    engine = _source_engine([], {})
    conn = _sql_connection(db, engine, database=database, name=f"src {database}")
    company = _company(db, conn.id, database=database, name=f"{database} Co")
    _document_config(db, company, conn.id, entity_type)
    return db, company


_REQUIRED_LINE_WRITE_ROWS = [
    MappingWriteRow(source_path="dtl_key", transform="string", sorento_field="source_ref", scope=SCOPE_LINE),
    MappingWriteRow(source_path="item_code", transform="ref_product", sorento_field="product_ref", scope=SCOPE_LINE),
    MappingWriteRow(source_path="qty_ordered", transform="decimal", sorento_field="qty_ordered", scope=SCOPE_LINE),
]


@pytest.mark.parametrize("field", ["from_so_line_ref", "from_so_external", "from_po_line_ref"])
def test_a_wire_minted_field_is_refused_as_a_line_mapping_target(session_factory, field):
    """AC-06-07 second half: an operator row targeting a wire-minted field is
    refused at save time - the catalog never offers it. Already true today
    (the field does not exist at all yet), and must stay true once Group C's
    catalog is built (the field must still never be an accepted target)."""
    db, company = _guard_task(session_factory, database=f"AED_MINT_{field.upper()}")
    try:
        service = CompanyService(db)
        rows = list(_REQUIRED_LINE_WRITE_ROWS) + [
            MappingWriteRow(source_path="SomeCol", transform="string", sorento_field=field, scope=SCOPE_LINE),
        ]
        with pytest.raises(AutocountServiceError) as excinfo:
            service.replace_mapping(
                DEFAULT_TENANT_ID, company.id, ENTITY_PURCHASE_ORDER, rows, line_rows_submitted=True,
            )
        assert field in str(excinfo.value), str(excinfo.value)
    finally:
        db.close()
        RUNTIME.dispose_all()


@pytest.mark.parametrize("entity_type", [ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER])
def test_a_doclist_only_line_sends_from_so_numbers_alone_with_no_ref_invented(entity_type):
    extra = [MappingRow("FromSODocList", "from_so_numbers", "string_list", SCOPE_LINE)]
    line = _map_one_line(entity_type, extra, {"FromSODocList": "SO1, SO2"})
    payload = line.sink_payload(contract_version=2)
    assert payload.get("from_so_numbers") == ["SO1", "SO2"], payload
    assert "from_so_line_ref" not in payload, payload
    assert getattr(line, "from_so_line_ref", _MISSING) is None


@pytest.mark.parametrize("entity_type", [ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER])
def test_product_code_travels_alongside_linkage_fields_on_the_same_v2_line(entity_type):
    extra = [
        MappingRow("ItemCode", "product_code", "string", SCOPE_LINE),
        MappingRow("FromSODocKey", "from_so_doc_key", "int", SCOPE_LINE),
        MappingRow("FromSODtlKey", "from_so_line_key", "int", SCOPE_LINE),
    ]
    line = _map_one_line(
        entity_type, extra,
        {"FromSODocKey": "45700100", "FromSODtlKey": "45700148"},
        database="AED_SORENTO",
    )
    payload = line.sink_payload(contract_version=2)
    assert payload.get("product_code") == "P1", payload
    assert payload.get("from_so_line_ref") == "AED_SORENTO:45700100:45700148", payload


# ═══════════════════════════════════════════════════════════════════════════
# Group C - catalog and presets (AC-06-10..15)
# ═══════════════════════════════════════════════════════════════════════════

LINE_LINKAGE_INPUT_TARGETS = INPUT_FIELDS


@pytest.mark.parametrize("entity_type", [ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER])
def test_line_catalog_offers_the_input_fields_plus_from_so_numbers_and_from_po_number(entity_type):
    names = line_accepted_field_names(entity_type)
    expected = set(LINE_LINKAGE_INPUT_TARGETS) | {"from_so_numbers", "from_po_number"}
    missing = expected - names
    assert not missing, f"{entity_type}: catalog missing {sorted(missing)}"
    for name in expected:
        assert sorento_field_for(entity_type, name, "line") == name, name


def test_sales_order_line_catalog_offers_none_of_the_linkage_targets():
    """Negative-space pin - already true today."""
    names = line_accepted_field_names(ENTITY_SALES_ORDER)
    linkage = set(LINE_LINKAGE_INPUT_TARGETS) | {
        "from_so_numbers", "from_po_number",
        "from_so_line_ref", "from_so_external", "from_po_line_ref",
    }
    present = linkage & names
    assert not present, f"sales_order line catalog must not offer {sorted(present)}"


@pytest.mark.parametrize("entity_type", [ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER])
def test_header_scope_refuses_every_line_only_linkage_target(entity_type):
    """Negative-space pin - already true today."""
    for name in LINE_LINKAGE_INPUT_TARGETS + ("from_so_line_ref", "from_so_external", "from_po_line_ref"):
        assert sorento_field_for(entity_type, name, "header") is None, name


def test_an_input_key_field_only_accepts_int_and_string_transforms(session_factory):
    db, company = _guard_task(session_factory, database="AED_INPUT_XFORM")
    try:
        service = CompanyService(db)
        ok_rows = list(_REQUIRED_LINE_WRITE_ROWS) + [
            MappingWriteRow(
                source_path="FromSODocKey", transform="int",
                sorento_field="from_so_doc_key", scope=SCOPE_LINE,
            ),
        ]
        try:
            service.replace_mapping(
                DEFAULT_TENANT_ID, company.id, ENTITY_PURCHASE_ORDER, ok_rows,
                line_rows_submitted=True,
            )
        except AutocountServiceError as exc:
            pytest.fail(f"'int' must be accepted for an input key field: {exc}")

        db.expire_all()
        bad_rows = list(_REQUIRED_LINE_WRITE_ROWS) + [
            MappingWriteRow(
                source_path="FromSODocKey", transform="decimal",
                sorento_field="from_so_doc_key", scope=SCOPE_LINE,
            ),
        ]
        with pytest.raises(AutocountServiceError) as excinfo:
            service.replace_mapping(
                DEFAULT_TENANT_ID, company.id, ENTITY_PURCHASE_ORDER, bad_rows,
                line_rows_submitted=True,
            )
        message = str(excinfo.value).lower()
        assert "from_so_doc_key" in message, message
        assert "transform" in message, message
    finally:
        db.close()
        RUNTIME.dispose_all()


def test_from_so_numbers_only_accepts_the_string_list_transform(session_factory):
    db, company = _guard_task(session_factory, database="AED_NUMBERS_XFORM")
    try:
        service = CompanyService(db)
        ok_rows = list(_REQUIRED_LINE_WRITE_ROWS) + [
            MappingWriteRow(
                source_path="FromSODocList", transform="string_list",
                sorento_field="from_so_numbers", scope=SCOPE_LINE,
            ),
        ]
        try:
            service.replace_mapping(
                DEFAULT_TENANT_ID, company.id, ENTITY_PURCHASE_ORDER, ok_rows,
                line_rows_submitted=True,
            )
        except AutocountServiceError as exc:
            pytest.fail(f"'string_list' must be accepted for from_so_numbers: {exc}")

        db.expire_all()
        bad_rows = list(_REQUIRED_LINE_WRITE_ROWS) + [
            MappingWriteRow(
                source_path="FromSODocList", transform="string",
                sorento_field="from_so_numbers", scope=SCOPE_LINE,
            ),
        ]
        with pytest.raises(AutocountServiceError) as excinfo:
            service.replace_mapping(
                DEFAULT_TENANT_ID, company.id, ENTITY_PURCHASE_ORDER, bad_rows,
                line_rows_submitted=True,
            )
        message = str(excinfo.value).lower()
        assert "from_so_numbers" in message, message
        assert "transform" in message, message
    finally:
        db.close()
        RUNTIME.dispose_all()


def test_from_po_number_only_accepts_the_string_transform(session_factory):
    """Codex round finding 4 - `from_po_number` was never named in
    `LINE_FIELD_ALLOWED_TRANSFORMS`, so `allowed is None` skipped the narrow-
    set check entirely and `int`/`decimal`/`ref_*` all saved onto it
    (`from_po_number` is a plain string field, `canonical/documents.py`).
    Locking it to `{"string"}` mirrors `from_so_external_db`/
    `from_so_external_doc_no` above."""
    db, company = _guard_task(session_factory, database="AED_PONUMBER_XFORM")
    try:
        service = CompanyService(db)
        ok_rows = list(_REQUIRED_LINE_WRITE_ROWS) + [
            MappingWriteRow(
                source_path="FromPODocNo", transform="string",
                sorento_field="from_po_number", scope=SCOPE_LINE,
            ),
        ]
        try:
            service.replace_mapping(
                DEFAULT_TENANT_ID, company.id, ENTITY_PURCHASE_ORDER, ok_rows,
                line_rows_submitted=True,
            )
        except AutocountServiceError as exc:
            pytest.fail(f"'string' must be accepted for from_po_number: {exc}")

        db.expire_all()
        for bad_transform in ("int", "decimal"):
            bad_rows = list(_REQUIRED_LINE_WRITE_ROWS) + [
                MappingWriteRow(
                    source_path="FromPODocNo", transform=bad_transform,
                    sorento_field="from_po_number", scope=SCOPE_LINE,
                ),
            ]
            with pytest.raises(AutocountServiceError) as excinfo:
                service.replace_mapping(
                    DEFAULT_TENANT_ID, company.id, ENTITY_PURCHASE_ORDER, bad_rows,
                    line_rows_submitted=True,
                )
            message = str(excinfo.value).lower()
            assert "from_po_number" in message, message
            assert "transform" in message, message
    finally:
        db.close()
        RUNTIME.dispose_all()


def test_from_po_number_refuses_a_ref_transform(session_factory):
    """The narrow set also blocks a `ref_*` transform - `from_po_number` is
    a plain scalar, never a reference field."""
    db, company = _guard_task(session_factory, database="AED_PONUMBER_REF")
    try:
        service = CompanyService(db)
        rows = list(_REQUIRED_LINE_WRITE_ROWS) + [
            MappingWriteRow(
                source_path="FromPODocNo", transform="ref_product",
                sorento_field="from_po_number", scope=SCOPE_LINE,
            ),
        ]
        with pytest.raises(AutocountServiceError) as excinfo:
            service.replace_mapping(
                DEFAULT_TENANT_ID, company.id, ENTITY_PURCHASE_ORDER, rows,
                line_rows_submitted=True,
            )
        message = str(excinfo.value).lower()
        assert "from_po_number" in message, message
    finally:
        db.close()
        RUNTIME.dispose_all()


def test_a_formula_row_may_not_target_from_so_numbers(session_factory):
    db, company = _guard_task(session_factory, database="AED_FORMULA_LIST")
    try:
        service = CompanyService(db)
        rows = list(_REQUIRED_LINE_WRITE_ROWS) + [
            MappingWriteRow(
                source_path="FromSODocList", transform="string_list",
                sorento_field="from_so_numbers", formula="upper(trim(value))",
                scope=SCOPE_LINE,
            ),
        ]
        with pytest.raises(AutocountServiceError) as excinfo:
            service.replace_mapping(
                DEFAULT_TENANT_ID, company.id, ENTITY_PURCHASE_ORDER, rows,
                line_rows_submitted=True,
            )
        message = str(excinfo.value).lower()
        assert "from_so_numbers" in message, message
        assert "list" in message, message
    finally:
        db.close()
        RUNTIME.dispose_all()


# ── sprint-5/06 review round S3: `string_list` is a line-linkage-only lock ──


def test_string_list_is_refused_on_a_non_list_line_target(session_factory):
    """AC-06-11's both-directions lock, generalised (review S3): `string_list`
    may target ONLY `from_so_numbers` - an ordinary line field like
    `product_name` is never named in `LINE_FIELD_ALLOWED_TRANSFORMS` at all
    (that check alone skips it, `allowed is None`), so this must still 422,
    naming both the field and the transform."""
    db, company = _guard_task(session_factory, database="AED_LIST_LOCK_LINE")
    try:
        service = CompanyService(db)
        rows = list(_REQUIRED_LINE_WRITE_ROWS) + [
            MappingWriteRow(
                source_path="Description", transform="string_list",
                sorento_field="product_name", scope=SCOPE_LINE,
            ),
        ]
        with pytest.raises(AutocountServiceError) as excinfo:
            service.replace_mapping(
                DEFAULT_TENANT_ID, company.id, ENTITY_PURCHASE_ORDER, rows,
                line_rows_submitted=True,
            )
        message = str(excinfo.value).lower()
        assert "product_name" in message, message
        assert "string_list" in message, message
    finally:
        db.close()
        RUNTIME.dispose_all()


def test_string_list_is_refused_on_any_header_target(session_factory):
    """No header field is ever list-shaped - `string_list` on `po_number`
    (or any other header target) must 422, naming both the field and the
    transform (the header path never even checked `LINE_LIST_FIELDS` before
    - the row would have saved as-is)."""
    db, company = _guard_task(session_factory, database="AED_LIST_LOCK_HEADER")
    try:
        service = CompanyService(db)
        rows = [
            MappingWriteRow(
                source_path="DocNo", transform="string_list",
                sorento_field="po_number", scope=SCOPE_HEADER,
            ),
        ]
        with pytest.raises(AutocountServiceError) as excinfo:
            service.replace_mapping(
                DEFAULT_TENANT_ID, company.id, ENTITY_PURCHASE_ORDER, rows,
            )
        message = str(excinfo.value).lower()
        assert "po_number" in message, message
        assert "string_list" in message, message
    finally:
        db.close()
        RUNTIME.dispose_all()


# ── sprint-5/06 review round nit: the cap warning names the SOURCE, not the
#    raw cell value ──────────────────────────────────────────────────────


def test_string_list_cap_warning_names_the_source_path_not_the_raw_value(caplog):
    """`MappingRow.coerce` passes its OWN `source_path` through to
    `t_string_list` for exactly this transform - the warning must name it
    (so an operator can find the offending row) and must never echo the full
    (potentially long) raw comma-separated cell back into the log."""
    row = MappingRow("FromSODocList", "from_so_numbers", "string_list", SCOPE_LINE)
    raw = ", ".join(f"SO{i}" for i in range(1, 60))  # 59 unique entries, caps at 50
    with caplog.at_level(logging.WARNING):
        result = row.coerce(raw)
    assert result == [f"SO{i}" for i in range(1, 51)], result
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "no WARNING logged when the list was capped past 50 entries"
    messages = [r.getMessage() for r in warnings]
    assert any("FromSODocList" in m for m in messages), messages
    assert not any("SO59" in m for m in messages), (
        f"the raw cell value must never be echoed into the warning: {messages}"
    )


# ── AC-06-12: `_PO_LINE_QUERY` gains the SO / source-PO joins + columns ────


def test_po_line_query_selects_the_seven_linkage_columns_via_the_new_joins():
    text = _PO_LINE_QUERY
    for fragment in (
        "d.FromSODtlKey AS FromSODtlKey",
        "so.DocKey AS FromSODocKey",
        "so.DocNo AS FromSODocNo",
        "d.FromSODocList AS FromSODocList",
        "CASE WHEN d.FromDocType = 'PO' THEN d.FromDocDtlKey END AS FromPODtlKey",
        "sh.DocKey AS FromPODocKey",
        "sh.DocNo AS FromPODocNo",
        "LEFT JOIN {database}.dbo.SODTL AS sd ON sd.DtlKey = d.FromSODtlKey",
        "LEFT JOIN {database}.dbo.SO AS so ON so.DocKey = sd.DocKey",
        "LEFT JOIN {database}.dbo.PODTL AS src ON src.DtlKey = d.FromDocDtlKey AND d.FromDocType = 'PO'",
        "LEFT JOIN {database}.dbo.PO AS sh ON sh.DocKey = src.DocKey",
    ):
        assert fragment in text, f"missing {fragment!r} in _PO_LINE_QUERY:\n{text}"
    assert "WHERE d.DocKey = :doc_key AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL" in text, text
    assert "UDF" not in text, "no per-company UDF column belongs in the shared preset text"
    assert SPO_PRESET.line_query == _PO_LINE_QUERY
    assert PO_PRESET.line_query == _PO_LINE_QUERY


# ── AC-06-13: header OUTER APPLY + fingerprint gain the four aggregates ────


def test_po_header_query_and_fingerprint_query_gain_the_four_link_aggregates():
    aggregates = (
        "SUM(CASE WHEN d.FromSODtlKey IS NOT NULL THEN 1 ELSE 0 END) AS LinkedSOCount",
        "SUM(d.FromSODtlKey) AS FromSOKeySum",
        "SUM(CASE WHEN d.FromDocType = 'PO' AND d.FromDocDtlKey IS NOT NULL THEN 1 ELSE 0 END) AS LinkedPOCount",
        "SUM(CASE WHEN d.FromDocType = 'PO' THEN d.FromDocDtlKey END) AS FromPOKeySum",
    )
    for fragment in aggregates:
        assert fragment in _PO_HEADER_QUERY, f"missing {fragment!r} in _PO_HEADER_QUERY OUTER APPLY"
        assert fragment in _PO_FINGERPRINT_QUERY, f"missing {fragment!r} in _PO_FINGERPRINT_QUERY"
    for exposed in (
        "l.LinkedSOCount AS LinkedSOCount", "l.FromSOKeySum AS FromSOKeySum",
        "l.LinkedPOCount AS LinkedPOCount", "l.FromPOKeySum AS FromPOKeySum",
    ):
        assert exposed in _PO_HEADER_QUERY, f"header does not expose {exposed!r}"


# ── AC-06-14: PO_PRESET.line / SPO_PRESET.line gain the six rows ──────────

LINE_LINKAGE_PRESET_FIELDS = (
    PresetField("FromSODocKey", "from_so_doc_key", "int"),
    PresetField("FromSODtlKey", "from_so_line_key", "int"),
    PresetField("FromSODocList", "from_so_numbers", "string_list"),
    PresetField("FromPODocKey", "from_po_doc_key", "int"),
    PresetField("FromPODtlKey", "from_po_line_key", "int"),
    PresetField("FromPODocNo", "from_po_number", "string"),
)


@pytest.mark.parametrize("preset", [PO_PRESET, SPO_PRESET], ids=["PO_PRESET", "SPO_PRESET"])
def test_po_and_spo_presets_gain_the_six_enabled_not_required_linkage_line_rows(preset):
    for expected in LINE_LINKAGE_PRESET_FIELDS:
        rows = [f for f in preset.line if f.canonical_field == expected.canonical_field]
        assert rows, f"{preset.label}: no line row targets {expected.canonical_field!r}"
        assert rows[0] == expected, f"{preset.label}: {rows[0]} != {expected}"
        assert rows[0].required is False


def test_so_preset_line_is_unchanged_by_the_line_linkage_rows():
    """Negative-space pin - already true today."""
    linkage_targets = {f.canonical_field for f in LINE_LINKAGE_PRESET_FIELDS}
    so_targets = {f.canonical_field for f in SO_PRESET.line}
    overlap = linkage_targets & so_targets
    assert not overlap, sorted(overlap)


def test_no_preset_row_targets_a_from_so_external_field():
    """Negative-space pin - already true today."""
    for preset in (PO_PRESET, SPO_PRESET, SO_PRESET):
        for field in preset.line:
            assert not field.canonical_field.startswith("from_so_external"), (
                f"{preset.label}: {field.canonical_field} must not be preset-sourced from Ref/UDF text"
            )


# ── AC-06-15: re-offer via a header aggregate value change ────────────────


def _po_link_rig(session_factory, *, database="AED_LINK_RESTAGE"):
    """A self-contained PO document task on a SQLite source whose header
    query computes a ``linked_so_count`` aggregate exactly the way
    ``_PO_HEADER_QUERY``'s new ``LinkedSOCount`` will (a subquery over the
    line table's own linkage column) - proven independently of the real
    preset text, which AC-06-12/13 pin on their own."""
    db = session_factory()
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE po_header (doc_key TEXT PRIMARY KEY, doc_no TEXT, "
            "status TEXT, doc_date TEXT, last_modified TEXT)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE po_line (dtl_key TEXT PRIMARY KEY, doc_key TEXT, "
            "item_code TEXT, qty_ordered TEXT, from_so_doc_key TEXT, from_so_dtl_key TEXT)"
        )
        for row in [
            ("D001", "PO-00001", "open", "2026-08-01", "2026-08-01 09:00:00"),
            ("D002", "PO-00002", "open", "2026-08-02", "2026-08-02 09:00:00"),
        ]:
            conn.exec_driver_sql("INSERT INTO po_header VALUES (?, ?, ?, ?, ?)", row)
        for row in [
            ("D001-1", "D001", "ITEM-A", "10", "45700100", None),
            ("D002-1", "D002", "ITEM-B", "5", None, None),
        ]:
            conn.exec_driver_sql("INSERT INTO po_line VALUES (?, ?, ?, ?, ?, ?)", row)

    conn_row = _sql_connection(db, engine, database=database, name=f"src {database}")
    company = _company(db, conn_row.id, database=database, name=f"{database} Co")

    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PURCHASE_ORDER,
        source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = {
        "connectionId": conn_row.id,
        "query": (
            "SELECT doc_key, doc_no, status, doc_date, last_modified, "
            "(SELECT COUNT(*) FROM po_line pl WHERE pl.doc_key = po_header.doc_key "
            "AND pl.from_so_dtl_key IS NOT NULL) AS linked_so_count FROM po_header"
        ),
        "lineQuery": (
            "SELECT dtl_key, item_code, qty_ordered, from_so_doc_key, from_so_dtl_key "
            "FROM po_line WHERE doc_key = :doc_key"
        ),
        "keyColumns": ["doc_key"],
        "watermarkColumn": "last_modified",
        "comparedColumns": [],
        "fromDate": "2026-01-01",
        "docDateColumn": "doc_date",
        "lineKeyColumn": "dtl_key",
        "lineProductColumn": "item_code",
        "lineWarehouseColumn": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileAt": "02:00",
    }
    config.result_columns = [
        "doc_key", "doc_no", "status", "doc_date", "last_modified", "linked_so_count",
    ]
    db.add(config)
    db.commit()
    db.refresh(config)

    def seed(scope, source_path, canonical_field, transform, *, required=False):
        db.add(AcFieldMapping(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
            entity_type=ENTITY_PURCHASE_ORDER, scope=scope, source_path=source_path,
            canonical_field=canonical_field, transform=transform,
            is_required=required, is_enabled=True,
        ))

    seed(SCOPE_HEADER, "doc_no", "po_number", "string", required=True)
    seed(SCOPE_HEADER, "status", "status", "string", required=True)
    seed(SCOPE_LINE, "dtl_key", "source_ref", "string", required=True)
    seed(SCOPE_LINE, "item_code", "product_ref", "ref_product", required=True)
    seed(SCOPE_LINE, "qty_ordered", "qty_ordered", "decimal", required=True)
    seed(SCOPE_LINE, "from_so_doc_key", "from_so_doc_key", "int")
    seed(SCOPE_LINE, "from_so_dtl_key", "from_so_line_key", "int")
    db.commit()
    return db, company, config, engine


def _run_po(db, company, mode):
    job = JobService(db).create_and_enqueue(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_PURCHASE_ORDER, "mode": mode},
    )
    db.refresh(job)
    return job


def _staged_for_po(db, job_id):
    return {
        record.source_ref: record
        for record in db.query(AcStagedRecord).filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID, AcStagedRecord.job_id == job_id,
        )
    }


def test_a_document_whose_only_change_is_a_newly_populated_fromsodtlkey_is_restaged_as_an_update(
    session_factory,
):
    db, company, config, engine = _po_link_rig(session_factory)
    try:
        job1 = _run_po(db, company, RUN_MODE_MANUAL)
        assert job1.status in (JOB_DONE, JOB_NEEDS_REVIEW), (job1.status, job1.error, job1.logs_json)
        first = _staged_for_po(db, job1.id)
        assert len(first) == 2, sorted(first)
        first_d001_ref = next(ref for ref in first if ref.endswith("D001"))
        before_lines = first[first_d001_ref].canonical_json.get("lines") or []
        assert before_lines and all(
            (line or {}).get("from_so_line_ref") is None for line in before_lines
        ), "no from_so_line_ref before FromSODtlKey is populated"

        # The ONLY change: FromSODtlKey (from_so_dtl_key) newly populated on
        # ONE line. Header LastModified is never touched.
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "UPDATE po_line SET from_so_dtl_key = '45700148' WHERE dtl_key = 'D001-1'"
            )
        db.expire_all()

        job2 = _run_po(db, company, RUN_MODE_RECONCILE)
        assert job2.status in (JOB_DONE, JOB_NEEDS_REVIEW), (job2.status, job2.error, job2.logs_json)
        run2 = db.query(AcSyncRun).filter(AcSyncRun.job_id == job2.id).one()
        second = _staged_for_po(db, job2.id)
        changed = [ref for ref in second if ref.endswith("D001")]
        assert changed, (
            f"D001 was not re-staged - run2 scanned={run2.rows_scanned} "
            f"updated={run2.updated_count} staged={sorted(second)}"
        )
        record = second[changed[0]]
        assert record.op == STAGED_OP_UPSERT
        lines = record.canonical_json.get("lines") or []
        assert lines, record.canonical_json
        assert lines[0].get("from_so_line_ref") == "AED_LINK_RESTAGE:45700100:45700148", lines[0]
        assert run2.updated_count >= 1
        assert run2.added_count == 0
    finally:
        db.close()
        RUNTIME.dispose_all()
