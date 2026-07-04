"""WhatsApp template management routes (plan 07). Mounted under the omnichannel
channels prefix; gated by `wa_templates.read` / `wa_templates.manage`. Distinct from
the send-picker `GET /channels/{id}/templates` (gated `conversations.reply`)."""
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from app.services.storage import storage_for_tenant
from app.uploads import detect_upload_mime
from ..schemas import TemplateDetail, TemplateManageListResponse
from ..template_schemas import WaTemplateDoc
from ..services.template_management_service import TemplateManagementService, TemplateNotFound

router = APIRouter()

# Draft media-header sample cap (matches the avatar/branding ceilings).
_SAMPLE_MAX_BYTES = 5 * 1024 * 1024


def _service(db: Session) -> TemplateManagementService:
    return TemplateManagementService(db)


@router.get("/{channel_id}/templates/manage", response_model=TemplateManageListResponse)
def list_templates(
    channel_id: str,
    current_user: User = Depends(require_permission("wa_templates.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    category: Optional[str] = None,
    language: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
) -> TemplateManageListResponse:
    try:
        items, total = _service(db).list(
            channel_id, current_user.tenant_id, page=page, page_size=page_size,
            search=search, status_filter=status_filter, category=category,
            language=language, sort_by=sort_by, sort_dir=sort_dir,
        )
    except TemplateNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found.")
    return TemplateManageListResponse(data=items, total=total, page=page)


@router.get("/{channel_id}/templates/manage/{template_id}", response_model=TemplateDetail)
def get_template(
    channel_id: str,
    template_id: str,
    current_user: User = Depends(require_permission("wa_templates.read")),
    db: Session = Depends(get_db),
) -> TemplateDetail:
    try:
        return _service(db).get(channel_id, template_id, current_user.tenant_id)
    except TemplateNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found.")


@router.post("/{channel_id}/templates/sync", response_model=TemplateManageListResponse)
def sync_templates(
    channel_id: str,
    current_user: User = Depends(require_permission("wa_templates.manage")),
    db: Session = Depends(get_db),
) -> TemplateManageListResponse:
    try:
        items, total = _service(db).sync(channel_id, current_user.tenant_id)
    except TemplateNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found.")
    return TemplateManageListResponse(data=items, total=total, page=0)


@router.post("/{channel_id}/templates/upload-sample")
def upload_media_sample(
    channel_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("wa_templates.manage")),
    db: Session = Depends(get_db),
) -> dict:
    """Sniff-gated upload of a draft media-header sample → returns a storage key
    placed in the builder doc (`header.sampleKey`). Images + PDF only (GP-6)."""
    raw = file.file.read(_SAMPLE_MAX_BYTES + 1)
    if len(raw) > _SAMPLE_MAX_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "File is larger than 5MB.")
    mime = detect_upload_mime(raw)
    if mime is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unsupported file type (images or PDF only).")
    key = storage_for_tenant(db, current_user.tenant_id).save(
        f"omni/templates/{channel_id}/sample", raw, mime
    )
    return {"sampleKey": key, "mime": mime}


@router.post("/{channel_id}/templates", response_model=TemplateDetail, status_code=status.HTTP_201_CREATED)
def create_draft(
    channel_id: str,
    doc: WaTemplateDoc,
    current_user: User = Depends(require_permission("wa_templates.manage")),
    db: Session = Depends(get_db),
) -> TemplateDetail:
    try:
        return _service(db).save_draft(channel_id, doc, current_user.tenant_id)
    except TemplateNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found.")


@router.post("/{channel_id}/templates/{template_id}/submit", response_model=TemplateDetail)
def submit_template(
    channel_id: str,
    template_id: str,
    current_user: User = Depends(require_permission("wa_templates.manage")),
    db: Session = Depends(get_db),
) -> TemplateDetail:
    try:
        return _service(db).submit(channel_id, template_id, current_user.tenant_id)
    except TemplateNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found.")


@router.patch("/{channel_id}/templates/{template_id}", response_model=TemplateDetail)
def edit_template(
    channel_id: str,
    template_id: str,
    doc: WaTemplateDoc,
    current_user: User = Depends(require_permission("wa_templates.manage")),
    db: Session = Depends(get_db),
) -> TemplateDetail:
    try:
        return _service(db).edit(channel_id, template_id, doc, current_user.tenant_id)
    except TemplateNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found.")


@router.delete("/{channel_id}/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    channel_id: str,
    template_id: str,
    current_user: User = Depends(require_permission("wa_templates.manage")),
    db: Session = Depends(get_db),
) -> Response:
    try:
        _service(db).delete(channel_id, template_id, current_user.tenant_id)
    except TemplateNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
