"""Embedded Signup onboarding route - exchange code + provision channel.
Gated by `channels.manage`."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from ..adapters.base import CodeExchangeError
from ..origins import InvalidOrigin
from ..schemas import (
    ChannelItem,
    ConnectWebchatRequest,
    ManualConnectRequest,
    MetaConnectRequest,
    MetaPagesRequest,
    MetaPagesResult,
    OnboardingCallbackRequest,
    WebchatConnectResult,
)
from ..services.meta_connect_service import (
    ConnectSessionConsumed,
    ConnectSessionExpired,
    ConnectSessionNotFound,
    ExternalAccountInUse,
    MetaConnectService,
    PageNotFound,
)
from ..services.onboarding_service import (
    ManualConnectError,
    OnboardingResolveError,
    OnboardingService,
    PhoneNumberInUse,
    WorkspaceNotFound,
)
from ..services.webchat_service import WebchatService

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
    except OnboardingResolveError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
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


# ── Messenger + Instagram connect flow (plan 32 S3, A7a) ────────────────────
@router.post("/meta/pages", response_model=MetaPagesResult)
def list_meta_pages(
    body: MetaPagesRequest,
    current_user: User = Depends(require_permission("channels.manage")),
    db: Session = Depends(get_db),
) -> MetaPagesResult:
    try:
        return MetaConnectService(db).list_pages(
            body, current_user.tenant_id, current_user.id
        )
    except CodeExchangeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post("/meta/connect", response_model=ChannelItem, status_code=status.HTTP_201_CREATED)
def connect_meta_channel(
    body: MetaConnectRequest,
    current_user: User = Depends(require_permission("channels.manage")),
    db: Session = Depends(get_db),
) -> ChannelItem:
    try:
        return MetaConnectService(db).connect(
            body, current_user.tenant_id, current_user.id
        )
    except WorkspaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    except (ConnectSessionNotFound, PageNotFound):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connect session not found.")
    # `{"reason": ...}` is the documented typed-error contract (plan §5.1) -
    # `ConnectMetaError.reasonMessage` (plan 32 / A7a S6, `lib/channel-
    # capabilities.ts`) maps each `.reason` to the SAME copy
    # `meta_connect_service.py`'s exception carries, so the wizard shows the
    # exact prose the mock always showed without changing this tested,
    # documented body shape.
    except ConnectSessionExpired as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"reason": exc.reason})
    except ConnectSessionConsumed as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"reason": exc.reason})
    except ExternalAccountInUse as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, {"reason": exc.reason})
    except CodeExchangeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


# ── Web chat connect flow (plan 34 S1, A7b) ──────────────────────────────────
@router.post(
    "/webchat/connect", response_model=WebchatConnectResult, status_code=status.HTTP_201_CREATED
)
def connect_webchat(
    body: ConnectWebchatRequest,
    current_user: User = Depends(require_permission("channels.manage")),
    db: Session = Depends(get_db),
) -> WebchatConnectResult:
    try:
        return WebchatService(db).connect(body, current_user.tenant_id)
    except WorkspaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    except InvalidOrigin as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"fieldErrors": {"allowedOrigins": exc.message}},
        )
