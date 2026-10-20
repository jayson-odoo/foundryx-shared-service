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
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from .canonical.documents import (
    ENTITY_CANCEL_PURCHASE_ORDER,
    ENTITY_CANCEL_SALES_ORDER,
    ENTITY_CONSIGNMENT,
    ENTITY_CONSIGNMENT_RETURN,
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
    ENTITY_AR_OUTSTANDING,
    ENTITY_CASH_SALE,
    ENTITY_CREDIT_NOTE,
    ENTITY_DEBIT_NOTE,
    ENTITY_INVOICE,
)
from .canonical.masters import (
    LOCKED_MAPPING_SOURCES,
    ENTITY_BRAND,
    ENTITY_BRANCH,
    ENTITY_CUSTOMER,
    ENTITY_PRODUCT,
    ENTITY_PRODUCT_CATEGORY,
    ENTITY_STOCK_BALANCE,
    ENTITY_UNIT_OF_MEASURE,
    ENTITY_WAREHOUSE,
)
from .mapping import DEFAULT_STATUS_FORMULA, SCOPE_HEADER, SCOPE_LINE
from .mapping_catalog import (
    accepted_fields,
    line_accepted_fields,
    line_required_field_names,
    required_field_names,
)
from .models import SOURCE_IMPL_AUTOCOUNT_HTTP, AcEntityConfig, AcFieldMapping


@dataclass(frozen=True)
class PresetField:
    """One preset-seeded mapping row."""

    source_path: str
    canonical_field: str
    transform: str
    formula: Optional[str] = None
    required: bool = False
    # sprint-5/10 (AC-10-74, R10) - present but seeded DISABLED, never
    # omitted: the operator can SEE the row exists and turn it on
    # deliberately, which an absent row cannot express. ANDed into
    # ``_seed_rows``'s own column-not-found ``is_enabled`` computation, so a
    # disabled preset row stays disabled even on a genuinely-first save
    # (``available_columns=None``, "nothing proven wrong yet" would
    # otherwise enable everything).
    #
    # review round 1 should-fix 7 - NOT ``repr=False``: hiding a real field
    # from ``repr()`` blinds `tests/test_autocount_so_ref.py`'s
    # ``sha256(repr(PO_PRESET))``/``SPO_PRESET`` drift guard to a genuine
    # future edit of any SO/PO/SPO preset row (the very thing that fingerprint
    # exists to catch). The fingerprint constants are RE-BASELINED instead
    # (their `enabled=True` is now visible on every row, zero row content
    # change) - see that file's own commit note.
    enabled: bool = True


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
    # feat/line-fingerprint-sweep - a cheap GROUP BY over the line table,
    # scoped by the SAME header cut the fingerprint mismatch guard already
    # rides (`from_date`, `ItemCode`/`Qty NOT NULL`), run on an interval by
    # the incremental sweep to catch a line-only edit AutoCount never bumps
    # the header's `LastModified` for (prod finding: `SODTL.TransferedQty`
    # rising with no `SO.LastModified` change - see `sql_source/source.py`'s
    # own sweep docstring for the full mechanism).
    fingerprint_query: str = ""


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

#     !!  ADDING A SELECTED COLUMN CHANGES THE ROW HASH (feat/spo-container-
#         number).  !!
# `_PO_HEADER_QUERY` now selects `h.Ref AS Ref` where it did not before; the
# change-detection engine hashes a header row over its OWN `result_columns`
# with no special knowledge of any one column (the same mechanism the
# `LineCount` fingerprint above rides), so every EXISTING shipping_order
# task re-stages every SPO once, as an update, the first run after this
# lane's backfill adds `Ref` to its `result_columns` - intended, not a bug:
# it is exactly how the newly-populated container number reaches Sorento.


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
    "h.UDF_DelDate AS RequestedDeliveryDate, h.Note AS Note, h.Ref AS Ref, "
    "h.Transferable AS Transferable, "
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

