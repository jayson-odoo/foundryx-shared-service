"""Planner 3D job service: staff submit / read / approve / cancel and the
worker pull flow (claim, inputs, heartbeat, outputs, finish).

Staff paths take the tenant from the signed-in user and resolve every id WITH
it. Worker paths resolve the job by the id the worker was handed, then use THAT
job's ``tenant_id`` for every follow-up read and for storage.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image
from sqlalchemy.orm import Session

from app.config import settings
from app.services.storage import storage_for_tenant

from .. import schemas
from ..models import (
    DIRECTION_IN,
    DIRECTION_OUT,
    KIND_CONVERT,
    KIND_MODEL,
    KIND_RENDER,
    P3Job,
    P3JobFile,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
)
from ..repositories import job_repository as repo
from . import events_service, paste_back, sniff
from .errors import P3Error

logger = logging.getLogger(__name__)

MB = 1024 * 1024
MAX_PHOTOS = 3
PHOTO_CAP = 20 * MB
RENDER_INPUT_CAP = 40 * MB
PNG_CAP = 40 * MB
GLB_CAP = 100 * MB
JSON_CAP = 1 * MB
MAX_PROMPT = 300
MAX_SIDE_PX = 4096

EXPORT_NAMES = ("model.glb", "model.gltf", "model.obj", "model.mtl", "model.fbx", "model.stl")
_CANDIDATE = re.compile(r"^candidate-([1-3])\.(glb|json)$")
_ROLE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


def cap_for(name: str) -> int:
    """The byte cap of an output name (reads stop at cap + 1)."""
    ext = name.rsplit(".", 1)[-1].lower()
    if ext == "json":
        return JSON_CAP
    if ext == "png":
        return PNG_CAP
    return GLB_CAP


def allowed_output(kind: str, name: str) -> bool:
    if kind == KIND_MODEL:
        return _CANDIDATE.match(name) is not None
    if kind == KIND_RENDER:
        return name in ("render.png", "diff.json")
    if kind == KIND_CONVERT:
        return name in EXPORT_NAMES
    return False


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _key_hint(tenant_id: str, job_id: str, name: str) -> str:
    return f"planner3d/{tenant_id}/{job_id}/{name}"


def _store(db: Session, tenant_id: str, job_id: str, name: str, data: bytes, mime: str) -> str:
    return storage_for_tenant(db, tenant_id).save(_key_hint(tenant_id, job_id, name), data, mime)


def _drop_blob(db: Session, tenant_id: str, key: str) -> None:
    try:
        storage_for_tenant(db, tenant_id).delete(key)
    except Exception:  # noqa: BLE001 - cleanup must never mask the real error
        logger.warning("planner3d: could not delete a stored blob", exc_info=True)


# ── presenters ──────────────────────────────────────────────────────────────

def present_many(db: Session, tenant_id: str, jobs: Sequence[P3Job]) -> List[schemas.JobOut]:
    files = repo.files_for_jobs(db, tenant_id, [j.id for j in jobs])
    by_job: Dict[str, List[P3JobFile]] = {}
    for f in files:
        by_job.setdefault(f.job_id, []).append(f)
    out = []
    for job in jobs:
        rows = by_job.get(job.id, [])
        ordered = [f for f in rows if f.direction == DIRECTION_IN] + [
            f for f in rows if f.direction == DIRECTION_OUT
        ]
        out.append(
            schemas.JobOut(
                id=job.id,
                kind=job.kind,
                status=job.status,
                engine=job.engine,
                progress=job.progress or 0,
                params=job.params_json,
                error=(
                    schemas.JobErrorOut(code=job.error_code, message=job.error_message or "")
                    if job.error_code
                    else None
                ),
                gpuSeconds=job.gpu_seconds,
                peakRssMb=job.peak_rss_mb,
                attempts=job.attempts or 0,
                approvedCandidate=job.approved_candidate,
                sourceJobId=job.source_job_id,
                files=[
                    schemas.JobFileOut(
                        direction=f.direction,
                        role=f.role,
                        name=f.name,
                        mime=f.mime,
                        size=f.size,
                        sha256=f.sha256,
                    )
                    for f in ordered
                ],
                createdAt=job.created_at,
                startedAt=job.started_at,
                finishedAt=job.finished_at,
            )
        )
    return out


def present_one(db: Session, tenant_id: str, job: P3Job) -> schemas.JobOut:
    return present_many(db, tenant_id, [job])[0]


# ── staff: submit ───────────────────────────────────────────────────────────

def submit_model(
    db: Session,
    tenant_id: str,
    user_id: str,
    photos: Sequence[bytes],
    length_mm: int,
    width_mm: int,
    height_mm: int,
) -> schemas.JobOut:
    if not 1 <= len(photos) <= MAX_PHOTOS:
        raise P3Error(422, "photo_count", f"Send between 1 and {MAX_PHOTOS} photos.")
    prepared: List[Tuple[str, bytes, str]] = []
    for i, data in enumerate(photos, start=1):
        mime = sniff.sniff_image(data)
        if mime is None:
            raise P3Error(422, "photo_type", "Photos must be PNG, JPEG or WebP images.")
        prepared.append((f"photo-{i}.{sniff.IMAGE_EXT[mime]}", data, mime))
    params = {"dimensionsMm": {"length": length_mm, "width": width_mm, "height": height_mm}}
    return _create_with_inputs(
        db, tenant_id, user_id, KIND_MODEL, params, [(n, "photo", d, m) for n, d, m in prepared]
    )


def submit_render(
    db: Session,
    tenant_id: str,
    user_id: str,
    scene: bytes,
    mask: bytes,
    depth: bytes,
    prompt: str,
    seed: Optional[int],
) -> schemas.JobOut:
    if not prompt.strip() or len(prompt) > MAX_PROMPT:
        raise P3Error(422, "prompt", f"The prompt must be 1 to {MAX_PROMPT} characters.")
    for label, data in (("scene", scene), ("mask", mask), ("depth", depth)):
        if not sniff.is_png(data):
            raise P3Error(422, f"{label}_type", f"The {label} must be a PNG image.")
    try:
        scene_size = Image.open(io.BytesIO(scene)).size
        mask_size = Image.open(io.BytesIO(mask)).size
    except Exception as exc:  # noqa: BLE001 - any decode failure is the client's bad file
        raise P3Error(422, "image_invalid", "A PNG could not be read.") from exc
    depth_size = None
    try:
        depth_size = Image.open(io.BytesIO(depth)).size
    except Exception as exc:  # noqa: BLE001
        raise P3Error(422, "image_invalid", "A PNG could not be read.") from exc
    for size in (scene_size, mask_size, depth_size):
        if max(size) > MAX_SIDE_PX:
            raise P3Error(422, "image_too_large", f"Images may be at most {MAX_SIDE_PX} pixels per side.")
    if scene_size != mask_size:
        raise P3Error(422, "mask_size", "The mask must be the same size as the scene.")
    return _create_with_inputs(
        db,
        tenant_id,
        user_id,
        KIND_RENDER,
        {"prompt": prompt, "seed": seed},
        [
            ("scene.png", "scene.png", scene, sniff.MIME_PNG),
            ("mask.png", "mask.png", mask, sniff.MIME_PNG),
            ("depth.png", "depth.png", depth, sniff.MIME_PNG),
        ],
    )


def _create_with_inputs(
    db: Session,
    tenant_id: str,
    user_id: str,
    kind: str,
    params: dict,
    inputs: Sequence[Tuple[str, str, bytes, str]],
    source_job_id: Optional[str] = None,
) -> schemas.JobOut:
    job = P3Job(
        tenant_id=tenant_id,
        kind=kind,
        status=STATUS_QUEUED,
        params_json=params,
        created_by_user_id=user_id,
        source_job_id=source_job_id,
    )
    saved: List[str] = []
    try:
        repo.add(db, job)
        for name, role, data, mime in inputs:
            key = _store(db, tenant_id, job.id, name, data, mime)
            saved.append(key)
            repo.add(
                db,
                P3JobFile(
                    tenant_id=tenant_id,
                    job_id=job.id,
                    direction=DIRECTION_IN,
                    role=role,
                    name=name,
                    mime=mime,
                    size=len(data),
                    sha256=_sha(data),
                    storage_key=key,
                ),
            )
        db.commit()
    except Exception:
        db.rollback()
        for key in saved:
            _drop_blob(db, tenant_id, key)
        raise
    db.refresh(job)
    return present_one(db, tenant_id, job)


# ── staff: read ─────────────────────────────────────────────────────────────

def list_jobs(db: Session, tenant_id: str, kind: Optional[str], status: Optional[str]) -> schemas.JobList:
    rows, total = repo.list_for_tenant(db, tenant_id, kind, status)
    return schemas.JobList(items=present_many(db, tenant_id, rows), total=total)


def _tenant_job(db: Session, tenant_id: str, job_id: str) -> P3Job:
    job = repo.get_for_tenant(db, tenant_id, job_id)
    if job is None:
        raise P3Error(404, "job_not_found", "Job not found.")
    return job


def get_job(db: Session, tenant_id: str, job_id: str) -> schemas.JobOut:
    return present_one(db, tenant_id, _tenant_job(db, tenant_id, job_id))


def download(db: Session, tenant_id: str, job_id: str, name: str) -> Tuple[bytes, str]:
    _tenant_job(db, tenant_id, job_id)
    row = repo.find_file(db, tenant_id, job_id, name)
    if row is None:
        raise P3Error(404, "file_not_found", "File not found.")
    return _fetch(db, tenant_id, row)


def _fetch(db: Session, tenant_id: str, row: P3JobFile) -> Tuple[bytes, str]:
    try:
        data, _ = storage_for_tenant(db, tenant_id).fetch(row.storage_key)
    except Exception as exc:  # noqa: BLE001 - a missing blob is a 404, not a 500
        logger.warning("planner3d: stored file unreadable (%s)", type(exc).__name__)
        raise P3Error(404, "file_not_found", "File not found.") from exc
    return data, row.mime


# ── staff: approve + cancel ─────────────────────────────────────────────────

def approve(db: Session, tenant_id: str, user_id: str, job_id: str, candidate: str) -> schemas.JobOut:
    job = _tenant_job(db, tenant_id, job_id)
    if job.kind != KIND_MODEL or job.status != STATUS_SUCCEEDED or job.approved_candidate:
        raise P3Error(409, "not_approvable", "Only a finished, not yet approved model job can be approved.")
    row = repo.find_file(db, tenant_id, job.id, candidate, DIRECTION_OUT)
    if row is None or not re.match(r"^candidate-[1-3]\.glb$", candidate):
        raise P3Error(422, "unknown_candidate", "That candidate does not exist on this job.")
    data, _ = _fetch(db, tenant_id, row)
    try:
        if not repo.mark_approved(db, tenant_id, job.id, candidate):
            db.rollback()
            raise P3Error(409, "not_approvable", "This job was already approved.")
        out = _create_with_inputs_no_commit(
            db, tenant_id, user_id, {"candidate": candidate}, data, job.id
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return present_one(db, tenant_id, out)


def _create_with_inputs_no_commit(
    db: Session, tenant_id: str, user_id: str, params: dict, glb: bytes, source_job_id: str
) -> P3Job:
    convert = P3Job(
        tenant_id=tenant_id,
        kind=KIND_CONVERT,
        status=STATUS_QUEUED,
        params_json=params,
        created_by_user_id=user_id,
        source_job_id=source_job_id,
    )
    repo.add(db, convert)
    key = _store(db, tenant_id, convert.id, "model.glb", glb, sniff.MIME_GLB)
    repo.add(
        db,
        P3JobFile(
            tenant_id=tenant_id,
            job_id=convert.id,
            direction=DIRECTION_IN,
            role="model",
            name="model.glb",
            mime=sniff.MIME_GLB,
            size=len(glb),
            sha256=_sha(glb),
            storage_key=key,
        ),
    )
    return convert


def cancel(db: Session, tenant_id: str, job_id: str) -> schemas.JobOut:
    job = _tenant_job(db, tenant_id, job_id)
    if not repo.cancel(db, tenant_id, job.id):
        db.rollback()
        raise P3Error(409, "already_finished", "This job has already finished.")
    db.commit()
    db.expire_all()
    done = _tenant_job(db, tenant_id, job_id)
    events_service.queue_job_event(db, done)
    return present_one(db, tenant_id, done)


# ── worker ──────────────────────────────────────────────────────────────────

def _held_job(db: Session, job_id: str, worker: str) -> P3Job:
    """A job the worker holds right now (running + its name), else 404."""
    job = repo.get_by_id(db, job_id)
    if job is None or job.status != STATUS_RUNNING or job.worker_name != worker:
        raise P3Error(404, "job_not_found", "Job not found.")
    return job


def claim(db: Session, worker: str, kinds: Sequence[str]) -> Optional[schemas.ClaimResponse]:
    lost: List[str] = []
    requeued = repo.requeue_stale(db, int(getattr(settings, "planner3d_lease_minutes", 10) or 10), lost)
    for job_id in requeued:
        _void_outputs(db, job_id)
    job = repo.claim_oldest(db, kinds, worker)
    db.commit()
    for lost_id in lost:
        lost_job = repo.get_by_id(db, lost_id)
        if lost_job is not None:
            events_service.queue_job_event(db, lost_job)
    if job is None:
        return None
    inputs = repo.in_files(db, job.tenant_id, job.id)
    return schemas.ClaimResponse(
        jobId=job.id,
        kind=job.kind,
        params=job.params_json,
        inputs=[
            schemas.ClaimInput(role=f.role, name=f.name, mime=f.mime, size=f.size, sha256=f.sha256)
            for f in inputs
        ],
    )


def _void_outputs(db: Session, job_id: str) -> None:
    """A requeued job starts over: outputs of the lost attempt are dropped."""
    job = repo.get_by_id(db, job_id)
    if job is None:
        return
    for row in repo.out_files(db, job.tenant_id, job.id):
        _drop_blob(db, job.tenant_id, row.storage_key)
        repo.delete_file(db, row)


def input_bytes(db: Session, worker: str, job_id: str, name: str) -> Tuple[bytes, str]:
    job = _held_job(db, job_id, worker)
    row = repo.find_file(db, job.tenant_id, job.id, name, DIRECTION_IN)
    if row is None:
        raise P3Error(404, "file_not_found", "File not found.")
    return _fetch(db, job.tenant_id, row)


def heartbeat(db: Session, worker: str, job_id: str, progress: Optional[int]) -> None:
    job = repo.get_by_id(db, job_id)
    if job is None or job.worker_name != worker:
        raise P3Error(404, "job_not_found", "Job not found.")
    if job.status == STATUS_CANCELLED:
        raise P3Error(409, "cancelled", "This job was cancelled.")
    if not repo.heartbeat(db, job.id, worker, progress):
        db.rollback()
        raise P3Error(404, "job_not_found", "Job not found.")
    db.commit()


def put_output(
    db: Session, worker: str, job_id: str, name: str, role: Optional[str], data: bytes
) -> schemas.OutputAck:
    job = _held_job(db, job_id, worker)
    if not allowed_output(job.kind, name):
        raise P3Error(422, "name_not_allowed", "That file name is not allowed for this job.")
    if len(data) > cap_for(name):
        raise P3Error(413, "file_too_large", "The file is over the size limit.")
    mime = sniff.sniff_for_name(name, data)
    if mime is None:
        raise P3Error(422, "file_type", "The file content does not match its name.")
    if name.endswith(".png"):
        try:
            side = max(Image.open(io.BytesIO(data)).size)
        except Exception as exc:  # noqa: BLE001 - unreadable image is a bad upload
            raise P3Error(422, "file_type", "The image could not be read.") from exc
        if side > MAX_SIDE_PX:
            raise P3Error(422, "image_too_large", f"Images may be at most {MAX_SIDE_PX} pixels per side.")
    role = (role or name).strip()
    if not _ROLE.match(role):
        raise P3Error(422, "role", "The role is not valid.")
    tenant_id = job.tenant_id
    key = _store(db, tenant_id, job.id, name, data, mime)
    try:
        existing = repo.find_file(db, tenant_id, job.id, name, DIRECTION_OUT)
        old_key = existing.storage_key if existing else None
        if existing:
            repo.delete_file(db, existing)
        repo.add(
            db,
            P3JobFile(
                tenant_id=tenant_id,
                job_id=job.id,
                direction=DIRECTION_OUT,
                role=role,
                name=name,
                mime=mime,
                size=len(data),
                sha256=_sha(data),
                storage_key=key,
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        _drop_blob(db, tenant_id, key)
        raise
    if old_key:
        _drop_blob(db, tenant_id, old_key)
    return schemas.OutputAck(name=name, size=len(data), sha256=_sha(data))


def _success_problem(db: Session, job: P3Job) -> Optional[Tuple[str, str]]:
    """None when the job's outputs satisfy its kind, else (code, message)."""
    outs = {f.name: f for f in repo.out_files(db, job.tenant_id, job.id)}
    if job.kind == KIND_MODEL:
        glbs = [n for n in outs if re.match(r"^candidate-[1-3]\.glb$", n)]
        if len(glbs) < 2:
            return "no_candidates", "A model job needs at least two candidate models."
        return None
    if job.kind == KIND_CONVERT:
        missing = [n for n in EXPORT_NAMES if n not in outs]
        if missing:
            return "missing_outputs", "Missing export files: " + ", ".join(missing)
        return None
    if job.kind == KIND_RENDER:
        render = outs.get("render.png")
        if render is None:
            return "no_render", "The worker returned no render."
        scene = repo.find_file(db, job.tenant_id, job.id, "scene.png", DIRECTION_IN)
        mask = repo.find_file(db, job.tenant_id, job.id, "mask.png", DIRECTION_IN)
        if scene is None or mask is None:
            return "no_render", "The job inputs are missing."
        try:
            result = paste_back.product_diff(
                _fetch(db, job.tenant_id, scene)[0],
                _fetch(db, job.tenant_id, render)[0],
                _fetch(db, job.tenant_id, mask)[0],
            )
        except (ValueError, OSError, Image.DecompressionBombError) as exc:
            return "render_invalid", f"The render could not be checked: {exc}"
        if result["changed_pixels"] > 0:
            return (
                "product_changed",
                f"{result['changed_pixels']} product pixels differ from the scene.",
            )
        return None
    return "bad_kind", "Unknown job kind."


def finish(
    db: Session,
    worker: str,
    job_id: str,
    status: str,
    error: Optional[schemas.FinishError],
    gpu_seconds: Optional[float],
    peak_rss_mb: Optional[float],
) -> schemas.JobOut:
    job = _held_job(db, job_id, worker)
    values: dict = {
        "gpu_seconds": gpu_seconds,
        "peak_rss_mb": int(round(peak_rss_mb)) if peak_rss_mb is not None else None,
    }
    if status == "failed":
        values.update(
            status=STATUS_FAILED,
            error_code=(error.code if error else "worker_failed"),
            error_message=(error.message[:200] if error else ""),
        )
    else:
        problem = _success_problem(db, job)
        if problem:
            values.update(status=STATUS_FAILED, error_code=problem[0], error_message=problem[1])
        else:
            values.update(status=STATUS_SUCCEEDED, progress=100)
    if not repo.finish(db, job.id, worker, **values):
        db.rollback()
        raise P3Error(404, "job_not_found", "Job not found.")
    db.commit()
    db.expire_all()
    done = repo.get_by_id(db, job_id)
    events_service.queue_job_event(db, done)
    return present_one(db, done.tenant_id, done)
