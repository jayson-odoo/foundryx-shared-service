"""Impersonation routes (plan 03 §13). Use `get_real_user` (not the effective
user) so an impersonated session can never start/stop its own impersonation."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import effective_permission_keys, get_real_user
from app.models.impersonation import ImpersonationSession
from app.models.user import User
from app.schemas.impersonation import (
    ImpersonationSessionResponse,
    ImpersonationTargetUser,
    StartImpersonationRequest,
)
from app.services.impersonation_service import (
    CannotImpersonateSelf,
    ImpersonationService,
    NotAllowed,
    TargetMorePrivileged,
    TargetNotFound,
    TargetNotImpersonatable,
)

router = APIRouter()


def _response(row: ImpersonationSession, target: User) -> ImpersonationSessionResponse:
    return ImpersonationSessionResponse(
        sessionId=row.id,
        startedAt=row.started_at,
        targetUser=ImpersonationTargetUser(
            id=target.id,
            name=target.name,
            email=target.email,
            avatar=target.avatar,
            status=target.status,
        ),
        permissions=sorted(effective_permission_keys(target)),
    )


@router.post("/start", response_model=ImpersonationSessionResponse)
def start_impersonation(
    payload: StartImpersonationRequest,
    request: Request,
    real_user: User = Depends(get_real_user),
    db: Session = Depends(get_db),
) -> ImpersonationSessionResponse:
    service = ImpersonationService(db)
    try:
        row, target = service.start(
            real_user,
            payload.targetUserId,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except NotAllowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don’t have permission to impersonate.")
    except CannotImpersonateSelf:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can’t impersonate yourself.")
    except TargetNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Target user not found.")
    except TargetNotImpersonatable:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This user can’t be impersonated (inactive, or also an impersonator).",
        )
    except TargetMorePrivileged:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can only impersonate users whose permissions you already have.",
        )
    return _response(row, target)


@router.post("/stop")
def stop_impersonation(
    real_user: User = Depends(get_real_user),
    db: Session = Depends(get_db),
) -> dict:
    ended = ImpersonationService(db).stop(real_user)
    return {"ended": ended}


@router.get("/current", response_model=Optional[ImpersonationSessionResponse])
def current_impersonation(
    real_user: User = Depends(get_real_user),
    db: Session = Depends(get_db),
) -> Optional[ImpersonationSessionResponse]:
    result = ImpersonationService(db).current(real_user)
    if result is None:
        return None
    row, target = result
    return _response(row, target)
