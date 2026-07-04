"""Permission catalog route — the grouped catalog driving the role Permissions tab."""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.tenant import PLATFORM_TENANT_ID
from app.models.user import User
from app.repositories.module_repository import ModuleRepository
from app.schemas.permission import PermissionResourceOut
from app.services.permission_service import PermissionService

router = APIRouter()


@router.get("", response_model=List[PermissionResourceOut])
def list_catalog(
    current_user: User = Depends(require_permission("roles.read")),
    db: Session = Depends(get_db),
) -> List[PermissionResourceOut]:
    # Platform keys are operator-only — tenant role editors never see them.
    # Module keys narrow to the tenant's INSTALLED modules (plan 08 §6).
    is_platform = current_user.tenant_id == PLATFORM_TENANT_ID
    installed = (
        None if is_platform else ModuleRepository(db).installed_module_names(current_user.tenant_id)
    )
    return PermissionService(db).catalog(
        include_platform=is_platform, installed_modules=installed
    )
