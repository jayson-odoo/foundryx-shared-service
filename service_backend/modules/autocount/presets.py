"""AutoCount document mapping PRESETS (sprint-5/02, AC-02-16/17).

A brand-new SO/PO task's first clean save seeds its header+line mapping from
the documented AutoCount SQL pack, so an operator opening the Mapping tab for
the first time sees a complete, editable starting point rather than an empty
table. From that moment the DATABASE is the source of truth (the D5 rule
every other seed in this module already follows) - a preset is a STARTING
POINT, never re-applied, never a fallback an operator's edits could be
silently reverted to.

A row whose source column the task's ACTUAL query does not return lands
``is_enabled=False`` (still an ordinary, editable row - a stale
column-not-found chip in the UI, never a save-time error) rather than being
omitted, so a customer whose query differs slightly from the documented pack
still sees the full shape and fixes the picker in place.

``list_mapping_presets`` (sprint-5/02 S3, AC-02-16 "Use preset" action) is the
SAME registry read-only, database-substituted - the mapping editor's picker
and ``seed_document_mapping``'s first-save seed are two views of ONE table,
never two copies to drift apart.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from .canonical.documents import (
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
)
from .mapping import DEFAULT_STATUS_FORMULA, SCOPE_HEADER, SCOPE_LINE
from .models import AcFieldMapping


@dataclass(frozen=True)
class PresetField:
    """One preset-seeded mapping row."""

    source_path: str
    canonical_field: str
    transform: str
    formula: Optional[str] = None
    required: bool = False


@dataclass(frozen=True)
class DocumentPreset:
    label: str
    header_query: str
    line_query: str
    key_columns: Tuple[str, ...]
    watermark_column: str
    doc_date_column: str
    from_date: str
    filter_formula: Optional[str]
    header: Tuple[PresetField, ...]
    line: Tuple[PresetField, ...]


# ── Sales Order ───────────────────────────────────────────────────────────────
#
#     !!  TABLE NAMES + AutoKey JOINS MATCH THE SQL PACK (S2, review round).  !!
# (`documentation/plans/sprint-4/22-autocount-db-etl-autocount-sql.md`.)
# Real AutoCount tables are `SO`/`SODTL`/`PO`/`PODTL` - the earlier
# `SO_Header`/`SO_Dtl`/`PO_Header`/`PO_Dtl` names (and a bare `DebtorAutoKey`/
# `ItemAutoKey`/`LocationAutoKey` column, as if AutoCount stored a master's
# key directly on the document) were placeholders that never matched a real
# schema OR the live tasks built against the pack. `ref_customer`/
# `ref_supplier`/`ref_product`/`ref_warehouse` mint `{database}:{AutoKey}` -
# a wrong/missing AutoKey means the reference can never resolve against the
# ALREADY-SYNCED master, so this is a functional-correctness fix, not a
# cosmetic one. `RequestedDeliveryDate`/`ExpectedDate` are simplified to the
# header's own UDF override column (never the pack's OUTER APPLY "first
# line's delivery date" fallback) - line-derived aggregates belong to the
# mapping engine's OWN `lines.*` facts (`DEFAULT_STATUS_FORMULA` already
# reads `lines.count`/`lines.open_count` that way), not a second SQL-side
# computation of the same shape.
_SO_HEADER_QUERY = (
    "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, c.AutoKey AS DebtorAutoKey, "
    "h.SalesAgent AS SalesAgent, h.DocDate AS DocDate, "
    "h.UDF_DelDate AS RequestedDeliveryDate, h.Note AS Note, "
    "h.Cancelled AS Cancelled, h.DebtorCode AS DebtorCode, "
    "h.DebtorName AS DebtorName, h.LastModified AS LastModified "
    "FROM {database}.dbo.SO AS h "
    "LEFT JOIN {database}.dbo.Debtor AS c ON c.AccNo = h.DebtorCode"
)
_SO_LINE_QUERY = (
    "SELECT d.DtlKey AS DtlKey, i.AutoKey AS ItemAutoKey, "
    "w.AutoKey AS LocationAutoKey, d.Qty AS Qty, "
    "d.TransferedQty AS TransferedQty, d.UnitPrice AS UnitPrice, "
    "d.DiscountAmt AS DiscountAmt, d.SubTotal AS SubTotal, d.UOM AS UOM, "
    "d.DeliveryDate AS DeliveryDate, d.ItemCode AS ItemCode, "
    "d.Description AS Description, d.Location AS Location, d.Seq AS Seq "
    "FROM {database}.dbo.SODTL AS d "
    "LEFT JOIN {database}.dbo.Item AS i ON i.ItemCode = d.ItemCode "
    "LEFT JOIN {database}.dbo.Location AS w ON w.Location = d.Location "
    "WHERE d.DocKey = :doc_key"
)

SO_PRESET = DocumentPreset(
    label="AutoCount SO",
    header_query=_SO_HEADER_QUERY,
    line_query=_SO_LINE_QUERY,
    key_columns=("DocKey",),
    watermark_column="LastModified",
    doc_date_column="DocDate",
    from_date="2026-01-01",
    filter_formula=None,
    header=(
        PresetField("DocNo", "so_number", "string", required=True),
        PresetField("DebtorAutoKey", "customer_ref", "ref_customer"),
        PresetField("SalesAgent", "sales_agent_ref", "ref_sales_agent"),
        PresetField("DocDate", "doc_date", "date"),
        PresetField("RequestedDeliveryDate", "requested_delivery_date", "date"),
        PresetField("Note", "internal_note", "string"),
        PresetField("Cancelled", "status", "string", formula=DEFAULT_STATUS_FORMULA, required=True),
        PresetField("DebtorCode", "customer_code", "string"),
        PresetField("DebtorName", "customer_name", "string"),
        PresetField("SalesAgent", "agent_code", "string"),
    ),
    line=(
        PresetField("DtlKey", "source_ref", "string", required=True),
        PresetField("ItemAutoKey", "product_ref", "ref_product", required=True),
        PresetField("LocationAutoKey", "warehouse_ref", "ref_warehouse"),
        PresetField("Qty", "qty_ordered", "decimal", required=True),
        PresetField("TransferedQty", "qty_delivered", "decimal"),
        PresetField("UnitPrice", "unit_price", "decimal"),
        PresetField("DiscountAmt", "discount", "decimal"),
        PresetField("SubTotal", "line_total", "decimal"),
        PresetField("UOM", "uom", "string"),
        PresetField("DeliveryDate", "required_date", "date"),
        PresetField("ItemCode", "product_code", "string"),
        PresetField("Description", "product_name", "string"),
        PresetField("Location", "warehouse_code", "string"),
        # S3 (AC-02-27) - the line queries already SELECT Seq; without a
        # preset row consuming it, line_number never reaches Sorento.
        PresetField("Seq", "line_number", "string"),
    ),
)


# ── Purchase Order ────────────────────────────────────────────────────────────
# Same S2 table-name/AutoKey-join fix as SO above. `PurchaseAgent` (not
# `SalesAgent` - the earlier query's copy-paste from the SO header) is the
# pack's real PO agent column. `UDF_Currency` is selected alongside
# `CurrencyCode` for the S4 currency-fallback formula below.
_PO_HEADER_QUERY = (
    "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, s.AutoKey AS CreditorAutoKey, "
    "h.PurchaseAgent AS SalesAgent, h.DocDate AS DocDate, "
    "h.UDF_DelDate AS ExpectedDate, h.Note AS Note, h.Cancelled AS Cancelled, "
    "h.CreditorCode AS CreditorCode, h.CreditorName AS CreditorName, "
    "h.CurrencyCode AS CurrencyCode, h.UDF_Currency AS UDF_Currency, "
    "h.LastModified AS LastModified "
    "FROM {database}.dbo.PO AS h "
    "LEFT JOIN {database}.dbo.Creditor AS s ON s.AccNo = h.CreditorCode"
)
_PO_LINE_QUERY = (
    "SELECT d.DtlKey AS DtlKey, i.AutoKey AS ItemAutoKey, "
    "w.AutoKey AS LocationAutoKey, d.Qty AS Qty, "
    "d.TransferedQty AS TransferedQty, d.UnitPrice AS UnitPrice, "
    "d.DiscountAmt AS DiscountAmt, d.SubTotal AS SubTotal, d.UOM AS UOM, "
    "d.DeliveryDate AS ExpectedDate, d.ItemCode AS ItemCode, "
    "d.Description AS Description, d.Location AS Location, d.Seq AS Seq "
    "FROM {database}.dbo.PODTL AS d "
    "LEFT JOIN {database}.dbo.Item AS i ON i.ItemCode = d.ItemCode "
    "LEFT JOIN {database}.dbo.Location AS w ON w.Location = d.Location "
    "WHERE d.DocKey = :doc_key"
)

# addendum §3/§9 - a PO task filters OUT the SPO-numbered documents its
# sibling SPO task owns (and vice versa, once ENTITY_SHIPPING_ORDER exists in
# slice S3). Seeded now so a PO task created in this slice already carries
# the documented string - not yet EVALUATED at fetch time (AC-02-11, S3).
_PO_FILTER_FORMULA = 'not(startswith(upper(trim(DocNo)), "SPO-"))'

PO_PRESET = DocumentPreset(
    label="AutoCount PO",
    header_query=_PO_HEADER_QUERY,
    line_query=_PO_LINE_QUERY,
    key_columns=("DocKey",),
    watermark_column="LastModified",
    doc_date_column="DocDate",
    from_date="2026-01-01",
    filter_formula=_PO_FILTER_FORMULA,
    header=(
        PresetField("DocNo", "po_number", "string", required=True),
        PresetField("CreditorAutoKey", "supplier_ref", "ref_supplier"),
        PresetField("DocDate", "issue_date", "date"),
        PresetField("ExpectedDate", "expected_date", "date"),
        PresetField("CurrencyCode", "currency", "string"),
        PresetField("Note", "internal_note", "string"),
        PresetField("Cancelled", "status", "string", formula=DEFAULT_STATUS_FORMULA, required=True),
        PresetField("CreditorCode", "supplier_code", "string"),
        PresetField("CreditorName", "supplier_name", "string"),
        PresetField("SalesAgent", "agent_code", "string"),
    ),
    line=(
        PresetField("DtlKey", "source_ref", "string", required=True),
        PresetField("ItemAutoKey", "product_ref", "ref_product", required=True),
        PresetField("LocationAutoKey", "warehouse_ref", "ref_warehouse"),
        PresetField("Qty", "qty_ordered", "decimal", required=True),
        PresetField("TransferedQty", "qty_received", "decimal"),
        PresetField("UnitPrice", "unit_cost", "decimal"),
        PresetField("DiscountAmt", "discount", "decimal"),
        PresetField("SubTotal", "line_total", "decimal"),
        PresetField("UOM", "uom", "string"),
        PresetField("ExpectedDate", "expected_date", "date"),
        PresetField("ItemCode", "product_code", "string"),
        PresetField("Description", "product_name", "string"),
        PresetField("Location", "warehouse_code", "string"),
        # S3 (AC-02-27) - the line queries already SELECT Seq; without a
        # preset row consuming it, line_number never reaches Sorento.
        PresetField("Seq", "line_number", "string"),
    ),
)

# ── Shipping Order ────────────────────────────────────────────────────────────
# addendum §3/§9 - the PO task's sibling: same PO_Header/PO_Dtl tables (a
# shipping order is a specially-numbered PO in AutoCount), split by the
# OPPOSITE `filterFormula` (SPO- prefix IN, not out). No `internal_note` -
# Sorento's shipping-order schema carries no such field either (same rule as
# PO's own).
_SPO_FILTER_FORMULA = 'startswith(upper(trim(DocNo)), "SPO-")'

SPO_PRESET = DocumentPreset(
    label="AutoCount SPO",
    header_query=_PO_HEADER_QUERY,
    line_query=_PO_LINE_QUERY,
    key_columns=("DocKey",),
    watermark_column="LastModified",
    doc_date_column="DocDate",
    from_date="2026-01-01",
    filter_formula=_SPO_FILTER_FORMULA,
    header=(
        PresetField("DocNo", "spo_number", "string", required=True),
        PresetField("CreditorAutoKey", "supplier_ref", "ref_supplier"),
        PresetField("DocDate", "issue_date", "date"),
        PresetField("ExpectedDate", "expected_date", "date"),
        PresetField("CurrencyCode", "currency", "string"),
        PresetField("Cancelled", "status", "string", formula=DEFAULT_STATUS_FORMULA, required=True),
        PresetField("CreditorCode", "supplier_code", "string"),
        PresetField("CreditorName", "supplier_name", "string"),
        PresetField("SalesAgent", "agent_code", "string"),
    ),
    line=(
        PresetField("DtlKey", "source_ref", "string", required=True),
        PresetField("ItemAutoKey", "product_ref", "ref_product", required=True),
        PresetField("LocationAutoKey", "warehouse_ref", "ref_warehouse"),
        PresetField("Qty", "qty_ordered", "decimal", required=True),
        PresetField("TransferedQty", "qty_received", "decimal"),
        PresetField("UnitPrice", "unit_cost", "decimal"),
        PresetField("UOM", "uom", "string"),
        PresetField("ExpectedDate", "expected_date", "date"),
        PresetField("ItemCode", "product_code", "string"),
        PresetField("Description", "product_name", "string"),
        PresetField("Location", "warehouse_code", "string"),
        # S3 (AC-02-27) - the line queries already SELECT Seq; without a
        # preset row consuming it, line_number never reaches Sorento.
        PresetField("Seq", "line_number", "string"),
    ),
)

DOCUMENT_PRESETS: Dict[str, DocumentPreset] = {
    ENTITY_SALES_ORDER: SO_PRESET,
    ENTITY_PURCHASE_ORDER: PO_PRESET,
    ENTITY_SHIPPING_ORDER: SPO_PRESET,
}


def _seed_rows(
    db: Session,
    tenant_id: str,
    company_id: str,
    entity_type: str,
    scope: str,
    fields: Sequence[PresetField],
    available_columns: Optional[Dict[str, str]],
    *,
    sort_start: int = 0,
) -> int:
    known = set(available_columns or {})
    created = 0
    for order, spec in enumerate(fields, start=sort_start):
        db.add(
            AcFieldMapping(
                tenant_id=tenant_id,
                company_id=company_id,
                entity_type=entity_type,
                scope=scope,
                source_path=spec.source_path,
                canonical_field=spec.canonical_field,
                transform=spec.transform,
                formula=spec.formula,
                is_required=spec.required,
                # A column the task's ACTUAL query does not return lands
                # disabled - still an ordinary editable row, never omitted
                # (AC-02-16) - `available_columns=None` (query never
                # previewed) seeds every row enabled, matching "nothing
                # proven wrong yet".
                is_enabled=(available_columns is None or spec.source_path in known),
                sort_order=order,
            )
        )
        created += 1
    return created


def seed_document_mapping(
    db: Session,
    tenant_id: str,
    company_id: str,
    entity_type: str,
    *,
    header_columns: Optional[Dict[str, str]],
    line_columns: Optional[Dict[str, str]],
) -> int:
    """Seed the entity's preset header+line mapping rows. Returns the count
    created (0 when no preset is registered for ``entity_type``, e.g. a
    non-document entity).

    No ``database_name`` param (review nit - was accepted but unused): a
    mapping ROW is source_path/canonical_field only, never a query string -
    only ``list_mapping_presets`` (the "Use preset" read view) needs the
    company's database name, to substitute it into the documented query text.

    The CALLER (``EtlService.update_task``) is responsible for only invoking
    this on a genuinely first save (the entity's mapping is empty) - this
    function itself does not re-check, matching ``_seed_mapping_rows``'s
    existing seed-if-absent contract for masters.
    """
    preset = DOCUMENT_PRESETS.get(entity_type)
    if preset is None:
        return 0
    created = _seed_rows(
        db, tenant_id, company_id, entity_type, SCOPE_HEADER, preset.header, header_columns,
    )
    created += _seed_rows(
        db, tenant_id, company_id, entity_type, SCOPE_LINE, preset.line, line_columns,
        sort_start=len(preset.header),
    )
    db.flush()
    return created


def list_mapping_presets(entity_type: str, database_name: str) -> List[Dict[str, object]]:
    """The mapping editor's "Use preset" action (sprint-5/02 S3, AC-02-16) -
    a READ-ONLY, database-substituted view of the SAME registry
    ``seed_document_mapping`` seeds from. ``{database}`` in the documented
    query text is filled in with the company's OWN database name so the
    picker offers a statement ready to paste, never a placeholder the
    operator has to hand-edit. Empty for any entity with no registered
    preset (a non-document entity, or a document family not yet documented).
    """
    preset = DOCUMENT_PRESETS.get(entity_type)
    if preset is None:
        return []
    return [
        {
            "entityType": entity_type,
            "label": preset.label,
            "headerQuery": preset.header_query.replace("{database}", database_name),
            "lineQuery": preset.line_query.replace("{database}", database_name),
            "keyColumns": list(preset.key_columns),
            "watermarkColumn": preset.watermark_column,
            "docDateColumn": preset.doc_date_column,
            "fromDate": preset.from_date or None,
            "filterFormula": preset.filter_formula,
        }
    ]
