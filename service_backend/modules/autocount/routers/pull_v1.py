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

Router stays thin: every DB touch and business decision lives in
``PullAuthentication``/``PullGatewayService``/``PullService``/
``SnapshotService`` (already built by S3) - this file only parses, calls,
audits and shapes the HTTP response.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

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


async def _read_json_body(request: Request) -> Any:
    """Never raises - a missing/empty/malformed body reads as ``{}``, which
    the caller's OWN validation turns into the flat 422 (Appendix A6), never
    a native ``RequestValidationError``."""
    try:
        raw_bytes = await request.body()
    except Exception:  # noqa: BLE001 - defensive; a body read genuinely never fails here
        return {}
    if not raw_bytes:
        return {}
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


# ── POST /snapshots (AC-10-29/30/31) ─────────────────────────────────────


@router.post("/snapshots")
async def build_snapshot(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    raw = await _read_json_body(request)
    company_code_hint = raw.get("companyCode") if isinstance(raw, dict) else None
    entity_hint = raw.get("entity") if isinstance(raw, dict) else None
    ctx = _CallContext()
    try:
        key_row = resolve_pull_key(request, db)
        ctx.key_row = key_row

        company_code_raw = raw.get("companyCode") if isinstance(raw, dict) else None
        entity_wire = raw.get("entity") if isinstance(raw, dict) else None
        if (
            not isinstance(company_code_raw, str)
            or not company_code_raw.strip()
            or not isinstance(entity_wire, str)
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
        return JSONResponse(status_code=202, content=body)
    except PullGatewayError as exc:
        _merge_error_context(ctx, exc)
        exc.with_context(company_code=company_code_hint, entity=entity_hint)
        _finalize(db, ctx, "build", exc.status_code)
        return exc.to_response()


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
        return JSONResponse(status_code=200, content=body)
    except PullGatewayError as exc:
        _merge_error_context(ctx, exc)
        _finalize(db, ctx, "get_header", exc.status_code)
        return exc.to_response()


# ── GET /snapshots/{id}/rows (AC-10-30/31/33) ────────────────────────────


@router.get("/snapshots/{snapshot_id}/rows")
def get_snapshot_rows_route(
    snapshot_id: str, request: Request, db: Session = Depends(get_db)
) -> JSONResponse:
    ctx = _CallContext()
    page = max(_parse_int_query(request, "page", 1), 1)
    page_size = max(_parse_int_query(request, "pageSize", 1000), 1)
    ctx.page = page
    try:
        key_row = resolve_pull_key(request, db)
        ctx.key_row = key_row

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
        return JSONResponse(status_code=200, content=body)
    except PullGatewayError as exc:
        _merge_error_context(ctx, exc)
        _finalize(db, ctx, "get_rows", exc.status_code)
        return exc.to_response()
