"""Current-user routes — per-user view preferences (column order/width/
visibility), the change-email ceremony's self-service surface (plan
sprint-2/04) and avatar/profile self-service (plan sprint-2/06). All
endpoints are self-scope only — perm-free like /auth/me."""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.v1.auth import enforce_throttle
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.app_store import InstalledModuleOut
from app.services.app_store_service import AppStoreService
from app.schemas.account import (
    AvatarOut,
    ChangeEmailRequest,
    PendingEmailChangeOut,
    ProfileOut,
    ProfileUpdateRequest,
)
from app.schemas.preference import ProfilePreferences, ViewPreferenceData
from app.services.avatar_service import AVATAR_MAX_BYTES, AvatarError, AvatarService
from app.services.email_change_service import (
    EmailChangeService,
    InvalidPassword,
    SameEmail,
)
from app.services.preference_service import PreferenceService
from app.services.throttle import ThrottleService, client_ip

router = APIRouter()


@router.post("/avatar", response_model=AvatarOut)
async def upload_own_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AvatarOut:
    """Set own avatar (plan 06 D5) — the gate runs on SNIFFED bytes, the
    declared content-type is ignored (it's client input)."""
    # Cap the read — a full read() buffers an arbitrary-size body in RAM
    # before any size check (review finding). One byte past the cap is
    # enough for the service's too-large 422.
    content = await file.read(AVATAR_MAX_BYTES + 1)
    try:
        user = AvatarService(db).set_avatar(current_user, content)
    except AvatarError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return AvatarOut(avatar=user.avatar)


@router.delete("/avatar", response_model=AvatarOut)
def remove_own_avatar(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AvatarOut:
    user = AvatarService(db).remove_avatar(current_user)
    return AvatarOut(avatar=user.avatar)


@router.patch("/profile", response_model=ProfileOut)
def update_own_profile(
    payload: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileOut:
    """Self-editable profile (plan 06) — name only; email = the ceremony."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name is required.")
    current_user.name = name
    db.commit()
    return ProfileOut(name=name)


@router.post("/change-email", response_model=PendingEmailChangeOut)
def request_email_change(
    payload: ChangeEmailRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PendingEmailChangeOut:
    """Start the dual-confirmation ceremony: password re-entry (fresh proof,
    not just a live session) → approve link to the CURRENT mailbox. Password
    failures are throttle-counted like login failures; the response is
    uniform whether or not the new address is taken (no enumeration)."""
    throttle = ThrottleService(db)
    ip = client_ip(request)
    # Before bcrypt, like login (plan 10 §5).
    enforce_throttle(throttle, ip, current_user.email)
    service = EmailChangeService(db)
    try:
        row = service.request(current_user, payload.newEmail, payload.password)
    except InvalidPassword:
        throttle.record_login_failure(ip=ip, email=current_user.email)
        # 400, NOT 401 — the api-client treats 401-with-token as session death.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect password.",
        )
    except SameEmail:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The new email must be different from your current one.",
        )
    # Deliberately NO throttle.reset_email here (unlike login): a correct
    # password on this endpoint must not clear a LOGIN lockout, or a
    # session-holder could wipe the account's brute-force counter (review fix).
    return PendingEmailChangeOut.model_validate(row)


@router.get("/change-email", response_model=Optional[PendingEmailChangeOut])
def get_email_change(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Optional[PendingEmailChangeOut]:
    row = EmailChangeService(db).get_pending(current_user)
    return PendingEmailChangeOut.model_validate(row) if row else None


@router.delete("/change-email", status_code=status.HTTP_204_NO_CONTENT)
def cancel_email_change(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    EmailChangeService(db).cancel(current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/preferences", response_model=ProfilePreferences)
def save_profile_preferences(
    payload: ProfilePreferences,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfilePreferences:
    """User-level display preferences (plan sprint-2/05) — timezone (IANA,
    422 on unknown; null = browser tz). Self-scope, perm-free; the fresh
    value rides /auth/me + the login payload into the session."""
    return PreferenceService(db).save_profile(current_user, payload)


@router.get("/preferences/{view_key}", response_model=Optional[ViewPreferenceData])
def get_preferences(
    view_key: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Optional[ViewPreferenceData]:
    return PreferenceService(db).get(current_user.id, view_key, current_user.tenant_id)


@router.patch("/preferences/{view_key}", response_model=ViewPreferenceData)
def save_preferences(
    view_key: str,
    payload: ViewPreferenceData,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ViewPreferenceData:
    return PreferenceService(db).save(
        current_user.id, view_key, payload, current_user.tenant_id
    )


@router.get("/modules", response_model=List[InstalledModuleOut])
def my_tenant_modules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[InstalledModuleOut]:
    """The caller's tenant install list for MENU GATING — perm-free (self-scope,
    like /me/preferences). Decouples sidebar module-visibility from
    `app_store.read`: an agent who only uses a module's pages shouldn't need
    App Store read just to see its menu. The gated `/app-store/installed`
    stays for the store/console (which also needs INACTIVE state + management)."""
    return [
        InstalledModuleOut(
            module=tm.module.name, status=tm.status, version=tm.installed_version
        )
        for tm in AppStoreService(db).installed(current_user.tenant_id)
    ]
