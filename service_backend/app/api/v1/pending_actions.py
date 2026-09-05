"""Deferred actions - park / cancel / current (sprint-4/23, T5, AC-DLA-39/40).

Router = HTTP + Pydantic only. `PendingActionService` does the work; the
permission for a park is the ACTION's own key (resolved dynamically from the
body, not a static `Depends(require_permission(...))`), checked inside the
service the same way `require_permission` resolves fresh from the DB.

Mounted under `/api/v1/pending-actions` (the plan's explicit prefix - core
routes otherwise mount bare, but this stays inside the versioned prefix per
the brief).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deferred_actions.service import (
    ActionNotFound,
    AlreadySettled,
    ConflictingPendingAction,
    PendingActionService,
    PermissionDenied,
    TargetNotFound,
    UnknownActionKey,
)
from app.dependencies import get_actor_user_id, get_current_user
from app.models.pending_action import PendingAction
from app.models.user import User
from app.schemas.pending_action import (
    PendingActionCancelResponse,
    PendingActionCreate,
    PendingActionCreateResponse,
    PendingActionCurrentOut,
    PendingActionOut,
    PendingActionOutcomeOut,
)

router = APIRouter()


def _pending_out(service: PendingActionService, row: PendingAction) -> PendingActionOut:
    # Fix round 2, N1: the requester-name lookup is a tenant-scoped DB query
    # - it belongs in the service, not here. `PendingActionOut.requestedByName`
    # is a plain (non-aliased) field, so setting it post-validation is the
    # smallest way to merge the service's resolved name onto the ORM-mapped
    # schema without a second constructor call.
    out = PendingActionOut.model_validate(row)
    out.requestedByName = service.requester_name(row)
    return out


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=PendingActionCreateResponse)
def create_pending_action(
    body: PendingActionCreate,
    current_user: User = Depends(get_current_user),
    actor_user_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
):
    service = PendingActionService(db)
    try:
        row = service.park(
            tenant_id=current_user.tenant_id,
            actor=current_user,
            requested_by_id=actor_user_id,
            action_key=body.actionKey,
            entity_type=body.entityType,
            entity_id=body.entityId,
            payload=body.payload,
        )
    except UnknownActionKey as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except PermissionDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    except TargetNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except ConflictingPendingAction as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return PendingActionCreateResponse(
        id=row.id, commitAt=row.commit_at, windowSeconds=row.window_seconds
    )


@router.post("/{action_id}/cancel", response_model=PendingActionCancelResponse)
def cancel_pending_action(
    action_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = PendingActionService(db)
    try:
        row = service.cancel(current_user.tenant_id, action_id, current_user)
    except ActionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except PermissionDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    except AlreadySettled as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return PendingActionCancelResponse(id=row.id, status=row.status)


@router.get("/current", response_model=PendingActionCurrentOut)
def get_current_pending_action(
    entityType: str = Query(...),
    entityId: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = PendingActionService(db)
    try:
        result = service.current(current_user.tenant_id, entityType, entityId, current_user)
    except ActionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    pending = result["pending"]
    last_outcome = result["last_outcome"]
    return PendingActionCurrentOut(
        pending=_pending_out(service, pending) if pending else None,
        lastOutcome=PendingActionOutcomeOut.model_validate(last_outcome) if last_outcome else None,
    )