# feat/line-fingerprint-sweep - prod finding SO419208 (DocKey 45672056):
# AutoCount updates `SODTL.TransferedQty` (a delivery transfer) WITHOUT
# bumping `SO.LastModified`, so a plain `LastModified > :since` incremental
# never sees the change and the CRM copy stays stale until the next daily
# reconcile. A cheap `GROUP BY` over the line table, scoped by the SAME
# `from_date`/`ItemCode`/`Qty NOT NULL` cuts the header's own OUTER APPLY
# fingerprint already makes (so a pseudo-line/display-line can never move
# this fingerprint either, the same live findings the header cuts closed),
# run once per sweep interval to CATCH what the header hash cannot.
_SO_FINGERPRINT_QUERY = (
    "SELECT d.DocKey AS DocKey, COUNT(*) AS LineCount, SUM(d.Qty) AS QtySum, "
    "SUM(d.TransferedQty) AS TransferedSum, MAX(d.DtlKey) AS MaxDtlKey "
    "FROM {database}.dbo.SODTL AS d JOIN {database}.dbo.SO AS h ON h.DocKey = d.DocKey "
    "WHERE h.DocDate >= :from_date AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL "
    "GROUP BY d.DocKey"
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
        PresetField("Ref", "ref", "string"),
        PresetField("Transferable", "transferable", "bool"),
        # SS-PO-REF - a per-company UDF the shared header query never selects
        # (SQL pack section 4b): `plan_rows` seeds it DISABLED unless the
        # task's own query returns a `UDFNote` column.
        PresetField("UDFNote", "po_ref", "string"),
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
    fingerprint_query=_SO_FINGERPRINT_QUERY,
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
#     !!  LINE LINKAGE (sprint-5/06, AC-06-12/13) - PO/SPO ONLY.  !!
# `FromSODtlKey` (populated by AutoCount's stock "Transfer from S/O") points
# at the SODTL row a PO/SPO line was raised for; `FromDocType`/
# `FromDocDtlKey` (populated for an SPO transferred FROM a PO) point at the
# source PODTL row. Both are resolved to their OWN header's `DocKey`/`DocNo`
# here (never left as bare keys) so a mapped line carries enough to mint a
# ref (`mapping.py`) without a second round-trip. Four header-level
# aggregates (below) mirror this at the OUTER APPLY / fingerprint level, so
# change detection sees a link added/removed/re-pointed with NO line-level
# watermark. No `UDF_*` column here (D5, AC-06-24) - a per-company UDF
# (AED_SORENTO's ICB plugin) is a documented operator addition to the LIVE
# query, mapped to `from_so_external_*`, never baked into this shared text.
_PO_HEADER_QUERY = (
    "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, s.AutoKey AS CreditorAutoKey, "
    "h.PurchaseAgent AS SalesAgent, h.DocDate AS DocDate, "
    "CAST(l.FirstDeliveryDate AS date) AS ExpectedDate, h.Cancelled AS Cancelled, "
    "h.CreditorCode AS CreditorCode, h.CreditorName AS CreditorName, "
    "h.CurrencyCode AS CurrencyCode, h.LastModified AS LastModified, h.Ref AS Ref, "
    "l.LineCount AS LineCount, l.QtySum AS QtySum, l.TransferedSum AS TransferedSum, "
    "l.SubTotalSum AS SubTotalSum, l.MaxDtlKey AS MaxDtlKey, "
    "l.LinkedSOCount AS LinkedSOCount, l.FromSOKeySum AS FromSOKeySum, "
    "l.LinkedPOCount AS LinkedPOCount, l.FromPOKeySum AS FromPOKeySum "
    "FROM {database}.dbo.PO AS h "
    "LEFT JOIN {database}.dbo.Creditor AS s ON s.AccNo = h.CreditorCode "
    "OUTER APPLY ("
    "SELECT MIN(d.DeliveryDate) AS FirstDeliveryDate, COUNT(*) AS LineCount, "
    "SUM(d.Qty) AS QtySum, SUM(d.TransferedQty) AS TransferedSum, "
    "SUM(d.SubTotal) AS SubTotalSum, MAX(d.DtlKey) AS MaxDtlKey, "
    "SUM(CASE WHEN d.FromSODtlKey IS NOT NULL THEN 1 ELSE 0 END) AS LinkedSOCount, "
    "SUM(d.FromSODtlKey) AS FromSOKeySum, "
    "SUM(CASE WHEN d.FromDocType = 'PO' AND d.FromDocDtlKey IS NOT NULL THEN 1 ELSE 0 END) AS LinkedPOCount, "
    "SUM(CASE WHEN d.FromDocType = 'PO' THEN d.FromDocDtlKey END) AS FromPOKeySum "
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
    "d.Description AS Description, d.Location AS Location, d.Seq AS Seq, "
    "d.FromSODtlKey AS FromSODtlKey, so.DocKey AS FromSODocKey, "
    "so.DocNo AS FromSODocNo, d.FromSODocList AS FromSODocList, "
    "CASE WHEN d.FromDocType = 'PO' THEN d.FromDocDtlKey END AS FromPODtlKey, "
    "sh.DocKey AS FromPODocKey, sh.DocNo AS FromPODocNo "
    "FROM {database}.dbo.PODTL AS d "
    "LEFT JOIN {database}.dbo.Item AS i ON i.ItemCode = d.ItemCode "
    "LEFT JOIN {database}.dbo.Location AS w ON w.Location = d.Location "
    "LEFT JOIN {database}.dbo.SODTL AS sd ON sd.DtlKey = d.FromSODtlKey "
    "LEFT JOIN {database}.dbo.SO AS so ON so.DocKey = sd.DocKey "
    "LEFT JOIN {database}.dbo.PODTL AS src ON src.DtlKey = d.FromDocDtlKey AND d.FromDocType = 'PO' "
    "LEFT JOIN {database}.dbo.PO AS sh ON sh.DocKey = src.DocKey "
    "WHERE d.DocKey = :doc_key AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
)

# feat/line-fingerprint-sweep - the PO/PODTL equivalent of `_SO_FINGERPRINT_
# QUERY` above (see that constant's own comment for the mechanism), shared
# by PO and SPO exactly like their header/line queries already are. Same
# four link aggregates as the header's own OUTER APPLY (AC-06-13) - a link
# added/removed/re-pointed with NO other column change still moves this
# fingerprint, catching what the header hash alone might miss between
# reconciles.
_PO_FINGERPRINT_QUERY = (
    "SELECT d.DocKey AS DocKey, COUNT(*) AS LineCount, SUM(d.Qty) AS QtySum, "
    "SUM(d.TransferedQty) AS TransferedSum, MAX(d.DtlKey) AS MaxDtlKey, "
    "SUM(CASE WHEN d.FromSODtlKey IS NOT NULL THEN 1 ELSE 0 END) AS LinkedSOCount, "
    "SUM(d.FromSODtlKey) AS FromSOKeySum, "
    "SUM(CASE WHEN d.FromDocType = 'PO' AND d.FromDocDtlKey IS NOT NULL THEN 1 ELSE 0 END) AS LinkedPOCount, "
    "SUM(CASE WHEN d.FromDocType = 'PO' THEN d.FromDocDtlKey END) AS FromPOKeySum "
    "FROM {database}.dbo.PODTL AS d JOIN {database}.dbo.PO AS h ON h.DocKey = d.DocKey "
    "WHERE h.DocDate >= :from_date AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL "
    "GROUP BY d.DocKey"
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
        # sprint-5/06 (AC-06-14) - line linkage: enabled, not-required (an
        # unlinked line is the common case, never a save-time error).
        PresetField("FromSODocKey", "from_so_doc_key", "int"),
        PresetField("FromSODtlKey", "from_so_line_key", "int"),
        PresetField("FromSODocList", "from_so_numbers", "string_list"),
        PresetField("FromPODocKey", "from_po_doc_key", "int"),
        PresetField("FromPODtlKey", "from_po_line_key", "int"),
        PresetField("FromPODocNo", "from_po_number", "string"),
    ),
    fingerprint_query=_PO_FINGERPRINT_QUERY,
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
        # feat/spo-container-number - AutoCount's generic `PO.Ref` is where
        # Sorento's 68,519-allocation gap traces to: nothing selected it, so
        # every SPO reached Sorento with no container. SPO-only (a PO is not
        # a container booking) - PO_PRESET deliberately carries no row
        # sourced from Ref. `PO.UDF_ShipOrder` ('T'/'F', a per-company UDF)
        # would let a company route non-SPO-numbered documents through this
        # same field too; that is a documented backlog follow-up
        # (BL-SS-*, "PO.UDF_ShipOrder routing"), not built here.
        PresetField("Ref", "container_number", "string"),
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
        # sprint-5/06 (AC-06-14) - line linkage: enabled, not-required (an
        # unlinked line is the common case, never a save-time error).
        PresetField("FromSODocKey", "from_so_doc_key", "int"),
        PresetField("FromSODtlKey", "from_so_line_key", "int"),
        PresetField("FromSODocList", "from_so_numbers", "string_list"),
        PresetField("FromPODocKey", "from_po_doc_key", "int"),
        PresetField("FromPODtlKey", "from_po_line_key", "int"),
        PresetField("FromPODocNo", "from_po_number", "string"),
    ),
    fingerprint_query=_PO_FINGERPRINT_QUERY,
)

# ── AC-CANCEL-PULL - Cancel SO / Cancel PO / Consignment / Consignment Return ──
#
# Four LINKED documents on the SAME shape (schema read live from the SORENTO
# book 2026-10-13, counts and column names only):
#
#   XS / XSDTL                               Cancel SO     - Debtor side
#   XP / XPDTL                               Cancel PO     - Creditor side
#   Consignment / ConsignmentDTL             CG- notes     - Debtor side, no source doc
#   ConsignmentReturn / ConsignmentReturnDTL CG returns    - Debtor side, FromDocType 'CG'
#
# Every header has `DocKey` (PK), `DocNo`, `DocDate`, `Cancelled` ('T'/'F'),
# `Ref`, `Note` and `LastModified datetime NOT NULL` - the same incremental
# cursor SO/PO ride. Every DTL has `DtlKey`, `DocKey`, `Seq`, `ItemCode`,
# `Location`, `Qty`, `UOM`, `UnitPrice`, `SubTotal`, `Description` and the
# link triple `FromDocType`/`FromDocNo`/`FromDocDtlKey`, all selected verbatim.
# `FromDocDtlKey` facts (XSDTL, SORENTO, crew read-only count 2026-10-13):
# every line keyed until Oct 2024 (2023: 7,898/7,898; 2024: 5,420/6,544,
# Nov 2024 only 208/658), and ALWAYS NULL from Dec 2024 on (2025: 0/7,553;
# 2026: 0/5,510) while `FromDocNo` stays filled. The other DTL tables were not
# broken down by year. The API's DO lines carry `FromDocDtlKey` 0 always. The
# link triple is sent verbatim; how a line is linked to its source line is the
# CRM's rule (owner: exact links only - decision on recovering line keys is
# pending), never inferred here.
#
# The SAME pseudo/display-line cut as SO/PO (`ItemCode IS NOT NULL AND Qty IS
# NOT NULL`) in BOTH the header `LineCount` aggregate and the line fetch:
# XSDTL carries 56 item lines with a NULL Qty and 123 NULL-item lines with a
# Qty, exactly the two shapes the SO live findings closed.
#
# WIRE (CRM #1623): the record sent is these SELECTed rows themselves (the
# DO/GRN doc-feed shape - header columns + `Details`), so every column keeps
# its AutoCount name (`PurchaseAgent`, not an alias) and every line carries
# its `DocKey`. The master-ref joins (`*AutoKey`) and fingerprint aggregates
# are stripped before sending (`canonical.documents.LINKED_*_INTERNAL_COLUMNS`).
#
# Table and column names below are CODE CONSTANTS - never operator input.
# `{database}` is substituted from the task's own company, exactly like the
# SO/PO/SPO presets above.

# Status for a document that has no "fulfilled" quantity: voided or not.
LINKED_DOCUMENT_STATUS_FORMULA = 'if(Cancelled == "T", "cancelled", "open")'

_DEBTOR_PARTY = (
    "c.AutoKey AS DebtorAutoKey, h.DebtorCode AS DebtorCode, "
    "h.DebtorName AS DebtorName, h.SalesAgent AS SalesAgent",
    "LEFT JOIN {database}.dbo.Debtor AS c ON c.AccNo = h.DebtorCode",
)
_CREDITOR_PARTY = (
    "s.AutoKey AS CreditorAutoKey, h.CreditorCode AS CreditorCode, "
    "h.CreditorName AS CreditorName, h.PurchaseAgent AS PurchaseAgent",
    "LEFT JOIN {database}.dbo.Creditor AS s ON s.AccNo = h.CreditorCode",
)

_LINKED_LINE_CUT = "d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"


