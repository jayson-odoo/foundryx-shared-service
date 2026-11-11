"""Plan 57 S6 - the write gateway beyond the plan 55 link routes (contract
``57-autocount-write-qtso-contract.md``), mounted at ``/api/v1/autocount`` next to
``pull_v1`` (same ``X-API-Key`` auth, ``write_back`` scope, flat error envelope,
``no-store``). The router parses, maps camelCase to the AutoCount field allowlist and
shapes the answer; every decision lives in ``PrimitiveService`` / ``OperationService``.

There is deliberately no route that deletes a document: cancel is the only way one ends.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db

from ..models import AcCompany, AcPullApiKey
from ..pull_auth import PullGatewayError, resolve_pull_key
from ..services.pull_gateway_service import PullGatewayService
from ..services.pull_key_service import SCOPE_WRITE_BACK
from ..write_back import payloads
from ..write_back.call_log import REQUEST_ID_HEADER, give_request_id, request_id_of
from ..write_back.deps import get_operation_service, get_primitive_service
from ..write_back.operations import OperationResult, OperationService
from ..write_back.primitives import PrimitiveService
from .pull_v1 import (
    WriteBody,
    _CallContext,
    _finalize,
    _finalize_quietly,
    _int_field,
    _internal_error_response,
    _json_response,
    _merge_error_context,
    _optional_text,
    _parse_write_json,
    _qty_field,
    _read_request_body_bytes,
    _require_scope,
    _safe_echo,
    idempotency_key_header,
    optional_iso_date,
)

router = APIRouter()
logger = logging.getLogger(__name__)

KIND_SLUGS = {
    "quotations": "QT", "sales-orders": "SO", "purchase-orders": "PO", "shipping-purchase-orders": "SPO",
}
# wire (camelCase) -> AutoCount field names
HEADER_FIELDS = {
    name: name[0].upper() + name[1:] for name in (
        "docNo", "docDate", "debtorCode", "creditorCode", "displayTerm", "currencyCode", "currencyRate",
        "salesAgent", "purchaseAgent", "ref", "description", "remark1", "remark2", "remark3", "remark4",
        "yourPONo", "invAddr1", "invAddr2", "invAddr3", "invAddr4", "deliverAddr1", "deliverAddr2",
        "deliverAddr3", "deliverAddr4", "attention", "phone1", "fax1", "branchCode", "deliverContact",
        "deliverPhone1", "deliverFax1", "shipVia", "shipInfo", "refDocNo", "inclusiveTax",
    )
}
LINE_FIELDS = {
    "itemCode": "ItemCode", "uom": "UOM", "qty": "Qty", "unitPrice": "UnitPrice", "discount": "Discount",
    "location": "Location", "description": "Description", "deliveryDate": "DeliveryDate",
    "taxCode": "TaxCode", "desc2": "Desc2", "projNo": "ProjNo", "focQty": "FOCQty",
}
_FIELD_CODES = frozenset({
    "FIELD_REQUIRED", "FIELD_NOT_EDITABLE", "INVALID_PARAMS", "DOCNO_REQUIRED", "QTY_INVALID", "PRICE_INVALID",
    payloads.DEBTOR_TERM_MISSING,
})
_WRITE_DISABLED_CODES = ("WRITE_DISABLED", "WRITE_NOT_ALLOWED")


# ── shaping ──────────────────────────────────────────────────────────────────

def _status_of(outcome: str, code: Optional[str]) -> int:
    """done 200, pending_verification 202, field refusals 422, write refusals 403,
    other refusals 409, everything else (vendor_error, mismatch, recovered,
    needs_attention) 502."""
    if outcome == "done":
        return 200
    if outcome == "pending_verification":
        return 202
    if outcome == "refused":
        if code in _FIELD_CODES:
            return 422
        return 403 if code in _WRITE_DISABLED_CODES else 409
    return 502


_PASCAL_TO_CAMEL = {**{v: k for k, v in HEADER_FIELDS.items()}, **{v: k for k, v in LINE_FIELDS.items()}}
_PASCAL_NAMES = re.compile(
    r"\b(" + "|".join(sorted((re.escape(n) for n in _PASCAL_TO_CAMEL), key=len, reverse=True)) + r")\b"
)


def _camel_names(text: str) -> str:
    """AutoCount field names in ``text`` as the caller's camelCase names (the reverse
    of the allowlist maps): the wire never speaks AutoCount's names."""
    return _PASCAL_NAMES.sub(lambda m: _PASCAL_TO_CAMEL[m.group(1)], text)


