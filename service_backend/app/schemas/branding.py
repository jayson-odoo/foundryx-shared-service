"""Tenant branding schemas (plan sprint-2/03) — camelCase wire contracts.

``tokens`` is the curated theme document {"light": {...}, "dark": {...}} —
whitelisted keys only, validated in the SERVICE (named 422 errors), not here:
the whitelist is data, not schema shape.
"""
from typing import Dict, Optional

from pydantic import BaseModel, Field

TokensDoc = Dict[str, Dict[str, str]]


SocialsDoc = Dict[str, Optional[str]]
FooterDoc = Dict[str, Optional[str]]


class BrandingResponse(BaseModel):
    """A tenant's branding record (admin surfaces). No row = zeroed defaults."""

    slogan: Optional[str] = None
    appName: Optional[str] = None
    logoUrl: Optional[str] = None
    faviconUrl: Optional[str] = None
    illustrationUrl: Optional[str] = None
    tokens: Optional[TokensDoc] = None
    # Social URLs + email footer (plan 07 D4) — template-engine brand blocks.
    socials: Optional[SocialsDoc] = None
    footer: Optional[FooterDoc] = None
    version: int = 0


class BrandingUpdateRequest(BaseModel):
    slogan: Optional[str] = Field(default=None, max_length=120)
    # Tenant product/system name — "Welcome to {appName}" on sign-in.
    appName: Optional[str] = Field(default=None, max_length=60)
    tokens: Optional[TokensDoc] = None
    socials: Optional[SocialsDoc] = None
    footer: Optional[FooterDoc] = None


class PublicBrandingResponse(BaseModel):
    """Pre-auth branding for a host slug. Unknown slug = uniform defaults
    (``isBranded`` false) — tenant existence is never enumerable here."""

    isBranded: bool = False
    tenantName: Optional[str] = None
    appName: Optional[str] = None
    slogan: Optional[str] = None
    logoUrl: Optional[str] = None
    faviconUrl: Optional[str] = None
    illustrationUrl: Optional[str] = None
    tokens: Optional[TokensDoc] = None
    version: int = 0
