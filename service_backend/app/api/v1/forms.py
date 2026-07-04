"""Form engine endpoints (plan sprint-3/01) — HTTP only (Router → Service →
Repository). Two routers wired in ``main.py``:

- ``router`` (``/forms``): definition CRUD + lifecycle (publish/unpublish/
  archive/restore), versions, preview/fill, submit + submissions + the scoped
  graph. Gated ``forms.read``/``forms.manage`` and (submissions tab)
  ``submissions.read``.
- ``submissions_router`` (``/submissions``): single submission read + transition.

Two endpoints are gated by ``get_current_user`` ONLY (D19 — any authed user
fills/submits an internal form, no ``forms.read`` required): ``GET /{id}/fill``
and ``POST /{id}/submissions``. The 422 contracts the frontend service pins:
publish → ``{"problems": [...]}``, submit → ``{"fieldErrors": {...}}``; 409s
carry a plain detail string.
"""
import json
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import (
    effective_permission_keys,
    get_current_user,
    get_db,
    require_permission,
)
from app.models.user import User
from app.schemas.filters import FilterGroup
from app.schemas.form import (
    FormCreateRequest,
    FormDetailOut,
    FormFillViewOut,
    FormListResponse,
    FormNeighborResponse,
    FormSubmissionGraphOut,
    FormSubmissionOut,
    FormUpdateRequest,
    FormVersionDefinitionOut,
    FormVersionListResponse,
    PublicFormViewOut,
    SubmissionListResponse,
    TransitionRequest,
)
from app.services.filter_translator import FilterError
from app.services.form_service import (
    FormClosed,
    FormNotFound,
    FormPublishBlocked,
    FormRevisionBlocked,
    FormRevisionForbidden,
    FormService,
    FormSubmitInvalid,
    FormValidationError,
    SubmissionNotFound,
    UploadedFormFile,
)
from app.services.throttle import Throttled, ThrottleService, client_ip


# Submit accepts EITHER application/json ({answers, honeypot}) OR multipart
# (a `payload` JSON part + `file:<fieldKey>` parts) — the file path (D12). Files
# are read with a CAPPED read so an oversize body is never buffered whole.
async def _read_submission(request: Request) -> Tuple[Dict[str, Any], str, List[UploadedFormFile]]:
    ctype = request.headers.get("content-type", "")
    if not ctype.startswith("multipart/form-data"):
        try:
            body = await request.json()
        except Exception as exc:  # malformed/non-JSON body → 422, not 500
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Malformed request body."
            ) from exc
        if not isinstance(body, dict):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Malformed request body.")
        return (body.get("answers") or {}), (body.get("honeypot") or ""), []

    form = await request.form()
    raw = form.get("payload")
    try:
        payload = json.loads(raw) if isinstance(raw, str) and raw else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Malformed submission payload.") from exc

    cap = int(settings.form_upload_max_file_mb * 1024 * 1024)
    uploads: List[UploadedFormFile] = []
    for name, part in form.multi_items():
        if not name.startswith("file:") or not hasattr(part, "filename"):
            continue
        content = await part.read(cap + 1)
        if len(content) > cap:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "A file is too large.")
        uploads.append(UploadedFormFile(name[len("file:"):], part.filename or "file", content))
    return (payload.get("answers") or {}), (payload.get("honeypot") or ""), uploads

router = APIRouter()
submissions_router = APIRouter()
public_router = APIRouter()


def _parse_filter(raw: Optional[str]) -> Optional[FilterGroup]:
    if not raw:
        return None
    try:
        return FilterGroup.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid filter.") from exc


# ---- list ----


