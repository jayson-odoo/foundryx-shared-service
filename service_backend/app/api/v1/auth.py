"""Authentication routes. Thin layer: validate input, delegate to AuthService,
translate domain outcomes to HTTP. No DB queries or business rules here.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import effective_permission_keys, get_current_user
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    SignupRequest,
    UserOut,
)
from app.schemas.account import EmailChangeTokenRequest
from app.schemas.role import RoleOut
from app.schemas.user import SetPasswordRequest
from app.services.auth_service import (
    AccountInactive,
    AuthService,
    EmailAlreadyExists,
    InvalidCredentials,
    TenantInactive,
)
from app.services.email_change_service import (
    EmailChangeService,
    EmailTaken,
    InvalidChangeToken,
)
from app.services.throttle import Throttled, ThrottleService, client_ip
from app.services.user_service import InvalidToken, UserService

router = APIRouter()

# Single message for both unknown-email and wrong-password - no user enumeration.
_INVALID_CREDENTIALS = "Invalid email or password."

# Uniform forgot-password reply - identical whether or not the account exists.
_FORGOT_PASSWORD_MESSAGE = (
    "If an account exists for this email, a reset link has been sent."
)


def enforce_throttle(throttle: ThrottleService, ip: str, email: str | None = None) -> None:
    """429 + Retry-After when over the limit. Runs BEFORE any credential work
    (plan 10 §5) - cheap rejection under attack. The 429 is deliberately
    distinct from the uniform 401: locking is observable anyway."""
    try:
        throttle.enforce(ip=ip, email=email)
    except Throttled as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )


def _to_user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        tenantId=user.tenant_id,
        # From the tenant's is_platform flag (source of truth), not the seeded id.
        isPlatformTenant=bool(user.tenant is not None and user.tenant.is_platform),
        email=user.email,
        name=user.name,
        avatar=user.avatar,
        roles=[RoleOut(id=r.id, name=r.name) for r in user.roles],
        permissions=sorted(effective_permission_keys(user)),
        status=user.status,
        timezone=user.timezone,
    )


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest, request: Request, db: Session = Depends(get_db)
) -> LoginResponse:
    throttle = ThrottleService(db)
    ip = client_ip(request)
    # Dual check BEFORE bcrypt (plan 10 §5): IP first, then the account.
    enforce_throttle(throttle, ip, payload.email)

    service = AuthService(db)
    try:
        user, token = service.login(
            payload.email, payload.password, payload.tenantSlug, payload.rememberMe
        )
    except InvalidCredentials:
        throttle.record_login_failure(ip=ip, email=payload.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_CREDENTIALS,
        )
    except TenantInactive:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This tenant is suspended. Contact support.",
        )
    except AccountInactive:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not activated. Please verify your email.",
        )
    throttle.reset_email(payload.email)
    return LoginResponse(access_token=token, user=_to_user_out(user))


@router.post("/forgot-password")
def forgot_password(
    payload: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Public + enumeration-safe (plan 10 D1): ALWAYS the same 200, whether or
    not the account exists. Every request counts toward the IP throttle - the
    endpoint sends mail, so unthrottled it is a mail-bombing vector."""
    throttle = ThrottleService(db)
    ip = client_ip(request)
    enforce_throttle(throttle, ip)
    throttle.record_ip_attempt(ip=ip)

    UserService(db).forgot_password(payload.email, payload.tenantSlug)
    return {"message": _FORGOT_PASSWORD_MESSAGE}


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)) -> UserOut:
    # Parked until real tenant provisioning (plan 10 D3, BL-032) - a
    # kill-switch, not a deletion. 404 = the surface doesn't exist publicly.
    if not settings.signup_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    service = AuthService(db)
    try:
        user = service.register(payload.email, payload.password, payload.name)
    except EmailAlreadyExists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )
    return _to_user_out(user)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> UserOut:
    return _to_user_out(current_user)


@router.post("/approve-email-change")
def approve_email_change(
    payload: EmailChangeTokenRequest, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Public: redeem the OLD-side approve token (plan sprint-2/04). Moves the
    request to PENDING_NEW and mails the verify link to the NEW address.
    Failed redeems count toward the IP throttle (token guessing)."""
    throttle = ThrottleService(db)
    ip = client_ip(request)
    enforce_throttle(throttle, ip)
    try:
        EmailChangeService(db).approve(payload.token)
    except InvalidChangeToken:
        throttle.record_ip_attempt(ip=ip)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token.",
        )
    return {"message": "Change approved. Confirm from the new address to finish."}


@router.post("/verify-email-change")
def verify_email_change(
    payload: EmailChangeTokenRequest, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Public: redeem the NEW-side verify token - THE step that flips the
    account email (uniqueness re-checked transactionally; 409 on the race)."""
    throttle = ThrottleService(db)
    ip = client_ip(request)
    enforce_throttle(throttle, ip)
    try:
        EmailChangeService(db).verify(payload.token)
    except InvalidChangeToken:
        throttle.record_ip_attempt(ip=ip)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token.",
        )
    except EmailTaken:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email address is no longer available.",
        )
    return {"message": "Email updated. Sign in with your new address."}


@router.post("/set-password", response_model=UserOut)
def set_password(
    payload: SetPasswordRequest, request: Request, db: Session = Depends(get_db)
) -> UserOut:
    """Public: redeem an invite/reset token to set a password (INVITED -> ACTIVE).
    Single-use + expiry enforced in the service; failed redeems count toward
    the IP throttle (token guessing)."""
    throttle = ThrottleService(db)
    ip = client_ip(request)
    enforce_throttle(throttle, ip)
    try:
        user = UserService(db).set_password(payload.token, payload.password)
    except InvalidToken:
        throttle.record_ip_attempt(ip=ip)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token.",
        )
    return _to_user_out(user)
