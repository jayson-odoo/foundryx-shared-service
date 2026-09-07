"""Hotfix fix/spo-container-catalog: the Sorento target catalog must offer
``container_number`` for shipping orders, and must never drift from the
canonical model again.

Prod finding (#59 deployed): ``mapping_catalog._SPO_FALLBACK_FIELDS`` was not
extended with ``container_number`` while ``CanonicalShippingOrder.
FALLBACK_FIELDS`` was. Consequences: the Mapping tab shows the backfilled
``Ref -> Container number`` row under "Not delivered to Sorento"
(``sorento_field_for`` returns None); saving the SPO mapping runs
``delete_unknown(accepted | PRESERVED_CANONICAL_FIELDS)`` which DELETES the
row; and the PUT guard (AC-15-42) refuses to re-add it.

Red tests, written before the coder:
1. ``accepted_field_names(shipping_order)`` contains ``container_number``;
   ``sorento_field_for(shipping_order, "container_number", "header")`` is the
   wire name ``container_number``; it is not a required field.
2. ``purchase_order`` (and ``sales_order``) do NOT offer it (guard-green).
3. Save round-trip through ``CompanyService.replace_mapping`` (the Mapping
   tab's PUT path): the backfilled row survives a save that includes it
   (enabled, projected); a save WITHOUT it removes it - normal replace
   semantics, it is a deliverable row now, not provenance.
4. Parity pin: for every document entity the catalog's accepted HEADER set
   equals ``Canonical<X>.SINK_FIELDS + FALLBACK_FIELDS`` minus the minted
   identity (``source_ref``), derived from the canonical classes so a future
   model field without a catalog entry goes red. Line scope likewise, with
   the one legitimately non-mappable key pinned explicitly.
5. ``mapping_view`` projects the Ref row with ``sorento_field ==
   "container_number"`` and lists it in the picker catalog.
"""
from __future__ import annotations

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.documents import (
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
    CanonicalPurchaseOrder,
    CanonicalPurchaseOrderLine,
    CanonicalSalesOrder,
    CanonicalSalesOrderLine,
    CanonicalShippingOrder,
    CanonicalShippingOrderLine,
)
from modules.autocount.mapping import SCOPE_HEADER
from modules.autocount.mapping_catalog import (
    SORENTO_FIELDS,
    SORENTO_LINE_FIELDS,
    accepted_field_names,
    line_accepted_field_names,
    required_field_names,
    sorento_field_for,
)
from modules.autocount.models import AcFieldMapping
from modules.autocount.services.company_service import (
    AutocountServiceError,
    CompanyService,
    MappingWriteRow,
)
from modules.autocount.sql_source.runtime import RUNTIME
from tests.test_autocount_document_mapping import (
    _auth,
    _company,
    _document_config,
    _source_engine,
    _sql_connection,
)

DOCUMENT_MODELS = {
    ENTITY_SALES_ORDER: (CanonicalSalesOrder, CanonicalSalesOrderLine),
    ENTITY_PURCHASE_ORDER: (CanonicalPurchaseOrder, CanonicalPurchaseOrderLine),
    ENTITY_SHIPPING_ORDER: (CanonicalShippingOrder, CanonicalShippingOrderLine),
}

# Identity is minted by the engine, never mapped (mapping_catalog._MINTED_FIELDS).
MINTED_HEADER_FIELDS = frozenset({"source_ref"})
# `from_so_numbers` is derived by the engine from AutoCount's FromSODocList
# (addendum section 4), never an operator-mapped line target - the ONE
# legitimate difference between a line model's wire set and the picker.
ENGINE_DERIVED_LINE_FIELDS = frozenset({"from_so_numbers"})


# ── 1 + 2: the catalog itself ───────────────────────────────────────────────


def test_catalog_offers_container_number_as_an_optional_shipping_order_header_target():
    names = accepted_field_names(ENTITY_SHIPPING_ORDER)
    assert "container_number" in names, sorted(names)
    assert sorento_field_for(ENTITY_SHIPPING_ORDER, "container_number", "header") == (
        "container_number"
    )
    assert "container_number" not in required_field_names(ENTITY_SHIPPING_ORDER)
    # Header only - a line row targeting it is still refused.
    assert sorento_field_for(ENTITY_SHIPPING_ORDER, "container_number", "line") is None


@pytest.mark.parametrize("entity_type", [ENTITY_PURCHASE_ORDER, ENTITY_SALES_ORDER])
def test_catalog_does_not_offer_container_number_to_other_documents(entity_type):
    assert "container_number" not in accepted_field_names(entity_type)
    assert sorento_field_for(entity_type, "container_number", "header") is None


