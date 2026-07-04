"""Soft references (sprint-3/10 D6) — cross-module data WITHOUT FKs.

A consumer stores a ``SoftRef{module, entity_type, id}`` (JSON column v1) instead
of an FK into another module's schema. Resolution goes through a provider
``<entity>.resolve`` capability — ``resolve_soft_ref`` → ``resolve_capability``
→ the provider's handler. NO ``app_ems → app_omnichannel`` query, ever. An orphan
(provider inactive/uninstalled) → ``None`` → UI "linked record unavailable".

Security generalizes the polymorphic-target_id rule (sprint-2/01 leak):
save-time validate (ref resolves + the target's tenant matches the author's →
422 else) + resolve-time tenant-scope (the handler scopes internally).
"""
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class SoftRef:
    module: str
    entity_type: str
    id: str

    def to_json(self) -> dict:
        return {"module": self.module, "entityType": self.entity_type, "id": self.id}

    @staticmethod
    def from_json(data: Optional[dict]) -> "Optional[SoftRef]":
        if not data:
            return None
        return SoftRef(
            module=data["module"], entity_type=data["entityType"], id=data["id"]
        )


def _resolve_key(ref: SoftRef) -> str:
    return f"{ref.entity_type}.resolve"


def resolve_soft_ref(
    db: Session, tenant_id: str, ref: Optional[SoftRef], version: int = 1
) -> Optional[Any]:
    """Resolve through the provider's ``<entity>.resolve`` capability, tenant-
    scoped. Returns ``None`` if the ref is absent or the provider is inactive/
    gone (orphan) — never a dangling FK, never a cross-schema query."""
    if ref is None:
        return None
    from app.module_platform.capabilities import resolve_capability

    handler = resolve_capability(db, tenant_id, _resolve_key(ref), version)
    if handler is None:
        return None
    return handler(db, tenant_id, {"id": ref.id})


def validate_soft_ref(
    db: Session, tenant_id: str, ref: Optional[SoftRef], version: int = 1
) -> bool:
    """Save-time gate: the ref must resolve to a record in the author's tenant.
    Returns True if valid (or absent); False otherwise (caller raises 422)."""
    if ref is None:
        return True
    return resolve_soft_ref(db, tenant_id, ref, version) is not None
