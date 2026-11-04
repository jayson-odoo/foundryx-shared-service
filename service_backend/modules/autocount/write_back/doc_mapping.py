"""Wrapper document -> canonical record (plan 55 S4, AC-55-30/31).

A document read through the AutoCount wrapper (Details rows with ItemCode,
Location, FromSODtlKey, FromSODocList, FromDocType/FromDocNo/FromDocDtlKey) is
mapped through the UNCHANGED ``MappingEngine`` with the in-memory
``WRAPPER_PO`` / ``WRAPPER_SPO`` / ``WRAPPER_SO`` preset fields (never seeded,
never in ``HTTP_PRESETS``). Before mapping, the wrapper-only source keys the SQL
path gets from joins (``FromSODocKey``, ``FromPODocKey``) are resolved from the
company's staged SO / PO documents; an unresolved link keeps its document
number and drops the ref, it is never an error.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from modules.autocount.canonical.base import CanonicalRecord
from modules.autocount.canonical.documents import (
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
)
from modules.autocount.mapping import (
    SCOPE_HEADER,
    SCOPE_LINE,
    MappingEngine,
    MappingRow,
    flat_profile,
)
from modules.autocount.models import AcCompany
from modules.autocount.presets import (
    WRAPPER_PO,
    WRAPPER_SO,
    WRAPPER_SPO,
    PresetField,
    WrapperPreset,
)
from modules.autocount.write_back.repository import StagedDocRepository

Doc = Dict[str, Any]

KIND_PO = "PO"
KIND_SPO = "SPO"
KIND_SO = "SO"

ENTITY_BY_KIND = {
    KIND_PO: ENTITY_PURCHASE_ORDER,
    KIND_SPO: ENTITY_SHIPPING_ORDER,
    KIND_SO: ENTITY_SALES_ORDER,
}
_PRESET_BY_KIND = {KIND_PO: WRAPPER_PO, KIND_SPO: WRAPPER_SPO, KIND_SO: WRAPPER_SO}
_LINES_KEY = "_lines"


class WrapperMappingError(Exception):
    """The document could not be mapped; the text names fields, never data."""


def detect_kind(doc: Doc, kind: Optional[str] = None) -> str:
    """``kind`` when given, else SPO (``ShippingPO "T"``), SO (carries a
    ``DebtorCode``), otherwise PO."""
    if kind:
        return kind
    if doc.get("ShippingPO") == "T":
        return KIND_SPO
    if "DebtorCode" in doc:
        return KIND_SO
    return KIND_PO


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _rows(fields: Sequence[PresetField], scope: str) -> List[MappingRow]:
    return [
        MappingRow(
            source_path=f.source_path,
            canonical_field=f.canonical_field,
            transform=f.transform,
            scope=scope,
            is_required=f.required,
            is_enabled=True,
            formula=f.formula,
        )
        for f in fields
    ]


def mapping_rows(preset: WrapperPreset) -> List[MappingRow]:
    return _rows(preset.header, SCOPE_HEADER) + _rows(preset.line, SCOPE_LINE)


def _dtl_index(
    db: Session, tenant_id: str, company: AcCompany, entity_type: str
) -> Dict[int, Tuple[Any, str]]:
    """Staged line DtlKey -> (document DocKey, DocNo) for one entity (DtlKey is
    unique across an AutoCount book)."""
    index: Dict[int, Tuple[Any, str]] = {}
    for staged in StagedDocRepository(db).for_entity(tenant_id, company.id, entity_type):
        raw = staged.raw_json or {}
        for line in raw.get(_LINES_KEY) or []:
            if isinstance(line, dict) and line.get("DtlKey"):
                index[line["DtlKey"]] = (raw.get("DocKey"), str(raw.get("DocNo") or ""))
    return index


def _present(value: Any) -> bool:
    """A wrapper link key counts only when set (0 and "" mean unlinked)."""
    return not _blank(value) and value != 0


def _keep_line(line: Doc) -> bool:
    """The SQL path's ``ItemCode IS NOT NULL AND Qty IS NOT NULL`` cut: a blank
    item with a zero quantity is a spacer row; a blank item WITH a quantity is
    kept so the required product ref fails loudly."""
    if not _blank(line.get("ItemCode")):
        return line.get("Qty") is not None
    qty = line.get("Qty")
    return qty is not None and Decimal(str(qty)) != 0


def _premap_line(
    line: Doc, kind: str, so_index: Dict[int, Tuple[Any, str]], po_index: Dict[int, Tuple[Any, str]]
) -> Doc:
    out = dict(line)
    so_key = line.get("FromSODtlKey")
    out["FromSODtlKey"] = so_key if _present(so_key) else None
    out["FromSODocList"] = line.get("FromSODocList") if _present(line.get("FromSODocList")) else None
    out["FromSODocKey"] = so_index[so_key][0] if _present(so_key) and so_key in so_index else None
    po_dtl = line.get("FromDocDtlKey") if line.get("FromDocType") == "PO" else None
    out["FromPODtlKey"] = po_dtl if _present(po_dtl) else None
    out["FromPODocNo"] = line.get("FromDocNo") if out["FromPODtlKey"] is not None else None
    out["FromPODocKey"] = po_index[po_dtl][0] if _present(po_dtl) and po_dtl in po_index else None
    return out


def _raw_for_mapping(
    db: Session, tenant_id: str, company: AcCompany, doc: Doc, kind: str
) -> Doc:
    """The document as ``{header..., "_lines": [...]}``: accepts either shape
    (``Details`` from the wrapper, ``_lines`` as staged)."""
    lines = doc.get(_LINES_KEY)
    if lines is None:
        lines = doc.get("Details") or []
    raw = {k: v for k, v in doc.items() if k not in ("Details", _LINES_KEY)}
    so_index = _dtl_index(db, tenant_id, company, ENTITY_SALES_ORDER) if kind != KIND_SO else {}
    po_index = _dtl_index(db, tenant_id, company, ENTITY_PURCHASE_ORDER) if kind == KIND_SPO else {}
    raw[_LINES_KEY] = [
        _premap_line(line, kind, so_index, po_index)
        for line in lines
        if isinstance(line, dict) and _keep_line(line)
    ]
    return raw


def map_wrapper_document(
    db: Session,
    *,
    tenant_id: str,
    company: AcCompany,
    doc: Doc,
    kind: Optional[str] = None,
) -> Tuple[str, CanonicalRecord]:
    """``(entity_type, canonical record)`` for a wrapper document, or a
    ``WrapperMappingError`` naming the failing fields."""
    resolved = detect_kind(doc, kind)
    entity_type = ENTITY_BY_KIND[resolved]
    engine = MappingEngine(
        mapping_rows(_PRESET_BY_KIND[resolved]),
        entity_type=entity_type,
        profile=flat_profile(entity_type, ["DocKey"]),
        database_name=company.database_name,
    )
    mapped = engine.map_document(_raw_for_mapping(db, tenant_id, company, doc, resolved))
    if not mapped.ok:
        raise WrapperMappingError("; ".join(err.message() for err in mapped.errors)[:2000])
    return entity_type, mapped.record
