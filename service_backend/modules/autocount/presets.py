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


# ``LineCount`` fingerprint mismatch guard (S2, review round 4) - a plain
# COLUMN-NAME CONVENTION, not an engine concept: both presets below select a
# ``LineCount`` aggregate over the OUTER APPLY (see the "LINE FINGERPRINT"
# note ahead of ``_SO_HEADER_QUERY``) purely for change detection. A paged
# document run (``SqlDbSource.fetch_page``) additionally treats a header row
# carrying this EXACT column name, with a value greater than zero, whose own
# ``lineQuery`` fetch came back with ZERO rows, as a genuine mismatch (a
# broken line query/join, not a real zero-line document) - staged FAILED,
# never silently accepted and never pushed. A task with no such column, or
# one reporting zero, is untouched by the guard - the engine itself stays
# fingerprint-agnostic.
LINE_COUNT_FINGERPRINT_COLUMN = "LineCount"


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
#     !!  LINE FINGERPRINT (plan sprint-5/03 S4, AC-03-20).  !!
# Live 2026-09-05: header `LastModified` moved for only 19% of fulfilled
# June-2026 SOs - fulfilment (`TransferedQty` rising) is a LINE fact and
# would otherwise reach the sync only through a full reconcile pass whose
# HEADER hash happens to change for some unrelated reason. `LineCount`/
# `QtySum`/`TransferedSum`/`SubTotalSum`/`MaxDtlKey` are computed here, over
# the OUTER APPLY, so a line-only edit (a new line, a qty change, fulfilment)
# changes the HEADER row's own hash - the change-detection engine has no
# special knowledge of these columns at all, they are just ordinary result
# columns that happen to be line-derived. `ItemCode IS NOT NULL` drops
# description-only/sub-total display lines from the aggregate so a cosmetic
# note does not masquerade as a fulfilment/qty change.
#     !!  PSEUDO-LINE EXCLUSION (live finding, 2026-09).  !!
# AutoCount also lets a header carry a "pseudo-line" whose `ItemCode` IS
# present (the cut above alone does not drop it) but whose `Qty` is NULL
# and price is zero - a marker/bundle item such as `ItemCode 'PP'
# "PROMOTION PACKAGE"` that exists to group the real lines underneath it,
# never a real quantity to deliver. Left uncut, it inflates `LineCount`
# past what `lineQuery` (below) actually fetches once ITS OWN `Qty IS NOT
# NULL` cut drops the same row - a disagreement the LineCount-mismatch
# guard (S2, review round 4) reads as a broken line query on a perfectly
# normal document. 570 real SOs (18.6k marker lines) tripped exactly this
# before both queries carried the SAME `Qty IS NOT NULL` cut. The MIRROR
# gap (live 2026-09-06): a `NULL`-`ItemCode` display line (e.g. `Description
# 'CURRENCY ROUNDING DIFFERENCE'`, `Qty 1`) is dropped from the header
# aggregate by `ItemCode IS NOT NULL` but, before this fix, `lineQuery`
# carried no such cut - the row reached the mapper and failed the required
# `product_ref`. `lineQuery` now carries the SAME `ItemCode IS NOT NULL AND
# Qty IS NOT NULL` filter as the header fingerprint's `OUTER APPLY`, so a
# row either counts in both places or neither.
_SO_HEADER_QUERY = (
    "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, c.AutoKey AS DebtorAutoKey, "
    "h.SalesAgent AS SalesAgent, h.DocDate AS DocDate, "
    "h.UDF_DelDate AS RequestedDeliveryDate, h.Note AS Note, "
    "h.Cancelled AS Cancelled, h.DebtorCode AS DebtorCode, "
    "h.DebtorName AS DebtorName, h.LastModified AS LastModified, "
    "l.LineCount AS LineCount, l.QtySum AS QtySum, l.TransferedSum AS TransferedSum, "
    "l.SubTotalSum AS SubTotalSum, l.MaxDtlKey AS MaxDtlKey "
    "FROM {database}.dbo.SO AS h "
    "LEFT JOIN {database}.dbo.Debtor AS c ON c.AccNo = h.DebtorCode "
    "OUTER APPLY ("
    "SELECT COUNT(*) AS LineCount, SUM(d.Qty) AS QtySum, "
    "SUM(d.TransferedQty) AS TransferedSum, SUM(d.SubTotal) AS SubTotalSum, "
    "MAX(d.DtlKey) AS MaxDtlKey "
    "FROM {database}.dbo.SODTL AS d "
    "WHERE d.DocKey = h.DocKey AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
    ") AS l"
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
    "WHERE d.DocKey = :doc_key AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
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
# pack's real PO agent column.
#
#     !!  ExpectedDate + currency MATCH THE PACK EXACTLY (SF2, security
#         re-review round) - PO HAS NO UDF_DelDate/UDF_Currency COLUMN.  !!
# The earlier version of this query invented `h.UDF_DelDate`/`h.UDF_Currency`
# by copying SO's "header UDF override" shape - PO has no such columns at
# all (documentation/plans/sprint-4/22-autocount-db-etl-autocount-sql.md
# section 3). The pack derives `ExpectedDate` via `OUTER APPLY MIN(d.
# DeliveryDate)` over PODTL (the first line's delivery date) and reads
# `currency` straight off `h.CurrencyCode` with NO override at the header
# level at all - `CanonicalPurchaseOrderLine` separately carries its OWN
# per-line `currency` (`COALESCE(d.UDF_Currency, h.CurrencyCode)`, pack
# section 4's line query) which is a LINE concern, not this header's.
# Line fingerprint (plan sprint-5/03 S4, AC-03-20 - see the SO header's own
# comment above for the 19%-of-fulfilled-SOs finding this closes) - added to
# the SAME `OUTER APPLY` that already computes `FirstDeliveryDate`, with the
# SAME `ItemCode IS NOT NULL` line filter, and the SAME pseudo-line
# exclusion (`Qty IS NOT NULL` - see the SO header's own comment above for
# the PROMOTION PACKAGE marker-item finding) PO/SPO share with SO.
# `_PO_LINE_QUERY` below (shared by PO and SPO) carries the SAME
# `ItemCode IS NOT NULL AND Qty IS NOT NULL` cut as this header's `OUTER
# APPLY` - see the SO header's own comment above for the live finding
# (`ItemCode NULL` display lines such as 'CURRENCY ROUNDING DIFFERENCE')
# this closes.
_PO_HEADER_QUERY = (
    "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, s.AutoKey AS CreditorAutoKey, "
    "h.PurchaseAgent AS SalesAgent, h.DocDate AS DocDate, "
    "CAST(l.FirstDeliveryDate AS date) AS ExpectedDate, h.Cancelled AS Cancelled, "
    "h.CreditorCode AS CreditorCode, h.CreditorName AS CreditorName, "
    "h.CurrencyCode AS CurrencyCode, h.LastModified AS LastModified, "
    "l.LineCount AS LineCount, l.QtySum AS QtySum, l.TransferedSum AS TransferedSum, "
    "l.SubTotalSum AS SubTotalSum, l.MaxDtlKey AS MaxDtlKey "
    "FROM {database}.dbo.PO AS h "
    "LEFT JOIN {database}.dbo.Creditor AS s ON s.AccNo = h.CreditorCode "
    "OUTER APPLY ("
    "SELECT MIN(d.DeliveryDate) AS FirstDeliveryDate, COUNT(*) AS LineCount, "
    "SUM(d.Qty) AS QtySum, SUM(d.TransferedQty) AS TransferedSum, "
    "SUM(d.SubTotal) AS SubTotalSum, MAX(d.DtlKey) AS MaxDtlKey "
    "FROM {database}.dbo.PODTL AS d "
    "WHERE d.DocKey = h.DocKey AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
    ") AS l"
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
    "WHERE d.DocKey = :doc_key AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
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
        # SF2 (security re-review round) - matches the pack exactly: PO
        # has no UDF currency override at the HEADER level (that lives on
        # PODTL's own line, a separate concern - see the header query's
        # own comment above).
        PresetField("CurrencyCode", "currency", "string"),
        # SF-a (code-review round) - the pack is explicit: "Do NOT map
        # internal_note on PO" (section 3). A Note->internal_note row was
        # left over from copying SO's shape; PO's header query no longer
        # even selects Note (SF2), so this row would have sat is_enabled
        # =False forever - deleted outright rather than left disabled.
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
        # SF2 (security re-review round) - matches the pack exactly: PO
        # has no UDF currency override at the HEADER level (that lives on
        # PODTL's own line, a separate concern - see the header query's
        # own comment above).
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
    seed_header: bool = True,
    seed_line: bool = True,
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
    # Per-scope (sprint-5/02 hotfix): the caller passes which scopes are still
    # empty. Migration 0010 backfilled LINE rows onto every existing document
    # task, so "the mapping is empty" was never true again for those tasks and
    # a header that was never mapped could not be seeded - the operator saw an
    # empty header section with no formula to edit.
    created = 0
    if seed_header:
        created += _seed_rows(
            db, tenant_id, company_id, entity_type, SCOPE_HEADER, preset.header,
            header_columns,
        )
    if seed_line:
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
