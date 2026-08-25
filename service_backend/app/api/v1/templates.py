"""Template engine endpoints (plan 07) - gated templates.read / templates.manage.

Tenant scope: a tenant works its own tier (fork-on-edit over platform
defaults). The PLATFORM TENANT maps to scope ``None`` - it maintains the
NULL-tier defaults through these same endpoints (D13).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_permission
from app.models.template import Template
from app.models.user import User
from app.schemas.filters import FilterGroup
from app.schemas.template import (
    ContextFactOut,
    ListFactOut,
    TemplateContextOut,
    TemplateCreateRequest,
    TemplateDetail,
    TemplateItem,
    TemplateListResponse,
    TemplateNeighborResponse,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    TemplateTestSendResponse,
    TemplateUpdateRequest,
)
from app.services.filter_translator import FilterError
from app.services.template_service import (
    TemplateError,
    TemplateNotFound,
    TemplateService,
)
from app.template_engine import list_contexts

router = APIRouter()


def _scope(user: User):
    """Platform tenant maintains the NULL tier (D13)."""
    return None if user.tenant.is_platform else user.tenant_id


def _parse_filter(raw: Optional[str]) -> Optional[FilterGroup]:
    if not raw:
        return None
    try:
        return FilterGroup.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid filter.") from exc


def _item(service: TemplateService, row: Template) -> TemplateItem:
    from app.template_engine import get_context

    context = get_context(row.context)
    return TemplateItem(
        id=row.id,
        key=row.key,
        name=row.name,
        type=row.type,
        context=row.context,
        context_label=context.label if context else row.context,
        tier=service.tier_of(row),
        is_system=row.is_system,
        subject=row.subject,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _detail(service: TemplateService, row: Template) -> TemplateDetail:
    item = _item(service, row)
    return TemplateDetail(**item.model_dump(by_alias=False), doc=row.doc_json)


@router.get("", response_model=TemplateListResponse)
def list_templates(
    current_user: User = Depends(require_permission("templates.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
    context: Optional[str] = None,
) -> TemplateListResponse:
    service = TemplateService(db)
    try:
        rows, total = service.list(
            _scope(current_user),
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
            context=context,
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return TemplateListResponse(data=[_item(service, r) for r in rows], total=total, page=page)


@router.get("/contexts", response_model=list[TemplateContextOut])
def template_contexts(
    current_user: User = Depends(require_permission("templates.read")),
) -> list[TemplateContextOut]:
    return [
        TemplateContextOut(
            key=c.key,
            label=c.label,
            fact_sources=list(c.fact_sources),
            facts=[ContextFactOut(key=f.key, label=f.label, sample=f.sample) for f in c.facts],
            list_facts=[
                ListFactOut(
                    key=lf.key,
                    label=lf.label,
                    item_facts=[
                        ContextFactOut(key=i.key, label=i.label, sample=i.sample)
                        for i in lf.item_facts
                    ],
                )
                for lf in c.list_facts
            ],
            required_facts=list(c.required_facts),
        )
        for c in list_contexts()
    ]


@router.get("/at", response_model=TemplateNeighborResponse)
def template_at(
    current_user: User = Depends(require_permission("templates.read")),
    db: Session = Depends(get_db),
    index: int = Query(0, ge=0),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> TemplateNeighborResponse:
    service = TemplateService(db)
    try:
        row, total = service.get_at(
            index,
            _scope(current_user),
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return TemplateNeighborResponse(template=_item(service, row) if row else None, total=total)


@router.post("/preview")
async def preview_template(
    payload: TemplatePreviewRequest,
    current_user: User = Depends(require_permission("templates.read")),
    db: Session = Depends(get_db),
    download: bool = Query(False),
):
    """Preview a template. ``format=html`` → email HTML JSON (default);
    ``format=pdf`` → the document-surface PDF inline (``?download=true`` →
    attachment). The PDF render is CPU-bound + sync - offloaded to a threadpool
    so the event loop stays free (D8)."""
    service = TemplateService(db)
    if payload.format == "pdf":
        try:
            pdf = await run_in_threadpool(
                service.preview_pdf,
                _scope(current_user),
                doc=payload.doc,
                subject=payload.subject,
                context=payload.context,
            )
        except TemplateError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
        disposition = "attachment" if download else "inline"
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'{disposition}; filename="preview.pdf"'},
        )

    if payload.format == "canvasPdf":
        try:
            pdf = await run_in_threadpool(
                service.preview_canvas_pdf,
                _scope(current_user),
                doc=payload.doc,
                subject=payload.subject,
                context=payload.context,
            )
        except (TemplateError, ValueError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
        disposition = "attachment" if download else "inline"
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'{disposition}; filename="badge.pdf"'},
        )

    if payload.format == "canvasHtml":
        try:
            canvas_html = await run_in_threadpool(
                service.preview_canvas_html,
                _scope(current_user),
                doc=payload.doc,
                subject=payload.subject,
                context=payload.context,
            )
        except (TemplateError, ValueError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
        return Response(content=canvas_html, media_type="text/html")

    if payload.format == "docHtml":
        # In-app document preview sheet (no browser PDF-viewer chrome) - same
        # compiler as the PDF; the editor renders this in a sandboxed iframe.
        try:
            doc_html = await run_in_threadpool(
                service.preview_doc_html,
                _scope(current_user),
                doc=payload.doc,
                subject=payload.subject,
                context=payload.context,
            )
        except TemplateError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
        return Response(content=doc_html, media_type="text/html")

    try:
        rendered = service.preview(
            _scope(current_user),
            doc=payload.doc,
            subject=payload.subject,
            context=payload.context,
        )
    except TemplateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return TemplatePreviewResponse(subject=rendered.subject, html=rendered.html, text=rendered.text)


@router.get("/{template_id}", response_model=TemplateDetail)
def get_template(
    template_id: str,
    current_user: User = Depends(require_permission("templates.read")),
    db: Session = Depends(get_db),
) -> TemplateDetail:
    service = TemplateService(db)
    try:
        row = service.get(template_id, _scope(current_user))
    except TemplateNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found.")
    return _detail(service, row)


@router.post("", response_model=TemplateDetail, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: TemplateCreateRequest,
    current_user: User = Depends(require_permission("templates.manage")),
    db: Session = Depends(get_db),
) -> TemplateDetail:
    service = TemplateService(db)
    try:
        row = service.create(
            _scope(current_user),
            name=payload.name,
            subject=payload.subject,
            context=payload.context,
            doc=payload.doc,
            type_=payload.type,
        )
    except TemplateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return _detail(service, row)


@router.patch("/{template_id}", response_model=TemplateDetail)
def update_template(
    template_id: str,
    payload: TemplateUpdateRequest,
    current_user: User = Depends(require_permission("templates.manage")),
    db: Session = Depends(get_db),
) -> TemplateDetail:
    service = TemplateService(db)
    try:
        row = service.update(
            template_id,
            _scope(current_user),
            name=payload.name,
            subject=payload.subject,
            doc=payload.doc,
        )
    except TemplateNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found.")
    except TemplateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return _detail(service, row)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: str,
    current_user: User = Depends(require_permission("templates.manage")),
    db: Session = Depends(get_db),
) -> None:
    service = TemplateService(db)
    try:
        service.delete(template_id, _scope(current_user))
    except TemplateNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found.")
    except TemplateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.post("/{template_id}/duplicate", response_model=TemplateDetail)
def duplicate_template(
    template_id: str,
    current_user: User = Depends(require_permission("templates.manage")),
    db: Session = Depends(get_db),
) -> TemplateDetail:
    service = TemplateService(db)
    try:
        row = service.duplicate(template_id, _scope(current_user))
    except TemplateNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found.")
    return _detail(service, row)


@router.post("/{template_id}/reset", response_model=TemplateDetail)
def reset_template(
    template_id: str,
    current_user: User = Depends(require_permission("templates.manage")),
    db: Session = Depends(get_db),
) -> TemplateDetail:
    service = TemplateService(db)
    try:
        row = service.reset(template_id, _scope(current_user))
    except TemplateNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found.")
    except TemplateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return _detail(service, row)


@router.post("/{template_id}/test-send", response_model=TemplateTestSendResponse)
def test_send_template(
    template_id: str,
    current_user: User = Depends(require_permission("templates.manage")),
    db: Session = Depends(get_db),
) -> TemplateTestSendResponse:
    service = TemplateService(db)
    try:
        to_email = service.test_send(template_id, _scope(current_user), current_user)
    except TemplateNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found.")
    except TemplateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return TemplateTestSendResponse(to_email=to_email)
