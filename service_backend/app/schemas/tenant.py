"""Tenant admin schemas (plan 07 §9) — the Platform Console contracts.

Exposes camelCase to the frontend. ``status`` on the wire is the lifecycle
CATEGORY (ACTIVE / SUSPENDED / ARCHIVED) — labels/colors stay a display concern.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import EmailStr, Field, field_validator

from app.schemas.base import ApiModel

from app.schemas.filters import FilterGroup
from app.schemas.password import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    validate_password_strength,
)


class TenantItem(ApiModel):
    id: str
    name: str
    slug: str
    status: str
    # Engine-driven display (sprint-2/01) — render these, not a hardcoded
    # registry, so renamed/custom statuses show correctly. statusId lets the
    # console derive the row's available transitions from the edge graph.
    statusId: Optional[str] = None
    statusLabel: Optional[str] = None
    statusColor: Optional[str] = None
    # Per-record fireable edges (sprint-2/02) — populated ONLY while a
    # conditioned tenant edge exists (rule-engine D6: failing edges hidden).
    # None = no conditions anywhere; the client derives buttons from statusId.
    availableTransitionIds: Optional[List[str]] = None
    isPlatform: bool
    contactName: Optional[str] = None
    contactEmail: Optional[str] = None
    customDomain: Optional[str] = None
    userCount: int
    createdAt: datetime


class TenantDetail(TenantItem):
    notes: Optional[str] = None
    updatedAt: datetime


class TenantListResponse(ApiModel):
    data: List[TenantItem]
    total: int
    page: int


class TenantNeighborResponse(ApiModel):
    tenant: Optional[TenantDetail] = None
    total: int


class TenantProvisionRequest(ApiModel):
    """Tenant + its first admin user, provisioned in one transaction (plan 07 §7)."""

    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=3, max_length=63)
    contactName: Optional[str] = Field(default=None, max_length=120)
    contactEmail: Optional[EmailStr] = None
    notes: Optional[str] = Field(default=None, max_length=2000)
    adminName: str = Field(min_length=1, max_length=120)
    adminEmail: EmailStr
    # Same server-side policy as signup/set-password (plan 10 review) — the
    # operator-set temp password is live immediately, no redeem step weakens it.
    # Cap at 72 — bcrypt hashes only the first 72 bytes and raises on longer.
    adminPassword: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    _password_policy = field_validator("adminPassword")(validate_password_strength)


class TenantUpdate(ApiModel):
    """Slug is immutable; lifecycle moves via the explicit action endpoints."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    contactName: Optional[str] = Field(default=None, max_length=120)
    contactEmail: Optional[EmailStr] = None
    customDomain: Optional[str] = Field(default=None, max_length=253)
    notes: Optional[str] = Field(default=None, max_length=2000)


class TenantTransitionItem(ApiModel):
    """An outgoing graph edge the actor may fire — label = button text."""

    id: str
    label: str
    toStatusId: str
    toStatusLabel: str
    toStatusColor: str


class TenantTransitionListResponse(ApiModel):
    data: List[TenantTransitionItem]


class TenantTransitionRequest(ApiModel):
    transitionId: str


class TenantPurgeRequest(ApiModel):
    """Typed confirmation (module-uninstall UX) — must equal the tenant slug."""

    confirmSlug: str


class TenantExportRequest(ApiModel):
    columns: List[str]
    ids: Optional[List[str]] = None
    statusView: Optional[str] = None
    search: Optional[str] = None
    sortBy: Optional[str] = None
    sortDir: Optional[str] = None
    filter: Optional[FilterGroup] = None
