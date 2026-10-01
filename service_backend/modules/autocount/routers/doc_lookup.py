"""Find an AutoCount document by number (sprint-5/17) - authed operator routes.

Thin: HTTP + Pydantic only; every handler hands off to ``DocLookupService``.
The tenant comes from the authenticated user, never from client input. Read
only towards AutoCount (the live search is the ``autocount_doc_lookup`` job).
"""
from typing import NoReturn, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import effective_permission_keys, get_actor_user_id, require_permission
from app.models.user import User

from ..doc_lookup.schemas import (
    DocLookupJobOut,
    DocLookupSettingsIn,
    DocLookupSettingsOut,
    DocLookupStartIn,
    DocTypeListOut,
    StoredLookupOut,
)
from ..doc_lookup.service import DocLookupError, DocLookupService, job_view

router = APIRouter()

READ = "autocount.pull.read"


def _raise(exc: DocLookupError) -> NoReturn:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message, **exc.extra},
    ) from exc


@router.get("/types", response_model=DocTypeListOut)
def list_doc_types(
    company_id: Optional[str] = Query(None, alias="companyId"),
    current_user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
) -> DocTypeListOut:
    try:
        return DocTypeListOut(data=DocLookupService(db).types(
            current_user.tenant_id, company_id, effective_permission_keys(current_user),
        ))
    except DocLookupError as exc:
        _raise(exc)


@router.get("/stored", response_model=StoredLookupOut)
def stored_lookup(
    company_id: str = Query(..., alias="companyId"),
    doc_no: str = Query(..., alias="docNo"),
    doc_type: Optional[str] = Query(None, alias="docType"),
    current_user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
) -> StoredLookupOut:
    try:
        body = DocLookupService(db).stored(
            current_user.tenant_id, company_id, doc_no, doc_type,
            effective_permission_keys(current_user),
        )
    except DocLookupError as exc:
        _raise(exc)
    return StoredLookupOut(**body)


@router.get("/settings", response_model=DocLookupSettingsOut)
def get_settings(
    company_id: str = Query(..., alias="companyId"),
    current_user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
) -> DocLookupSettingsOut:
    try:
        return DocLookupSettingsOut(**DocLookupService(db).get_settings(current_user.tenant_id, company_id))
    except DocLookupError as exc:
        _raise(exc)


@router.put("/settings", response_model=DocLookupSettingsOut)
def save_settings(
    body: DocLookupSettingsIn,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> DocLookupSettingsOut:
    try:
        saved = DocLookupService(db).save_settings(
            current_user.tenant_id, body.companyId,
            back_days=body.lastModifiedBackDays, forward_days=body.docDateForwardDays,
        )
    except DocLookupError as exc:
        _raise(exc)
    return DocLookupSettingsOut(**saved)


@router.post("", response_model=DocLookupJobOut, status_code=status.HTTP_202_ACCEPTED)
def start_lookup(
    body: DocLookupStartIn,
    current_user: User = Depends(require_permission(READ)),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> DocLookupJobOut:
    try:
        job = DocLookupService(db).start(
            current_user.tenant_id, actor_id, company_id=body.companyId,
            doc_no_raw=body.docNo, doc_type_key=body.docType, around_day_raw=body.aroundDay,
            permissions=effective_permission_keys(current_user),
        )
    except DocLookupError as exc:
        _raise(exc)
    return DocLookupJobOut(**job_view(job))


@router.get("/jobs/{job_id}", response_model=DocLookupJobOut)
def get_lookup_job(
    job_id: str,
    current_user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
) -> DocLookupJobOut:
    try:
        job = DocLookupService(db).get_job(
            current_user.tenant_id, job_id, effective_permission_keys(current_user),
        )
    except DocLookupError as exc:
        _raise(exc)
    return DocLookupJobOut(**job_view(job))


@router.post("/jobs/{job_id}/stop", response_model=DocLookupJobOut)
def stop_lookup_job(
    job_id: str,
    current_user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
) -> DocLookupJobOut:
    try:
        job = DocLookupService(db).stop(
            current_user.tenant_id, job_id, effective_permission_keys(current_user),
        )
    except DocLookupError as exc:
        _raise(exc)
    return DocLookupJobOut(**job_view(job))