def _linked_header_query(
    header_table: str, line_table: str, party: Tuple[str, str], *, transferred: bool = False,
) -> str:
    """``transferred`` (AC-CONSIGN-PULL, consignment only): a
    ``TransferedSum`` aggregate - a transfer out of a consignment may not
    bump the header ``LastModified``, so the header hash must move on it."""
    party_columns, party_join = party
    transferred_out = ", l.TransferedSum AS TransferedSum" if transferred else ""
    transferred_in = ", SUM(d.TransferedQty) AS TransferedSum" if transferred else ""
    return (
        "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, h.DocDate AS DocDate, "
        f"{party_columns}, h.Ref AS Ref, h.Description AS Description, "
        "h.RefDocNo AS RefDocNo, h.CurrencyCode AS CurrencyCode, "
        "h.Note AS Note, h.Cancelled AS Cancelled, "
        "h.LastModified AS LastModified, "
        "l.LineCount AS LineCount, l.QtySum AS QtySum, "
        "l.SubTotalSum AS SubTotalSum, l.MaxDtlKey AS MaxDtlKey, "
        "l.LinkedLineCount AS LinkedLineCount, l.FromDocKeySum AS FromDocKeySum"
        f"{transferred_out} "
        f"FROM {{database}}.dbo.{header_table} AS h "
        f"{party_join} "
        "OUTER APPLY ("
        "SELECT COUNT(*) AS LineCount, SUM(d.Qty) AS QtySum, "
        "SUM(d.SubTotal) AS SubTotalSum, MAX(d.DtlKey) AS MaxDtlKey, "
        "COUNT(d.FromDocDtlKey) AS LinkedLineCount, "
        "SUM(d.FromDocDtlKey) AS FromDocKeySum"
        f"{transferred_in} "
        f"FROM {{database}}.dbo.{line_table} AS d "
        f"WHERE d.DocKey = h.DocKey AND {_LINKED_LINE_CUT}"
        ") AS l"
    )


def _linked_line_query(line_table: str, *, transferred: bool = False) -> str:
    transferred_col = "d.TransferedQty AS TransferedQty, " if transferred else ""
    return (
        "SELECT d.DocKey AS DocKey, d.DtlKey AS DtlKey, d.Seq AS Seq, "
        "i.AutoKey AS ItemAutoKey, "
        "d.ItemCode AS ItemCode, d.Description AS Description, "
        "w.AutoKey AS LocationAutoKey, d.Location AS Location, d.Qty AS Qty, "
        "d.UOM AS UOM, d.UnitPrice AS UnitPrice, d.SubTotal AS SubTotal, "
        f"{transferred_col}"
        "d.FromDocType AS FromDocType, d.FromDocNo AS FromDocNo, "
        "d.FromDocDtlKey AS FromDocDtlKey "
        f"FROM {{database}}.dbo.{line_table} AS d "
        "LEFT JOIN {database}.dbo.Item AS i ON i.ItemCode = d.ItemCode "
        "LEFT JOIN {database}.dbo.Location AS w ON w.Location = d.Location "
        f"WHERE d.DocKey = :doc_key AND {_LINKED_LINE_CUT}"
    )


def _linked_fingerprint_query(
    header_table: str, line_table: str, *, transferred: bool = False,
) -> str:
    """The line-only-edit sweep (see `_SO_FINGERPRINT_QUERY`). Catches a line
    added/removed, a qty change and a change to a FILLED `FromDocDtlKey`;
    it does NOT see a text-only edit of `FromDocNo`/`ItemCode`/`Location`
    on an existing line (no portable text aggregate) - those reach the CRM
    on the next reconcile or the next header `LastModified` bump."""
    return (
        "SELECT d.DocKey AS DocKey, COUNT(*) AS LineCount, SUM(d.Qty) AS QtySum, "
        "MAX(d.DtlKey) AS MaxDtlKey, SUM(d.FromDocDtlKey) AS FromDocKeySum, "
        "COUNT(d.FromDocDtlKey) AS LinkedLineCount"
        f"{', SUM(d.TransferedQty) AS TransferedSum' if transferred else ''} "
        f"FROM {{database}}.dbo.{line_table} AS d "
        f"JOIN {{database}}.dbo.{header_table} AS h ON h.DocKey = d.DocKey "
        f"WHERE h.DocDate >= :from_date AND {_LINKED_LINE_CUT} "
        "GROUP BY d.DocKey"
    )


def _linked_header_fields(
    party_prefix: str, party_source: str, ref_transform: str, agent_column: str,
) -> Tuple[PresetField, ...]:
    return (
        PresetField("DocNo", "doc_no", "string", required=True),
        PresetField("DocDate", "doc_date", "date"),
        PresetField(
            "Cancelled", "status", "string", formula=LINKED_DOCUMENT_STATUS_FORMULA,
        ),
        PresetField(f"{party_source}AutoKey", f"{party_prefix}_ref", ref_transform),
        PresetField(f"{party_source}Code", f"{party_prefix}_code", "string"),
        PresetField(f"{party_source}Name", f"{party_prefix}_name", "string"),
        PresetField(agent_column, "agent_code", "string"),
        PresetField("Ref", "ref", "string"),
        PresetField("Note", "note", "string"),
    )


_LINKED_LINE_FIELDS: Tuple[PresetField, ...] = (
    PresetField("DtlKey", "source_ref", "string", required=True),
    PresetField("Seq", "line_number", "string"),
    PresetField("ItemAutoKey", "product_ref", "ref_product"),
    PresetField("ItemCode", "product_code", "string", required=True),
    PresetField("Description", "product_name", "string"),
    PresetField("LocationAutoKey", "warehouse_ref", "ref_warehouse"),
    PresetField("Location", "warehouse_code", "string"),
    PresetField("Qty", "qty", "decimal", required=True),
    PresetField("UOM", "uom", "string"),
    PresetField("UnitPrice", "unit_price", "decimal"),
    PresetField("SubTotal", "line_total", "decimal"),
    PresetField("FromDocType", "from_doc_type", "string"),
    PresetField("FromDocNo", "from_doc_no", "string"),
    PresetField("FromDocDtlKey", "from_doc_line_key", "int"),
)


# AC-CONSIGN-PULL - the consignment preset's extra line row (contract 2.9,
# sorento-crm#1654): the quantity already transferred out of the consignment.
_CONSIGNMENT_TRANSFERRED_LINE_FIELD = PresetField("TransferedQty", "qty_transferred", "decimal")


def _linked_preset(
    label: str, header_table: str, line_table: str, *, debtor_side: bool,
    transferred: bool = False,
) -> DocumentPreset:
    party = _DEBTOR_PARTY if debtor_side else _CREDITOR_PARTY
    header = (
        _linked_header_fields("customer", "Debtor", "ref_customer", "SalesAgent")
        if debtor_side
        else _linked_header_fields("supplier", "Creditor", "ref_supplier", "PurchaseAgent")
    )
    return DocumentPreset(
        label=label,
        header_query=_linked_header_query(header_table, line_table, party, transferred=transferred),
        line_query=_linked_line_query(line_table, transferred=transferred),
        key_columns=("DocKey",),
        watermark_column="LastModified",
        doc_date_column="DocDate",
        from_date="2026-01-01",
        filter_formula=None,
        header=header,
        line=_LINKED_LINE_FIELDS + ((_CONSIGNMENT_TRANSFERRED_LINE_FIELD,) if transferred else ()),
        fingerprint_query=_linked_fingerprint_query(header_table, line_table, transferred=transferred),
    )


CANCEL_SO_PRESET = _linked_preset("AutoCount Cancel SO", "XS", "XSDTL", debtor_side=True)
CANCEL_PO_PRESET = _linked_preset("AutoCount Cancel PO", "XP", "XPDTL", debtor_side=False)
CONSIGNMENT_PRESET = _linked_preset(
    "AutoCount Consignment", "Consignment", "ConsignmentDTL", debtor_side=True,
    transferred=True,
)
CONSIGNMENT_RETURN_PRESET = _linked_preset(
    "AutoCount Consignment Return", "ConsignmentReturn", "ConsignmentReturnDTL",
    debtor_side=True,
)

