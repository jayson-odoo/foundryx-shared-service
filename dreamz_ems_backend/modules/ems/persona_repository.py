"""Persona RBAC repository (sprint-4/06 slice 0b) — pure SQLAlchemy.

Every query is tenant-scoped (the tenant comes from the authenticated context,
never client input — AC-06-57). Backs ``PersonaService`` (business rules) and
``effective_portal_keys`` (the portal RBAC gate).
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from modules.ems.models import (
    Persona,
    PersonaMembership,
    PersonaPermission,
)


class PersonaRepository:
    def __init__(self, db: Session):
        self.db = db

    # ── personas ─────────────────────────────────────────────────────────────

    def list_personas(self, tenant_id: str) -> List[Persona]:
        return (
            self.db.query(Persona)
            .filter(Persona.tenant_id == tenant_id)
            .order_by(Persona.sort_order, Persona.key)
            .all()
        )

    def get_persona(self, tenant_id: str, persona_id: str) -> Optional[Persona]:
        return (
            self.db.query(Persona)
            .filter(Persona.id == persona_id, Persona.tenant_id == tenant_id)
            .first()
        )

    def get_persona_by_key(self, tenant_id: str, key: str) -> Optional[Persona]:
        return (
            self.db.query(Persona)
            .filter(Persona.tenant_id == tenant_id, Persona.key == key)
            .first()
        )

    def add(self, row, *, commit: bool = True):
        self.db.add(row)
        if commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def delete_persona(self, persona: Persona, *, commit: bool = True) -> None:
        # Drop grants + memberships first (no DB cascade on cross-schema cols).
        self.db.query(PersonaPermission).filter(
            PersonaPermission.persona_id == persona.id
        ).delete(synchronize_session=False)
        self.db.query(PersonaMembership).filter(
            PersonaMembership.persona_id == persona.id
        ).delete(synchronize_session=False)
        self.db.delete(persona)
        if commit:
            self.db.commit()
        else:
            self.db.flush()

    # ── persona permissions (grants) ─────────────────────────────────────────

    def list_permissions(self, tenant_id: str, persona_id: str) -> List[PersonaPermission]:
        return (
            self.db.query(PersonaPermission)
            .filter(
                PersonaPermission.tenant_id == tenant_id,
                PersonaPermission.persona_id == persona_id,
            )
            .all()
        )

    def set_permissions(
        self, tenant_id: str, persona_id: str, keys: List[str], *, commit: bool = True
    ) -> None:
        """Replace the persona's granted portal keys with ``keys`` (deduped)."""
        self.db.query(PersonaPermission).filter(
            PersonaPermission.tenant_id == tenant_id,
            PersonaPermission.persona_id == persona_id,
        ).delete(synchronize_session=False)
        for key in dict.fromkeys(keys):  # preserve order, dedupe
            self.db.add(
                PersonaPermission(
                    tenant_id=tenant_id, persona_id=persona_id, permission_key=key
                )
            )
        if commit:
            self.db.commit()
        else:
            self.db.flush()

    # ── memberships ──────────────────────────────────────────────────────────

    def list_memberships_for_profile(
        self, tenant_id: str, profile_id: str
    ) -> List[PersonaMembership]:
        return (
            self.db.query(PersonaMembership)
            .filter(
                PersonaMembership.tenant_id == tenant_id,
                PersonaMembership.profile_id == profile_id,
            )
            .all()
        )

    def get_membership(self, tenant_id: str, membership_id: str) -> Optional[PersonaMembership]:
        return (
            self.db.query(PersonaMembership)
            .filter(
                PersonaMembership.id == membership_id,
                PersonaMembership.tenant_id == tenant_id,
            )
            .first()
        )

    def find_membership(
        self,
        tenant_id: str,
        profile_id: str,
        persona_id: str,
        scope_type: str,
        scope_id: Optional[str],
    ) -> Optional[PersonaMembership]:
        return (
            self.db.query(PersonaMembership)
            .filter(
                PersonaMembership.tenant_id == tenant_id,
                PersonaMembership.profile_id == profile_id,
                PersonaMembership.persona_id == persona_id,
                PersonaMembership.scope_type == scope_type,
                PersonaMembership.scope_id.is_(None)
                if scope_id is None
                else PersonaMembership.scope_id == scope_id,
            )
            .first()
        )

    def delete_membership(self, membership: PersonaMembership, *, commit: bool = True) -> None:
        self.db.delete(membership)
        if commit:
            self.db.commit()
        else:
            self.db.flush()

    # ── effective portal keys (the RBAC gate read) ───────────────────────────

    def effective_permission_keys(self, tenant_id: str, profile_id: str) -> List[str]:
        """Union of ``persona_permissions.permission_key`` over every persona the
        profile is a member of (tenant-scoped — a membership / persona in another
        tenant never leaks). ONE joined query."""
        rows = (
            self.db.query(PersonaPermission.permission_key)
            .join(
                PersonaMembership,
                PersonaMembership.persona_id == PersonaPermission.persona_id,
            )
            .filter(
                PersonaMembership.tenant_id == tenant_id,
                PersonaMembership.profile_id == profile_id,
                PersonaPermission.tenant_id == tenant_id,
            )
            .distinct()
            .all()
        )
        return [r[0] for r in rows]
