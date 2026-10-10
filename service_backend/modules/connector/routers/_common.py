"""Shared router plumbing for the public connector endpoints (HTTP only)."""

from __future__ import annotations
from typing import Optional

from fastapi import Depends, HTTPException, Request

from app.api_errors import ApiError
from app.services.throttle import client_ip
from sqlalchemy.orm import Session

from app.database import get_db

from .. import registry
from ..services.client_access import client_allowed
from ..services.oauth_service import OAuthService, ProductContext, ProductNotFound, resolve_context


def maybe_context(p: str, db: Session = Depends(get_db)) -> Optional[ProductContext]:
    """Resolved ONCE per request (FastAPI caches the dependency): the allow-list
    and the endpoint share it. None = unknown/misconfigured/inactive."""
    try:
        return resolve_context(db, p)
    except ProductNotFound:
        return None


def product_context(ctx: Optional[ProductContext] = Depends(maybe_context)) -> ProductContext:
    """Uniform 404 for unknown/misconfigured/inactive - says nothing about why."""
    if ctx is None:
        raise HTTPException(status_code=404, detail="Not found")
    return ctx


def oauth_service(ctx: ProductContext = Depends(product_context),
                  db: Session = Depends(get_db)) -> OAuthService:
    return OAuthService(db, ctx)


def require_method(request: Request, *allowed: str) -> None:
    if request.method not in allowed:
        raise HTTPException(status_code=405, detail="Method not allowed",
                            headers={"Allow": ", ".join(allowed)})


def require_allowed_client(request: Request,
                           ctx: Optional[ProductContext] = Depends(maybe_context),
                           db: Session = Depends(get_db)) -> None:
    """Runs BEFORE auth on the Claude-facing endpoints: uniform 403, no detail.
    The list is the owning tenant's setting (else the environment); an unknown
    product uses the environment list, so it answers the same as before."""
    # unknown and unusable products get the environment list: no key probing
    raw = registry.tenant_config(db, ctx.tenant_id if ctx else None).allowed_client_cidrs or ""
    if not client_allowed(client_ip(request), raw):
        raise ApiError(403, "forbidden", "Forbidden")
