"""Persona RBAC business logic (sprint-4/06 slice 0b).

Owns: persona CRUD (system rows delete-locked, key locked on system),
portal-key grants, scoped persona memberships, and the shared ``grant_persona``
helper that the three acquisition paths (AUTO / STAFF / INVITE, AC-06-22) all
funnel through. Tenant-scoped everywhere (AC-06-57).

Raises HTTPException for the router (the persona-management API is staff-authed
and benefits from direct HTTP semantics, like the other EMS services).
"""
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modules.ems.models import (
    PERSONA_GRANT_STAFF,
    PERSONA_SCOPE_PROJECT,
    PERSONA_SCOPE_TENANT,
    Persona,
    PersonaMembership,
    Profile,
)
from modules.ems.persona_repository import PersonaRepository
from modules.ems.portal_rbac import is_portal_permission

_VALID_SCOPE_TYPES = {PERSONA_SCOPE_TENANT, PERSONA_SCOPE_PROJECT}


class PersonaService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = PersonaRepository(db)

    # ── persona CRUD (AC-06-19, 26) ──────────────────────────────────────────

    def list(self, tenant_id: str) -> List[Persona]:
        return self.repo.list_personas(tenant_id)

    def get(self, tenant_id: str, persona_id: str) -> Persona:
        persona = self.repo.get_persona(tenant_id, persona_id)
        if persona is None:
            raise HTTPException(404, "Persona not found.")
        return persona

    def create(self, tenant_id: str, data: dict) -> Persona:
        key = (data.get("key") or "").strip()
        if not key:
            raise HTTPException(422, "Persona key is required.")
        if self.repo.get_persona_by_key(tenant_id, key) is not None:
            raise HTTPException(409, "A persona with this key already exists.")
        persona = Persona(
            tenant_id=tenant_id,
            key=key,
            label=(data.get("label") or key).strip(),
            description=data.get("description"),
            is_system=False,  # tenant-created personas are never system
            sort_order=data.get("sortOrder") or 0,
        )
        return self.repo.add(persona)

    def update(self, tenant_id: str, persona_id: str, data: dict) -> Persona:
        persona = self.get(tenant_id, persona_id)
        # Key is LOCKED on system personas (AC-06-19 — keys editable on custom).
        if "key" in data and data["key"] is not None:
            new_key = data["key"].strip()
            if persona.is_system and new_key != persona.key:
                raise HTTPException(422, "A system persona's key cannot be changed.")
            if new_key != persona.key:
                if self.repo.get_persona_by_key(tenant_id, new_key) is not None:
                    raise HTTPException(409, "A persona with this key already exists.")
                persona.key = new_key
        if "label" in data and data["label"] is not None:
            persona.label = data["label"].strip()
        if "description" in data:
            persona.description = data["description"]
        if "sortOrder" in data and data["sortOrder"] is not None:
            persona.sort_order = data["sortOrder"]
        return self.repo.add(persona)

    def delete(self, tenant_id: str, persona_id: str) -> None:
        persona = self.get(tenant_id, persona_id)
        if persona.is_system:
            raise HTTPException(409, "A system persona cannot be deleted.")
        self.repo.delete_persona(persona)

    # ── portal-key grants (AC-06-21, 26) ─────────────────────────────────────

    def get_permissions(self, tenant_id: str, persona_id: str) -> List[str]:
        self.get(tenant_id, persona_id)  # scope guard
        return [p.permission_key for p in self.repo.list_permissions(tenant_id, persona_id)]

    def set_permissions(self, tenant_id: str, persona_id: str, keys: List[str]) -> List[str]:
        self.get(tenant_id, persona_id)  # scope guard
        # Foolproof: only grant keys that exist in the portal catalog (AC-06-21).
        unknown = [k for k in keys if not is_portal_permission(k)]
        if unknown:
            raise HTTPException(422, f"Unknown portal permission keys: {', '.join(unknown)}")
        self.repo.set_permissions(tenant_id, persona_id, keys)
        return self.get_permissions(tenant_id, persona_id)

    # ── memberships (AC-06-20, 22) ───────────────────────────────────────────

    def list_profile_memberships(
        self, tenant_id: str, profile_id: str
    ) -> List[PersonaMembership]:
        self._assert_profile(tenant_id, profile_id)
        return self.repo.list_memberships_for_profile(tenant_id, profile_id)

    def assign_membership(
        self,
        tenant_id: str,
        profile_id: str,
        data: dict,
    ) -> PersonaMembership:
        """STAFF acquisition path (AC-06-22). Resolve the persona by id, validate
        the scope, idempotent-grant."""
        self._assert_profile(tenant_id, profile_id)
        persona = self.get(tenant_id, data["personaId"])  # tenant-scoped 404
        scope_type = (data.get("scopeType") or PERSONA_SCOPE_TENANT).strip()
        if scope_type not in _VALID_SCOPE_TYPES:
            raise HTTPException(422, f"Invalid scope type: {scope_type}")
        scope_id = data.get("scopeId")
        if scope_type == PERSONA_SCOPE_TENANT:
            scope_id = None  # tenant-wide membership has no scope id
        elif not scope_id:
            raise HTTPException(422, "A project-scoped membership requires a scopeId.")
        else:
            # Polymorphic-target_id rule (BL-030 / plan sprint-2/01): validate the
            # project scope belongs to THIS tenant at SAVE — not just scope-at-use —
            # so a client can't plant a foreign project id on a membership.
            self._assert_project(tenant_id, scope_id)
        return self._grant(
            tenant_id,
            profile_id,
            persona,
            scope_type,
            scope_id,
            via=PERSONA_GRANT_STAFF,
        )

    def revoke_membership(self, tenant_id: str, profile_id: str, membership_id: str) -> None:
        self._assert_profile(tenant_id, profile_id)
        membership = self.repo.get_membership(tenant_id, membership_id)
        if membership is None or membership.profile_id != profile_id:
            raise HTTPException(404, "Membership not found.")
        self.repo.delete_membership(membership)

    def _grant(
        self,
        tenant_id: str,
        profile_id: str,
        persona: Persona,
        scope_type: str,
        scope_id: Optional[str],
        *,
        via: str,
        commit: bool = True,
    ) -> PersonaMembership:
        existing = self.repo.find_membership(
            tenant_id, profile_id, persona.id, scope_type, scope_id
        )
        if existing is not None:
            return existing  # idempotent vs the UNIQUE
        membership = PersonaMembership(
            tenant_id=tenant_id,
            profile_id=profile_id,
            persona_id=persona.id,
            scope_type=scope_type,
            scope_id=scope_id,
            granted_via=via,
        )
        try:
            return self.repo.add(membership, commit=commit)
        except IntegrityError:
            # Concurrent grant race — UNIQUE backstop; re-resolve the row.
            self.db.rollback()
            return self.repo.find_membership(
                tenant_id, profile_id, persona.id, scope_type, scope_id
            )

    def _assert_profile(self, tenant_id: str, profile_id: str) -> Profile:
        prof = (
            self.db.query(Profile)
            .filter(
                Profile.id == profile_id,
                Profile.tenant_id == tenant_id,
                Profile.is_deleted.is_(False),
            )
            .first()
        )
        if prof is None:
            raise HTTPException(404, "Profile not found.")
        return prof

    def _assert_project(self, tenant_id: str, project_id: str) -> None:
        """Validate a project-scope id belongs to this tenant (save-time guard)."""
        from modules.ems.models import Project

        exists = (
            self.db.query(Project.id)
            .filter(
                Project.id == project_id,
                Project.tenant_id == tenant_id,
                Project.is_deleted.is_(False),
            )
            .first()
        )
        if exists is None:
            raise HTTPException(422, "Unknown project for this tenant.")


def grant_persona(
    db: Session,
    tenant_id: str,
    profile_id: str,
    persona_key: str,
    scope_type: str,
    scope_id: Optional[str],
    via: str,
    *,
    commit: bool = True,
) -> Optional[PersonaMembership]:
    """Idempotent persona grant by KEY — the shared helper the three acquisition
    paths funnel through (AC-06-22). Resolves the persona by (tenant, key); a
    missing persona (e.g. a tenant that never seeded it) is a no-op None rather
    than a raise so the AUTO/INVITE paths stay failure-isolated. Tenant-scoped."""
    repo = PersonaRepository(db)
    persona = repo.get_persona_by_key(tenant_id, persona_key)
    if persona is None:
        return None
    if scope_type == PERSONA_SCOPE_TENANT:
        scope_id = None
    return PersonaService(db)._grant(
        tenant_id, profile_id, persona, scope_type, scope_id, via=via, commit=commit
    )
