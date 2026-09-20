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
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db

from ..models import AcPullApiKey
from ..pull_auth import PullGatewayError, resolve_pull_key
from ..services.pull_gateway_service import (
    ENTITY_WIRE_TO_INTERNAL,
    PullGatewayService,
    gateway_snapshot_header,
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

        company, snapshot = PullGatewayService(db).build(
            key_row, company_code_raw, internal_entity
        )
        ctx.company_id = company.id
        ctx.snapshot_id = snapshot.id

        body = {
            "snapshotId": snapshot.id,
            "status": snapshot.status,
            "entity": entity_wire,
            "companyCode": company_code_raw,
        }
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

        snapshot = PullGatewayService(db).get_snapshot_for_key(key_row, snapshot_id)
        ctx.company_id = snapshot.company_id
        ctx.entity_type = snapshot.entity_type
        ctx.snapshot_id = snapshot.id
        ctx.record_count = snapshot.record_count

        body = gateway_snapshot_header(snapshot)
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
