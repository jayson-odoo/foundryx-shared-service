"""Planner 3D worker pull API. ``"public": true`` in the manifest: no session,
the worker proves itself with a bearer token (sha256 compared) and names itself
in ``X-Planner3d-Worker``. HTTP only."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.database import get_db

from .. import schemas
from ..services import job_service, worker_auth
from ..services.errors import P3Error

router = APIRouter()

_FILE_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}


def _http(exc: P3Error) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}
    )


def require_worker(
    authorization: Optional[str] = Header(default=None),
    x_planner3d_worker: Optional[str] = Header(default=None),
) -> str:
    try:
        return worker_auth.authenticate(authorization, x_planner3d_worker)
    except worker_auth.WorkerAuthError:
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "Worker authentication failed."},
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/claim", response_model=schemas.ClaimResponse)
def claim(
    body: schemas.ClaimRequest,
    worker: str = Depends(require_worker),
    db: Session = Depends(get_db),
):
    got = job_service.claim(db, worker, body.kinds)
    if got is None:
        return Response(status_code=204)
    return got


@router.get("/jobs/{job_id}/inputs/{name}")
def get_input(
    job_id: str, name: str, worker: str = Depends(require_worker), db: Session = Depends(get_db)
) -> Response:
    try:
        data, mime = job_service.input_bytes(db, worker, job_id, name)
    except P3Error as exc:
        raise _http(exc)
    return Response(content=data, media_type=mime, headers=_FILE_HEADERS)


@router.post("/jobs/{job_id}/heartbeat")
def heartbeat(
    job_id: str,
    body: schemas.HeartbeatRequest,
    worker: str = Depends(require_worker),
    db: Session = Depends(get_db),
) -> dict:
    try:
        job_service.heartbeat(db, worker, job_id, body.progress)
    except P3Error as exc:
        raise _http(exc)
    return {"ok": True}


@router.put("/jobs/{job_id}/outputs/{name}", response_model=schemas.OutputAck, status_code=201)
async def put_output(
    job_id: str,
    name: str,
    request: Request,
    role: Optional[str] = Query(default=None, max_length=32),
    worker: str = Depends(require_worker),
    db: Session = Depends(get_db),
) -> schemas.OutputAck:
    cap = job_service.cap_for(name)
    declared = request.headers.get("content-length")
    try:
        if declared and declared.isdigit() and int(declared) > cap:
            raise P3Error(413, "file_too_large", "The file is over the size limit.")
        chunks = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > cap:
                raise P3Error(413, "file_too_large", "The file is over the size limit.")
            chunks.append(chunk)
        return await run_in_threadpool(
            job_service.put_output, db, worker, job_id, name, role, b"".join(chunks)
        )
    except P3Error as exc:
        raise _http(exc)


@router.post("/jobs/{job_id}/finish", response_model=schemas.JobOut)
def finish(
    job_id: str,
    body: schemas.FinishRequest,
    worker: str = Depends(require_worker),
    db: Session = Depends(get_db),
) -> schemas.JobOut:
    try:
        return job_service.finish(
            db, worker, job_id, body.status, body.error, body.gpuSeconds, body.peakRssMb
        )
    except P3Error as exc:
        raise _http(exc)
