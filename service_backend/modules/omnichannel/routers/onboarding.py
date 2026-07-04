"""Embedded Signup onboarding route — exchange code + provision channel.
Gated by `channels.manage`."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from ..adapters.base import CodeExchangeError
from ..schemas import ChannelItem, ManualConnectRequest, OnboardingCallbackRequest
from ..services.onboarding_service import (
    ManualConnectError,
    OnboardingService,
    PhoneNumberInUse,
    WorkspaceNotFound,
)

router = APIRouter()


@router.post("/oauth-callback", response_model=ChannelItem, status_code=status.HTTP_201_CREATED)
def oauth_callback(
    body: OnboardingCallbackRequest,
    current_user: User = Depends(require_permission("channels.manage")),
    db: Session = Depends(get_db),
) -> ChannelItem:
    try:
        return OnboardingService(db).complete(body, current_user.tenant_id)
    except WorkspaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    except PhoneNumberInUse as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except CodeExchangeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post("/manual-connect", response_model=ChannelItem, status_code=status.HTTP_201_CREATED)
def manual_connect(
    body: ManualConnectRequest,
    current_user: User = Depends(require_permission("channels.manage")),
    db: Session = Depends(get_db),
) -> ChannelItem:
    try:
        return OnboardingService(db).manual_connect(body, current_user.tenant_id)
    except WorkspaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    except PhoneNumberInUse as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except ManualConnectError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
