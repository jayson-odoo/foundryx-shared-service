"""Planner 3D tenant gateway (contract 3.1-3.3, 3.5, 3.7): uploads, model jobs, the
job object. The tenant ALWAYS comes from the resolved key; every id is resolved with
it, so another tenant's id answers the same 404 / 422 as an unknown one.

Jobs land in the S3 ``p3_job`` queue as ``queued``; the Mac worker claims them
(``job_service.claim``). There is no second queue.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.services.storage import storage_for_tenant

from ..models import (
    DIRECTION_IN,
    DIRECTION_OUT,
    KIND_MODEL,
    STATUS_QUEUED,
    STATUS_SUCCEEDED,
    P3Job,
    P3JobFile,
    P3Upload,
)
from ..repositories import job_repository as repo
from . import signed_files, sniff
from .errors import P3Error

logger = logging.getLogger(__name__)

MB = 1024 * 1024
UPLOAD_CAP = 20 * MB
UPLOAD_TTL = timedelta(hours=24)
IDEMPOTENCY_WINDOW = timedelta(hours=24)
MAX_PHOTOS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _z(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── uploads ─────────────────────────────────────────────────────────────────

def upload(db: Session, tenant_id: str, key_id: str, data: bytes) -> Dict[str, Any]:
    if len(data) > UPLOAD_CAP:
        raise P3Error(413, "file_too_large", "The file is over the 20 MB limit.")
    mime = sniff.sniff_image(data)
    if mime is None:
        raise P3Error(415, "unsupported_file", "Send a PNG, JPEG or WebP image.")
    try:
        Image.open(io.BytesIO(data)).size  # header only: an image that cannot be read is refused
    except Exception as exc:  # noqa: BLE001
        raise P3Error(415, "unsupported_file", "The image could not be read.") from exc
    upload_id = f"upl_{uuid.uuid4().hex}"
    key = storage_for_tenant(db, tenant_id).save(
        f"planner3d/{tenant_id}/uploads/{upload_id}.{sniff.IMAGE_EXT[mime]}", data, mime
    )
    row = P3Upload(
        id=upload_id,
        tenant_id=tenant_id,
        api_key_id=key_id,
        mime=mime,
        size=len(data),
        sha256=_sha(data),
        storage_key=key,
        expires_at=_now() + UPLOAD_TTL,
    )
    try:
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        _drop_blob(db, tenant_id, key)
        raise
    return {"id": row.id, "mime": row.mime, "size": row.size, "sha256": row.sha256, "expiresAt": _z(row.expires_at)}


def _drop_blob(db: Session, tenant_id: str, key: str) -> None:
    try:
        storage_for_tenant(db, tenant_id).delete(key)
    except Exception:  # noqa: BLE001 - cleanup must never mask the real error
        logger.warning("planner3d: could not delete a stored upload", exc_info=True)


def purge_unused_uploads(db: Session, limit: int = 500) -> int:
    """Remove uploads no job took once they expired (contract 3.2). An upload a job
    used is kept: its blob is that job's input."""
    rows = (
        db.query(P3Upload)
        .filter(P3Upload.used_at.is_(None), P3Upload.expires_at < _now())
        .limit(limit)
        .all()
    )
    for row in rows:
        _drop_blob(db, row.tenant_id, row.storage_key)
        db.delete(row)
    db.commit()
    return len(rows)


# ── model jobs ──────────────────────────────────────────────────────────────

def _bad(message: str, field: str) -> P3Error:
    err = P3Error(422, "invalid_request", message)
    err.details = [{"loc": ["body", field], "msg": message}]
    return err


def _request_hash(body: Dict[str, Any]) -> str:
    return _sha(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())


def _live_idempotent(db: Session, tenant_id: str, ref: str) -> Optional[P3Job]:
    job = (
        db.query(P3Job)
        .filter(P3Job.tenant_id == tenant_id, P3Job.idempotency_ref == ref)
        .first()
    )
    if job is None:
        return None
    created = job.created_at if job.created_at.tzinfo else job.created_at.replace(tzinfo=timezone.utc)
    if created < _now() - IDEMPOTENCY_WINDOW:
        job.idempotency_ref = None  # the window passed: the key may name a new job
        db.flush()
        return None
    return job


def _replay(job: P3Job, request_hash: str) -> P3Job:
    if job.request_hash != request_hash:
        raise P3Error(409, "idempotency_conflict", "This Idempotency-Key was used with a different request.")
    return job


