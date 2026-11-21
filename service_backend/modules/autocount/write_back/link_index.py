"""The PO -> SO link index writer (plan 62 D8): the ONE function that keeps ``ac_po_so_link`` true.

Called from every staging write of a PURCHASE ORDER (the sync stage / delete paths and the
write-back stage). The rows come from the PO's NEWEST staged copy only; a cancelled or deleted
PO has none. Never commits: the caller's transaction carries it.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from modules.autocount.canonical.documents import ENTITY_PURCHASE_ORDER, ENTITY_SALES_ORDER, ENTITY_SHIPPING_ORDER
from modules.autocount.write_back.repository import (
    PoSoLinkRepository,
    SoRowIndexRepository,
    SpoPoLinkRepository,
    StagedDocRepository,
)

Link = Tuple[Optional[int], int, Decimal]


def _int(value: Any) -> Optional[int]:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def links_of(raw: Optional[Dict[str, Any]]) -> List[Link]:
    """``(po_dtl_key, so_dtl_key, qty)`` of every linked, positive-qty line of a staged PO copy."""
    lines = (raw or {}).get("_lines")
    out: List[Link] = []
    for line in lines if isinstance(lines, list) else []:
        if not isinstance(line, dict):
            continue
        so_key = _int(line.get("FromSODtlKey"))
        if not so_key:
            continue
        try:
            qty = Decimal(str(line.get("Qty") if line.get("Qty") is not None else 0))
        except InvalidOperation:
            continue
        if qty > 0:
            out.append((_int(line.get("DtlKey")), so_key, qty))
    return out


def refresh_po_links(db: Session, tenant_id: str, company_id: str, source_ref: str, *, deleted: bool = False) -> None:
    """Rewrite one PO's index rows from its newest staged copy (none when it is deleted or cancelled)."""
    links: List[Link] = []
    if not deleted:
        newest = StagedDocRepository(db).newest(tenant_id, company_id, ENTITY_PURCHASE_ORDER, source_ref)
        raw = (newest.raw_json or {}) if newest is not None else {}
        if newest is not None and raw.get("Cancelled") != "T":
            links = links_of(raw)
    PoSoLinkRepository(db).replace_for_po(tenant_id, company_id, source_ref, links)


def refresh_po_links_from_doc(db: Session, tenant_id: str, company_id: str, source_ref: str, doc: Dict[str, Any]) -> None:
    """Rewrite one PO's index rows from a document AutoCount just read back (a verified write), for
    the case where the staged copy belongs to another job and is left alone."""
    links = [] if doc.get("Cancelled") == "T" else links_of({"_lines": doc.get("Details")})
    PoSoLinkRepository(db).replace_for_po(tenant_id, company_id, source_ref, links)


# ── SPO -> PO-row index (lane AUTOCOUNT-STRANDED-OPS, C.d) ──────────────────────────────────────────

SpoLink = Tuple[Optional[int], int, Decimal]


def spo_links_of(raw: Optional[Dict[str, Any]]) -> List[SpoLink]:
    """``(spo_dtl_key, po_dtl_key, qty)`` of every line of a staged SPO copy that points at a PO row
    (``FromDocDtlKey``), whatever its qty: a zero-qty row still holds the PO row (``ROW_ON_SPO``)."""
    lines = (raw or {}).get("_lines")
    out: List[SpoLink] = []
    for line in lines if isinstance(lines, list) else []:
        if not isinstance(line, dict):
            continue
        po_key = _int(line.get("FromDocDtlKey"))
        if not po_key:
            continue
        try:
            qty = Decimal(str(line.get("Qty") if line.get("Qty") is not None else 0))
        except InvalidOperation:
            qty = Decimal(0)
        out.append((_int(line.get("DtlKey")), po_key, qty))
    return out