# ── Plan 32 - billing documents IV / CS / CN / DN (CRM contract 2.6) ─────────
#
# REF `documentation/plans/sprint-5/32-autocount-billing-feed-contract.md`
# (copied from the CRM's REF-autocount-billing-schema.md). Nothing here has
# been run against the billing tables yet (SELECT is granted after 25 Oct);
# the column names are the REF's [C-off]/[C-3p]/[I] reading, so the text is a
# PRESET - operator-editable after the REF section 6 checks.
#
# * Header: `NetTotal` (incl. tax, before cash rounding) is `total`, never
#   `FinalTotal` (= NetTotal + RoundAdj) or the CRM's `total = net_total +
#   tax_total` check fails. `local_net_total` = `LocalNetTotal - LocalTax`
#   (REF [?]: LocalNetTotal almost certainly includes tax). `DocStatus` is
#   selected so the task's `filterFormula` can drop drafts once REF check 6.2
#   names the draft letter (owner ruling 20 Oct: no guessed letter).
# * Billing line cut (differs from the order family): keep any line with a
#   non-zero `SubTotal` - a charge/discount/rounding line has no `ItemCode`
#   and may have a NULL `Qty` - and drop pure text lines (`SubTotal` NULL/0
#   AND `Qty` NULL). The SAME predicate in the header aggregate, the line
#   fetch and the sweep. `NULL <> 0` is unknown, so a NULL-SubTotal line
#   survives only on a non-NULL `Qty`.
# * Line fingerprint (contract 14.3): COUNT, SUM(Qty), SUM(SubTotal),
#   SUM(Tax), MAX(DtlKey), COUNT(FromDocDtlKey), plus SUM(TransferedQty) on
#   IVDTL/CSDTL - a line-only edit never bumps the header `LastModified`
#   (proven on SO). Named `LineFp*`, never `LineCount`: the LineCount guard
#   keys on that exact name.
# * Line links (contract 14.3, owner ruling 20 Oct: exact links only): each
#   source line table is joined ONLY on its own `FromDocType`, by DtlKey, to
#   read the DocKey of the header that owns the source line; the engine mints
#   `from_line_ref` from it (`mapping.MappingEngine._mint_plan32_line_refs`).
#   IV/CS lines come from SO or DO (QT has no ref), CN lines from IV, DN lines
#   have no source. The DO hop needs `DODTL` on the read-only grant (RUNBOOK
#   0.1): without it the line query fails loudly at Preview, never an
#   unlinked push.
# * Not handled yet (REF check 6.5): package parent/child lines (`DtlType`,
#   `ParentDtlKey`) are not de-duplicated - no rule exists yet.

BILLING_DOCUMENT_STATUS_FORMULA = 'if(Cancelled == "T", "cancelled", "posted")'

_BILLING_LINE_CUT = "(d.SubTotal <> 0 OR d.Qty IS NOT NULL)"

# (link column alias, source line table, join alias, FromDocType) per entity.
_BILLING_LINKS: Dict[str, Tuple[Tuple[str, str, str, str], ...]] = {
    ENTITY_INVOICE: (("LinkSODocKey", "SODTL", "so", "SO"), ("LinkDODocKey", "DODTL", "dd", "DO")),
    ENTITY_CASH_SALE: (("LinkSODocKey", "SODTL", "so", "SO"), ("LinkDODocKey", "DODTL", "dd", "DO")),
    ENTITY_CREDIT_NOTE: (("LinkIVDocKey", "IVDTL", "ivl", "IV"),),
    ENTITY_DEBIT_NOTE: (),
}

_BILLING_LINK_FIELDS: Dict[str, PresetField] = {
    "LinkSODocKey": PresetField("LinkSODocKey", "link_so_doc_key", "int"),
    "LinkDODocKey": PresetField("LinkDODocKey", "link_do_doc_key", "int"),
    "LinkIVDocKey": PresetField("LinkIVDocKey", "link_iv_doc_key", "int"),
}


def _billing_line_aggregates(*, transferred: bool) -> str:
    return (
        "COUNT(*) AS LineFpCount, SUM(d.Qty) AS LineFpQty, "
        "SUM(d.SubTotal) AS LineFpSubTotal, SUM(d.Tax) AS LineFpTax, "
        "MAX(d.DtlKey) AS LineFpMaxDtlKey, COUNT(d.FromDocDtlKey) AS LineFpLinked"
        + (", SUM(d.TransferedQty) AS LineFpTransfered" if transferred else "")
    )


def _billing_header_query(
    header_table: str, line_table: str, *, transferred: bool, against: bool,
) -> str:
    fingerprint_out = (
        "l.LineFpCount AS LineFpCount, l.LineFpQty AS LineFpQty, "
        "l.LineFpSubTotal AS LineFpSubTotal, l.LineFpTax AS LineFpTax, "
        "l.LineFpMaxDtlKey AS LineFpMaxDtlKey, l.LineFpLinked AS LineFpLinked"
        + (", l.LineFpTransfered AS LineFpTransfered" if transferred else "")
    )
    return (
        "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, h.DocDate AS DocDate, "
        "h.DocStatus AS DocStatus, c.AutoKey AS DebtorAutoKey, "
        "h.DebtorCode AS DebtorCode, h.DebtorName AS DebtorName, "
        "h.SalesAgent AS SalesAgent, h.CurrencyCode AS CurrencyCode, "
        "h.CurrencyRate AS CurrencyRate, h.TotalExTax AS TotalExTax, h.Tax AS Tax, "
        "h.NetTotal AS NetTotal, h.LocalNetTotal - h.LocalTax AS LocalNetExTax, "
        "h.Ref AS Ref, h.Description AS Description, "
        + ("h.OurInvoiceNo AS OurInvoiceNo, " if against else "")
        + "h.Cancelled AS Cancelled, h.LastModified AS LastModified, "
        f"{fingerprint_out} "
        f"FROM {{database}}.dbo.{header_table} AS h "
        "LEFT JOIN {database}.dbo.Debtor AS c ON c.AccNo = h.DebtorCode "
        f"OUTER APPLY (SELECT {_billing_line_aggregates(transferred=transferred)} "
        f"FROM {{database}}.dbo.{line_table} AS d "
        f"WHERE d.DocKey = h.DocKey AND {_BILLING_LINE_CUT}) AS l"
    )


def _billing_line_query(line_table: str, links: Tuple[Tuple[str, str, str, str], ...]) -> str:
    link_columns = "".join(f", {alias}.DocKey AS {column}" for column, _, alias, _ in links)
    link_joins = "".join(
        f" LEFT JOIN {{database}}.dbo.{table} AS {alias} "
        f"ON d.FromDocType = '{kind}' AND {alias}.DtlKey = d.FromDocDtlKey"
        for _, table, alias, kind in links
    )
    return (
        "SELECT d.DocKey AS DocKey, d.DtlKey AS DtlKey, d.Seq AS Seq, "
        "i.AutoKey AS ItemAutoKey, d.ItemCode AS ItemCode, "
        "d.Description AS Description, d.UOM AS UOM, d.Qty AS Qty, "
        "d.UnitPrice AS UnitPrice, d.DiscountAmt AS DiscountAmt, "
        "d.SubTotalExTax AS SubTotalExTax, d.TaxCode AS TaxCode, "
        "d.TaxRate AS TaxRate, d.Tax AS Tax, d.SubTotal AS SubTotal, "
        "d.FromDocType AS FromDocType, d.FromDocNo AS FromDocNo, "
        f"d.FromDocDtlKey AS FromDocDtlKey{link_columns} "
        f"FROM {{database}}.dbo.{line_table} AS d "
        "LEFT JOIN {database}.dbo.Item AS i ON i.ItemCode = d.ItemCode"
        f"{link_joins} "
        f"WHERE d.DocKey = :doc_key AND {_BILLING_LINE_CUT}"
    )


def _billing_fingerprint_query(header_table: str, line_table: str, *, transferred: bool) -> str:
    return (
        f"SELECT d.DocKey AS DocKey, {_billing_line_aggregates(transferred=transferred)} "
        f"FROM {{database}}.dbo.{line_table} AS d "
        f"JOIN {{database}}.dbo.{header_table} AS h ON h.DocKey = d.DocKey "
        f"WHERE h.DocDate >= :from_date AND {_BILLING_LINE_CUT} "
        "GROUP BY d.DocKey"
    )


_BILLING_HEADER_FIELDS: Tuple[PresetField, ...] = (
    PresetField("DocNo", "doc_no", "string", required=True),
    PresetField("DocDate", "doc_date", "date", required=True),
    PresetField(
        "Cancelled", "status", "string", formula=BILLING_DOCUMENT_STATUS_FORMULA, required=True,
    ),
    PresetField("LastModified", "source_modified_at", "datetime"),
    PresetField("DebtorAutoKey", "customer_ref", "ref_customer"),
    PresetField("DebtorCode", "customer_code", "string"),
    PresetField("DebtorName", "customer_name", "string"),
    PresetField("SalesAgent", "agent_code", "string"),
    PresetField("CurrencyCode", "currency_code", "string"),
    PresetField("CurrencyRate", "currency_rate", "decimal"),
    PresetField("TotalExTax", "net_total", "decimal", required=True),
    PresetField("Tax", "tax_total", "decimal", required=True),
    PresetField("NetTotal", "total", "decimal", required=True),
    PresetField("LocalNetExTax", "local_net_total", "decimal", required=True),
    PresetField("Ref", "ref", "string"),
    PresetField("Description", "description", "string"),
)