# ── 4: parity pin (this cannot recur) ───────────────────────────────────────


@pytest.mark.parametrize("entity_type", sorted(DOCUMENT_MODELS))
def test_header_catalog_equals_the_canonical_wire_set_minus_minted_identity(entity_type):
    """Derived from the canonical class, not spelled out: a field added to
    ``SINK_FIELDS``/``FALLBACK_FIELDS`` without a catalog entry (or the
    reverse) fails here by name."""
    header_model, _ = DOCUMENT_MODELS[entity_type]
    expected = (
        frozenset(header_model.SINK_FIELDS) | frozenset(header_model.FALLBACK_FIELDS)
    ) - MINTED_HEADER_FIELDS
    actual = accepted_field_names(entity_type)
    assert actual == expected, (
        f"{entity_type}: catalog missing {sorted(expected - actual)}, "
        f"catalog extra {sorted(actual - expected)}"
    )


@pytest.mark.parametrize("entity_type", sorted(DOCUMENT_MODELS))
def test_line_catalog_equals_the_canonical_line_wire_set_minus_engine_derived(entity_type):
    _, line_model = DOCUMENT_MODELS[entity_type]
    expected = (
        frozenset(line_model.SINK_FIELDS) | frozenset(line_model.FALLBACK_FIELDS)
    ) - ENGINE_DERIVED_LINE_FIELDS
    actual = line_accepted_field_names(entity_type)
    assert actual == expected, (
        f"{entity_type}: line catalog missing {sorted(expected - actual)}, "
        f"line catalog extra {sorted(actual - expected)}"
    )


def test_every_document_entity_with_a_wire_model_is_in_both_catalogs():
    for entity_type in DOCUMENT_MODELS:
        assert entity_type in SORENTO_FIELDS, entity_type
        assert entity_type in SORENTO_LINE_FIELDS, entity_type


# ── 3 + 5: the save path the Mapping tab uses, and its projection ──────────


def _spo_task(session_factory, *, database: str):
    """An SPO task exactly as the 0016 backfill leaves it: preset-shaped
    header rows plus the enabled ``Ref -> container_number`` row, and ``Ref``
    among the previewed result columns."""
    db = session_factory()
    engine = _source_engine([], {})
    conn = _sql_connection(db, engine, database=database, name=f"src {database}")
    company = _company(db, conn.id, database=database, name=f"{database} Co")
    config = _document_config(db, company, conn.id, ENTITY_SHIPPING_ORDER)
    config.result_columns = ["DocKey", "DocNo", "Cancelled", "DocDate", "LastModified", "Ref"]
    db.commit()
    for order, (source_path, canonical_field, required) in enumerate([
        ("DocNo", "spo_number", True),
        ("Cancelled", "status", True),
        ("Ref", "container_number", False),
    ]):
        db.add(AcFieldMapping(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
            entity_type=ENTITY_SHIPPING_ORDER, scope=SCOPE_HEADER,
            source_path=source_path, canonical_field=canonical_field, transform="string",
            is_required=required, is_enabled=True, sort_order=order,
        ))
    db.commit()
    return db, company


def _ref_rows(db, company_id: str):
    return (
        db.query(AcFieldMapping)
        .filter(
            AcFieldMapping.company_id == company_id,
            AcFieldMapping.entity_type == ENTITY_SHIPPING_ORDER,
            AcFieldMapping.scope == SCOPE_HEADER,
            AcFieldMapping.canonical_field == "container_number",
        )
        .all()
    )


def test_mapping_view_projects_the_backfilled_ref_row_as_delivered(session_factory):
    db, company = _spo_task(session_factory, database="AED_CAT_VIEW")
    try:
        view = CompanyService(db).mapping_view(DEFAULT_TENANT_ID, company.id, ENTITY_SHIPPING_ORDER)
        ref_rows = [row for row in view.rows if row.source_path == "Ref"]
        assert len(ref_rows) == 1, [(r.source_path, r.canonical_field) for r in view.rows]
        assert ref_rows[0].canonical_field == "container_number"
        assert ref_rows[0].sorento_field == "container_number", (
            "the Ref row is projected as 'Not delivered to Sorento'"
        )
        assert ref_rows[0].scope == SCOPE_HEADER
        picker = {f.field: f.required for f in view.sorento_fields}
        assert picker.get("container_number") is False, sorted(picker)
    finally:
        db.close()
        RUNTIME.dispose_all()


