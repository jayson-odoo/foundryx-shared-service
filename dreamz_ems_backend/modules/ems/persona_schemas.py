"""Persona RBAC wire schemas (sprint-4/06 slice 0b) — camelCase via ApiModel."""
from datetime import datetime
from typing import List, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import ApiModel


class _Base(ApiModel):
    model_config = ConfigDict(from_attributes=True)


class PersonaOut(_Base):
    id: str
    key: str
    label: str
    description: Optional[str] = None
    isSystem: bool = Field(validation_alias="is_system")
    sortOrder: int = Field(validation_alias="sort_order")
    createdAt: datetime = Field(validation_alias="created_at")


class PersonaIn(ApiModel):
    key: str
    label: Optional[str] = None
    description: Optional[str] = None
    sortOrder: Optional[int] = None


class PersonaPatch(ApiModel):
    key: Optional[str] = None
    label: Optional[str] = None
    description: Optional[str] = None
    sortOrder: Optional[int] = None


class PortalPermissionOut(ApiModel):
    key: str
    label: str
    description: str = ""


class PersonaPermissionsIn(ApiModel):
    keys: List[str] = []


class PersonaPermissionsOut(ApiModel):
    keys: List[str] = []


class PersonaMembershipOut(_Base):
    id: str
    profileId: str = Field(validation_alias="profile_id")
    personaId: str = Field(validation_alias="persona_id")
    scopeType: str = Field(validation_alias="scope_type")
    scopeId: Optional[str] = Field(default=None, validation_alias="scope_id")
    grantedVia: str = Field(validation_alias="granted_via")
    createdAt: datetime = Field(validation_alias="created_at")


class PersonaMembershipIn(ApiModel):
    personaId: str
    scopeType: Optional[str] = None  # 'tenant' (default) | 'project'
    scopeId: Optional[str] = None  # required for project scope


class ProfileInviteIn(ApiModel):
    """Staff "Send portal invite" payload (AC-06-15c). All optional — a plain
    invite carries no grant; a persona+context grants it on acceptance
    (granted_via=INVITE, AC-06-22 INVITE path)."""
    personaKey: Optional[str] = None
    scopeType: Optional[str] = None  # 'tenant' (default) | 'project'
    scopeId: Optional[str] = None  # required for project scope


class ProfileInviteOut(ApiModel):
    """Generic success — the raw token is never leaked in the response body."""
    sent: bool = True
    email: str


class PortalSurfaceContextOut(ApiModel):
    scopeType: str
    scopeId: Optional[str] = None
    # A human label for the context (AC-06-25) — the event/project name for a
    # project scope so the filter pill reads the real name (not "Event {id}").
    # None for tenant-wide / an unresolvable id (the FE falls back to a generic
    # label).
    label: Optional[str] = None


class PortalSurfaceOut(ApiModel):
    key: str
    label: str
    gatingPermission: str
    module: str
    sortOrder: int
    description: Optional[str] = None
    # The profile's scoped contexts for this surface (memberships whose persona
    # grants the surface's gating key) — the dashboard scopes data to these.
    contexts: List[PortalSurfaceContextOut] = []
