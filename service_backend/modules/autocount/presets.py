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

SPO (shipping order) is deliberately absent here - ``ENTITY_SHIPPING_ORDER``
does not exist yet (sprint-5/02 slice S3); ``seed_document_mapping`` is a
no-op for any entity with no registered preset, which covers it naturally
until S3 adds one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from .canonical.documents import ENTITY_PURCHASE_ORDER, ENTITY_SALES_ORDER
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

_SO_HEADER_QUERY = (
    "SELECT DocKey, DocNo, DebtorAutoKey, SalesAgent, DocDate, "
    "RequestedDeliveryDate, Note, Cancelled, DebtorCode, DebtorName, "
    "LastModified FROM {database}.dbo.SO_Header"
)
_SO_LINE_QUERY = (
    "SELECT DtlKey, ItemAutoKey, LocationAutoKey, Qty, TransferedQty, "
    "UnitPrice, DiscountAmt, SubTotal, UOM, DeliveryDate, ItemCode, "
    "Description, Location, Seq FROM {database}.dbo.SO_Dtl "
    "WHERE DocKey = :doc_key"
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
    ),
)


# ── Purchase Order ────────────────────────────────────────────────────────────

_PO_HEADER_QUERY = (
    "SELECT DocKey, DocNo, CreditorAutoKey, SalesAgent, DocDate, "
    "ExpectedDate, Note, Cancelled, CreditorCode, CreditorName, CurrencyCode, "
    "LastModified FROM {database}.dbo.PO_Header"
)
_PO_LINE_QUERY = (
    "SELECT DtlKey, ItemAutoKey, LocationAutoKey, Qty, TransferedQty, "
    "UnitPrice, DiscountAmt, SubTotal, UOM, ExpectedDate, ItemCode, "
    "Description, Location, Seq FROM {database}.dbo.PO_Dtl "
    "WHERE DocKey = :doc_key"
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
    ),
)

DOCUMENT_PRESETS: Dict[str, DocumentPreset] = {
    ENTITY_SALES_ORDER: SO_PRESET,
    ENTITY_PURCHASE_ORDER: PO_PRESET,
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
    database_name: str,
    *,
    header_columns: Optional[Dict[str, str]],
    line_columns: Optional[Dict[str, str]],
) -> int:
    """Seed the entity's preset header+line mapping rows. Returns the count
    created (0 when no preset is registered for ``entity_type``, e.g. a
    non-document entity or shipping_order before slice S3).

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
