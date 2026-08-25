"""Master-toggle routes (S0 plan §5, AC-S0-6 / AC-S0-9).

HTTP + Pydantic only: the tenant and the user both come from the JWT, so there
is no path here by which a caller names whose toggle to read or write.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import OptInIn, OptInOut
from ..services.optin import EMAIL_RE, OptInService
from ..services.settings import calendar_service_account_email

router = APIRouter()


def _out(row, service_account_email=None) -> OptInOut:
    return OptInOut(
        enabled=row.enabled,
        lastSyncedAt=row.last_synced_at,
        calendarEmail=row.calendar_email,
        serviceAccountEmail=service_account_email,
    )


@router.get("", response_model=OptInOut)
def get_opt_in(
    current_user: User = Depends(require_permission("meetings.view")),
    db: Session = Depends(get_db),
) -> OptInOut:
    return _out(
        OptInService(db).get(current_user.tenant_id, current_user.id),
        calendar_service_account_email(db, current_user.tenant_id),
    )


@router.put("", response_model=OptInOut)
def set_opt_in(
    body: OptInIn,
    current_user: User = Depends(require_permission("meetings.view")),
    db: Session = Depends(get_db),
) -> OptInOut:
    sent = body.model_dump(exclude_unset=True)
    address = (body.calendarEmail or "").strip()
    if address and not EMAIL_RE.match(address):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enter a valid email address.",
        )
    return _out(
        OptInService(db).set(
            current_user.tenant_id,
            current_user.id,
            body.enabled,
            calendar_email=body.calendarEmail,
            set_calendar_email="calendarEmail" in sent,
        ),
        calendar_service_account_email(db, current_user.tenant_id),
    )
