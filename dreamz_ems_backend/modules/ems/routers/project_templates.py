"""EMS event-templates routes (sprint-3/11) — preset + eligibility-flow owner."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from modules.ems.schemas import (
    ListResponse,
    ProjectTemplateIn,
    ProjectTemplateOut,
    ProjectTemplatePatch,
    TemplateChildIn,
    TemplateChildOut,
)
from modules.ems.services import ProjectTemplateService

router = APIRouter()


@router.get("", response_model=ListResponse)
def list_templates(
    type_id: Optional[str] = Query(None),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(require_permission("project_templates.read")),
    db: Session = Depends(get_db),
):
    rows, total = ProjectTemplateService(db).list(
        current_user.tenant_id, type_id=type_id, page=page, page_size=page_size
    )
    return ListResponse(
        items=[ProjectTemplateOut.model_validate(r) for r in rows], total=total, page=page, pageSize=page_size
    )


@router.post("", response_model=ProjectTemplateOut, status_code=201)
def create_template(
    body: ProjectTemplateIn,
    current_user: User = Depends(require_permission("project_templates.manage")),
    db: Session = Depends(get_db),
):
    return ProjectTemplateOut.model_validate(
        ProjectTemplateService(db).create(current_user.tenant_id, body.model_dump())
    )


@router.get("/{template_id}", response_model=ProjectTemplateOut)
def get_template(
    template_id: str,
    current_user: User = Depends(require_permission("project_templates.read")),
    db: Session = Depends(get_db),
):
    return ProjectTemplateOut.model_validate(
        ProjectTemplateService(db).get(current_user.tenant_id, template_id)
    )


@router.patch("/{template_id}", response_model=ProjectTemplateOut)
def update_template(
    template_id: str,
    body: ProjectTemplatePatch,
    current_user: User = Depends(require_permission("project_templates.manage")),
    db: Session = Depends(get_db),
):
    return ProjectTemplateOut.model_validate(
        ProjectTemplateService(db).update(
            current_user.tenant_id, template_id, body.model_dump(exclude_unset=True)
        )
    )


@router.delete("/{template_id}", status_code=204)
def delete_template(
    template_id: str,
    current_user: User = Depends(require_permission("project_templates.manage")),
    db: Session = Depends(get_db),
):
    ProjectTemplateService(db).delete(current_user.tenant_id, template_id)


# ── roles + segments (template-owned; AC-11-01) ──────────────────────────────


@router.get("/{template_id}/roles", response_model=list[TemplateChildOut])
def list_roles(
    template_id: str,
    current_user: User = Depends(require_permission("project_templates.read")),
    db: Session = Depends(get_db),
):
    rows = ProjectTemplateService(db).list_children(current_user.tenant_id, template_id, "role")
    return [TemplateChildOut.model_validate(r) for r in rows]


@router.post("/{template_id}/roles", response_model=TemplateChildOut, status_code=201)
def add_role(
    template_id: str,
    body: TemplateChildIn,
    current_user: User = Depends(require_permission("project_templates.manage")),
    db: Session = Depends(get_db),
):
    return TemplateChildOut.model_validate(
        ProjectTemplateService(db).add_child(current_user.tenant_id, template_id, "role", body.name)
    )


@router.delete("/{template_id}/roles/{role_id}", status_code=204)
def delete_role(
    template_id: str,
    role_id: str,
    current_user: User = Depends(require_permission("project_templates.manage")),
    db: Session = Depends(get_db),
):
    ProjectTemplateService(db).delete_child(current_user.tenant_id, template_id, "role", role_id)


@router.get("/{template_id}/segments", response_model=list[TemplateChildOut])
def list_segments(
    template_id: str,
    current_user: User = Depends(require_permission("project_templates.read")),
    db: Session = Depends(get_db),
):
    rows = ProjectTemplateService(db).list_children(current_user.tenant_id, template_id, "segment")
    return [TemplateChildOut.model_validate(r) for r in rows]


@router.post("/{template_id}/segments", response_model=TemplateChildOut, status_code=201)
def add_segment(
    template_id: str,
    body: TemplateChildIn,
    current_user: User = Depends(require_permission("project_templates.manage")),
    db: Session = Depends(get_db),
):
    return TemplateChildOut.model_validate(
        ProjectTemplateService(db).add_child(current_user.tenant_id, template_id, "segment", body.name)
    )


@router.delete("/{template_id}/segments/{segment_id}", status_code=204)
def delete_segment(
    template_id: str,
    segment_id: str,
    current_user: User = Depends(require_permission("project_templates.manage")),
    db: Session = Depends(get_db),
):
    ProjectTemplateService(db).delete_child(current_user.tenant_id, template_id, "segment", segment_id)
