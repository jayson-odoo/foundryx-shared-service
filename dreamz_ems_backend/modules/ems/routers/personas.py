"""Staff persona-management API (sprint-4/06 slice 0b) — AC-06-26.

Staff-authed (``require_permission`` + the loader's ``require_module("ems")``
gate). Service-Repository layered — NO DB/SQL here. Lets ``personas.manage``
staff configure personas, grant portal keys, and assign personas to Profiles
(the STAFF acquisition path, AC-06-22).
"""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from modules.ems.persona_schemas import (
    PersonaIn,
    PersonaOut,
    PersonaPatch,
    PersonaPermissionsIn,
    PersonaPermissionsOut,
    PortalPermissionOut,
)
from modules.ems.persona_service import PersonaService
from modules.ems.portal_rbac import list_portal_permissions

router = APIRouter()


@router.get("", response_model=List[PersonaOut])
def list_personas(
    current_user: User = Depends(require_permission("personas.read")),
    db: Session = Depends(get_db),
):
    return [
        PersonaOut.model_validate(p)
        for p in PersonaService(db).list(current_user.tenant_id)
    ]


@router.post("", response_model=PersonaOut, status_code=201)
def create_persona(
    body: PersonaIn,
    current_user: User = Depends(require_permission("personas.manage")),
    db: Session = Depends(get_db),
):
    return PersonaOut.model_validate(
        PersonaService(db).create(current_user.tenant_id, body.model_dump())
    )


# Specific path BEFORE the /{persona_id} param route (catalog for the grant UI).
@router.get("/portal-permissions", response_model=List[PortalPermissionOut])
def portal_permission_catalog(
    current_user: User = Depends(require_permission("personas.read")),
    db: Session = Depends(get_db),
):
    return [
        PortalPermissionOut(key=p.key, label=p.label, description=p.description)
        for p in list_portal_permissions()
    ]


@router.get("/{persona_id}", response_model=PersonaOut)
def get_persona(
    persona_id: str,
    current_user: User = Depends(require_permission("personas.read")),
    db: Session = Depends(get_db),
):
    return PersonaOut.model_validate(
        PersonaService(db).get(current_user.tenant_id, persona_id)
    )


@router.patch("/{persona_id}", response_model=PersonaOut)
def update_persona(
    persona_id: str,
    body: PersonaPatch,
    current_user: User = Depends(require_permission("personas.manage")),
    db: Session = Depends(get_db),
):
    return PersonaOut.model_validate(
        PersonaService(db).update(
            current_user.tenant_id, persona_id, body.model_dump(exclude_unset=True)
        )
    )


@router.delete("/{persona_id}", status_code=204)
def delete_persona(
    persona_id: str,
    current_user: User = Depends(require_permission("personas.manage")),
    db: Session = Depends(get_db),
):
    PersonaService(db).delete(current_user.tenant_id, persona_id)


@router.get("/{persona_id}/permissions", response_model=PersonaPermissionsOut)
def get_persona_permissions(
    persona_id: str,
    current_user: User = Depends(require_permission("personas.read")),
    db: Session = Depends(get_db),
):
    return PersonaPermissionsOut(
        keys=PersonaService(db).get_permissions(current_user.tenant_id, persona_id)
    )


@router.put("/{persona_id}/permissions", response_model=PersonaPermissionsOut)
def set_persona_permissions(
    persona_id: str,
    body: PersonaPermissionsIn,
    current_user: User = Depends(require_permission("personas.manage")),
    db: Session = Depends(get_db),
):
    return PersonaPermissionsOut(
        keys=PersonaService(db).set_permissions(
            current_user.tenant_id, persona_id, body.keys
        )
    )
