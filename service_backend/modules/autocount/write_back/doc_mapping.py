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
from modules.autocount.write_back.repository import SoRowIndexRepository, StagedDocRepository

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


def _doc_key_of(source_ref: str) -> Any:
    """The DocKey of a staged ``{db}:{DocKey}`` source ref (int when numeric, as the raw carries it)."""
    tail = str(source_ref).rsplit(":", 1)[-1]
    try:
        return int(tail)
    except ValueError:
        return tail or None


def _so_dtl_lookup(db: Session, tenant_id: str, company: AcCompany, keys: Sequence[int]) -> Dict[int, Tuple[Any, str]]:
    """SO line DtlKey -> (DocKey, DocNo) for just ``keys``, from the SO-row index (lane AUTOCOUNT-STRANDED-OPS
    C.d): one indexed query, never a load of every staged SO. The newest staged SO holding a key wins."""
    out: Dict[int, Tuple[Any, str]] = {}
    rows = SoRowIndexRepository(db).rows_for_keys(tenant_id, company.id, keys)
    floor = ""
    for row in sorted(rows, key=lambda r: (r.staged_at.isoformat() if r.staged_at else floor, r.so_source_ref)):
        out[int(row.so_dtl_key)] = (_doc_key_of(row.so_source_ref), str(row.so_doc_no or ""))
    return out


def _po_dtl_lookup(db: Session, tenant_id: str, company: AcCompany, lines: Sequence[Doc]) -> Dict[int, Tuple[Any, str]]:
    """PO line DtlKey -> (DocKey, DocNo) for the PO rows an SPO's lines point at: the newest staged copy of each
    PO the lines NAME (``FromDocNo``, one indexed query), never a load of every staged PO (C.d). A line that
    names no PO falls back to the full walk (rare: AutoCount fills FromDocNo on an SPO line)."""
    wanted = {int(ln["FromDocDtlKey"]) for ln in lines
              if isinstance(ln, dict) and ln.get("FromDocType") == "PO" and _present(ln.get("FromDocDtlKey"))}
    if not wanted:
        return {}
    numbers = {str(ln.get("FromDocNo")) for ln in lines
               if isinstance(ln, dict) and ln.get("FromDocType") == "PO" and not _blank(ln.get("FromDocNo"))}
    index: Dict[int, Tuple[Any, str]] = {}
    for staged in StagedDocRepository(db).newest_by_doc_nos(tenant_id, company.id, ENTITY_PURCHASE_ORDER, numbers):
        raw = staged.raw_json or {}
        for line in raw.get(_LINES_KEY) or []:
            if isinstance(line, dict) and line.get("DtlKey") in wanted:
                index[line["DtlKey"]] = (raw.get("DocKey"), str(raw.get("DocNo") or ""))
    if wanted - set(index) and any(isinstance(ln, dict) and ln.get("FromDocType") == "PO" and _blank(ln.get("FromDocNo"))
                                   for ln in lines):
        index = {**_dtl_index(db, tenant_id, company, ENTITY_PURCHASE_ORDER), **index}
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
    so_keys = [int(ln["FromSODtlKey"]) for ln in lines if isinstance(ln, dict) and _present(ln.get("FromSODtlKey"))]
    so_index = _so_dtl_lookup(db, tenant_id, company, so_keys) if kind != KIND_SO and so_keys else {}
    po_index = _po_dtl_lookup(db, tenant_id, company, lines) if kind == KIND_SPO else {}
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
    replaced: Optional[Dict[int, int]] = None,
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
    if replaced:
        _mark_replaced(mapped.record, company.database_name, doc.get("DocKey"), replaced)
    return entity_type, mapped.record


def _mark_replaced(record: CanonicalRecord, database: str, doc_key: Any, replaced: Dict[int, int]) -> None:
    """Plan 57 S5: a line an operation re-created carries the ref of the row it
    replaced (``{db}:{DocKey}:{old DtlKey}``); ``replaced`` maps new -> old DtlKey.
    Only the operation's own push passes it, so a later ordinary edit never repeats it."""
    for line in getattr(record, "lines", None) or []:
        try:
            dtl = int(str(line.source_ref).rsplit(":", 1)[-1])
        except (TypeError, ValueError):
            continue
        if dtl in replaced and hasattr(line, "replaces_line_ref"):
            line.replaces_line_ref = f"{database}:{doc_key}:{replaced[dtl]}"
