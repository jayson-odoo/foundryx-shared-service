"""App Store models (plan 08) — global module catalog + per-tenant install state.

``modules`` is the global catalog, synced from on-disk ``manifest.json`` files at
bootstrap (same pattern as the permission CSV sync). ``tenant_modules`` is the
per-tenant lifecycle row: INSTALL → ACTIVE; DEACTIVATE → INACTIVE (data kept);
UNINSTALL → row deleted after the tenant's module data is wiped.

Code is global — ``modules.version`` is what's deployed; ``installed_version``
is what the tenant's DATA is provisioned at and gates features (D3/D4: version
gating, never per-tenant code).
"""
import uuid
from typing import Tuple

from sqlalchemy import Boolean, Column, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base

# Per-tenant install statuses — code branches only on these.
MODULE_STATUS_ACTIVE = "ACTIVE"
MODULE_STATUS_INACTIVE = "INACTIVE"


def parse_version(version: str) -> Tuple[int, ...]:
    """'1.2.3' → (1, 2, 3) for ordering. Non-numeric parts compare as 0."""
    parts = []
    for chunk in version.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


class Module(Base):
    __tablename__ = "modules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # manifest `module_name` — the API identity.
    name = Column(String, nullable=False, unique=True, index=True)
    # Current CODE version (manifest) — global for every tenant.
    version = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    icon = Column(String, nullable=True)
    # Removed-from-disk modules are delisted (not deleted) to preserve FK history.
    is_listed = Column(Boolean, nullable=False, default=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TenantModule(Base):
    __tablename__ = "tenant_modules"
    __table_args__ = (UniqueConstraint("tenant_id", "module_id", name="uq_tenant_module"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    module_id = Column(String, ForeignKey("modules.id"), nullable=False)
    status = Column(String, nullable=False, default=MODULE_STATUS_ACTIVE)
    # What this tenant is provisioned at — gates features (D4).
    installed_version = Column(String, nullable=False)

    installed_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    module = relationship("Module", lazy="joined")