_BILLING_LINE_FIELDS: Tuple[PresetField, ...] = (
    PresetField("DtlKey", "source_ref", "string", required=True),
    PresetField("Seq", "line_number", "int"),
    PresetField("ItemAutoKey", "product_ref", "ref_product"),
    PresetField("ItemCode", "product_code", "string"),
    PresetField("Description", "description", "string"),
    PresetField("UOM", "uom", "string"),
    PresetField("Qty", "quantity", "decimal"),
    PresetField("UnitPrice", "unit_price", "decimal"),
    PresetField("DiscountAmt", "discount_amount", "decimal"),
    PresetField("SubTotalExTax", "net_amount", "decimal"),
    PresetField("TaxCode", "tax_code", "string"),
    PresetField("TaxRate", "tax_rate", "decimal"),
    PresetField("Tax", "tax_amount", "decimal"),
    PresetField("SubTotal", "line_total", "decimal"),
    PresetField("FromDocType", "from_doc_type", "string"),
    PresetField("FromDocNo", "from_doc_no", "string"),
    PresetField("FromDocDtlKey", "from_doc_line_key", "int"),
)


def _billing_preset(
    label: str, entity_type: str, header_table: str, line_table: str, *,
    transferred: bool = False, against: bool = False,
) -> DocumentPreset:
    links = _BILLING_LINKS[entity_type]
    header = _BILLING_HEADER_FIELDS + (
        (PresetField("OurInvoiceNo", "against_doc_no", "string"),) if against else ()
    )
    return DocumentPreset(
        label=label,
        header_query=_billing_header_query(
            header_table, line_table, transferred=transferred, against=against,
        ),
        line_query=_billing_line_query(line_table, links),
        key_columns=("DocKey",),
        watermark_column="LastModified",
        doc_date_column="DocDate",
        # Contract 12 "Backfill": the start date is shared-service
        # configuration (owner ruling Q2, 1 Jan 2023).
        from_date="2023-01-01",
        filter_formula=None,
        header=header,
        line=_BILLING_LINE_FIELDS + tuple(_BILLING_LINK_FIELDS[column] for column, *_ in links),
        fingerprint_query=_billing_fingerprint_query(
            header_table, line_table, transferred=transferred,
        ),
    )


INVOICE_PRESET = _billing_preset(
    "AutoCount Invoice", ENTITY_INVOICE, "IV", "IVDTL", transferred=True,
)
CASH_SALE_PRESET = _billing_preset(
    "AutoCount Cash Sale", ENTITY_CASH_SALE, "CS", "CSDTL", transferred=True,
)
CREDIT_NOTE_PRESET = _billing_preset(
    "AutoCount Credit Note", ENTITY_CREDIT_NOTE, "CN", "CNDTL", against=True,
)
DEBIT_NOTE_PRESET = _billing_preset(
    "AutoCount Debit Note", ENTITY_DEBIT_NOTE, "DN", "DNDTL", against=True,
)


# ── Plan 32 - AR outstanding sweep (CRM contract 2.10) ───────────────────────
#
# One record per DEBTOR (contract 14.2, the whole truth for that debtor), run
# as a document task: the header row is the debtor, its lines are its OPEN AR
# items. Owner rulings 20 Oct:
# * Scope = every debtor with ANY AR row, open or not, so a debtor whose last
#   item is paid re-stages (its fingerprint moves) and pushes `0` / `[]`.
# * `TotalOutstanding` = SUM(ARInvoice.Outstanding) + SUM(ARDN.Outstanding)
#   - SUM(ARCN.NetTotal - ARCN.KnockOffAmt) (Q1 (a)). REF section 4 names no
#   rate column on the AR tables, so this is right for MYR debtors only until
#   the REF section 6 check names the debtor figure (or a rate column).
# * `Outstanding` per item stays in the document's own currency (CRM displays
#   it with the document's `currency_code`).
# An AR row maps to its billing document by `DocNo` + `DebtorCode` with
# EXACTLY one match across the table(s) it can come from (`SourceType`/
# `SourceKey` are REF [I], unconfirmed); an ARInvoice row can be an IV or a CS.
# An AR row with no single match (hand-keyed AR, ambiguous number) is in the
# total but not in the lines. A CN's item is the unapplied amount, negative.
# The debtor's latest AR `LastModified` is the watermark AND the date floor;
# a knock-off may bump no `LastModified`, which the fingerprint sweep (SUM,
# open COUNT, MAX(LastModified), contract 14.3) catches on its interval. The
# read time (`as_of`) is stamped at mapping time - never a SQL column, which
# would move every debtor's row hash on every run.
# Unconfirmed until access (REF section 6): `Cancelled` on ARDN/ARCN (only
# ARInvoice lists it), and whether a knock-off bumps any `LastModified`.

_AR_ITEMS = (
    "SELECT i.DebtorCode AS DebtorCode, i.Outstanding AS Amount, "
    "i.LastModified AS LastModified "
    "FROM {database}.dbo.ARInvoice AS i WHERE COALESCE(i.Cancelled, 'F') <> 'T' "
    "UNION ALL SELECT n.DebtorCode, n.Outstanding, n.LastModified "
    "FROM {database}.dbo.ARDN AS n "
    "UNION ALL SELECT r.DebtorCode, -(r.NetTotal - r.KnockOffAmt), r.LastModified "
    "FROM {database}.dbo.ARCN AS r"
)

_AR_DEBTOR_TOTALS = (
    "SELECT a.DebtorCode AS DebtorCode, SUM(a.Amount) AS TotalOutstanding, "
    "SUM(CASE WHEN a.Amount <> 0 THEN 1 ELSE 0 END) AS OpenCount, "
    "MAX(a.LastModified) AS LastModified "
    f"FROM ({_AR_ITEMS}) AS a GROUP BY a.DebtorCode"
)

_AR_HEADER_QUERY = (
    "SELECT c.AutoKey AS DebtorKey, c.AccNo AS DebtorCode, "
    "s.TotalOutstanding AS TotalOutstanding, s.OpenCount AS OpenCount, "
    "s.LastModified AS LastModified "
    "FROM {database}.dbo.Debtor AS c "
    f"JOIN ({_AR_DEBTOR_TOTALS}) AS s ON s.DebtorCode = c.AccNo"
)


def _ar_match(table: str, ar_alias: str, prefix: str) -> str:
    return (
        f"(SELECT COUNT(*) FROM {{database}}.dbo.{table} AS b "
        f"WHERE b.DocNo = {ar_alias}.DocNo AND b.DebtorCode = {ar_alias}.DebtorCode) AS {prefix}Hits, "
        f"(SELECT MIN(b.DocKey) FROM {{database}}.dbo.{table} AS b "
        f"WHERE b.DocNo = {ar_alias}.DocNo AND b.DebtorCode = {ar_alias}.DebtorCode) AS {prefix}Key"
    )


_AR_LINE_QUERY = (
    "SELECT x.DocType AS DocType, x.BillingDocKey AS BillingDocKey, "
    "x.Outstanding AS Outstanding, x.DueDate AS DueDate FROM ("
    "SELECT CASE WHEN m.IvHits = 1 THEN 'IV' ELSE 'CS' END AS DocType, "
    "CASE WHEN m.IvHits = 1 THEN m.IvKey ELSE m.CsKey END AS BillingDocKey, "
    "i.Outstanding AS Outstanding, i.DueDate AS DueDate, i.DebtorCode AS DebtorCode "
    "FROM {database}.dbo.ARInvoice AS i "
    f"CROSS APPLY (SELECT {_ar_match('IV', 'i', 'Iv')}, {_ar_match('CS', 'i', 'Cs')}) AS m "
    "WHERE COALESCE(i.Cancelled, 'F') <> 'T' AND i.Outstanding <> 0 "
    "AND m.IvHits + m.CsHits = 1 "
    "UNION ALL SELECT 'DN', m.DnKey, n.Outstanding, n.DueDate, n.DebtorCode "
    "FROM {database}.dbo.ARDN AS n "
    f"CROSS APPLY (SELECT {_ar_match('DN', 'n', 'Dn')}) AS m "
    "WHERE n.Outstanding <> 0 AND m.DnHits = 1 "
    "UNION ALL SELECT 'CN', m.CnKey, -(r.NetTotal - r.KnockOffAmt), NULL, r.DebtorCode "
    "FROM {database}.dbo.ARCN AS r "
    f"CROSS APPLY (SELECT {_ar_match('CN', 'r', 'Cn')}) AS m "
    "WHERE r.NetTotal - r.KnockOffAmt <> 0 AND m.CnHits = 1"
    ") AS x JOIN {database}.dbo.Debtor AS c ON c.AccNo = x.DebtorCode "
    "WHERE c.AutoKey = :doc_key"
)

