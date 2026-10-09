"""Shared router plumbing for the public connector endpoints (HTTP only)."""

from __future__ import annotations
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db

from ..services.oauth_service import OAuthService, ProductContext, ProductNotFound, resolve_context


def product_context(p: str, db: Session = Depends(get_db)) -> ProductContext:
    """Uniform 404 for unknown/misconfigured/inactive - says nothing about why."""
    try:
        return resolve_context(db, p)
    except ProductNotFound:
        raise HTTPException(status_code=404, detail="Not found") from None


def oauth_service(ctx: ProductContext = Depends(product_context),
                  db: Session = Depends(get_db)) -> OAuthService:
    return OAuthService(db, ctx, settings.public_base_url)


def require_method(request: Request, *allowed: str) -> None:
    if request.method not in allowed:
        raise HTTPException(status_code=405, detail="Method not allowed",
                            headers={"Allow": ", ".join(allowed)})