@router.get("", response_model=FormListResponse)
def list_forms(
    current_user: User = Depends(require_permission("forms.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    status_view: Optional[str] = None,
    filter: Optional[str] = None,
) -> FormListResponse:
    try:
        items, total = FormService(db).list(
            current_user.tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            status_view=status_view,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return FormListResponse(data=items, total=total, page=page)


@router.get("/at", response_model=FormNeighborResponse)
def form_at(
    index: int = Query(0, ge=0),
    current_user: User = Depends(require_permission("forms.read")),
    db: Session = Depends(get_db),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    status_view: Optional[str] = None,
    filter: Optional[str] = None,
) -> FormNeighborResponse:
    try:
        item, total = FormService(db).get_at(
            index,
            current_user.tenant_id,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            status_view=status_view,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return FormNeighborResponse(form=item, total=total)


@router.get("/export", response_class=PlainTextResponse)
def export_forms(
    current_user: User = Depends(require_permission("forms.read")),
    db: Session = Depends(get_db),
    columns: str = Query("name,status,access,submissionCount"),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    status_view: Optional[str] = None,
    filter: Optional[str] = None,
) -> PlainTextResponse:
    try:
        csv_text = FormService(db).export_forms_csv(
            current_user.tenant_id,
            [c for c in columns.split(",") if c],
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            status_view=status_view,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=forms.csv"},
    )


# ---- detail + writes ----


@router.post("", response_model=FormDetailOut, status_code=status.HTTP_201_CREATED)
def create_form(
    body: FormCreateRequest,
    current_user: User = Depends(require_permission("forms.manage")),
    db: Session = Depends(get_db),
) -> FormDetailOut:
    service = FormService(db)
    try:
        form = service.create(
            current_user.tenant_id,
            current_user,
            name=body.name,
            description=body.description or "",
            access=body.access,
        )
    except FormValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return FormDetailOut(**service.to_detail(current_user.tenant_id, form))


@router.get("/{form_id}", response_model=FormDetailOut)
def get_form(
    form_id: str,
    current_user: User = Depends(require_permission("forms.read")),
    db: Session = Depends(get_db),
) -> FormDetailOut:
    service = FormService(db)
    try:
        form = service.get(current_user.tenant_id, form_id)
    except FormNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found.")
    return FormDetailOut(**service.to_detail(current_user.tenant_id, form))


@router.patch("/{form_id}", response_model=FormDetailOut)
def update_form(
    form_id: str,
    body: FormUpdateRequest,
    current_user: User = Depends(require_permission("forms.manage")),
    db: Session = Depends(get_db),
) -> FormDetailOut:
    service = FormService(db)
    try:
        form = service.update(
            current_user.tenant_id,
            form_id,
            fields_set=set(body.model_fields_set),
            **body.model_dump(),
        )
    except FormNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found.")
    except FormValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return FormDetailOut(**service.to_detail(current_user.tenant_id, form))


@router.delete("/{form_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_form(
    form_id: str,
    current_user: User = Depends(require_permission("forms.manage")),
    db: Session = Depends(get_db),
) -> None:
    try:
        FormService(db).delete(current_user.tenant_id, form_id)
    except FormNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found.")


# ---- lifecycle actions ----


@router.post("/{form_id}/publish", response_model=FormDetailOut)
def publish_form(
    form_id: str,
    current_user: User = Depends(require_permission("forms.manage")),
    db: Session = Depends(get_db),
) -> FormDetailOut:
    service = FormService(db)
    try:
        form = service.publish(current_user.tenant_id, form_id, current_user)
    except FormNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found.")
    except FormPublishBlocked as exc:
        # The frontend FormPublishError reads detail.problems.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"problems": exc.problems}
        )
    return FormDetailOut(**service.to_detail(current_user.tenant_id, form))


def _lifecycle(form_id: str, current_user: User, db: Session, fn) -> FormDetailOut:
    service = FormService(db)
    try:
        form = fn(service)
    except FormNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found.")
    return FormDetailOut(**service.to_detail(current_user.tenant_id, form))


@router.post("/{form_id}/unpublish", response_model=FormDetailOut)
def unpublish_form(form_id: str, current_user: User = Depends(require_permission("forms.manage")), db: Session = Depends(get_db)) -> FormDetailOut:
    return _lifecycle(form_id, current_user, db, lambda s: s.unpublish(current_user.tenant_id, form_id))


@router.post("/{form_id}/archive", response_model=FormDetailOut)
def archive_form(form_id: str, current_user: User = Depends(require_permission("forms.manage")), db: Session = Depends(get_db)) -> FormDetailOut:
    return _lifecycle(form_id, current_user, db, lambda s: s.archive(current_user.tenant_id, form_id))


@router.post("/{form_id}/restore", response_model=FormDetailOut)
def restore_form(form_id: str, current_user: User = Depends(require_permission("forms.manage")), db: Session = Depends(get_db)) -> FormDetailOut:
    return _lifecycle(form_id, current_user, db, lambda s: s.restore(current_user.tenant_id, form_id))


# ---- versions ----


@router.get("/{form_id}/versions", response_model=FormVersionListResponse)
def list_versions(
    form_id: str,
    current_user: User = Depends(require_permission("forms.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100),
) -> FormVersionListResponse:
    service = FormService(db)
    try:
        items, total = service.list_versions(current_user.tenant_id, form_id, page=page, page_size=page_size)
    except FormNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found.")
    return FormVersionListResponse(data=items, total=total, page=page)


@router.get("/{form_id}/versions/{version_id}", response_model=FormVersionDefinitionOut)
def get_version_definition(
    form_id: str,
    version_id: str,
    current_user: User = Depends(require_permission("submissions.read")),
    db: Session = Depends(get_db),
) -> FormVersionDefinitionOut:
    """One version's immutable definition — the submission detail page
    re-renders answers against their PINNED version forever (D9)."""
    service = FormService(db)
    version = service.get_version(current_user.tenant_id, form_id, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found.")
    return FormVersionDefinitionOut(
        id=version.id,
        version_number=version.version_number,
        definition=version.definition_json,
    )


# ---- preview / fill (D9) ----


@router.post("/{form_id}/preview", response_model=FormFillViewOut)
def preview_form(
    form_id: str,
    current_user: User = Depends(require_permission("forms.read")),
    db: Session = Depends(get_db),
) -> FormFillViewOut:
    service = FormService(db)
    try:
        return FormFillViewOut(**service.preview(current_user.tenant_id, form_id))
    except FormNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found.")


@router.get("/{form_id}/fill", response_model=FormFillViewOut)
def fill_form(
    form_id: str,
    current_user: User = Depends(get_current_user),  # any authed user (D19)
    db: Session = Depends(get_db),
) -> FormFillViewOut:
    service = FormService(db)
    try:
        view = service.fill(current_user.tenant_id, form_id)
    except FormNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found.")
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This form is not published.")
    return FormFillViewOut(**view)


# ---- submit (D14/D19) ----


@router.post("/{form_id}/submissions", response_model=FormSubmissionOut, status_code=status.HTTP_201_CREATED)
async def submit_form(
    form_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),  # any authed user (D19)
    db: Session = Depends(get_db),
) -> FormSubmissionOut:
    answers, _honeypot, uploads = await _read_submission(request)
    service = FormService(db)
    try:
        submission = service.submit(current_user.tenant_id, form_id, current_user, answers, uploads)
    except FormNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found.")
    except FormSubmitInvalid as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"fieldErrors": exc.field_errors}
        )
    except FormClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return FormSubmissionOut(
        **service.get_submission(current_user.tenant_id, submission.id, current_user)
    )


# ---- submissions list + export + graph ----


@router.get("/{form_id}/submissions", response_model=SubmissionListResponse)
def list_submissions(
    form_id: str,
    current_user: User = Depends(require_permission("submissions.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    segment: Optional[str] = None,
    group: Optional[str] = None,
) -> SubmissionListResponse:
    service = FormService(db)
    try:
        if group:
            # The revision chain for one group (R3 history) — every revision,
            # newest first, each pinned to its own version.
            items = service.list_revisions(current_user.tenant_id, form_id, group, current_user)
            return SubmissionListResponse(data=items, total=len(items), page=0)
        items, total = service.list_submissions(
            current_user.tenant_id,
            form_id,
            current_user,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            segment=segment,
        )
    except FormNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found.")
    return SubmissionListResponse(data=items, total=total, page=page)


@router.get("/{form_id}/submissions/export", response_class=PlainTextResponse)
def export_submissions(
    form_id: str,
    current_user: User = Depends(require_permission("submissions.read")),
    db: Session = Depends(get_db),
    columns: str = Query("id,respondent,statusLabel,submittedAt"),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    segment: Optional[str] = None,
) -> PlainTextResponse:
    service = FormService(db)
    try:
        csv_text = service.export_submissions_csv(
            current_user.tenant_id,
            form_id,
            current_user,
            [c for c in columns.split(",") if c],
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            segment=segment,
        )
    except FormNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found.")
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=submissions.csv"},
    )


@router.get("/{form_id}/graph", response_model=FormSubmissionGraphOut)
def submission_graph(
    form_id: str,
    current_user: User = Depends(require_permission("submissions.read")),
    db: Session = Depends(get_db),
) -> FormSubmissionGraphOut:
    """The form's scope-filtered status graph — the Submissions tab transition
    buttons need it WITHOUT statuses.read (gated submissions.read, D15)."""
    service = FormService(db)
    try:
        return FormSubmissionGraphOut(**service.submission_graph(current_user.tenant_id, form_id))
    except FormNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found.")


# ---- single submission (separate /submissions router) ----


@submissions_router.get("/{submission_id}", response_model=FormSubmissionOut)
def get_submission(
    submission_id: str,
    current_user: User = Depends(require_permission("submissions.read")),
    db: Session = Depends(get_db),
) -> FormSubmissionOut:
    service = FormService(db)
    try:
        return FormSubmissionOut(**service.get_submission(current_user.tenant_id, submission_id, current_user))
    except SubmissionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found.")


@submissions_router.get("/{submission_id}/files/{field_key}/{index}")
def submission_file(
    submission_id: str,
    field_key: str,
    index: int,
    current_user: User = Depends(require_permission("submissions.read")),
    db: Session = Depends(get_db),
):
    """Serve an uploaded file/signature from a submission (D12). Authed +
    tenant-scoped; CSP-sandboxed + nosniff (a quarantined upload may be a
    script-bearing SVG/HTML — sandbox keeps it inert on direct navigation, the
    branding-asset hardening). Presigned URLs expire → never immutable-cache."""
    from app.services.storage import storage_for_tenant

    found = FormService(db).submission_file_key(
        current_user.tenant_id, submission_id, field_key, index
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    storage_key, mime, filename = found
    try:
        location, value = storage_for_tenant(db, current_user.tenant_id).resolve(storage_key)
    except Exception:  # noqa: BLE001 — unresolvable key (connection gone)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    headers = {
        "Content-Disposition": f'inline; filename="{filename}"',
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=300",
    }
    if location in ("presigned", "url"):
        return RedirectResponse(value, headers=headers)
    return FileResponse(value, media_type=mime, headers=headers)


@submissions_router.post("/{submission_id}/transition", response_model=FormSubmissionOut)
def transition_submission(
    submission_id: str,
    body: TransitionRequest,
    current_user: User = Depends(require_permission("submissions.manage")),
    db: Session = Depends(get_db),
) -> FormSubmissionOut:
    from app.services.status_machine import (
        TransitionConditionsNotMet,
        TransitionForbidden,
        TransitionNotAllowed,
    )

    service = FormService(db)
    try:
        row = service.transition_submission(
            current_user.tenant_id, submission_id, body.transitionId, current_user
        )
    except SubmissionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission or transition not found.")
    except TransitionForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, exc.message)
    except (TransitionNotAllowed, TransitionConditionsNotMet) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message)
    return FormSubmissionOut(**row)


# ---- revisions (plan sprint-4/04) ----
#
# Gated by ``get_current_user`` ONLY — a submission's OWNER may revise/resubmit
# even without ``submissions.manage`` (filling/correcting ≠ administering, D19);
# the service authorizes owner-OR-manage as the real boundary.


@submissions_router.post("/{submission_id}/revise", response_model=FormSubmissionOut)
def revise_submission(
    submission_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FormSubmissionOut:
    """Clone a frozen current submission into a new Draft revision (R2)."""
    service = FormService(db)
    can_manage = "submissions.manage" in effective_permission_keys(current_user)
    try:
        draft = service.revise(
            current_user.tenant_id, submission_id, current_user, can_manage=can_manage
        )
    except SubmissionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found.")
    except FormRevisionForbidden:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't revise this submission.")
    except FormRevisionBlocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return FormSubmissionOut(
        **service.get_submission(current_user.tenant_id, draft.id, current_user)
    )


@submissions_router.post("/{submission_id}/resubmit", response_model=FormSubmissionOut)
async def resubmit_revision(
    submission_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FormSubmissionOut:
    """Save edited answers into a Draft revision + fire its Submit edge (R3)."""
    answers, _honeypot, uploads = await _read_submission(request)
    service = FormService(db)
    can_manage = "submissions.manage" in effective_permission_keys(current_user)
    try:
        submission = service.resubmit_revision(
            current_user.tenant_id,
            submission_id,
            current_user,
            answers,
            uploads,
            can_manage=can_manage,
        )
    except SubmissionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found.")
    except FormRevisionForbidden:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't edit this submission.")
    except FormSubmitInvalid as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"fieldErrors": exc.field_errors}
        )
    except FormRevisionBlocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return FormSubmissionOut(
        **service.get_submission(current_user.tenant_id, submission.id, current_user)
    )


# ---- public (pre-auth) surface (plan sprint-3/02, D11/D12) ----
#
# Tenant is resolved from the subdomain frontend-side and carried in the path
# (the /public/branding precedent — the browser hits the API origin directly, so
# the subdomain can't survive on the Host header). Unknown tenant / non-public /
# unpublished form = a UNIFORM 404 (no enumeration). The POST is throttled
# per-IP in its OWN bucket, honeypotted, and submits anonymously (user=None).


@public_router.get("/{tenant_slug}/{form_slug}", response_model=PublicFormViewOut)
def public_form_view(
    tenant_slug: str,
    form_slug: str,
    db: Session = Depends(get_db),
) -> PublicFormViewOut:
    view = FormService(db).public_view(tenant_slug, form_slug)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found.")
    return PublicFormViewOut(**view)


@public_router.post(
    "/{tenant_slug}/{form_slug}/submissions", status_code=status.HTTP_204_NO_CONTENT
)
async def public_form_submit(
    tenant_slug: str,
    form_slug: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    throttle = ThrottleService(db)
    ip = client_ip(request)
    # Throttle BEFORE any work (the cheapest gate; mirrors the auth endpoints).
    try:
        throttle.enforce_form_public(ip=ip)
    except Throttled as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many submissions. Please try again later.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    throttle.record_form_public(ip=ip)

    answers, honeypot, uploads = await _read_submission(request)
    service = FormService(db)
    try:
        service.public_submit(tenant_slug, form_slug, answers, honeypot, uploads)
    except FormNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found.")
    except FormSubmitInvalid as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"fieldErrors": exc.field_errors}
        )
    except FormClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
