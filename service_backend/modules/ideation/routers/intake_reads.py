"""Intake read router (public, workspace-key authed) - read-only lookups the
integration/brain side needs to *configure* intake, kept separate from the intake
write path (``routers/intake.py``) so the two evolve independently.

**Public** because it is authenticated by a workspace/integration key, not a user
session - the tenant is derived from the key via ``get_api_workspace`` (same
mechanism as ``create-idea``). Read-only + simple.

``GET /ideation/intake/products`` lists the key's tenant's ELIGIBLE ideation
products (core ``public.products`` with ``kind == 'software'``, not deleted) so the
sorento admin can bind a workspace to a Product by name instead of pasting a UUID.

``GET /ideation/intake/status-events`` (issue #94, plan section 7.1) is the
requester status-update EVENT FEED the CRM pulls to send the "ideation status
update" WhatsApp template - see ``documentation/ideation/status-events-contract.md``.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.catalog import Product
from modules.omnichannel.api_auth import ApiWorkspace, get_api_workspace

from ..services.status_events import (
    DEFAULT_FEED_LIMIT,
    MAX_FEED_LIMIT,
    list_feed_events,
)

router = APIRouter()


@router.get("/products")
def list_intake_products(
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> list[dict]:
    """List the tenant's eligible ideation products (``kind == 'software'``).

    Returns ``[{id, name, kind}]`` ordered by name. Tenant is derived from the
    workspace key - never from the request - so a key can only ever see its own
    tenant's catalog."""
    rows = (
        db.query(Product)
        .filter(
            Product.tenant_id == api_ws.tenant_id,
            Product.kind == "software",
            Product.is_deleted.is_(False),
        )
        .order_by(Product.name.asc())
        .all()
    )
    return [{"id": r.id, "name": r.name, "kind": r.kind} for r in rows]


@router.get("/status-events")
def list_status_events(
    after: int = Query(0),
    limit: int = Query(DEFAULT_FEED_LIMIT, le=MAX_FEED_LIMIT),
    include_test: bool = Query(False, alias="includeTest"),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> dict:
    """AC-94-66: tenant T's requester status-update events with
    ``seq > after``, ascending, at most ``limit`` (default 100, max 200).
    ``includeTest`` opts into console/``--say`` test-idea events, off by
    default (AC-94-67). Tenant is derived from the workspace key - never
    from the request - so a key can only ever see its own tenant's events."""
    return list_feed_events(
        db, api_ws.tenant_id, after=after, limit=limit, include_test=include_test
    )
