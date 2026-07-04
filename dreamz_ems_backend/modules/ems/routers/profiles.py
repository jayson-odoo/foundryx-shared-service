"""EMS profiles routes (sprint-3/11) — admin-side Resource CRUD + tier-1
transitions. Gated profiles.read / profiles.manage; the loader wraps the whole
router in require_module('ems')."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.user import User
from modules.ems.models import PERSONA_SCOPE_PROJECT, PERSONA_SCOPE_TENANT
from modules.ems.persona_schemas import (
    PersonaMembershipIn,
    PersonaMembershipOut,
    ProfileInviteIn,
    ProfileInviteOut,
)
from modules.ems.persona_repository import PersonaRepository
from modules.ems.persona_service import PersonaService
from modules.ems.portal_auth_service import PortalAuthService, ProfileNotFound
from modules.ems.schemas import (
    ExportRequest,
    ListResponse,
    ProfileIn,
    ProfileOut,
    ProfilePatch,
    TransitionIn,
)
from modules.ems.services import ProfileService

router = APIRouter()


@router.get("", response_model=ListResponse)
def list_profiles(
    search: Optional[str] = Query(None),
    trashed: bool = Query(False),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    sort_by: Optional[str] = Query(None),
    sort_dir: str = Query("asc"),
    current_user: User = Depends(require_permission("profiles.read")),
    db: Session = Depends(get_db),
):
    rows, total = ProfileService(db).list(
        current_user.tenant_id, search=search, page=page, page_size=page_size,
        trashed=trashed, sort_by=sort_by, sort_dir=sort_dir,
    )
    return ListResponse(
        items=[ProfileOut.model_validate(r) for r in rows], total=total, page=page, pageSize=page_size
    )


@router.post("/export", response_class=PlainTextResponse)
def export_profiles(
    body: ExportRequest,
    current_user: User = Depends(require_permission("profiles.read")),
    db: Session = Depends(get_db),
):
    csv_text = ProfileService(db).export_csv(
        current_user.tenant_id, body.columns, ids=body.ids, search=body.search, trashed=body.trashed
    )
    return PlainTextResponse(csv_text, media_type="text/csv")


@router.post("", response_model=ProfileOut, status_code=201)
def create_profile(
    body: ProfileIn,
    current_user: User = Depends(require_permission("profiles.manage")),
    db: Session = Depends(get_db),
):
    return ProfileOut.model_validate(
        ProfileService(db).create(current_user.tenant_id, body.model_dump())
    )


@router.get("/{profile_id}", response_model=ProfileOut)
def get_profile(
    profile_id: str,
    current_user: User = Depends(require_permission("profiles.read")),
    db: Session = Depends(get_db),
):
    return ProfileOut.model_validate(ProfileService(db).get(current_user.tenant_id, profile_id))


@router.patch("/{profile_id}", response_model=ProfileOut)
def update_profile(
    profile_id: str,
    body: ProfilePatch,
    current_user: User = Depends(require_permission("profiles.manage")),
    db: Session = Depends(get_db),
):
    return ProfileOut.model_validate(
        ProfileService(db).update(current_user.tenant_id, profile_id, body.model_dump(exclude_unset=True))
    )


@router.delete("/{profile_id}", status_code=204)
def delete_profile(
    profile_id: str,
    current_user: User = Depends(require_permission("profiles.manage")),
    db: Session = Depends(get_db),
):
    ProfileService(db).delete(current_user.tenant_id, profile_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{profile_id}/transition", response_model=ProfileOut)
def transition_profile(
    profile_id: str,
    body: TransitionIn,
    current_user: User = Depends(require_permission("profiles.manage")),
    db: Session = Depends(get_db),
):
    return ProfileOut.model_validate(
        ProfileService(db).transition(current_user.tenant_id, profile_id, body.toStatusId, current_user)
    )


# ── Send portal invite (sprint-4/06, AC-06-15c STAFF trigger) ─────────────────
# Gated personas.manage — issuing portal access (with an optional persona grant)
# is persona/portal administration, not profile editing.


@router.post("/{profile_id}/invite", response_model=ProfileInviteOut)
def send_portal_invite(
    profile_id: str,
    body: ProfileInviteIn,
    current_user: User = Depends(require_permission("personas.manage")),
    db: Session = Depends(get_db),
):
    tenant_id = current_user.tenant_id

    # Validate the optional persona grant up front (foolproof: only a real
    # persona + a real, tenant-owned project scope can ride the invite).
    scope_type = body.scopeType
    scope_id = body.scopeId
    if body.personaKey:
        if PersonaRepository(db).get_persona_by_key(tenant_id, body.personaKey) is None:
            raise HTTPException(422, "Unknown persona for this tenant.")
        scope_type = (scope_type or PERSONA_SCOPE_TENANT).strip()
        if scope_type not in (PERSONA_SCOPE_TENANT, PERSONA_SCOPE_PROJECT):
            raise HTTPException(422, f"Invalid scope type: {scope_type}")
        if scope_type == PERSONA_SCOPE_TENANT:
            scope_id = None
        elif not scope_id:
            raise HTTPException(422, "A project-scoped grant requires a scopeId.")
        else:
            # Save-time tenant-scope guard (polymorphic-target_id rule).
            PersonaService(db)._assert_project(tenant_id, scope_id)
    else:
        scope_type = None
        scope_id = None

    # Tenant-scoped resolution — a foreign-tenant / unknown id is a 404 here.
    profile = ProfileService(db).get(tenant_id, profile_id)
    if not (profile.email or "").strip():
        raise HTTPException(422, "This profile has no email — add one to send an invite.")

    try:
        PortalAuthService(db).issue_profile_invite(
            tenant_id,
            profile_id,
            grant_persona_key=body.personaKey,
            grant_scope_type=scope_type,
            grant_scope_id=scope_id,
        )
    except ProfileNotFound:
        raise HTTPException(404, "Profile not found.")
    return ProfileInviteOut(sent=True, email=profile.email)


# ── Profile persona memberships (sprint-4/06 0b STAFF path, AC-06-22/26) ──────
# Gated by personas.* — assigning a persona is persona management, not profile
# administration.


@router.get("/{profile_id}/personas", response_model=List[PersonaMembershipOut])
def list_profile_personas(
    profile_id: str,
    current_user: User = Depends(require_permission("personas.read")),
    db: Session = Depends(get_db),
):
    return [
        PersonaMembershipOut.model_validate(m)
        for m in PersonaService(db).list_profile_memberships(current_user.tenant_id, profile_id)
    ]


@router.post("/{profile_id}/personas", response_model=PersonaMembershipOut, status_code=201)
def assign_profile_persona(
    profile_id: str,
    body: PersonaMembershipIn,
    current_user: User = Depends(require_permission("personas.manage")),
    db: Session = Depends(get_db),
):
    return PersonaMembershipOut.model_validate(
        PersonaService(db).assign_membership(
            current_user.tenant_id, profile_id, body.model_dump()
        )
    )


@router.delete("/{profile_id}/personas/{membership_id}", status_code=204)
def revoke_profile_persona(
    profile_id: str,
    membership_id: str,
    current_user: User = Depends(require_permission("personas.manage")),
    db: Session = Depends(get_db),
):
    PersonaService(db).revoke_membership(current_user.tenant_id, profile_id, membership_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
