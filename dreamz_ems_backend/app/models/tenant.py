"""Tenant model — root of multi-tenancy (SaaS, plan 07).

A tenant is a workspace: users/roles/data are scoped to it via ``tenant_id``.
Lifecycle is a core ``statuses`` row (FK) — behavior binds to the status TRAIT
FLAGS (``blocks_access`` / ``is_archived``, sprint-2/01 D2); transitions move
along the status-engine edge graph only. Labels/colors stay editable.

The reserved **platform tenant** (``is_platform``) hosts the operator team;
platform endpoints require membership in it (``require_platform_permission``).
"""
import re
import uuid

from sqlalchemy import Boolean, Column, ForeignKey, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base

# Stable id/slug for the bootstrap tenant every row falls back to until tenant
# resolution is explicit everywhere. Keep in sync with scripts/init_db.py.
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_TENANT_SLUG = "default"
DEFAULT_TENANT_NAME = "Dreamz EMS"

# The reserved operator tenant (plan 07 §5) — seeded at bootstrap.
PLATFORM_TENANT_ID = "00000000-0000-0000-0000-000000000002"
PLATFORM_TENANT_SLUG = "platform"
PLATFORM_TENANT_NAME = "Dreamz Platform"

# Slugs that can never be tenant identities (infra/system hostnames). Mirrors
# the frontend list in lib/tenant.ts.
RESERVED_TENANT_SLUGS = frozenset(
    {
        "www",
        "api",
        "app",
        "admin",
        "platform",
        "default",
        "mail",
        "ftp",
        "assets",
        "static",
        "docs",
        "status",
        "support",
        "billing",
    }
)

# lowercase kebab, 3-63 chars, no leading/trailing/double hyphen.
_SLUG_RE = re.compile(r"^[a-z0-9](?:-?[a-z0-9]){2,62}$")


def is_valid_tenant_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug))


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    # URL identity (subdomain) — immutable after creation.
    slug = Column(String, unique=True, nullable=False, index=True)
    # Lifecycle — a status-engine row; behavior binds to its trait flags.
    status_id = Column(String, ForeignKey("statuses.id"), nullable=False, index=True)
    # Exactly one seeded row true — the operator tenant.
    is_platform = Column(Boolean, nullable=False, default=False)
    contact_name = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)
    # Schema-ready; CNAME/infra wiring is BL-034.
    custom_domain = Column(String, unique=True, nullable=True)
    notes = Column(String, nullable=True)

    created_at = Column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        UTCDateTime(),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # joined: the lifecycle check in get_current_user/login reads the category
    # on every request — load it with the tenant row, never lazily/N+1.
    status = relationship("Status", lazy="joined")

    @property
    def signin_allowed(self) -> bool:
        """Single chokepoint for the lifecycle rule (login + per-request).

        Behavior binds to the status TRAIT FLAGS (sprint-2/01 D2) — a status
        that blocks access or archives the tenant kills sign-in; a missing
        status row counts as not-allowed (defensive — FK should prevent it).
        """
        return (
            self.status is not None
            and not self.status.blocks_access
            and not self.status.is_archived
        )
