"""Sprint-5/10 S4 - the PUBLIC pull gateway (Appendix A), mounted at
``/api/v1/autocount`` via the manifest's ``"public": true`` router entry
(mirrors omnichannel's own ``api_v1`` entry - ``app/module_loader.py``
skips the session/module gate for it). ``X-API-Key`` authed, NO JWT
dependency anywhere on this router - see ``pull_auth.resolve_pull_key``.

Every response here is the FLAT Appendix A6 envelope
``{code,message,companyCode,entity}`` on failure - NEVER core's
``{"error": {...}}`` ``/api/v1/*`` wrapper (``app/api_errors.py``'s global
``RequestValidationError`` handler). Request bodies and query params are
therefore parsed MANUALLY: this router never lets FastAPI's automatic
Pydantic body/query binding raise, since that raises straight past this
file's own error handling and into core's global handler.

Security round 1 (independent Opus review, HIGH 1) - EVERY route also
catches a bare ``Exception``, never only ``PullGatewayError``: an unexpected
failure anywhere downstream (a driver-level ``OverflowError``, a race, a
future bug) must still render the flat envelope, still write one audit row,
and must NEVER leak a traceback/exception text into the body - it is logged
server-side instead.

Router stays thin: every DB touch and business decision lives in
``PullAuthentication``/``PullGatewayService``/``PullService``/
``SnapshotService`` (already built by S3) - this file only parses, calls,
audits and shapes the HTTP response.
"""
from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db

