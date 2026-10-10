"""Shared router plumbing for the public connector endpoints (HTTP only)."""

from __future__ import annotations
from fastapi import Depends, HTTPException, Request

from app.api_errors import ApiError
from app.services.throttle import client_ip
from sqlalchemy.orm import Session

from app.database import get_db
from app.repositories.tenant_repository import TenantRepository

from .. import registry
from ..services.client_access import client_allowed
from ..services.oauth_service import OAuthService, ProductContext, ProductNotFound, resolve_context


def product_context(p: str, db: Session = Depends(get_db)) -> ProductContext:
    """Uniform 404 for unknown/misconfigured/inactive - says nothing about why."""
    try:
        return resolve_context(db, p)
    except ProductNotFound:
        raise HTTPException(status_code=404, detail="Not found") from None


def oauth_service(ctx: ProductContext = Depends(product_context),
                  db: Session = Depends(get_db)) -> OAuthService:
    return OAuthService(db, ctx, registry.tenant_config(db, ctx.tenant_id).public_base_url)


def require_method(request: Request, *allowed: str) -> None:
    if request.method not in allowed:
        raise HTTPException(status_code=405, detail="Method not allowed",
                            headers={"Allow": ", ".join(allowed)})


def require_allowed_client(request: Request, p: str, db: Session = Depends(get_db)) -> None:
    """Runs BEFORE auth on the Claude-facing endpoints: uniform 403, no detail.
    The list is the owning tenant's setting (else the environment); an unknown
    product uses the environment list, so it answers the same as before."""
    st = registry.resolve_product(db, p)
    owner = st and (st.product or st.partial)
    tenant_id = owner.tenant_id if owner else ""
    if owner and not tenant_id:
        tenant = TenantRepository(db).get_by_slug(owner.tenant_slug)
        tenant_id = tenant.id if tenant else ""
    raw = registry.tenant_config(db, tenant_id or None).allowed_client_cidrs or ""
    if not client_allowed(client_ip(request), raw):
        raise ApiError(403, "forbidden", "Forbidden")
