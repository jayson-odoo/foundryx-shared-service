"""EMS event-types routes (sprint-3/11) — category master data."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from modules.ems.schemas import ListResponse, ProjectTypeIn, ProjectTypeOut, ProjectTypePatch
from modules.ems.services import ProjectTypeService

router = APIRouter()


@router.get("", response_model=ListResponse)
def list_types(
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(require_permission("project_types.read")),
    db: Session = Depends(get_db),
):
    rows, total = ProjectTypeService(db).list(current_user.tenant_id, page=page, page_size=page_size)
    return ListResponse(
        items=[ProjectTypeOut.model_validate(r) for r in rows], total=total, page=page, pageSize=page_size
    )


@router.post("", response_model=ProjectTypeOut, status_code=201)
def create_type(
    body: ProjectTypeIn,
    current_user: User = Depends(require_permission("project_types.manage")),
    db: Session = Depends(get_db),
):
    return ProjectTypeOut.model_validate(
        ProjectTypeService(db).create(current_user.tenant_id, body.model_dump())
    )


@router.get("/{type_id}", response_model=ProjectTypeOut)
def get_type(
    type_id: str,
    current_user: User = Depends(require_permission("project_types.read")),
    db: Session = Depends(get_db),
):
    return ProjectTypeOut.model_validate(ProjectTypeService(db).get(current_user.tenant_id, type_id))


@router.patch("/{type_id}", response_model=ProjectTypeOut)
def update_type(
    type_id: str,
    body: ProjectTypePatch,
    current_user: User = Depends(require_permission("project_types.manage")),
    db: Session = Depends(get_db),
):
    return ProjectTypeOut.model_validate(
        ProjectTypeService(db).update(current_user.tenant_id, type_id, body.model_dump(exclude_unset=True))
    )


@router.delete("/{type_id}", status_code=204)
def delete_type(
    type_id: str,
    current_user: User = Depends(require_permission("project_types.manage")),
    db: Session = Depends(get_db),
):
    ProjectTypeService(db).delete(current_user.tenant_id, type_id)