def test_saving_the_spo_mapping_with_the_ref_row_keeps_it(session_factory):
    """The Mapping tab's PUT re-submits every row it shows. With the row
    included the save must succeed (no 'not a Sorento field accepted for
    shipping_order' 422) and the row must still be there, enabled and
    projected, afterwards."""
    db, company = _spo_task(session_factory, database="AED_CAT_KEEP")
    try:
        service = CompanyService(db)
        rows = [
            MappingWriteRow(source_path="DocNo", transform="string", sorento_field="spo_number"),
            MappingWriteRow(source_path="Cancelled", transform="string", sorento_field="status"),
            MappingWriteRow(
                source_path="Ref", transform="string", sorento_field="container_number",
            ),
        ]
        try:
            view = service.replace_mapping(
                DEFAULT_TENANT_ID, company.id, ENTITY_SHIPPING_ORDER, rows,
            )
        except AutocountServiceError as exc:
            pytest.fail(f"saving the SPO mapping with its Ref row was refused: {exc}")

        db.expire_all()
        stored = _ref_rows(db, company.id)
        assert len(stored) == 1, "the Ref -> container_number row did not survive the save"
        assert stored[0].source_path == "Ref"
        assert stored[0].is_enabled is True
        assert stored[0].is_required is False
        projected = [r for r in view.rows if r.canonical_field == "container_number"]
        assert projected and projected[0].sorento_field == "container_number"
    finally:
        db.close()
        RUNTIME.dispose_all()


def test_saving_the_spo_mapping_without_the_ref_row_removes_it(session_factory):
    """Deliverable rows follow replace semantics (AC-15-41): an operator who
    drops the Ref row and saves gets exactly that - no stale row lingers as
    if it were provenance.

    Pre-fix finding (origin/main 148a2552): this SAME sweep is what removes
    the backfilled row when the editor omits it because the catalog projected
    it as not delivered - see the editor-shaped round trip below."""
    db, company = _spo_task(session_factory, database="AED_CAT_DROP")
    try:
        service = CompanyService(db)
        service.replace_mapping(
            DEFAULT_TENANT_ID, company.id, ENTITY_SHIPPING_ORDER,
            [
                MappingWriteRow(source_path="DocNo", transform="string", sorento_field="spo_number"),
                MappingWriteRow(source_path="Cancelled", transform="string", sorento_field="status"),
            ],
        )
        db.expire_all()
        assert _ref_rows(db, company.id) == []
        header = (
            db.query(AcFieldMapping)
            .filter(
                AcFieldMapping.company_id == company.id,
                AcFieldMapping.entity_type == ENTITY_SHIPPING_ORDER,
                AcFieldMapping.scope == SCOPE_HEADER,
            )
            .all()
        )
        assert sorted(r.canonical_field for r in header) == ["spo_number", "status"]
    finally:
        db.close()
        RUNTIME.dispose_all()


PRESET_HEADER_ROWS = [
    ("DocNo", "spo_number", "string", True),
    ("CreditorAutoKey", "supplier_ref", "ref_supplier", False),
    ("DocDate", "issue_date", "date", False),
    ("ExpectedDate", "expected_date", "date", False),
    ("CurrencyCode", "currency", "string", False),
    ("Cancelled", "status", "string", True),
    ("CreditorCode", "supplier_code", "string", False),
    ("CreditorName", "supplier_name", "string", False),
    ("SalesAgent", "agent_code", "string", False),
    ("Ref", "container_number", "string", False),
]


def _prod_shaped_spo_task(session_factory, *, database: str):
    """The ten header rows a prod SPO task carries after 0016: the nine
    preset rows plus the backfilled ``Ref -> container_number``."""
    db = session_factory()
    engine = _source_engine([], {})
    conn = _sql_connection(db, engine, database=database, name=f"src {database}")
    company = _company(db, conn.id, database=database, name=f"{database} Co")
    config = _document_config(db, company, conn.id, ENTITY_SHIPPING_ORDER)
    config.result_columns = ["DocKey", "LastModified"] + [row[0] for row in PRESET_HEADER_ROWS]
    db.commit()
    for order, (source_path, canonical_field, transform, required) in enumerate(PRESET_HEADER_ROWS):
        db.add(AcFieldMapping(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
            entity_type=ENTITY_SHIPPING_ORDER, scope=SCOPE_HEADER,
            source_path=source_path, canonical_field=canonical_field, transform=transform,
            is_required=required, is_enabled=True, sort_order=order,
        ))
    db.commit()
    company_id = company.id
    db.close()
    return company_id


def _header_rows(db, company_id: str):
    return sorted(
        row.canonical_field
        for row in db.query(AcFieldMapping).filter(
            AcFieldMapping.company_id == company_id,
            AcFieldMapping.entity_type == ENTITY_SHIPPING_ORDER,
            AcFieldMapping.scope == SCOPE_HEADER,
        )
    )


