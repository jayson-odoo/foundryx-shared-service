"""Preview-job poll + cancel (sprint-5/11 S4, AC-11-22/24/27). Thin: HTTP +
Pydantic only.

No DB query and no raw SQL lives here (code-review hard-fail). The tenant
comes from the authenticated user - NEVER from client input - and both
handlers hand off to ``PreviewJobService``. Reuses the EXISTING
``autocount.companies.{read,manage}`` keys (no new permission, no grant
sweep needed for existing tenants).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import PreviewJobOut
from ..services.preview_job_service import PreviewJobService

router = APIRouter()


@router.get("/{job_id}", response_model=PreviewJobOut)
def get_preview_job(
    job_id: str,
    current_user: User = Depends(require_permission("autocount.companies.read")),
    db: Session = Depends(get_db),
) -> PreviewJobOut:
    """AC-11-22/27 - polled while ``queued``/``running``; tenant-scoped, a
    cross-tenant or unknown job id is a uniform 404 (no leak). ``result`` is
    withheld (review round 1, S1) unless the caller also holds the scope's
    own start key - resolved in the SERVICE (``effective_permission_keys``),
    never here."""
    view = PreviewJobService(db).get(current_user.tenant_id, job_id, current_user=current_user)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview job not found.")
    return view


@router.post("/{job_id}/cancel", response_model=PreviewJobOut)
def cancel_preview_job(
    job_id: str,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> PreviewJobOut:
    """AC-11-24 - a no-op 200 carrying the terminal status against an
    already-terminal job, never a 409 the UI has to explain. ``result`` is
    withheld the SAME way the poll route withholds it (review round 2,
    item 1) - resolved in the SERVICE, never here."""
    view = PreviewJobService(db).cancel(current_user.tenant_id, job_id, current_user=current_user)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview job not found.")
    return view
