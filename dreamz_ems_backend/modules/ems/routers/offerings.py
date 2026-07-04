"""EMS offerings routes (sprint-4/05, Cluster D) — per-event Offerings + capacity
minting. Mounted under /ems/projects so offerings are project-scoped. Gated
offerings.read / offerings.manage; loader wraps in require_module('ems')."""
from typing import List

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from modules.ems.schemas import (
    CapacityUnitOut,
    OfferingIn,
    OfferingOut,
    OfferingPatch,
    RegisterIn,
)
from modules.ems.services import CheckoutService, OfferingService

router = APIRouter()


@router.get("/{project_id}/offerings", response_model=List[OfferingOut])
def list_offerings(
    project_id: str,
    current_user: User = Depends(require_permission("offerings.read")),
    db: Session = Depends(get_db),
):
    rows = OfferingService(db).list(current_user.tenant_id, project_id)
    return [OfferingOut.model_validate(r) for r in rows]


@router.post("/{project_id}/offerings", response_model=OfferingOut, status_code=201)
def create_offering(
    project_id: str,
    body: OfferingIn,
    current_user: User = Depends(require_permission("offerings.manage")),
    db: Session = Depends(get_db),
):
    return OfferingOut.model_validate(
        OfferingService(db).create(current_user.tenant_id, project_id, body.model_dump())
    )


@router.get("/{project_id}/offerings/{offering_id}", response_model=OfferingOut)
def get_offering(
    project_id: str,
    offering_id: str,
    current_user: User = Depends(require_permission("offerings.read")),
    db: Session = Depends(get_db),
):
    return OfferingOut.model_validate(
        OfferingService(db).get(current_user.tenant_id, project_id, offering_id)
    )


@router.patch("/{project_id}/offerings/{offering_id}", response_model=OfferingOut)
def update_offering(
    project_id: str,
    offering_id: str,
    body: OfferingPatch,
    current_user: User = Depends(require_permission("offerings.manage")),
    db: Session = Depends(get_db),
):
    return OfferingOut.model_validate(
        OfferingService(db).update(
            current_user.tenant_id, project_id, offering_id, body.model_dump(exclude_unset=True)
        )
    )


@router.delete("/{project_id}/offerings/{offering_id}", status_code=204)
def delete_offering(
    project_id: str,
    offering_id: str,
    current_user: User = Depends(require_permission("offerings.manage")),
    db: Session = Depends(get_db),
):
    OfferingService(db).delete(current_user.tenant_id, project_id, offering_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/offerings/{offering_id}/mint", response_model=List[CapacityUnitOut]
)
def mint_seats(
    project_id: str,
    offering_id: str,
    current_user: User = Depends(require_permission("offerings.manage")),
    db: Session = Depends(get_db),
):
    rows = OfferingService(db).mint_capacity_units(current_user.tenant_id, project_id, offering_id)
    return [CapacityUnitOut.model_validate(r) for r in rows]


@router.post("/{project_id}/register")
def admin_register(
    project_id: str,
    body: RegisterIn,
    current_user: User = Depends(require_permission("offerings.manage")),
    db: Session = Depends(get_db),
):
    """Admin add-one (slice 2): confirm a registration → participants + signed-QR
    tickets + ONE Draft invoice (comp skips the invoice). Same atomic
    CheckoutService.confirm the public flow uses."""
    items = [i.model_dump() for i in body.items]
    return CheckoutService(db).confirm(current_user.tenant_id, project_id, items, comp=body.comp)


@router.get(
    "/{project_id}/offerings/{offering_id}/units", response_model=List[CapacityUnitOut]
)
def list_units(
    project_id: str,
    offering_id: str,
    current_user: User = Depends(require_permission("offerings.read")),
    db: Session = Depends(get_db),
):
    rows = OfferingService(db).list_capacity_units(current_user.tenant_id, project_id, offering_id)
    return [CapacityUnitOut.model_validate(r) for r in rows]