_AR_FINGERPRINT_QUERY = (
    "SELECT c.AutoKey AS DebtorKey, s.TotalOutstanding AS FpOutstanding, "
    "s.OpenCount AS FpOpenCount, s.LastModified AS FpLastModified "
    "FROM {database}.dbo.Debtor AS c "
    f"JOIN ({_AR_DEBTOR_TOTALS}) AS s ON s.DebtorCode = c.AccNo "
    "WHERE s.LastModified >= :from_date"
)

AR_OUTSTANDING_PRESET = DocumentPreset(
    label="AutoCount AR Outstanding",
    header_query=_AR_HEADER_QUERY,
    line_query=_AR_LINE_QUERY,
    key_columns=("DebtorKey",),
    watermark_column="LastModified",
    doc_date_column="LastModified",
    # A floor every live debtor clears: an open item is open whatever its age.
    from_date="2000-01-01",
    filter_formula=None,
    header=(
        PresetField("DebtorKey", "customer_ref", "ref_customer", required=True),
        PresetField("DebtorCode", "customer_code", "string"),
        PresetField("TotalOutstanding", "total_outstanding", "decimal", required=True),
    ),
    line=(
        PresetField("DocType", "ar_doc_type", "string", required=True),
        PresetField("BillingDocKey", "ar_doc_key", "int", required=True),
        PresetField("Outstanding", "outstanding", "decimal", required=True),
        PresetField("DueDate", "due_date", "date"),
    ),
    fingerprint_query=_AR_FINGERPRINT_QUERY,
)

DOCUMENT_PRESETS: Dict[str, DocumentPreset] = {
    ENTITY_SALES_ORDER: SO_PRESET,
    ENTITY_PURCHASE_ORDER: PO_PRESET,
    ENTITY_SHIPPING_ORDER: SPO_PRESET,
    ENTITY_CANCEL_SALES_ORDER: CANCEL_SO_PRESET,
    ENTITY_CANCEL_PURCHASE_ORDER: CANCEL_PO_PRESET,
    ENTITY_CONSIGNMENT: CONSIGNMENT_PRESET,
    ENTITY_CONSIGNMENT_RETURN: CONSIGNMENT_RETURN_PRESET,
    ENTITY_INVOICE: INVOICE_PRESET,
    ENTITY_CASH_SALE: CASH_SALE_PRESET,
    ENTITY_CREDIT_NOTE: CREDIT_NOTE_PRESET,
    ENTITY_DEBIT_NOTE: DEBIT_NOTE_PRESET,
    ENTITY_AR_OUTSTANDING: AR_OUTSTANDING_PRESET,
}


# sprint-5/12 (AC-12-12/15, UAC amendment 2026-09-22) - the TWO distinct
# causes a preset row lands disabled. Never one string for both: the reset
# dialog must not tell an operator a column is missing when the preset is
# simply withholding the row, because adding the lookup would change nothing.
# Mirrored on the frontend by `services/autocount-service.mock.ts`.
DISABLED_REASON_MISSING_COLUMN = "column not returned by the source"
DISABLED_REASON_WITHHELD = "withheld by the preset"


@dataclass(frozen=True)
class PlannedRow:
    """One preset row as ``_seed_rows`` WOULD create it (sprint-5/12, D1).

    Pure: no DB, no session. ``reset_mapping_to_preset``'s dry run and the
    seed itself both read this, so "would this row land enabled, and why
    not" can never drift between the preview an operator approves and the
    rows the apply writes.
    """

    spec: PresetField
    is_enabled: bool
    sort_order: int
    #: ``None`` when the row lands ENABLED.
    disabled_reason: Optional[str] = None
    #: What ``ac_field_mapping.is_required`` gets - the CATALOG's answer, not
    #: the preset's, whenever the catalog knows this entity (see
    #: ``planned_is_required``).
    is_required: bool = False


def planned_is_required(
    spec: PresetField, entity_type: Optional[str], scope: str
) -> bool:
    """Whether a seeded row is REQUIRED (sprint-5/12, owner ruling
    2026-09-22).

    ``mapping_catalog`` is the single source of truth: ``replace_mapping``
    already writes ``is_required = target in required_field_names(entity)``
    (``line_required_field_names`` for line scope), so deriving it the same
    way here makes first-save seeding, a reset and an ordinary Save agree.
    Before this, a seeded ``name``/``is_active`` row carried
    ``is_required=False`` (the preset's own flag) while a Save rewrote it to
    True, and the reset's dry run then reported those rows as ``changed``
    forever with no visible difference in the dialog.

    Falls back to ``PresetField.required`` only when the catalog has NO
    entry for that (entity, scope) - e.g. GRN's deliberately empty accepted
    set, where treating "no entry" as "nothing is required" would silently
    drop a preset's own intent. ``entity_type=None`` (a caller with no
    entity in hand) takes the same fallback.
    """
    if entity_type is None:
        return spec.required
    if scope == SCOPE_LINE:
        catalog = line_accepted_fields(entity_type)
        required = line_required_field_names(entity_type)
    else:
        catalog = accepted_fields(entity_type)
        required = required_field_names(entity_type)
    if not catalog:
        return spec.required
    return spec.canonical_field in required


def plan_rows(
    fields: Sequence[PresetField],
    # A plain sequence of COLUMN NAMES (review round 1 nit - the annotation
    # said ``Dict[str, str]`` while every live caller passes a list:
    # ``_preset_available_columns``'s ``effective_result_columns(...)``,
    # ``EtlService.update_task``'s stored ``result_columns``). ``None`` =
    # never previewed.
    available_columns: Optional[Sequence[str]],
    *,
    entity_type: Optional[str] = None,
    scope: str = SCOPE_HEADER,
    sort_start: int = 0,
) -> List[PlannedRow]:
    """The enable + required rules, split out of ``_seed_rows`` (sprint-5/12,
    D1).

    A column the task's ACTUAL query does not return lands disabled - still
    an ordinary editable row, never omitted (AC-02-16). ``available_columns
    =None`` (query never previewed) enables every row, matching "nothing
    proven wrong yet", EXCEPT a row the preset itself withholds
    (``PresetField.enabled=False``, AC-10-74's ``uom_code``), which is a
    policy orthogonal to column availability.

    The preset's own withholding wins the ``disabled_reason`` when BOTH
    causes apply - configuring the missing column would not enable the row,
    so naming it would send the operator down a dead end.

    ``is_required`` comes from the mapping catalog (``planned_is_required``)
    so a seeded row matches what a Save would write for the same field.
    """
    known = set(available_columns or ())
    planned: List[PlannedRow] = []
    for order, spec in enumerate(fields, start=sort_start):
        column_known = available_columns is None or spec.source_path in known
        if spec.canonical_field in LOCKED_MAPPING_SOURCES.get(entity_type, {}):
            # A locked identity row (branch AccNo/BranchCode) is ALWAYS seeded
            # enabled: the mapping save refuses to disable it, so a disabled
            # seed would 422 every plain Save with no way out.
            column_known = True
        reason: Optional[str] = None
        if not spec.enabled:
            reason = DISABLED_REASON_WITHHELD
        elif not column_known:
            reason = DISABLED_REASON_MISSING_COLUMN
        planned.append(
            PlannedRow(
                spec=spec,
                is_enabled=spec.enabled and column_known,
                sort_order=order,
                disabled_reason=reason,
                is_required=planned_is_required(spec, entity_type, scope),
            )
        )
    return planned


def _seed_rows(
    db: Session,
    tenant_id: str,
    company_id: str,
    entity_type: str,
    scope: str,
    fields: Sequence[PresetField],
    available_columns: Optional[Sequence[str]],
    *,
    sort_start: int = 0,
) -> int:
    planned = plan_rows(
        fields,
        available_columns,
        entity_type=entity_type,
        scope=scope,
        sort_start=sort_start,
    )
    for row in planned:
        spec = row.spec
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
                is_required=row.is_required,
                is_enabled=row.is_enabled,
                sort_order=row.sort_order,
            )
        )
    return len(planned)