from ..doc_feed.clock import myt_date
from ..models import AcPullApiKey
from ..pull_auth import PullGatewayError, resolve_pull_key
from ..services.pull_key_service import SCOPE_PULL, SCOPE_WRITE_BACK
from ..write_back.deps import get_operation_service, get_write_back_service
from ..write_back.operations import OperationService
from ..write_back.service import WriteActionResult, WriteBackService
from ..services.pull_gateway_service import (
    ENTITY_WIRE_TO_INTERNAL,
    PullGatewayService,
    DOC_SCOPE_KEYS,
    gateway_snapshot_header,
    is_doc_feed_entity,
    parse_doc_scope,
    translate_entity_wire,
    write_pull_audit,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Security round 1 MEDIUM 3 - an unauthenticated caller must never make this
# gateway read/echo an unbounded body. Appendix A does not name a limit, so
# a generous-for-a-two-field-JSON-body 16 KB is the cap; over it is a flat
# 413, never a native starlette/FastAPI body-size error.
MAX_BODY_BYTES = 16 * 1024
# Security round 1 HIGH 1 - `page` must never reach the repository layer
# unbounded (the PROVEN `OverflowError`/"OFFSET must be bigint" path).
# `pageSize` already clamps (AC-10-33); `page` is REJECTED instead, since a
# consumer paging past a legitimate `totalPages` is already served an empty
# `rows` array (AC-10-33) - a page this large is never a legitimate request.
MAX_PAGE = 10**6
# Security round 1 MEDIUM 3 - a value echoed into an error body (from a
# request that may not even be authenticated yet) is capped and sanitised
# regardless of size/type.
MAX_ECHO_LEN = 64
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")

NO_STORE_HEADERS = {"Cache-Control": "no-store"}


def _json_response(status_code: int, content: Any, headers: Optional[dict] = None) -> JSONResponse:
    """Every gateway response - success or error - carries `Cache-Control:
    no-store` (security round 1 MEDIUM 6): this surface serves a customer's
    ERP master data behind a bearer-style key, never cacheable by an
    intermediary."""
    merged = dict(NO_STORE_HEADERS)
    if headers:
        merged.update(headers)
    return JSONResponse(status_code=status_code, content=content, headers=merged)


def _safe_echo(value: Any) -> Optional[str]:
    """Security round 1 MEDIUM 3 - never reflect an unbounded/non-string/
    control-character value into a response body, authenticated or not. A
    non-string value (e.g. a JSON object where Appendix A6 expects a
    string) echoes as ``None`` rather than leaking its raw shape."""
    if not isinstance(value, str):
        return None
    return _CONTROL_CHARS_RE.sub("", value)[:MAX_ECHO_LEN]


async def _read_request_body_bytes(request: Request) -> bytes:
    """Sprint-5/10 S6 (live-replay Finding 2) - a FastAPI dependency, so it
    runs on the event loop BEFORE the (now plain-``def``, threadpooled)
    route body starts, while remaining the only ``await`` this router
    performs to read a request. Never raises - a read failure reads as
    ``b""``, which ``_parse_json_body`` (called INSIDE the route's own
    try/except, so it can render the flat Appendix A6 envelope) turns into
    ``{}`` the same way the old combined function did."""
    try:
        return await request.body()
    except Exception:  # noqa: BLE001 - defensive; a body read genuinely never fails here
        return b""


def _parse_json_body(raw_bytes: bytes) -> Any:
    """Never raises `RequestValidationError` - a missing/empty/malformed
    body reads as ``{}``, which the caller's OWN validation turns into the
    flat 422 (Appendix A6). An OVERSIZED body raises `PullGatewayError`
    (413) directly - checked on the RAW bytes, before `json.loads` is even
    attempted (security round 1 MEDIUM 3). Synchronous on purpose: the
    route that calls this is a plain ``def`` (Starlette threadpools it), so
    parsing a bounded, already-read byte string here does no blocking I/O."""
    if not raw_bytes:
        return {}
    if len(raw_bytes) > MAX_BODY_BYTES:
        raise PullGatewayError(413, "PAYLOAD_TOO_LARGE", "Request body is too large.")
    try:
        return json.loads(raw_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _parse_int_query(request: Request, name: str, default: int) -> int:
    """Never raises - an invalid/missing value silently falls back to
    ``default`` (the same "clamp, never error" ethos AC-10-33 states for
    ``pageSize``), so a native query-validation failure can never leak
    core's wrapper on this gateway either."""
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _parse_bounded_page(request: Request, *, minimum: int, maximum: int) -> Tuple[Optional[int], bool]:
    """Security round 1 HIGH 1 - unlike ``pageSize`` (silently clamped),
    ``page`` is REJECTED outright when out of range: ``(value, True)`` on
    success, ``(None, False)`` when missing bounds validation should 422.
    Handles an arbitrarily large digit string with no `OverflowError` (a
    Python `int()` never overflows; the danger was always downstream, at
    the point a huge value gets bound as a SQL parameter)."""
    raw = request.query_params.get("page")
    if raw is None:
        return minimum, True
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, False
    if value < minimum or value > maximum:
        return None, False
    return value, True


@dataclass
class _CallContext:
    """Everything the ONE audit write (AC-10-34) at the end of a call needs -
    filled in as each step learns more, backfilled from a raised
    ``PullGatewayError``'s own context when a failure short-circuits before
    the router itself would otherwise have learned it (e.g. an expired
    snapshot's company/entity, known only inside the service call that
    raised)."""

    key_row: Optional[AcPullApiKey] = None
    company_id: Optional[str] = None
    entity_type: Optional[str] = None
    snapshot_id: Optional[str] = None
    page: Optional[int] = None
    record_count: Optional[int] = None


def _merge_error_context(ctx: _CallContext, exc: PullGatewayError) -> None:
    if exc.snapshot_id is not None:
        ctx.snapshot_id = exc.snapshot_id
    if exc.company_id is not None:
        ctx.company_id = exc.company_id
    if exc.entity_type is not None:
        ctx.entity_type = exc.entity_type


def _finalize(db: Session, ctx: _CallContext, action: str, status_code: int) -> None:
    if ctx.key_row is None:
        # AC-10-34's own choice, stated once: a request whose key never
        # resolved has no tenant to attribute the row to - write NOTHING.
        return
    write_pull_audit(
        db,
        tenant_id=ctx.key_row.tenant_id,
        key_id=ctx.key_row.id,
        company_id=ctx.company_id,
        entity_type=ctx.entity_type,
        snapshot_id=ctx.snapshot_id,
        action=action,
        page=ctx.page,
        record_count=ctx.record_count,
        status_code=status_code,
    )


def _finalize_quietly(db: Session, ctx: _CallContext, action: str, status_code: int) -> None:
    """AC-10-58 L4 - the audit write on an ERROR path, which runs INSIDE an
    ``except`` block: an exception raised there escapes the whole ``try``
    statement (a later ``except Exception`` of the same ``try`` never sees
    it), so an audit-table hiccup would turn a clean flat 403/404/429 into an
    unhandled error for the consumer. The audit row is best-effort HERE and
    only here - the success path keeps calling ``_finalize`` directly, so a
    failure there is still caught by the route's own last-resort net and
    answered as a flat 500 (a 2xx must never be reported for a call that was
    not audited)."""
    try:
        _finalize(db, ctx, action, status_code)
    except Exception:  # noqa: BLE001 - observability NEVER breaks a response
        logger.exception(
            "autocount pull gateway failed to write an audit row (action=%s, status=%s)",
            action,
            status_code,
        )


def _require_scope(key_row: AcPullApiKey, scope: str) -> None:
    """403 ``SCOPE_REQUIRED`` unless the key carries ``scope``. Checked right
    after the key resolves, before any body, company or snapshot answer."""
    if scope not in (key_row.scopes or []):
        raise PullGatewayError(403, "SCOPE_REQUIRED", "This key does not carry the required scope.")


def _internal_error_response(
    db: Session,
    ctx: _CallContext,
    action: str,
    *,
    company_code: Optional[str] = None,
    entity: Optional[str] = None,
) -> JSONResponse:
    """Security round 1 HIGH 1 - the LAST-RESORT net: any exception this
    router's own `except PullGatewayError` did not anticipate. Logged
    server-side WITH the traceback (`logger.exception`, called from inside
    the `except` block so `sys.exc_info()` is still live); the response body
    carries only a stable, generic code/message - never the exception's own
    text, class name, or a stack frame."""
    logger.exception("autocount pull gateway internal error (action=%s)", action)
    _finalize_quietly(db, ctx, action, 500)
    body = {
        "code": "INTERNAL",
        "message": "An internal error occurred.",
        "companyCode": company_code,
        "entity": entity,
    }
    return _json_response(500, body)


# ── POST /snapshots (AC-10-29/30/31) ─────────────────────────────────────


@router.post("/snapshots")
def build_snapshot(
    request: Request,
    db: Session = Depends(get_db),
    raw_body: bytes = Depends(_read_request_body_bytes),
) -> JSONResponse:
    """Sprint-5/10 S6 (live-replay Finding 2) - a PLAIN ``def``, not
    ``async def``. This route's own downstream call
    (``PullGatewayService(db).build`` -> ... -> the eager job handler ->
    the fully-synchronous paged extraction) can genuinely run for minutes
    with NO ``await`` point of its own; declaring the route ``async def``
    made FastAPI run all of that directly on the ASGI event loop (never
    Starlette's automatic threadpool, which only plain ``def`` routes get),
    freezing every OTHER request on the same worker - every tenant, every
    route, including an unauthenticated ``/openapi.json`` - for the whole
    build duration (reproduced and timed 3 times in the replay). Mirrors
    ``routers/pull.py``'s own operator build route, which never exhibited
    the freeze for exactly this reason. The one genuinely async step (the
    body read) already happened on the event loop via the
    ``_read_request_body_bytes`` dependency above, before this function's
    body ever starts running in the threadpool."""
    ctx = _CallContext()
    company_code_hint: Optional[str] = None
    entity_hint: Optional[str] = None
    try:
        raw = _parse_json_body(raw_body)
        company_code_hint = _safe_echo(raw.get("companyCode")) if isinstance(raw, dict) else None
        entity_hint = _safe_echo(raw.get("entity")) if isinstance(raw, dict) else None

        key_row = resolve_pull_key(request, db)
        ctx.key_row = key_row
        _require_scope(key_row, SCOPE_PULL)

        company_code_raw = company_code_hint
        entity_wire = entity_hint
        if (
            not company_code_raw
            or not company_code_raw.strip()
            or not entity_wire
            or not entity_wire.strip()
        ):
            raise PullGatewayError(
                422, "INVALID_REQUEST", "companyCode and entity are both required."
            )
        internal_entity = translate_entity_wire(entity_wire)
        if internal_entity is None:
            raise PullGatewayError(
                422, "UNKNOWN_ENTITY",
                "entity must be one of: " + ", ".join(sorted(ENTITY_WIRE_TO_INTERNAL)) + ".",
            )
        ctx.entity_type = internal_entity

        scope = None
        if is_doc_feed_entity(internal_entity):
            scope = parse_doc_scope(
                raw if isinstance(raw, dict) else {},
                today_myt=myt_date(datetime.now(timezone.utc)),
            )
        elif isinstance(raw, dict):
            for scope_key in DOC_SCOPE_KEYS:
                if scope_key in raw:
                    raise PullGatewayError(
                        422, "INVALID_REQUEST",
                        f"{scope_key} is only accepted for the delivery_orders and "
                        "goods_receive_notes entities.",
                    )

        company, snapshot = PullGatewayService(db).build(
            key_row, company_code_raw, internal_entity, scope=scope
        )
        ctx.company_id = company.id
        ctx.snapshot_id = snapshot.id

        body = {
            "snapshotId": snapshot.id,
            "status": snapshot.status,
            "entity": entity_wire,
            "companyCode": company_code_raw,
        }
        if scope is not None:
            body.update({key: scope.get(key) for key in DOC_SCOPE_KEYS})
        _finalize(db, ctx, "build", 202)
        return _json_response(202, body)
    except PullGatewayError as exc:
        _merge_error_context(ctx, exc)
        exc.with_context(company_code=company_code_hint, entity=entity_hint)
        _finalize_quietly(db, ctx, "build", exc.status_code)
        return exc.to_response()
    except Exception:  # noqa: BLE001 - security round 1 HIGH 1, the last-resort net
        return _internal_error_response(
            db, ctx, "build", company_code=company_code_hint, entity=entity_hint
        )


# ── GET /snapshots/{id} (AC-10-30/31/32) ─────────────────────────────────


@router.get("/snapshots/{snapshot_id}")
def get_snapshot_header_route(
    snapshot_id: str, request: Request, db: Session = Depends(get_db)
) -> JSONResponse:
    ctx = _CallContext()
    try:
        key_row = resolve_pull_key(request, db)
        ctx.key_row = key_row
        _require_scope(key_row, SCOPE_PULL)

        service = PullGatewayService(db)
        snapshot = service.get_snapshot_for_key(key_row, snapshot_id)
        ctx.company_id = snapshot.company_id
        ctx.entity_type = snapshot.entity_type
        ctx.snapshot_id = snapshot.id
        ctx.record_count = snapshot.record_count

        body = gateway_snapshot_header(snapshot)
        # sprint-5/11 S5 (AC-11-41) - merged in AFTER the header (never a
        # key of its own inside `gateway_snapshot_header`, which stays a
        # pure projection of the snapshot's own columns) and OMITTED
        # entirely (never a bare `null`) when nothing useful is known.
        progress = service.snapshot_progress(key_row, snapshot)
        if progress is not None:
            body["progress"] = progress
        _finalize(db, ctx, "get_header", 200)
        return _json_response(200, body)
    except PullGatewayError as exc:
        _merge_error_context(ctx, exc)
        _finalize_quietly(db, ctx, "get_header", exc.status_code)
        return exc.to_response()
    except Exception:  # noqa: BLE001 - security round 1 HIGH 1, the last-resort net
        return _internal_error_response(db, ctx, "get_header")


# ── GET /snapshots/{id}/rows (AC-10-30/31/33) ────────────────────────────


@router.get("/snapshots/{snapshot_id}/rows")
def get_snapshot_rows_route(
    snapshot_id: str, request: Request, db: Session = Depends(get_db)
) -> JSONResponse:
    ctx = _CallContext()
    try:
        key_row = resolve_pull_key(request, db)
        ctx.key_row = key_row
        _require_scope(key_row, SCOPE_PULL)

        page, page_ok = _parse_bounded_page(request, minimum=1, maximum=MAX_PAGE)
        if not page_ok:
            raise PullGatewayError(
                422, "INVALID_REQUEST",
                f"page must be an integer between 1 and {MAX_PAGE}.",
            )
        ctx.page = page
        page_size = max(_parse_int_query(request, "pageSize", 1000), 1)

        snapshot = PullGatewayService(db).get_snapshot_for_key(key_row, snapshot_id)
        ctx.company_id = snapshot.company_id
        ctx.entity_type = snapshot.entity_type
        ctx.snapshot_id = snapshot.id

        rows, total, clamped_size = PullGatewayService(db).rows_page(
            snapshot, page=page, page_size=page_size
        )
        ctx.record_count = total
        total_pages = (total + clamped_size - 1) // clamped_size if clamped_size else 0
        body = {
            "snapshotId": snapshot.id,
            "page": page,
            "pageSize": clamped_size,
            "totalPages": total_pages,
            "recordCount": total,
            "rows": [row.payload_json for row in rows],
        }
        _finalize(db, ctx, "get_rows", 200)
        return _json_response(200, body)
    except PullGatewayError as exc:
        _merge_error_context(ctx, exc)
        _finalize_quietly(db, ctx, "get_rows", exc.status_code)
        return exc.to_response()
    except Exception:  # noqa: BLE001 - security round 1 HIGH 1, the last-resort net
        return _internal_error_response(db, ctx, "get_rows")


# ── plan 55: write-back routes (AC-55-40..45) ─────────────────────────────
# Same envelope rules as above (flat errors, no-store, manual body parsing).
# The key must carry the ``write_back`` scope; the company resolves exactly
# like ``/snapshots``; the service does every DB / AutoCount step.

_WRITE_DISABLED_CODES = ("WRITE_DISABLED", "WRITE_NOT_ALLOWED")


def _write_status(result: WriteActionResult) -> int:
    """done 200, pending_verification 202, write refusals 403, other refusals
    409, vendor_error / mismatch 502."""
    if result.outcome == "done":
        return 200
    if result.outcome == "pending_verification":
        return 202
    if result.outcome == "refused":
        return 403 if result.error_code in _WRITE_DISABLED_CODES else 409
    return 502


def _write_body(result: WriteActionResult) -> Dict[str, object]:
    body: Dict[str, object] = {
        "actionId": result.action_id,
        "outcome": result.outcome,
        "errorCode": result.error_code,
        "document": result.document,
    }
    if result.operation_id is not None:  # plan 57: an operation answered
        body.update(
            operationId=result.operation_id, message=result.message, warnings=list(result.warnings),
            docKey=result.doc_key, docNo=result.doc_no,
            replacedLines=[{"oldDtlKey": o, "newDtlKey": n} for o, n in result.replaced_lines],
        )
    return body


def optional_iso_date(raw: WriteBody, name: str) -> Optional["date"]:
    """An optional ``YYYY-MM-DD`` field; anything else is 422 ``INVALID_REQUEST``."""
    value = raw.get(name)
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise PullGatewayError(422, "INVALID_REQUEST", f"{name} must be a date (YYYY-MM-DD).") from None


_IDEMPOTENCY_KEY_RE = re.compile(r"^[\x20-\x7e]{1,128}$")


def idempotency_key_header(request: Request, *, required: bool) -> Optional[str]:
    """The ``Idempotency-Key`` header (contract section 2): 1..128 printable
    characters. Absent = ``None`` (or 422 ``IDEMPOTENCY_KEY_REQUIRED`` when required);
    blank, over-long or control characters = 422 ``IDEMPOTENCY_KEY_INVALID``."""
    raw = request.headers.get("Idempotency-Key")
    if raw is None:
        if required:
            raise PullGatewayError(422, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required.")
        return None
    if not _IDEMPOTENCY_KEY_RE.match(raw) or not raw.strip():
        raise PullGatewayError(422, "IDEMPOTENCY_KEY_INVALID", "Idempotency-Key must be 1 to 128 printable characters.")
    return raw


WriteBody = Dict[str, object]
MAX_KEY = 2**63 - 1
WriteCall = Callable[[WriteBackService, WriteBody, str, str, str], WriteActionResult]


def _parse_write_json(raw_bytes: bytes) -> WriteBody:
    """Body as a dict with JSON floats kept as ``Decimal`` (a quantity is never
    a binary float). Anything that is not a JSON object is a 422."""
    if len(raw_bytes) > MAX_BODY_BYTES:
        raise PullGatewayError(413, "PAYLOAD_TOO_LARGE", "Request body is too large.")
    try:
        raw = json.loads(raw_bytes or b"{}", parse_float=Decimal)
    except (ValueError, UnicodeDecodeError):  # incl. JSON errors and absurdly long integers
        raw = None
    if not isinstance(raw, dict):
        raise PullGatewayError(422, "INVALID_REQUEST", "A JSON object body is required.")
    return raw


def _int_field(raw: WriteBody, name: str) -> int:
    """A DocKey / DtlKey: an integer in 1..2**63-1 (the database's bigint range)."""
    value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_KEY:
        raise PullGatewayError(
            422, "INVALID_REQUEST", f"{name} must be an integer between 1 and {MAX_KEY}."
        )
    return value


def _qty_field(raw: WriteBody) -> Decimal:
    value = raw.get("qty")
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise PullGatewayError(422, "INVALID_REQUEST", "qty must be a number.")
    return Decimal(value)


def _optional_text(raw: WriteBody, name: str) -> Optional[str]:
    value = raw.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise PullGatewayError(422, "INVALID_REQUEST", f"{name} must be a string.")
    return value[:MAX_ECHO_LEN]


def _write_route(
    request: Request,
    db: Session,
    raw_body: bytes,
    service: WriteBackService,
    action: str,
    call: WriteCall,
) -> JSONResponse:
    """The shared write-route frame. ``call(service, raw, tenant_id, company_id,
    key_id)`` invokes the service method; everything before it is auth, scope,
    parse and company resolution (no service call on any failure)."""
    ctx = _CallContext()
    company_code_hint: Optional[str] = None
    try:
        key_row = resolve_pull_key(request, db)
        ctx.key_row = key_row
        if SCOPE_WRITE_BACK not in (key_row.scopes or []):
            raise PullGatewayError(
                403, "SCOPE_REQUIRED", "This key is not allowed to write."
            )
        raw = _parse_write_json(raw_body)
        company_code_hint = _safe_echo(raw.get("companyCode"))
        if not company_code_hint or not company_code_hint.strip():
            raise PullGatewayError(422, "INVALID_REQUEST", "companyCode is required.")
        company = PullGatewayService(db).resolve_company(key_row, company_code_hint)
        ctx.company_id = company.id
        result = call(service, raw, key_row.tenant_id, company.id, key_row.id)
        status_code = _write_status(result)
        _finalize(db, ctx, action, status_code)
        return _json_response(status_code, _write_body(result))
    except PullGatewayError as exc:
        _merge_error_context(ctx, exc)
        exc.with_context(company_code=company_code_hint)
        _finalize_quietly(db, ctx, action, exc.status_code)
        return exc.to_response()
    except Exception:  # noqa: BLE001 - the last-resort net, as for every route
        return _internal_error_response(db, ctx, action, company_code=company_code_hint)


@router.post("/po-links")
def link_po_row(
    request: Request,
    db: Session = Depends(get_db),
    raw_body: bytes = Depends(_read_request_body_bytes),
    service: WriteBackService = Depends(get_write_back_service),
    operations: OperationService = Depends(get_operation_service),
) -> JSONResponse:
    def call(
        svc: WriteBackService, raw: WriteBody, tenant_id: str, company_id: str, key_id: str
    ) -> WriteActionResult:
        return svc.link(
            operations=operations, idempotency_key=idempotency_key_header(request, required=False),
            tenant_id=tenant_id, company_id=company_id, key_id=key_id,
            po_doc_key=_int_field(raw, "poDocKey"), po_dtl_key=_int_field(raw, "poDtlKey"),
            so_doc_key=_int_field(raw, "soDocKey"), so_dtl_key=_int_field(raw, "soDtlKey"),
            qty=_qty_field(raw), so_doc_date=optional_iso_date(raw, "soDocDate"),
            expected_last_modified=_optional_text(raw, "expectedLastModified"),
        )

    return _write_route(request, db, raw_body, service, "write_link", call)


@router.post("/po-links/unlink")
def unlink_po_row(
    request: Request,
    db: Session = Depends(get_db),
    raw_body: bytes = Depends(_read_request_body_bytes),
    service: WriteBackService = Depends(get_write_back_service),
    operations: OperationService = Depends(get_operation_service),
) -> JSONResponse:
    def call(
        svc: WriteBackService, raw: WriteBody, tenant_id: str, company_id: str, key_id: str
    ) -> WriteActionResult:
        return svc.unlink(
            operations=operations, idempotency_key=idempotency_key_header(request, required=False),
            tenant_id=tenant_id, company_id=company_id, key_id=key_id,
            po_doc_key=_int_field(raw, "poDocKey"), po_dtl_key=_int_field(raw, "poDtlKey"),
            expected_last_modified=_optional_text(raw, "expectedLastModified"),
        )

    return _write_route(request, db, raw_body, service, "write_unlink", call)


@router.post("/spo-links/unlink")
def unlink_spo_row(
    request: Request,
    db: Session = Depends(get_db),
    raw_body: bytes = Depends(_read_request_body_bytes),
    service: WriteBackService = Depends(get_write_back_service),
    operations: OperationService = Depends(get_operation_service),
) -> JSONResponse:
    def call(
        svc: WriteBackService, raw: WriteBody, tenant_id: str, company_id: str, key_id: str
    ) -> WriteActionResult:
        return svc.spo_unlink(
            operations=operations, idempotency_key=idempotency_key_header(request, required=False),
            tenant_id=tenant_id, company_id=company_id, key_id=key_id,
            spo_doc_key=_int_field(raw, "spoDocKey"), spo_dtl_key=_int_field(raw, "spoDtlKey"),
            expected_last_modified=_optional_text(raw, "expectedLastModified"),
        )

    return _write_route(request, db, raw_body, service, "write_spo_unlink", call)


@router.post("/po-links/relocate")
def relocate_po_row(
    request: Request,
    db: Session = Depends(get_db),
    raw_body: bytes = Depends(_read_request_body_bytes),
    service: WriteBackService = Depends(get_write_back_service),
) -> JSONResponse:
    def call(
        svc: WriteBackService, raw: WriteBody, tenant_id: str, company_id: str, key_id: str
    ) -> WriteActionResult:
        return svc.relocate(
            tenant_id=tenant_id, company_id=company_id, key_id=key_id,
            po_doc_key=_int_field(raw, "poDocKey"), po_dtl_key=_int_field(raw, "poDtlKey"),
            expected_last_modified=_optional_text(raw, "expectedLastModified"),
        )

    return _write_route(request, db, raw_body, service, "write_relocate", call)
