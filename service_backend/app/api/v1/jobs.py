"""Background-jobs + storage-migration endpoints (sprint-4/10 Slice 2).

Thin HTTP/Pydantic layer only — all logic lives in ``JobService`` /
``StorageMigrationService`` (no DB access here). ``GET /jobs`` + ``GET
/jobs/{id}`` are readable by any authenticated tenant user (the generic Jobs
drawer); the storage-migration controls (start / abort / retry / complete) are
gated by ``integrations.migrate_storage``.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, get_current_user, require_permission
from app.jobs.repository import BackgroundJobRepository
from app.models.user import User
from app.schemas.job import JobListResponse, JobOut, StorageMigrationStartRequest
from app.storage_migration.service import StorageMigrationService

router = APIRouter()

_MIGRATE_PERM = "integrations.migrate_storage"


@router.post("/storage/migrations", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def start_storage_migration(
    payload: StorageMigrationStartRequest,
    user: User = Depends(require_permission(_MIGRATE_PERM)),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> JobOut:
    job = StorageMigrationService(db).start(
        user.tenant_id,
        actor_id,
        provider=payload.provider,
        name=payload.name,
        new_config=payload.config,
        new_credentials=payload.credentials,
    )
    return JobOut.model_validate(job)


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    type: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
) -> JobListResponse:
    rows, total = BackgroundJobRepository(db).list(
        user.tenant_id, job_type=type, status=status_filter, page=page, page_size=page_size
    )
    return JobListResponse(items=[JobOut.model_validate(r) for r in rows], total=total)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobOut:
    job = BackgroundJobRepository(db).get(user.tenant_id, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    return JobOut.model_validate(job)


@router.post("/jobs/{job_id}/abort", response_model=JobOut)
def abort_job(
    job_id: str,
    user: User = Depends(require_permission(_MIGRATE_PERM)),
    db: Session = Depends(get_db),
) -> JobOut:
    return JobOut.model_validate(StorageMigrationService(db).abort(user.tenant_id, job_id))


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(
    job_id: str,
    user: User = Depends(require_permission(_MIGRATE_PERM)),
    db: Session = Depends(get_db),
) -> JobOut:
    return JobOut.model_validate(StorageMigrationService(db).retry(user.tenant_id, job_id))


@router.post("/jobs/{job_id}/complete", response_model=JobOut)
def complete_job(
    job_id: str,
    user: User = Depends(require_permission(_MIGRATE_PERM)),
    db: Session = Depends(get_db),
) -> JobOut:
    return JobOut.model_validate(StorageMigrationService(db).complete(user.tenant_id, job_id))
