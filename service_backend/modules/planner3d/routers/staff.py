"""Planner 3D staff API (session JWT, module-gated, permission-gated).
HTTP only; every call is tenant-scoped from the signed-in user."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from .. import schemas
from ..services import events_service, job_service, key_service
from ..services.errors import P3Error

router = APIRouter()

_READ = require_permission("planner3d.jobs.read")
_MANAGE = require_permission("planner3d.jobs.manage")
_KEYS = require_permission("planner3d.keys.manage")
_HOOKS = require_permission("planner3d.webhooks.manage")

_FILE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox",
    "Cache-Control": "private, no-store",
}


def _http(exc: P3Error) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}
    )


def _read_capped(upload: UploadFile, cap: int) -> bytes:
    """At most ``cap`` bytes; one more byte read proves it is over."""
    data = upload.file.read(cap + 1)
    if len(data) > cap:
        raise P3Error(413, "file_too_large", "A file is over the size limit.")
    return data


@router.post("/jobs/models", response_model=schemas.JobOut, status_code=202)
def submit_model(
    photos: List[UploadFile] = File(...),
    lengthMm: int = Form(..., gt=0),
    widthMm: int = Form(..., gt=0),
    heightMm: int = Form(..., gt=0),
    user: User = Depends(_MANAGE),
    db: Session = Depends(get_db),
) -> schemas.JobOut:
    try:
        if len(photos) > job_service.MAX_PHOTOS:
            raise P3Error(422, "photo_count", f"Send at most {job_service.MAX_PHOTOS} photos.")
        blobs = [_read_capped(p, job_service.PHOTO_CAP) for p in photos]
        return job_service.submit_model(db, user.tenant_id, user.id, blobs, lengthMm, widthMm, heightMm)
    except P3Error as exc:
        raise _http(exc)


@router.post("/jobs/renders", response_model=schemas.JobOut, status_code=202)
def submit_render(
    scene: UploadFile = File(...),
    mask: UploadFile = File(...),
    depth: UploadFile = File(...),
    prompt: str = Form(..., min_length=1, max_length=job_service.MAX_PROMPT),
    seed: Optional[int] = Form(default=None),
    user: User = Depends(_MANAGE),
    db: Session = Depends(get_db),
) -> schemas.JobOut:
    try:
        cap = job_service.RENDER_INPUT_CAP
        return job_service.submit_render(
            db,
            user.tenant_id,
            user.id,
            _read_capped(scene, cap),
            _read_capped(mask, cap),
            _read_capped(depth, cap),
            prompt,
            seed,
        )
    except P3Error as exc:
        raise _http(exc)


@router.get("/jobs", response_model=schemas.JobList)
def list_jobs(
    kind: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    user: User = Depends(_READ),
    db: Session = Depends(get_db),
) -> schemas.JobList:
    return job_service.list_jobs(db, user.tenant_id, kind, status)


@router.get("/jobs/{job_id}", response_model=schemas.JobOut)
def get_job(job_id: str, user: User = Depends(_READ), db: Session = Depends(get_db)) -> schemas.JobOut:
    try:
        return job_service.get_job(db, user.tenant_id, job_id)
    except P3Error as exc:
        raise _http(exc)


@router.get("/jobs/{job_id}/files/{name}")
def download_file(
    job_id: str, name: str, user: User = Depends(_READ), db: Session = Depends(get_db)
) -> Response:
    try:
        data, mime = job_service.download(db, user.tenant_id, job_id, name)
    except P3Error as exc:
        raise _http(exc)
    headers = {**_FILE_HEADERS, "Content-Disposition": f'attachment; filename="{name}"'}
    return Response(content=data, media_type=mime, headers=headers)


@router.post("/jobs/{job_id}/approve", response_model=schemas.JobOut, status_code=202)
def approve_job(
    job_id: str,
    body: schemas.ApproveRequest,
    user: User = Depends(_MANAGE),
    db: Session = Depends(get_db),
) -> schemas.JobOut:
    try:
        return job_service.approve(db, user.tenant_id, user.id, job_id, body.candidate)
    except P3Error as exc:
        raise _http(exc)


@router.post("/jobs/{job_id}/cancel", response_model=schemas.JobOut)
def cancel_job(job_id: str, user: User = Depends(_MANAGE), db: Session = Depends(get_db)) -> schemas.JobOut:
    try:
        return job_service.cancel(db, user.tenant_id, job_id)
    except P3Error as exc:
        raise _http(exc)


# ── S1: gateway keys (contract 8, "Keys") ───────────────────────────────────

def _key_item(row) -> schemas.KeyItem:
    return schemas.KeyItem(
        id=row.id,
        name=row.name,
        keyMasked=key_service.masked(row),
        createdAt=row.created_at,
        lastUsedAt=row.last_used_at,
        revokedAt=row.revoked_at,
    )


@router.get("/keys", response_model=schemas.KeyList)
def list_keys(user: User = Depends(_KEYS), db: Session = Depends(get_db)) -> schemas.KeyList:
    return schemas.KeyList(data=[_key_item(r) for r in key_service.list_keys(db, user.tenant_id)])


@router.post("/keys", response_model=schemas.KeyCreated, status_code=201)
def create_key(
    body: schemas.KeyCreate,
    user: User = Depends(_KEYS),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> schemas.KeyCreated:
    row, full_key = key_service.issue(db, user.tenant_id, name=body.name, created_by=actor_id)
    return schemas.KeyCreated(**_key_item(row).model_dump(), key=full_key)


@router.delete("/keys/{key_id}", status_code=204)
def revoke_key(key_id: str, user: User = Depends(_KEYS), db: Session = Depends(get_db)) -> Response:
    try:
        key_service.revoke(db, user.tenant_id, key_id)
    except key_service.KeyNotFound:
        raise HTTPException(status_code=404, detail={"code": "key_not_found", "message": "Key not found."})
    return Response(status_code=204)


# ── S1: webhook receivers (contract 5.1, 8) ─────────────────────────────────

def _receiver_item(row) -> schemas.ReceiverItem:
    return schemas.ReceiverItem(
        id=row.id,
        url=row.url,
        events=list(row.events_json or []),
        createdAt=row.created_at,
        lastSuccessAt=row.last_success_at,
    )


@router.get("/receivers", response_model=schemas.ReceiverList)
def list_receivers(user: User = Depends(_HOOKS), db: Session = Depends(get_db)) -> schemas.ReceiverList:
    return schemas.ReceiverList(data=[_receiver_item(r) for r in events_service.list_receivers(db, user.tenant_id)])


@router.post("/receivers", response_model=schemas.ReceiverCreated, status_code=201)
def create_receiver(
    body: schemas.ReceiverCreate, user: User = Depends(_HOOKS), db: Session = Depends(get_db)
) -> schemas.ReceiverCreated:
    try:
        row, secret = events_service.create_receiver(db, user.tenant_id, body.url, body.events)
    except P3Error as exc:
        raise _http(exc)
    return schemas.ReceiverCreated(**_receiver_item(row).model_dump(), secret=secret)


@router.delete("/receivers/{receiver_id}", status_code=204)
def delete_receiver(receiver_id: str, user: User = Depends(_HOOKS), db: Session = Depends(get_db)) -> Response:
    try:
        events_service.delete_receiver(db, user.tenant_id, receiver_id)
    except P3Error as exc:
        raise _http(exc)
    return Response(status_code=204)