def refresh_spo_links(db: Session, tenant_id: str, company_id: str, source_ref: str, *, deleted: bool = False) -> None:
    """Rewrite one SPO's index rows from its newest staged copy (none when it is deleted or cancelled)."""
    links: List[SpoLink] = []
    doc_no: Optional[str] = None
    if not deleted:
        newest = StagedDocRepository(db).newest(tenant_id, company_id, ENTITY_SHIPPING_ORDER, source_ref, skip_failed=True)
        raw = (newest.raw_json or {}) if newest is not None else {}
        if newest is not None and raw.get("Cancelled") != "T":
            links = spo_links_of(raw)
            doc_no = str(raw.get("DocNo") or newest.doc_no or source_ref)
    SpoPoLinkRepository(db).replace_for_spo(tenant_id, company_id, source_ref, doc_no, links)


def refresh_spo_links_from_doc(db: Session, tenant_id: str, company_id: str, source_ref: str,
                               doc: Dict[str, Any]) -> None:
    """Rewrite one SPO's index rows from a document AutoCount just read back (a verified write), for the case
    where the staged copy belongs to another job and is left alone: every SPO of a live book (plan 71)."""
    cancelled = doc.get("Cancelled") == "T"
    links = [] if cancelled else spo_links_of({"_lines": doc.get("Details")})
    doc_no = None if cancelled else str(doc.get("DocNo") or source_ref)
    SpoPoLinkRepository(db).replace_for_spo(tenant_id, company_id, source_ref, doc_no, links)


# ── SO-row index (lane AUTOCOUNT-STRANDED-OPS, C.d) ─────────────────────────────────────────────────

SoRow = Tuple[int, Optional[str], bool]


def so_rows_of(copies: List[Dict[str, Any]]) -> List[SoRow]:
    """``(so_dtl_key, location, ambiguous)`` of every line of an SO's equally-newest staged copies: one entry
    per DtlKey; copies that disagree on its location -> ``(key, None, True)`` (``SO_LOCATION_AMBIGUOUS``)."""
    seen: Dict[int, set] = {}
    for raw in copies:
        lines = (raw or {}).get("_lines")
        for line in lines if isinstance(lines, list) else []:
            if not isinstance(line, dict):
                continue
            key = _int(line.get("DtlKey"))
            if key:
                seen.setdefault(key, set()).add(str(line.get("Location") or ""))
    return [(key, next(iter(locs)) if len(locs) == 1 else None, len(locs) > 1) for key, locs in seen.items()]


def refresh_so_rows(db: Session, tenant_id: str, company_id: str, source_ref: str, *, deleted: bool = False) -> None:
    """Rewrite one SO's index rows from its newest staged copy, every copy staged at that same moment
    included (none when the SO is deleted)."""
    rows: List[SoRow] = []
    doc_no: Optional[str] = None
    doc_key: Optional[str] = None
    staged_at = None
    if not deleted:
        staged = StagedDocRepository(db)
        newest = staged.newest(tenant_id, company_id, ENTITY_SALES_ORDER, source_ref, skip_failed=True)
        if newest is not None:
            copies = staged.copies_at(tenant_id, company_id, ENTITY_SALES_ORDER, source_ref, newest.created_at)
            rows = so_rows_of([c.raw_json or {} for c in copies] or [newest.raw_json or {}])
            doc_no = str((newest.raw_json or {}).get("DocNo") or newest.doc_no or "")
            raw_key = (newest.raw_json or {}).get("DocKey")
            doc_key = None if raw_key in (None, "") else str(raw_key)  # the raw DocKey (task key columns vary)
            staged_at = newest.created_at
    SoRowIndexRepository(db).replace_for_so(tenant_id, company_id, source_ref, doc_no, staged_at, rows, doc_key)


# the entities whose staging writes keep a write-back index
INDEXED_ENTITIES = (ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER, ENTITY_SALES_ORDER)


def refresh_links(db: Session, tenant_id: str, company_id: str, entity_type: str, source_ref: str, *,
                  deleted: bool = False) -> None:
    """The ONE hook every staging write calls: keeps whichever link index the entity feeds true."""
    if entity_type == ENTITY_PURCHASE_ORDER:
        refresh_po_links(db, tenant_id, company_id, source_ref, deleted=deleted)
    elif entity_type == ENTITY_SHIPPING_ORDER:
        refresh_spo_links(db, tenant_id, company_id, source_ref, deleted=deleted)
    elif entity_type == ENTITY_SALES_ORDER:
        refresh_so_rows(db, tenant_id, company_id, source_ref, deleted=deleted)
