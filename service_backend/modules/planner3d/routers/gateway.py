"""Planner 3D tenant gateway ``/api/v1/planner3d`` (contract 3; lane PLANNER-3D-S1).

Bearer ``fx3_live_...`` key (``gateway_auth``); errors use core's
``{"error": {"code", "message", "details"}}`` envelope. Consumer of record: sorento-crm
``planner_ss_client.py`` (``upload``, ``create_model_job``, ``get_job``). A wire change
here is a change to ``documentation/planner3d/module-contract.md`` in the same commit.
HTTP only: the work is ``services/gateway_service.py``.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db

from .. import schemas
from ..gateway_auth import AuditedRoute, Planner3dGatewayKey, get_planner3d_gateway_key
from ..services import gateway_service
from ..services.errors import P3Error

router = APIRouter(route_class=AuditedRoute)


def _api(exc: P3Error) -> ApiError:
    return ApiError(exc.status_code, exc.code, exc.message, getattr(exc, "details", None))


async def _read_file_part(request: Request) -> bytes:
    """The multipart part ``file``, read with a cap (cap + 1 bytes proves it is over)."""
    # The cap must hold BEFORE the body is parsed: Starlette spools a file part to
    # disk without a limit, so a body with no declared length is refused (411).
    declared = (request.headers.get("content-length") or "").strip()
    if not declared.isdigit():
        raise P3Error(411, "length_required", "Send the upload with a Content-Length header.")
    if int(declared) > gateway_service.UPLOAD_CAP + 64 * 1024:
        raise P3Error(413, "file_too_large", "The file is over the 20 MB limit.")
    try:
        form = await request.form()
    except Exception as exc:  # noqa: BLE001 - not multipart at all
        raise P3Error(400, "invalid_request", "Send the image as multipart form data, part 'file'.") from exc
    part = form.get("file")
    if part is None or isinstance(part, str) or not hasattr(part, "read"):
        raise P3Error(422, "invalid_request", "Send the image in a part named 'file'.")
    data = await part.read(gateway_service.UPLOAD_CAP + 1)
    if len(data) > gateway_service.UPLOAD_CAP:
        raise P3Error(413, "file_too_large", "The file is over the 20 MB limit.")
    return data


@router.post("/uploads", response_model=schemas.UploadOut, status_code=201)
async def create_upload(
    request: Request,
    key: Planner3dGatewayKey = Depends(get_planner3d_gateway_key),
    db: Session = Depends(get_db),
):
    try:
        data = await _read_file_part(request)
        return await run_in_threadpool(gateway_service.upload, db, key.tenant_id, key.key_id, data)
    except P3Error as exc:
        raise _api(exc)


@router.post("/models", response_model=schemas.GatewayJobOut, status_code=202)
def create_model(
    body: schemas.CreateModelRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=128),
    key: Planner3dGatewayKey = Depends(get_planner3d_gateway_key),
    db: Session = Depends(get_db),
):
    try:
        job, created = gateway_service.create_model(
            db,
            key.tenant_id,
            key.key_id,
            product_code=body.productCode,
            upload_ids=body.uploadIds,
            dimensions=body.dimensionsMm.model_dump(),
            company=body.company,
            idempotency_key=idempotency_key,
        )
    except P3Error as exc:
        raise _api(exc)
    if created:
        return job
    return JSONResponse(status_code=200, content=schemas.GatewayJobOut(**job).model_dump(mode="json"))


@router.get("/jobs/{job_id}", response_model=schemas.GatewayJobOut)
def get_job(
    job_id: str,
    key: Planner3dGatewayKey = Depends(get_planner3d_gateway_key),
    db: Session = Depends(get_db),
):
    try:
        return gateway_service.get_job(db, key.tenant_id, job_id)
    except P3Error as exc:
        raise _api(exc)
