"""Tenant branding (plan sprint-2/03) — one row per tenant, 1:1.

Image assets (storage keys + mimes), slogan, and curated theme-token overrides
over the FoundryX defaults. No row = stock branding. ``version`` bumps on every
mutation and cache-busts the public theme-CSS / asset URLs.
"""
from sqlalchemy import JSON, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base


class TenantBranding(Base):
    __tablename__ = "tenant_branding"

    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    slogan = Column(String, nullable=True)
    # Tenant-chosen product/system name ("Welcome to {app_name}"); NULL = fall
    # back to the tenant name (never the FoundryX product name — white-label).
    app_name = Column(String, nullable=True)

    # Storage keys (core StorageService.save) + mimes for serving. NEVER raw
    # URLs — the public asset route resolves them per backend (local/S3).
    logo_key = Column(String, nullable=True)
    logo_mime = Column(String, nullable=True)
    favicon_key = Column(String, nullable=True)
    favicon_mime = Column(String, nullable=True)
    illustration_key = Column(String, nullable=True)
    illustration_mime = Column(String, nullable=True)

    # {"light": {...}, "dark": {...}} — whitelisted keys only, stored as a true
    # diff vs the FoundryX defaults. none_as_null: Python None must store SQL
    # NULL, not JSON null (rule-engine lesson, sprint-2/02).
    tokens_json = Column(JSON(none_as_null=True), nullable=True)

    # Social profile URLs (plan 07 D4) — {"facebook": url, "instagram": …};
    # consumed by the template engine's Social Links / Brand Footer blocks.
    socials_json = Column(JSON(none_as_null=True), nullable=True)
    # Email footer fields — {"companyName": …, "addressLine": …, "tagline": …}.
    footer_json = Column(JSON(none_as_null=True), nullable=True)

    # Bumped per mutation — busts the long-cached public CSS/asset URLs.
    version = Column(Integer, nullable=False, default=0)

    created_at = Column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        UTCDateTime(),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    tenant = relationship("Tenant", lazy="joined")
