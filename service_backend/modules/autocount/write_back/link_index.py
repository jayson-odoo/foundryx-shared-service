"""The PO -> SO link index writer (plan 62 D8): the ONE function that keeps ``ac_po_so_link`` true.

Called from every staging write of a PURCHASE ORDER (the sync stage / delete paths and the
write-back stage). The rows come from the PO's NEWEST staged copy only; a cancelled or deleted
PO has none. Never commits: the caller's transaction carries it.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from modules.autocount.canonical.documents import ENTITY_PURCHASE_ORDER
from modules.autocount.write_back.repository import PoSoLinkRepository, StagedDocRepository

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