def seed_document_mapping(
    db: Session,
    tenant_id: str,
    company_id: str,
    entity_type: str,
    *,
    header_columns: Optional[Sequence[str]],
    line_columns: Optional[Sequence[str]],
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
    if preset is not None:
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
                "fingerprintQuery": (
                    preset.fingerprint_query.replace("{database}", database_name)
                    if preset.fingerprint_query else None
                ),
            }
        ]
    # S7 (sprint-5/08 review round 1, AC-08-16 second clause) - this endpoint
    # used to answer ``[]`` for every HTTP entity (product/customer/
    # warehouse/product_category/brand/unit_of_measure): it only ever
    # checked ``DOCUMENT_PRESETS``, so the Mapping tab's "Use preset" action
    # had nothing to show for the entities this plan actually added. No
    # ``{database}`` substitution applies to an HTTP preset - there is no
    # query text, only the endpoint path + field picks.
    http_preset = HTTP_PRESETS.get(entity_type)
    if http_preset is not None:
        return [
            {
                "entityType": entity_type,
                "label": http_preset.label,
                "path": http_preset.path,
                "keyFields": list(http_preset.key_fields),
                "watermarkField": http_preset.watermark_field,
                "distinctOf": (
                    list(http_preset.distinct_of) if http_preset.distinct_of else None
                ),
            }
        ]
    return []


# ── open REST API presets (sprint-5/08, AC-08-16) ─────────────────────────────
#
# The six confirmed ``hapi.sorento.cc.cd`` entities' default task config
# (endpoint path + key/watermark/distinctOf) and seeded mapping rows - the
# HTTP-source counterpart of ``DOCUMENT_PRESETS`` above, seeded the SAME
# seed-if-absent way (``EtlService.update_task``'s HTTP branch), never
# re-applied once an operator has edited the mapping.


@dataclass(frozen=True)
class HttpPreset:
    """One HTTP-source entity's default task config + seeded mapping rows."""

    label: str
    path: str
    key_fields: Tuple[str, ...]
    watermark_field: Optional[str]
    distinct_of: Optional[Tuple[str, ...]]
    rows: Tuple[PresetField, ...]
    # sprint-5/10 (AC-10-04, R9) - ANY preset MAY carry pre-filled lookups;
    # defaults empty so every OTHER preset in this file is unaffected. Each
    # entry is the SAME operator-editable shape ``http_source.lookups.
    # validate_lookups`` checks (``{path, as, on, fields}``) - a preset row,
    # never a special code path.
    lookups: Tuple[Dict[str, Any], ...] = ()
    # sprint-5/10 S5b (AC-10-40/41, R11) - ANY preset MAY carry a pre-filled
    # ``combine`` block (the SAME operator-editable shape
    # ``http_source.combine.validate_combine`` checks); ``None`` for every
    # OTHER preset in this file, unaffected.
    combine: Optional[Dict[str, Any]] = None


PRODUCT_HTTP_PRESET = HttpPreset(
    label="Item (open REST API)",
    path="/itembypage",
    key_fields=("ItemCode",),
    watermark_field="LastModified",
    distinct_of=None,
    lookups=(
        {
            "path": "/itemuombypage",
            "as": "uom",
            "on": [
                {"local": "ItemCode", "remote": "ItemCode"},
                {"local": "BaseUOM", "remote": "UOM", "match": "casefold_trim"},
            ],
            "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
        },
    ),
    rows=(
        PresetField("ItemCode", "code", "string", required=True),
        PresetField("Description", "name", "string"),
        # AC-10-73 (R10) - REPLACES the old `Desc2 -> description` row: the
        # manual Excel path writes `Description + " " + Desc2` (RAW join,
        # `.strip()` on the ENDS only - inner whitespace, e.g. a double
        # space, is NEVER collapsed) when `Desc2` is non-empty, else plain
        # `Description`. Sorento derives `is_discontinued`/L-W-H from this
        # TEXT, so parity is won here, not by a second code path.
        #
        #     !!  THIS ROW IS WHY THERE IS NO `Discontinued ->
        #         is_discontinued` ROW (BL-SS-260, owner ruling
        #         2026-09-22).  !!
        # Sorento reads "discontinued" off the `****` prefix of the
        # description TEXT this formula produces (plan 10 D22 + the Sorento
        # addendum; 2,882 live `SRT` descriptions carry it, pinned by
        # `test_s10_product_preset.py::test_description_starting_with_stars
        # _passes_through_unchanged`). `is_discontinued` is therefore absent
        # from `CanonicalProduct.SINK_FIELDS` and NEVER sent. Seeding a row
        # for it produced a mapping row the save gate refuses on a PUT and
        # every ordinary "Save mapping" silently swept away - a lie the
        # operator had to discover. `CanonicalProduct` still DECLARES the
        # field (staging/visibility, unchanged); only the preset row is
        # gone.
        PresetField(
            "Description",
            "description",
            "string",
            formula=(
                'trim(if(default(Desc2, "") != "", concat(Description, " ", '
                'Desc2), Description))'
            ),
        ),
        PresetField("ItemGroup", "category_code", "string"),
        PresetField("ItemBrand", "brand_code", "string"),
        # ITEM-TYPE-SS (partner of sorento #1450) - every `/itembypage` row
        # carries `ItemType`; existing tasks get this row from
        # `backfill_product_item_type` (module Alembic 0028).
        PresetField("ItemType", "item_type_code", "string"),
        # AC-10-74 (R10) - withheld during the check period: sending
        # `uom_code` would make a pull diverge from a manual upload on every
        # product (the manual template carries no UOM column). Seeded
        # PRESENT but DISABLED so the operator can see and re-enable it
        # deliberately - one item on the push-flip checklist.
        PresetField("BaseUOM", "uom_code", "string", enabled=False),
        PresetField("IsActive", "is_active", "t_f_bool"),
        # AC-10-59 (R5) - the pre-filled ItemUOM lookup's own alias, clamped
        # to 0 on a negative source price (a vendor sentinel, `-1.0`, not a
        # genuine price) as a VISIBLE, editable formula - never a coercion
        # hidden in `CanonicalProduct`. `<= 0` (not `< 0`) deliberately:
        # `-0.0` passes the model's `ge=0` bound and would otherwise be
        # delivered as the string `"-0.0"`.
        PresetField(
            "BaseUOMPrice", "list_price", "string",
            formula="if(number(value) <= 0, 0, number(value))",
        ),
    ),
)

CUSTOMER_HTTP_PRESET = HttpPreset(
    label="Debtor (open REST API)",
    path="/debtorbypage",
    key_fields=("AccNo",),
    watermark_field="LastModified",
    distinct_of=None,
    rows=(
        PresetField("AccNo", "code", "string", required=True),
        PresetField("CompanyName", "name", "string"),
        PresetField("Phone1", "phone_number", "string"),
        # SS-DEBTOR-AGENT - every `/debtorbypage` row carries `SalesAgent`;
        # existing tasks get this row from `backfill_customer_sales_agent`
        # (module Alembic 0029).
        PresetField("SalesAgent", "sales_agent_code", "string"),
        PresetField("IsActive", "is_active", "t_f_bool"),
    ),
)

WAREHOUSE_HTTP_PRESET = HttpPreset(
    label="Location (open REST API)",
    path="/location",
    key_fields=("Location",),
    watermark_field=None,
    distinct_of=None,
    rows=(
        PresetField("Location", "code", "string", required=True),
        PresetField("Description", "name", "string"),
        PresetField("Address1", "location", "string"),
        PresetField("IsActive", "is_active", "t_f_bool"),
    ),
)

PRODUCT_CATEGORY_HTTP_PRESET = HttpPreset(
    label="Item group (open REST API)",
    path="/ItemGroup",
    key_fields=("ItemGroup",),
    watermark_field=None,
    distinct_of=None,
    rows=(
        PresetField("ItemGroup", "code", "string", required=True),
        PresetField("Description", "name", "string", required=True),
        PresetField("Desc2", "description", "string"),
    ),
)

BRAND_HTTP_PRESET = HttpPreset(
    label="Item brand (open REST API)",
    path="/ItemBrand",
    key_fields=("ItemBrand",),
    watermark_field=None,
    distinct_of=None,
    rows=(
        PresetField("ItemBrand", "code", "string", required=True),
        # The vendor list's own ``Description`` is blank on every probed row
        # (UAC AC-08-16) - name = code, matching what Sorento's product path
        # already auto-creates today.
        PresetField("ItemBrand", "name", "string"),
        PresetField("Description", "description", "string"),
    ),
)

