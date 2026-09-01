"""Master-toggle routes (S0 plan §5, AC-S0-6 / AC-S0-9).

HTTP + Pydantic only: the tenant and the user both come from the JWT, so there
is no path here by which a caller names whose toggle to read or write.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import OptInIn, OptInOut
from ..services.optin import OptInService

router = APIRouter()


def _out(row) -> OptInOut:
    return OptInOut(enabled=row.enabled, lastSyncedAt=row.last_synced_at)


@router.get("", response_model=OptInOut)
def get_opt_in(
    current_user: User = Depends(require_permission("meetings.view")),
    db: Session = Depends(get_db),
) -> OptInOut:
    return _out(OptInService(db).get(current_user.tenant_id, current_user.id))


@router.put("", response_model=OptInOut)
def set_opt_in(
    body: OptInIn,
    current_user: User = Depends(require_permission("meetings.view")),
    db: Session = Depends(get_db),
) -> OptInOut:
    return _out(
        OptInService(db).set(current_user.tenant_id, current_user.id, body.enabled)
    )
