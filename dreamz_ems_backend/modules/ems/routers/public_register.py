"""Public (anonymous) registration portal (sprint-4/05, Cluster D) — READ-ONLY
slice-1 surface. Tenant slug rides in the PATH (the browser hits the API origin
directly, so the subdomain can't survive on Host — same precedent as public
forms). Unknown tenant / missing event = uniform 404 (no enumeration).

Slice-2 adds: window/published gating, cart + seat-map + checkout, per-IP
throttle + honeypot. This endpoint is perm-free (router spec ``public: true``)."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from modules.ems.schemas import (
    CheckoutConfirmIn,
    CheckoutGaIn,
    CheckoutSeatIn,
    PublicEventOut,
    PublicOfferingOut,
)
from modules.ems.services import CartService, OfferingService, resolve_public_event as _resolve

router = APIRouter()


@router.get("/{tenant_slug}/{project_id}", response_model=PublicEventOut)
def public_event(tenant_slug: str, project_id: str, db: Session = Depends(get_db)):
    tenant, project = _resolve(db, tenant_slug, project_id)
    offerings = OfferingService(db).list(tenant.id, project_id)
    out = [
        PublicOfferingOut(
            id=o.id,
            productName=o.productName,
            price=o.price,
            currency=o.currency,
            allocationMode=o.allocation_mode,
            remaining=max((o.unitCount or o.capacity) - o.soldCount, 0),
        )
        for o in offerings
    ]
    return PublicEventOut(
        projectId=project.id, title=project.title, tenantName=tenant.name, offerings=out
    )


# ── interactive checkout (anonymous; cart token in path) ─────────────────────


@router.get("/{tenant_slug}/{project_id}/checkout")
def public_checkout(tenant_slug: str, project_id: str, db: Session = Depends(get_db)):
    tenant, project = _resolve(db, tenant_slug, project_id)
    return CartService(db).checkout(tenant.id, project.id)


@router.post("/{tenant_slug}/{project_id}/cart")
def public_create_cart(tenant_slug: str, project_id: str, db: Session = Depends(get_db)):
    tenant, project = _resolve(db, tenant_slug, project_id)
    cart = CartService(db).create_cart(tenant.id, project.id)
    return {"cartId": cart.id}


@router.get("/{tenant_slug}/{project_id}/seatmap/{offering_id}")
def public_seatmap(
    tenant_slug: str,
    project_id: str,
    offering_id: str,
    cart: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    tenant, project = _resolve(db, tenant_slug, project_id)
    return CartService(db).seatmap(tenant.id, project.id, offering_id, cart)


@router.get("/{tenant_slug}/{project_id}/cart/{cart_id}")
def public_get_cart(tenant_slug: str, project_id: str, cart_id: str, db: Session = Depends(get_db)):
    tenant, _ = _resolve(db, tenant_slug, project_id)
    return CartService(db).get_cart(tenant.id, cart_id)


@router.post("/{tenant_slug}/{project_id}/cart/{cart_id}/seat")
def public_hold_seat(
    tenant_slug: str, project_id: str, cart_id: str, body: CheckoutSeatIn, db: Session = Depends(get_db)
):
    tenant, _ = _resolve(db, tenant_slug, project_id)
    return CartService(db).hold_seat(tenant.id, cart_id, body.offeringId, body.seatId)


@router.post("/{tenant_slug}/{project_id}/cart/{cart_id}/ga")
def public_set_ga(
    tenant_slug: str, project_id: str, cart_id: str, body: CheckoutGaIn, db: Session = Depends(get_db)
):
    tenant, _ = _resolve(db, tenant_slug, project_id)
    return CartService(db).set_ga(tenant.id, cart_id, body.offeringId, body.qty)


@router.post("/{tenant_slug}/{project_id}/cart/{cart_id}/confirm")
def public_confirm(
    tenant_slug: str, project_id: str, cart_id: str, body: CheckoutConfirmIn, db: Session = Depends(get_db)
):
    tenant, _ = _resolve(db, tenant_slug, project_id)
    attendees = [a.model_dump() for a in body.attendees]
    return CartService(db).confirm(tenant.id, cart_id, attendees)