# sprint-5/14 section 11 (D23) - the paged `branchbypage` address records, a
# regular master like product. The vendor row is unique on (AccNo, BranchCode)
# (BranchCode alone repeats), so both key the row; the raw row travels to the
# CRM (`CanonicalBranch.sink_payload`), these three are only what mapping
# reads and lets a tenant override.
BRANCH_HTTP_PRESET = HttpPreset(
    label="Branches (open REST API)",
    path="/branchbypage",
    key_fields=("AccNo", "BranchCode"),
    watermark_field=None,
    distinct_of=None,
    rows=(
        PresetField("AccNo", "acc_no", "string", required=True),
        PresetField("BranchCode", "code", "string", required=True),
        PresetField("BranchName", "name", "string"),
    ),
)

UNIT_OF_MEASURE_HTTP_PRESET = HttpPreset(
    label="Item UOM (open REST API, distinct)",
    path="/itembypage",
    key_fields=("value",),
    watermark_field=None,
    distinct_of=("BaseUOM", "SalesUOM", "PurchaseUOM"),
    rows=(
        PresetField("value", "code", "string", required=True),
        PresetField("value", "name", "string"),
    ),
)

# sprint-5/10 S5b (AC-10-40/41) - the stock balance preset: two ordered
# lookups (item master for BaseUOM/Description, then ItemUOM for the
# conversion Rate) + a PRE-FILLED ``combine`` block that expresses exactly
# what the old named reducer did (D4/D5) - the owner configures nothing.
# Every formula/shape here is byte-identical to
# ``test_s10_s5a_preview_funnel.py``'s own already-GREEN ``STOCK_COMBINE``
# fixture (S5a) - the two must never quietly drift apart.
_STOCK_ITEM_LOOKUP: Dict[str, Any] = {
    "path": "/itembypage",
    "as": "item",
    "on": [{"local": "ItemCode", "remote": "ItemCode"}],
    "fields": [
        {"remote": "BaseUOM", "as": "ItemBaseUOM"},
        {"remote": "Description", "as": "ItemDescription"},
    ],
}
_STOCK_ITEM_UOM_LOOKUP: Dict[str, Any] = {
    "path": "/itemuombypage",
    "as": "uom",
    "on": [
        {"local": "ItemCode", "remote": "ItemCode"},
        {"local": "UOM", "remote": "UOM", "match": "casefold_trim"},
    ],
    "fields": [{"remote": "Rate", "as": "UomRate"}],
}
_STOCK_COMBINE: Dict[str, Any] = {
    "computed": [
        {"alias": "item_code", "formula": "trim(ItemCode)"},
        {"alias": "location_code", "formula": "trim(Location)"},
        {
            "alias": "base_qty",
            "formula": (
                "if(lower(trim(UOM)) == lower(trim(ItemBaseUOM)), "
                "number(BalQty), number(BalQty) * number(UomRate))"
            ),
        },
    ],
    "require": [
        {
            "name": "uom_rate",
            "formula": (
                "lower(trim(UOM)) == lower(trim(ItemBaseUOM)) or "
                "number(default(UomRate, 0)) > 0"
            ),
            "reason": "uom_rate_unresolved",
        }
    ],
    "measure": "base_qty",
    "groupBy": ["item_code", "location_code"],
    "measures": [{"source": "base_qty", "op": "sum", "alias": "qty"}],
    "carry": ["ItemDescription", "ItemBaseUOM"],
    "round": [{"measure": "qty", "mode": "half_up", "dp": 0}],
    "drop": [
        {"name": "zero", "formula": "qty == 0"},
        {"name": "negative", "formula": "qty < 0", "listRows": True},
    ],
}

STOCK_BALANCE_HTTP_PRESET = HttpPreset(
    label="Stock balance (open REST API)",
    path="/itembatchbalqtybypage",
    # AC-10-40 - key fields are DERIVED from `combine.groupBy` at save time
    # (`EtlService._update_http_task`), never typed on the preset itself.
    key_fields=(),
    watermark_field=None,
    distinct_of=None,
    lookups=(_STOCK_ITEM_LOOKUP, _STOCK_ITEM_UOM_LOOKUP),
    combine=_STOCK_COMBINE,
    rows=(
        PresetField("item_code", "item_code", "string", required=True),
        PresetField("location_code", "location_code", "string", required=True),
        PresetField("ItemDescription", "item_description", "string"),
        PresetField("ItemBaseUOM", "uom_code", "string"),
        PresetField("qty", "qty", "int", required=True),
    ),
)

HTTP_PRESETS: Dict[str, HttpPreset] = {
    ENTITY_PRODUCT: PRODUCT_HTTP_PRESET,
    ENTITY_CUSTOMER: CUSTOMER_HTTP_PRESET,
    ENTITY_WAREHOUSE: WAREHOUSE_HTTP_PRESET,
    ENTITY_PRODUCT_CATEGORY: PRODUCT_CATEGORY_HTTP_PRESET,
    ENTITY_BRAND: BRAND_HTTP_PRESET,
    ENTITY_UNIT_OF_MEASURE: UNIT_OF_MEASURE_HTTP_PRESET,
    ENTITY_STOCK_BALANCE: STOCK_BALANCE_HTTP_PRESET,
    ENTITY_BRANCH: BRANCH_HTTP_PRESET,
}

# Parity-pinned (AC-08-17): backend keys == frontend `AC_HTTP_ENTITY_TYPES`.
HTTP_ENTITY_TYPES: Tuple[str, ...] = tuple(HTTP_PRESETS.keys())


def seed_http_preset_mapping(
    db: Session,
    tenant_id: str,
    company_id: str,
    entity_type: str,
    *,
    columns: Optional[Sequence[str]],
) -> int:
    """Seed an HTTP task's preset mapping rows on its first clean save
    (AC-08-16) - the SAME seed-if-absent contract as ``seed_document_mapping``
    (the caller only invokes this when the entity's mapping is empty).
    Returns the count created (0 when no preset is registered)."""
    preset = HTTP_PRESETS.get(entity_type)
    if preset is None:
        return 0
    created = _seed_rows(
        db, tenant_id, company_id, entity_type, SCOPE_HEADER, preset.rows, columns
    )
    db.flush()
    return created


def resolve_preset_rows(
    config: AcEntityConfig,
) -> Optional[Tuple[str, Tuple[PresetField, ...]]]:
    """The HEADER-scope preset for one task, or ``None`` when none is
    registered (sprint-5/12, AC-12-11, D1/D5).

    The rule is EXACTLY the one first-save seeding already follows, read off
    the SAME two registries: an ``autocount_http`` task gets
    ``HTTP_PRESETS[entity_type].rows`` (what ``seed_http_preset_mapping``
    seeds), anything else gets ``DOCUMENT_PRESETS[entity_type].header``
    (what ``seed_document_mapping`` seeds into ``SCOPE_HEADER``). So the
    covered set is exactly TWO families, both honestly reset-able: the HTTP
    presets (product/customer/warehouse/product_category/brand/
    unit_of_measure/stock_balance) and the DOCUMENT presets (sales_order/
    purchase_order/shipping_order, HEADER scope only - a reset never touches
    a line row, AC-12-13/27).

    Everything else answers ``None`` - the route turns that into a 422 and
    ``MappingViewResponse.hasPreset`` into ``False``, so the UI never has to
    guess "does this entity have a preset" from its entity type (D5: an HTTP
    task and a DB task of the SAME entity can legitimately differ).

    NOT a preset, deliberately: ``company_service._seed_mapping_rows``'s own
    ``DEFAULT_MAPPINGS`` starter rows for ``goods_received_note``/
    ``supplier``/``customer`` on a legacy ``autocount_read`` company. Those
    are a one-off convenience seed with no registry entry here, so such a
    task answers ``hasPreset=False``, the menu item never appears and a
    hand-posted reset 422s. That is the SAFE direction: resetting to a table
    this resolver does not own would silently overwrite an operator's rows
    with a shape nothing else in this module treats as authoritative.

    Row CONTENT lives in one place per source type (the registries above) and
    the enable rule in one place for everyone (``plan_rows``) - the two
    things D1 exists to keep from drifting.
    """
    if config.source_impl == SOURCE_IMPL_AUTOCOUNT_HTTP:
        http_preset = HTTP_PRESETS.get(config.entity_type)
        return (http_preset.label, http_preset.rows) if http_preset else None
    document_preset = DOCUMENT_PRESETS.get(config.entity_type)
    return (document_preset.label, document_preset.header) if document_preset else None