def _editor_payload(view: dict) -> list:
    """Exactly what the Mapping tab submits (``use-mapping-draft.ts``
    ``splitMappingRows`` + ``toWrite``): every header row the view projects
    WITH a ``sorentoField``; a row projected as not delivered
    (``sorentoField: null``) is filed under provenance and never sent."""
    return [
        {
            "sourcePath": row["sourcePath"], "transform": row["transform"],
            "formula": row.get("formula"), "sorentoField": row["sorentoField"],
            "scope": "header", "isEnabled": row["isEnabled"],
        }
        for row in view["rows"]
        if row["scope"] == "header" and row["sorentoField"]
    ]


def test_editor_shaped_put_round_trip_keeps_the_backfilled_ref_row(client, session_factory):
    """The Mapping tab's real save: GET the view, submit every row it shows
    as deliverable, PUT. On the pre-fix catalog the Ref row is projected
    ``sorentoField: null``, so the editor omits it and the header sweep
    (``delete_unknown``) DELETES it with a 200 - replayed and observed on
    origin/main 148a2552: the ten rows became nine. Once the catalog offers
    ``container_number`` the row is in the payload and survives."""
    company_id = _prod_shaped_spo_task(session_factory, database="AED_CAT_RT")
    try:
        headers = _auth(client)
        url = f"/autocount/companies/{company_id}/entities/{ENTITY_SHIPPING_ORDER}/mapping"
        view = client.get(url, headers=headers).json()
        ref = [row for row in view["rows"] if row["sourcePath"] == "Ref"]
        assert ref and ref[0]["sorentoField"] == "container_number", ref

        payload = _editor_payload(view)
        assert len(payload) == 10, [row["sorentoField"] for row in payload]
        response = client.put(url, headers=headers, json={"rows": payload, "lineRows": []})
        assert response.status_code == 200, response.text

        db = session_factory()
        assert _header_rows(db, company_id) == sorted(row[1] for row in PRESET_HEADER_ROWS)
        db.close()
        after = [row for row in response.json()["rows"] if row["sourcePath"] == "Ref"]
        assert after and after[0]["sorentoField"] == "container_number" and after[0]["isEnabled"]
    finally:
        RUNTIME.dispose_all()


def test_a_refused_save_deletes_nothing(client, session_factory):
    """The one protection that holds BEFORE and AFTER the catalog fix: the
    PUT guard (AC-15-42) raises inside the row loop, before
    ``delete_by_canonical``/``delete_unknown`` run, so a refused save is
    atomic - every stored header row, the backfilled Ref row included,
    survives a 422 untouched. (Pre-fix, a payload that named
    ``container_number`` itself was refused this way.)"""
    company_id = _prod_shaped_spo_task(session_factory, database="AED_CAT_422")
    try:
        headers = _auth(client)
        url = f"/autocount/companies/{company_id}/entities/{ENTITY_SHIPPING_ORDER}/mapping"
        payload = [
            {"sourcePath": "DocNo", "transform": "string", "sorentoField": "spo_number"},
            {"sourcePath": "Cancelled", "transform": "string", "sorentoField": "status"},
            {"sourcePath": "Ref", "transform": "string", "sorentoField": "not_a_sorento_field"},
        ]
        response = client.put(url, headers=headers, json={"rows": payload, "lineRows": []})
        assert response.status_code == 422, response.text
        assert "not_a_sorento_field" in response.text

        db = session_factory()
        assert _header_rows(db, company_id) == sorted(row[1] for row in PRESET_HEADER_ROWS)
        db.close()
    finally:
        RUNTIME.dispose_all()


def test_re_adding_the_ref_row_after_a_drop_is_accepted(session_factory):
    """The PUT guard (AC-15-42) admits the target again - the operator is
    never locked out of a field the wire accepts."""
    db, company = _spo_task(session_factory, database="AED_CAT_READD")
    try:
        service = CompanyService(db)
        base = [
            MappingWriteRow(source_path="DocNo", transform="string", sorento_field="spo_number"),
            MappingWriteRow(source_path="Cancelled", transform="string", sorento_field="status"),
        ]
        service.replace_mapping(DEFAULT_TENANT_ID, company.id, ENTITY_SHIPPING_ORDER, base)
        db.expire_all()
        assert _ref_rows(db, company.id) == []

        service.replace_mapping(
            DEFAULT_TENANT_ID, company.id, ENTITY_SHIPPING_ORDER,
            base + [MappingWriteRow(
                source_path="Ref", transform="string", sorento_field="container_number",
            )],
        )
        db.expire_all()
        stored = _ref_rows(db, company.id)
        assert len(stored) == 1 and stored[0].is_enabled is True
    finally:
        db.close()
        RUNTIME.dispose_all()