def create_model(
    db: Session,
    tenant_id: str,
    key_id: str,
    *,
    product_code: str,
    upload_ids: Sequence[str],
    dimensions: Dict[str, float],
    company: Optional[str],
    idempotency_key: Optional[str],
) -> Tuple[Dict[str, Any], bool]:
    """``(job object, created)``; ``created`` is False for an idempotent repeat."""
    ids = list(upload_ids)
    body = {
        "productCode": product_code,
        "uploadIds": ids,
        "dimensionsMm": {k: float(dimensions[k]) for k in ("length", "width", "height")},
        "company": company,
    }
    request_hash = _request_hash(body)
    if idempotency_key:
        existing = _live_idempotent(db, tenant_id, idempotency_key)
        if existing is not None:
            return present(db, _replay(existing, request_hash)), False

    if not 1 <= len(ids) <= MAX_PHOTOS:
        raise _bad(f"Send between 1 and {MAX_PHOTOS} upload ids.", "uploadIds")
    if len(set(ids)) != len(ids):
        raise _bad("An upload id is listed twice.", "uploadIds")
    uploads = {
        u.id: u
        for u in db.query(P3Upload).filter(P3Upload.tenant_id == tenant_id, P3Upload.id.in_(ids)).all()
    }
    now = _now()
    for upload_id in ids:
        row = uploads.get(upload_id)
        expires = None if row is None else (row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc))
        if row is None or (row.used_at is None and expires < now):
            raise _bad("An upload id is unknown or has expired.", "uploadIds")

    queued = db.query(P3Job).filter(P3Job.tenant_id == tenant_id, P3Job.status == STATUS_QUEUED).count()
    if queued >= int(getattr(settings, "planner3d_max_queued_jobs", 20) or 20):
        raise P3Error(429, "queue_full", "Too many jobs are already waiting. Try again later.")

    job = P3Job(
        tenant_id=tenant_id,
        kind=KIND_MODEL,
        status=STATUS_QUEUED,
        params_json=body,
        api_key_id=key_id,
        idempotency_ref=idempotency_key or None,
        request_hash=request_hash,
    )
    try:
        repo.add(db, job)
        for i, upload_id in enumerate(ids, start=1):
            row = uploads[upload_id]
            repo.add(
                db,
                P3JobFile(
                    tenant_id=tenant_id,
                    job_id=job.id,
                    direction=DIRECTION_IN,
                    role="photo",
                    name=f"photo-{i}.{sniff.IMAGE_EXT[row.mime]}",
                    mime=row.mime,
                    size=row.size,
                    sha256=row.sha256,
                    storage_key=row.storage_key,
                ),
            )
            if row.used_at is None:
                row.used_at = now
        db.commit()
    except IntegrityError:
        # A concurrent submit with the same Idempotency-Key won the insert.
        db.rollback()
        existing = _live_idempotent(db, tenant_id, idempotency_key) if idempotency_key else None
        if existing is None:
            raise
        return present(db, _replay(existing, request_hash)), False
    db.refresh(job)
    return present(db, job), True


# ── reads ───────────────────────────────────────────────────────────────────

def _tenant_job(db: Session, tenant_id: str, job_id: str) -> P3Job:
    job = repo.get_for_tenant(db, tenant_id, job_id)
    if job is None:
        raise P3Error(404, "not_found", "Not found.")
    return job


def get_job(db: Session, tenant_id: str, job_id: str) -> Dict[str, Any]:
    return present(db, _tenant_job(db, tenant_id, job_id))


def result_files(db: Session, job: P3Job) -> List[Dict[str, Any]]:
    """The job's result files with fresh signed links; empty unless it succeeded."""
    if job.status != STATUS_SUCCEEDED:
        return []
    out = []
    for f in repo.out_files(db, job.tenant_id, job.id):
        if job.kind == KIND_MODEL and not f.name.endswith(".glb"):
            continue  # candidate-N.json is the worker's own report, not a result
        url, expires = signed_files.signed_url(f.id)
        out.append(
            {
                "role": f.role,
                "name": f.name,
                "mime": f.mime,
                "size": f.size,
                "sha256": f.sha256,
                "url": url,
                "expiresAt": _z(expires),
            }
        )
    return sorted(out, key=lambda f: f["name"])


def error_out(job: P3Job) -> Optional[Dict[str, str]]:
    if not job.error_code:
        return None
    return {"code": job.error_code, "message": job.error_message or ""}


def present(db: Session, job: P3Job) -> Dict[str, Any]:
    params = job.params_json or {}
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "engine": job.engine,
        "createdAt": _z(job.created_at),
        "startedAt": _z(job.started_at),
        "finishedAt": _z(job.finished_at),
        "progress": job.progress or 0,
        "input": {
            "productCode": params.get("productCode"),
            "company": params.get("company"),
            "uploadIds": params.get("uploadIds") or [],
            "dimensionsMm": params.get("dimensionsMm"),
        },
        "result": {"files": result_files(db, job)},
        "error": error_out(job),
        "sourceJobId": job.source_job_id,
        "approvedCandidate": job.approved_candidate,
        "usage": {"gpuSeconds": _gpu_seconds(job.gpu_seconds), "paidCost": None},
    }


def _gpu_seconds(value: Optional[float]) -> Optional[int]:
    if value is None:
        return None
    whole = int(value)
    return whole if whole == value else whole + 1


# ── signed file links ───────────────────────────────────────────────────────

def signed_file(db: Session, file_id: str, exp: int, sig: str) -> Tuple[bytes, str, str]:
    """``(bytes, mime, name)`` for a valid link. The file row is looked up by id only
    AFTER the signature passed (the signature is the authorisation); every failure,
    including a tenant that lost the module, is the same 404."""
    from ..gateway_auth import module_enabled

    if not signed_files.verify(file_id, exp, sig):
        raise P3Error(404, "not_found", "Not found.")
    row = db.query(P3JobFile).filter(P3JobFile.id == file_id, P3JobFile.direction == DIRECTION_OUT).first()
    if row is None or not module_enabled(db, row.tenant_id):
        raise P3Error(404, "not_found", "Not found.")
    try:
        data, _ = storage_for_tenant(db, row.tenant_id).fetch(row.storage_key)
    except Exception as exc:  # noqa: BLE001 - a missing blob is a 404
        logger.warning("planner3d: signed file unreadable (%s)", type(exc).__name__)
        raise P3Error(404, "not_found", "Not found.") from exc
    return data, row.mime, row.name
