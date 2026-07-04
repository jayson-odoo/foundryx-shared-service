"""EMS venue master routes (sprint-4/05, Cluster D) — tenant-level venues +
zones + a functional seat map. Gated venues.read / venues.manage; the loader
wraps the router in require_module('ems')."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from modules.ems.schemas import (
    ListResponse,
    SeatGenerateIn,
    VenueIn,
    VenueOut,
    VenuePatch,
    VenueSeatOut,
    VenueZoneIn,
    VenueZoneOut,
    VenueZonePatch,
)
from modules.ems.services import VenueService

router = APIRouter()


@router.get("", response_model=ListResponse)
def list_venues(
    search: Optional[str] = Query(None),
    trashed: bool = Query(False),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    sort_by: Optional[str] = Query(None),
    sort_dir: str = Query("desc"),
    current_user: User = Depends(require_permission("venues.read")),
    db: Session = Depends(get_db),
):
    rows, total = VenueService(db).list(
        current_user.tenant_id, search=search, page=page, page_size=page_size,
        trashed=trashed, sort_by=sort_by, sort_dir=sort_dir,
    )
    return ListResponse(
        items=[VenueOut.model_validate(r) for r in rows], total=total, page=page, pageSize=page_size
    )


@router.post("", response_model=VenueOut, status_code=201)
def create_venue(
    body: VenueIn,
    current_user: User = Depends(require_permission("venues.manage")),
    db: Session = Depends(get_db),
):
    return VenueOut.model_validate(VenueService(db).create(current_user.tenant_id, body.model_dump()))


@router.get("/{venue_id}", response_model=VenueOut)
def get_venue(
    venue_id: str,
    current_user: User = Depends(require_permission("venues.read")),
    db: Session = Depends(get_db),
):
    return VenueOut.model_validate(VenueService(db).get(current_user.tenant_id, venue_id))


@router.patch("/{venue_id}", response_model=VenueOut)
def update_venue(
    venue_id: str,
    body: VenuePatch,
    current_user: User = Depends(require_permission("venues.manage")),
    db: Session = Depends(get_db),
):
    return VenueOut.model_validate(
        VenueService(db).update(current_user.tenant_id, venue_id, body.model_dump(exclude_unset=True))
    )


@router.delete("/{venue_id}", status_code=204)
def delete_venue(
    venue_id: str,
    current_user: User = Depends(require_permission("venues.manage")),
    db: Session = Depends(get_db),
):
    VenueService(db).delete(current_user.tenant_id, venue_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── zones ──

@router.get("/{venue_id}/zones", response_model=List[VenueZoneOut])
def list_zones(
    venue_id: str,
    current_user: User = Depends(require_permission("venues.read")),
    db: Session = Depends(get_db),
):
    rows = VenueService(db).list_zones(current_user.tenant_id, venue_id)
    return [VenueZoneOut.model_validate(r) for r in rows]


@router.post("/{venue_id}/zones", response_model=VenueZoneOut, status_code=201)
def create_zone(
    venue_id: str,
    body: VenueZoneIn,
    current_user: User = Depends(require_permission("venues.manage")),
    db: Session = Depends(get_db),
):
    return VenueZoneOut.model_validate(
        VenueService(db).create_zone(current_user.tenant_id, venue_id, body.model_dump())
    )


@router.patch("/zones/{zone_id}", response_model=VenueZoneOut)
def update_zone(
    zone_id: str,
    body: VenueZonePatch,
    current_user: User = Depends(require_permission("venues.manage")),
    db: Session = Depends(get_db),
):
    return VenueZoneOut.model_validate(
        VenueService(db).update_zone(current_user.tenant_id, zone_id, body.model_dump(exclude_unset=True))
    )


@router.delete("/zones/{zone_id}", status_code=204)
def delete_zone(
    zone_id: str,
    current_user: User = Depends(require_permission("venues.manage")),
    db: Session = Depends(get_db),
):
    VenueService(db).delete_zone(current_user.tenant_id, zone_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── seats ──

@router.get("/{venue_id}/seats", response_model=List[VenueSeatOut])
def list_seats(
    venue_id: str,
    current_user: User = Depends(require_permission("venues.read")),
    db: Session = Depends(get_db),
):
    rows = VenueService(db).list_seats(current_user.tenant_id, venue_id)
    return [VenueSeatOut.model_validate(r) for r in rows]


@router.post("/seats/generate", response_model=List[VenueSeatOut], status_code=201)
def generate_seats(
    body: SeatGenerateIn,
    current_user: User = Depends(require_permission("venues.manage")),
    db: Session = Depends(get_db),
):
    rows = VenueService(db).generate_seats(current_user.tenant_id, body.model_dump())
    return [VenueSeatOut.model_validate(r) for r in rows]


@router.delete("/zones/{zone_id}/seats", status_code=204)
def clear_zone_seats(
    zone_id: str,
    current_user: User = Depends(require_permission("venues.manage")),
    db: Session = Depends(get_db),
):
    VenueService(db).clear_zone_seats(current_user.tenant_id, zone_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