def _camel_message(message: str) -> str:
    """``FIELD_REQUIRED: DebtorCode`` -> ``FIELD_REQUIRED: debtorCode`` (the caller
    speaks camelCase; AutoCount's names never reach the wire)."""
    head, sep, rest = message.partition(": ")
    return f"{head}{sep}{rest[:1].lower()}{rest[1:]}" if sep else message


def operation_answer(result: OperationResult, doc_key: Optional[int]) -> Dict[str, Any]:
    answer = {
        "operationId": result.operation_id, "actionId": None, "outcome": result.outcome,
        "errorCode": result.error_code, "message": _camel_names(_camel_message(result.message)),
        "warnings": [_camel_names(w) for w in result.warnings], "docKey": result.doc_key or doc_key, "docNo": result.doc_no,
        "replacedLines": [{"oldDtlKey": o, "newDtlKey": n} for o, n in result.replaced_lines],
        "document": result.document,
    }
    if result.batch is not None:  # link_batch (plan 62 D5): the new PO row per SO row + the free row
        answer.update(links=result.batch.get("links") or [], skipped=result.batch.get("skipped") or [],
                      freeLine=result.batch.get("freeLine"))
    return answer


def _respond(answer: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    if answer.get("errorCode") in _FIELD_CODES:
        answer = dict(answer, message=_camel_message(str(answer.get("message") or "")))
    answer = dict(
        answer, message=_camel_names(str(answer.get("message") or "")),
        warnings=[_camel_names(str(w)) for w in answer.get("warnings") or []],
    )
    return _status_of(str(answer.get("outcome")), answer.get("errorCode")), answer


# ── body parsing (never raises past the frame) ───────────────────────────────

def _bad(code: str, message: str) -> PullGatewayError:
    return PullGatewayError(422, code, message)


def _vendor_date(value: Any, name: str) -> str:
    """``YYYY-MM-DD`` (or a full timestamp) as AutoCount's ``YYYY-MM-DDT00:00:00``."""
    text = str(value or "")
    try:
        day = date.fromisoformat(text[:10])
    except ValueError:
        raise _bad("INVALID_REQUEST", f"{name} must be a date (YYYY-MM-DD).") from None
    return f"{day.isoformat()}T00:00:00"


_optional_date = optional_iso_date


def _object(raw: WriteBody, name: str, *, required: bool = False) -> Dict[str, Any]:
    value = raw.get(name)
    if value is None and not required:
        return {}
    if not isinstance(value, dict):
        raise _bad("INVALID_REQUEST", f"{name} must be an object.")
    return value


def _create_header(raw: WriteBody) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, value in _object(raw, "header", required=True).items():
        if name not in HEADER_FIELDS:
            raise _bad("INVALID_REQUEST", f"header.{_safe_echo(name)} is not a known field.")
        out[HEADER_FIELDS[name]] = _vendor_date(value, name) if name == "docDate" else value
    return out


def _line(raw: Any, kind: str, *, create: bool) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise _bad("INVALID_REQUEST", "each line must be an object.")
    out: Dict[str, Any] = {}
    for name, value in raw.items():
        if name == "fromQuotation":
            if kind != "SO" or not isinstance(value, dict):
                raise _bad("INVALID_REQUEST", "fromQuotation is only for sales order lines.")
            out.update(FromDocType="QT", FromDocNo=value.get("docNo"), FromDocDtlKey=value.get("dtlKey") or 0)
        elif name in LINE_FIELDS:
            out[LINE_FIELDS[name]] = _vendor_date(value, name) if name == "deliveryDate" else value
        else:
            raise _bad("INVALID_REQUEST", f"line.{_safe_echo(name)} is not a known field.")
    return out


def _lines(raw: WriteBody, kind: str) -> List[Dict[str, Any]]:
    value = raw.get("lines")
    if not isinstance(value, list):
        raise _bad("INVALID_REQUEST", "lines must be an array.")
    return [_line(item, kind, create=True) for item in value]


def _edit_changes(raw: WriteBody) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Header and line changes; any key outside the allowlist is 422
    ``FIELD_NOT_EDITABLE`` naming it (ItemCode is never editable)."""
    header: Dict[str, Any] = {}
    for name, value in _object(raw, "header").items():
        vendor = name[:1].upper() + name[1:]
        if vendor not in payloads.EDIT_HEADER_KEYS:
            raise _bad("FIELD_NOT_EDITABLE", f"FIELD_NOT_EDITABLE: {_safe_echo(name)}")
        header[vendor] = value
    lines: List[Dict[str, Any]] = []
    for item in raw.get("lines") or []:
        if not isinstance(item, dict):
            raise _bad("INVALID_REQUEST", "each line must be an object.")
        change: Dict[str, Any] = {"DtlKey": _int_field(item, "dtlKey")}
        for name, value in item.items():
            if name == "dtlKey":
                continue
            vendor = LINE_FIELDS.get(name)
            if vendor not in payloads.EDIT_LINE_KEYS:
                raise _bad("FIELD_NOT_EDITABLE", f"FIELD_NOT_EDITABLE: {_safe_echo(name)}")
            change[vendor] = _vendor_date(value, name) if name == "deliveryDate" else value
        lines.append(change)
    return header, lines


def _kind(slug: str) -> str:
    try:
        return KIND_SLUGS[slug]
    except KeyError:
        raise PullGatewayError(404, "UNKNOWN_KIND", "Unknown document kind.") from None


def _path_key(value: str, name: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise _bad("INVALID_REQUEST", f"{name} must be an integer.") from None
    if not 1 <= number <= 2**63 - 1:
        raise _bad("INVALID_REQUEST", f"{name} is out of range.")
    return number


# ── the frame ────────────────────────────────────────────────────────────────

Run = Callable[[WriteBody, AcPullApiKey, AcCompany, Optional[str]], Tuple[int, Dict[str, Any]]]


def _frame(
    request: Request, db: Session, raw_body: bytes, action: str, run: Run, *,
    key_required: bool = False, with_body: bool = True, services: Sequence[Any] = (),
) -> JSONResponse:
    """Auth, scope, idempotency header, body, company resolution (no service call
    on any failure), then ``run``; one audit row at the end. ``services`` learn the
    caller's request id for the AutoCount call log (``X-Request-ID``, else the
    ``Idempotency-Key``; plan 61 section 4.8)."""
    ctx = _CallContext()
    company_code: Optional[str] = None
    try:
        key_row = resolve_pull_key(request, db)
        ctx.key_row = key_row
        _require_scope(key_row, SCOPE_WRITE_BACK)
        idem = idempotency_key_header(request, required=key_required)
        request_id = request_id_of(request.headers.get(REQUEST_ID_HEADER), idem)
        for service in services:
            give_request_id(service, request_id)
        raw = _parse_write_json(raw_body) if with_body else {}
        hint = raw.get("companyCode") if with_body else request.query_params.get("companyCode")
        company_code = _safe_echo(hint)
        if not company_code or not company_code.strip():
            raise _bad("INVALID_REQUEST", "companyCode is required.")
        company = PullGatewayService(db).resolve_company(key_row, company_code)
        ctx.company_id = company.id
        status, answer = run(raw, key_row, company, idem)
        _finalize(db, ctx, action, status)
        return _json_response(status, answer)
    except PullGatewayError as exc:
        _merge_error_context(ctx, exc)
        exc.with_context(company_code=company_code)
        _finalize_quietly(db, ctx, action, exc.status_code)
        return exc.to_response()
    except Exception:  # noqa: BLE001 - the last-resort net, as for every gateway route
        return _internal_error_response(db, ctx, action, company_code=company_code)


# ── primitives ───────────────────────────────────────────────────────────────

@router.post("/documents/{kind}")
def create_document(
    kind: str, request: Request, db: Session = Depends(get_db),
    raw_body: bytes = Depends(_read_request_body_bytes),
    prims: PrimitiveService = Depends(get_primitive_service),
    ops: OperationService = Depends(get_operation_service),
) -> JSONResponse:
    def run(raw: WriteBody, key: AcPullApiKey, company: AcCompany, idem: Optional[str]):
        name = _kind(kind)
        header, lines = _create_header(raw), _lines(raw, name)
        answer = ops.run_primitive(
            tenant_id=key.tenant_id, company_id=company.id, key_id=key.id, idempotency_key=idem or "",
            name="create_doc", kind=name, doc_key=None, params=raw,
            call=lambda: prims.create_doc(
                tenant_id=key.tenant_id, company_id=company.id, kind=name, header=header, lines=lines,
                key_id=key.id),
        )
        return _respond(answer)

    return _frame(request, db, raw_body, "write_create_doc", run, key_required=True, services=(prims, ops))


# B6: the read also takes the short kind names (the CRM read path); writes keep the contract slugs.
_READ_KIND_SLUGS = {**KIND_SLUGS, "qt": "QT", "so": "SO", "po": "PO", "spo": "SPO"}


_YMD = re.compile(r"\d{4}-\d{2}-\d{2}")


def _query_date(request: Request, name: str) -> Optional[date]:
    text = request.query_params.get(name)
    if text is None or text == "":
        return None
    if not _YMD.fullmatch(text):  # fromisoformat also takes 20261104 and week dates
        raise _bad("INVALID_REQUEST", f"{name} must be a date (YYYY-MM-DD).")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise _bad("INVALID_REQUEST", f"{name} must be a date (YYYY-MM-DD).") from None


@router.get("/documents/{kind}/{docKey}")
def read_document(
    kind: str, docKey: str, request: Request, db: Session = Depends(get_db),
    prims: PrimitiveService = Depends(get_primitive_service),
) -> JSONResponse:
    """B6: the document as AutoCount holds it now, in the primitive answer shape
    (``document`` = AutoCount's fields). Same key, scope and db3 guard as the writes;
    it never writes. ``?companyCode=`` required, ``?docDate=YYYY-MM-DD`` optional."""

    def run(raw: WriteBody, key: AcPullApiKey, company: AcCompany, idem: Optional[str]):
        try:
            name = _READ_KIND_SLUGS[kind]
        except KeyError:
            raise PullGatewayError(404, "UNKNOWN_KIND", "Unknown document kind.") from None
        doc_key, doc_date = _path_key(docKey, "docKey"), _query_date(request, "docDate")
        res = prims.read_doc(
            tenant_id=key.tenant_id, company_id=company.id, kind=name, doc_key=doc_key, doc_date=doc_date,
        )
        return _respond({
            "operationId": None, "actionId": None, "outcome": res.outcome, "errorCode": res.error_code,
            "message": res.message, "warnings": [], "docKey": res.doc_key or doc_key, "docNo": res.doc_no,
            "document": res.document,
        })

    return _frame(request, db, b"", "write_read_doc", run, with_body=False, services=(prims,))


@router.patch("/documents/{kind}/{docKey}")
def edit_document(
    kind: str, docKey: str, request: Request, db: Session = Depends(get_db),
    raw_body: bytes = Depends(_read_request_body_bytes),
    prims: PrimitiveService = Depends(get_primitive_service),
    ops: OperationService = Depends(get_operation_service),
) -> JSONResponse:
    def run(raw: WriteBody, key: AcPullApiKey, company: AcCompany, idem: Optional[str]):
        name, doc_key = _kind(kind), _path_key(docKey, "docKey")
        header, lines = _edit_changes(raw)
        doc_date, stamp = _optional_date(raw, "docDate"), _optional_text(raw, "expectedLastModified")
        answer = ops.run_primitive(
            tenant_id=key.tenant_id, company_id=company.id, key_id=key.id, idempotency_key=idem or "",
            name="edit_doc", kind=name, doc_key=doc_key, params=raw,
            call=lambda: prims.edit_doc(
                tenant_id=key.tenant_id, company_id=company.id, kind=name, doc_key=doc_key,
                header_changes=header, line_changes=lines, doc_date=doc_date,
                expected_last_modified=stamp, key_id=key.id),
        )
        return _respond(answer)

    return _frame(request, db, raw_body, "write_edit_doc", run, key_required=True, services=(prims, ops))


@router.post("/documents/{kind}/{docKey}/lines")
def add_document_line(
    kind: str, docKey: str, request: Request, db: Session = Depends(get_db),
    raw_body: bytes = Depends(_read_request_body_bytes),
    prims: PrimitiveService = Depends(get_primitive_service),
    ops: OperationService = Depends(get_operation_service),
) -> JSONResponse:
    def run(raw: WriteBody, key: AcPullApiKey, company: AcCompany, idem: Optional[str]):
        name, doc_key = _kind(kind), _path_key(docKey, "docKey")
        line = _line(_object(raw, "line", required=True), name, create=True)
        doc_date, stamp = _optional_date(raw, "docDate"), _optional_text(raw, "expectedLastModified")
        answer = ops.run_primitive(
            tenant_id=key.tenant_id, company_id=company.id, key_id=key.id, idempotency_key=idem or "",
            name="add_line", kind=name, doc_key=doc_key, params=raw,
            call=lambda: prims.add_line(
                tenant_id=key.tenant_id, company_id=company.id, kind=name, doc_key=doc_key, line=line,
                doc_date=doc_date, expected_last_modified=stamp, key_id=key.id),
        )
        return _respond(answer)

    return _frame(request, db, raw_body, "write_add_line", run, key_required=True, services=(prims, ops))


@router.post("/documents/{kind}/{docKey}/lines/{dtlKey}/delete")
def delete_document_line(
    kind: str, docKey: str, dtlKey: str, request: Request, db: Session = Depends(get_db),
    raw_body: bytes = Depends(_read_request_body_bytes),
    prims: PrimitiveService = Depends(get_primitive_service),
    ops: OperationService = Depends(get_operation_service),
) -> JSONResponse:
    def run(raw: WriteBody, key: AcPullApiKey, company: AcCompany, idem: Optional[str]):
        name, doc_key, dtl = _kind(kind), _path_key(docKey, "docKey"), _path_key(dtlKey, "dtlKey")
        doc_date, stamp = _optional_date(raw, "docDate"), _optional_text(raw, "expectedLastModified")
        answer = ops.run_primitive(
            tenant_id=key.tenant_id, company_id=company.id, key_id=key.id, idempotency_key=idem or "",
            name=f"delete_line:{dtl}", kind=name, doc_key=doc_key, params=raw,
            call=lambda: prims.delete_line(
                tenant_id=key.tenant_id, company_id=company.id, kind=name, doc_key=doc_key, dtl_key=dtl,
                doc_date=doc_date, expected_last_modified=stamp, key_id=key.id),
        )
        return _respond(answer)

    return _frame(request, db, raw_body, "write_delete_line", run, key_required=True, services=(prims, ops))


@router.post("/documents/{kind}/{docKey}/cancel")
def cancel_document(
    kind: str, docKey: str, request: Request, db: Session = Depends(get_db),
    raw_body: bytes = Depends(_read_request_body_bytes),
    prims: PrimitiveService = Depends(get_primitive_service),
    ops: OperationService = Depends(get_operation_service),
) -> JSONResponse:
    def run(raw: WriteBody, key: AcPullApiKey, company: AcCompany, idem: Optional[str]):
        name, doc_key = _kind(kind), _path_key(docKey, "docKey")
        doc_date, stamp = _optional_date(raw, "docDate"), _optional_text(raw, "expectedLastModified")
        answer = ops.run_primitive(
            tenant_id=key.tenant_id, company_id=company.id, key_id=key.id, idempotency_key=idem or "",
            name="cancel_doc", kind=name, doc_key=doc_key, params=raw,
            call=lambda: prims.cancel_doc(
                tenant_id=key.tenant_id, company_id=company.id, kind=name, doc_key=doc_key,
                doc_date=doc_date, expected_last_modified=stamp, key_id=key.id),
        )
        return _respond(answer)

    return _frame(request, db, raw_body, "write_cancel_doc", run, key_required=True, services=(prims, ops))


# ── operations ───────────────────────────────────────────────────────────────

def _operation_route(
    path: str, op: str, fields: Tuple[Tuple[str, str], ...], action: str, target_date: str
) -> None:
    """Register ``POST path`` running operation ``op``; ``fields`` = (wire name,
    operation param) pairs, all integer keys."""

    def endpoint(
        request: Request, db: Session = Depends(get_db),
        raw_body: bytes = Depends(_read_request_body_bytes),
        ops: OperationService = Depends(get_operation_service),
    ) -> JSONResponse:
        def run(raw: WriteBody, key: AcPullApiKey, company: AcCompany, idem: Optional[str]):
            params: Dict[str, Any] = {param: _int_field(raw, wire) for wire, param in fields}
            params["doc_date"] = _optional_date(raw, "docDate")
            params["target_doc_date"] = _optional_date(raw, target_date)  # soDocDate / poDocDate
            params["expected_last_modified"] = _optional_text(raw, "expectedLastModified")
            result = ops.run(
                tenant_id=key.tenant_id, company_id=company.id, key_id=key.id,
                idempotency_key=idem or "", op=op, params=params,
            )
            return _respond(operation_answer(result, params[fields[0][1]]))

        return _frame(request, db, raw_body, action, run, key_required=True, services=(ops,))

    endpoint.__name__ = f"op_{op}"
    router.add_api_route(path, endpoint, methods=["POST"])


@router.post("/po-links/batch")
def link_po_row_batch(
    request: Request, db: Session = Depends(get_db),
    raw_body: bytes = Depends(_read_request_body_bytes),
    ops: OperationService = Depends(get_operation_service),
) -> JSONResponse:
    """Plan 62 D1: link one PO row to 1..20 SO rows in one operation (one idempotency key)."""

    def run(raw: WriteBody, key: AcPullApiKey, company: AcCompany, idem: Optional[str]):
        try:
            entries = raw.get("links")
            if not isinstance(entries, list) or not entries:
                raise _bad("INVALID_REQUEST", "links must be a non-empty array.")
            if len(entries) > 20:
                raise _bad("INVALID_REQUEST", "links must hold at most 20 entries.")
            links = []
            seen: set = set()
            for entry in entries:
                if not isinstance(entry, dict):
                    raise _bad("INVALID_REQUEST", "each link must be an object.")
                so_dtl = _int_field(entry, "soDtlKey")
                if so_dtl in seen:
                    raise _bad("INVALID_REQUEST", "a soDtlKey is listed twice.")
                seen.add(so_dtl)
                links.append({
                    "so_doc_key": _int_field(entry, "soDocKey"), "so_dtl_key": so_dtl,
                    "qty": _qty_field(entry), "so_doc_date": _optional_date(entry, "soDocDate"),
                })
            params: Dict[str, Any] = {
                "doc_key": _int_field(raw, "poDocKey"), "dtl_key": _int_field(raw, "poDtlKey"), "links": links,
                "doc_date": _optional_date(raw, "docDate"),
                "expected_last_modified": _optional_text(raw, "expectedLastModified"),
            }
        except PullGatewayError as exc:  # a request-shape error still carries the batch fields
            exc.extra = {"links": [], "skipped": [], "freeLine": None}
            raise
        result = ops.run(
            tenant_id=key.tenant_id, company_id=company.id, key_id=key.id,
            idempotency_key=idem or "", op="link_batch", params=params,
        )
        answer = operation_answer(result, params["doc_key"])
        answer.setdefault("links", [])  # every outcome of this route carries these fields (contract section 4.1a)
        answer.setdefault("skipped", [])
        answer.setdefault("freeLine", None)
        return _respond(answer)

    return _frame(request, db, raw_body, "write_link_batch", run, key_required=True, services=(ops,))


_PO_KEYS = (("poDocKey", "doc_key"), ("poDtlKey", "dtl_key"), ("soDocKey", "so_doc_key"), ("soDtlKey", "so_dtl_key"))
_SPO_KEYS = (("spoDocKey", "spo_doc_key"), ("spoDtlKey", "spo_dtl_key"),
             ("poDocKey", "po_doc_key"), ("poDtlKey", "po_dtl_key"))
_operation_route("/po-links/relink", "relink_row", _PO_KEYS, "write_relink", "soDocDate")
_operation_route("/spo-links", "spo_link_row", _SPO_KEYS, "write_spo_link", "poDocDate")
_operation_route("/spo-links/relink", "spo_relink_row", _SPO_KEYS, "write_spo_relink", "poDocDate")


@router.get("/write-operations/{operationId}")
def get_write_operation(
    operationId: str, request: Request, db: Session = Depends(get_db),
    ops: OperationService = Depends(get_operation_service),
) -> JSONResponse:
    def run(raw: WriteBody, key: AcPullApiKey, company: AcCompany, idem: Optional[str]):
        try:
            result = ops.get(tenant_id=key.tenant_id, company_id=company.id, operation_id=operationId)
        except LookupError:
            raise PullGatewayError(404, "UNKNOWN_OPERATION", "No such operation.") from None
        return 200, operation_answer(result, None)  # a read: the state is the answer, whatever it is

    return _frame(request, db, b"", "write_operation_get", run, with_body=False)


@router.post("/write-operations/{operationId}/resume")
def resume_write_operation(
    operationId: str, request: Request, db: Session = Depends(get_db),
    raw_body: bytes = Depends(_read_request_body_bytes),
    ops: OperationService = Depends(get_operation_service),
) -> JSONResponse:
    def run(raw: WriteBody, key: AcPullApiKey, company: AcCompany, idem: Optional[str]):
        try:
            result = ops.resume(tenant_id=key.tenant_id, company_id=company.id, operation_id=operationId)
        except LookupError:
            raise PullGatewayError(404, "UNKNOWN_OPERATION", "No such operation.") from None
        status, answer = _respond(operation_answer(result, None))
        # a resume that put the line back (done or recovered) succeeded as a resume
        return (200 if result.outcome in ("done", "recovered") else status), answer

    return _frame(request, db, raw_body, "write_operation_resume", run, services=(ops,))


@router.get("/write-capabilities")
def get_write_capabilities(
    request: Request, db: Session = Depends(get_db),
    ops: OperationService = Depends(get_operation_service),
) -> JSONResponse:
    def run(raw: WriteBody, key: AcPullApiKey, company: AcCompany, idem: Optional[str]):
        return 200, {"book": ops.write_book(company), "capabilities": ops.capabilities(company)}

    return _frame(request, db, b"", "write_capabilities", run, with_body=False)
