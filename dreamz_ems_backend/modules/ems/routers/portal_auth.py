"""Profile Portal auth routes (sprint-4/06 slice 0a) — ``/portal/auth/*``.

Thin layer: validate input, delegate to PortalAuthService, translate domain
outcomes to HTTP. No DB queries / business rules here.

Wired into the manifest as a ``"public": true`` router (like public_register)
so the module loader does NOT inject the staff ``require_module`` gate — these
endpoints are pre-auth / Profile-authed and resolve their own tenant from the
``tenantSlug`` in the body. ``GET /me`` authenticates via ``current_profile``.

Security posture mirrors core ``/auth/*`` (AC-06-11/16): uniform 401 on login
(no enumeration), request-otp + forgot-password ALWAYS 200, throttle (own
portal scope) checked BEFORE bcrypt, failed redeems pump the throttle.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.throttle import Throttled, ThrottleService, client_ip
from modules.ems.models import Profile
from modules.ems.portal_auth_service import (
    InvalidCredentials,
    InvalidToken,
    PortalAuthService,
    TenantInactive,
)
from modules.ems.portal_deps import current_profile
from modules.ems.portal_schemas import (
    PortalForgotPasswordRequest,
    PortalLoginRequest,
    PortalLoginResponse,
    PortalOtpLoginRequest,
    PortalOtpRequest,
    PortalSetPasswordRequest,
    ProfileAuthOut,
)

router = APIRouter()

_INVALID_CREDENTIALS = "Invalid email or password."
_INVALID_TOKEN = "Invalid or expired code."
_INVALID_LINK = "Invalid or expired link."
_OTP_MESSAGE = "If an account exists for this email, a sign-in code has been sent."
_FORGOT_MESSAGE = "If an account exists for this email, a reset link has been sent."
_TENANT_SUSPENDED = "This tenant is suspended. Contact support."


def _enforce_portal_throttle(throttle: ThrottleService, ip: str) -> None:
    """429 + Retry-After when over the (own portal-scope) limit. Runs BEFORE any
    credential work (cheap rejection under attack)."""
    try:
        throttle.enforce_portal(ip=ip)
    except Throttled as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )


def _profile_out(profile: Profile) -> ProfileAuthOut:
    return ProfileAuthOut.model_validate(profile)


@router.post("/login", response_model=PortalLoginResponse)
def login(
    payload: PortalLoginRequest, request: Request, db: Session = Depends(get_db)
) -> PortalLoginResponse:
    throttle = ThrottleService(db)
    ip = client_ip(request)
    _enforce_portal_throttle(throttle, ip)

    service = PortalAuthService(db)
    try:
        profile, token = service.login(
            payload.email, payload.password, payload.tenantSlug, payload.rememberMe
        )
    except InvalidCredentials:
        throttle.record_portal(ip=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _INVALID_CREDENTIALS)
    except TenantInactive:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _TENANT_SUSPENDED)
    return PortalLoginResponse(access_token=token, profile=_profile_out(profile))


@router.post("/request-otp")
def request_otp(
    payload: PortalOtpRequest, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Public + enumeration-safe: ALWAYS the same 200. Pumps the portal IP
    throttle (the endpoint sends mail — unthrottled it is a mail-bombing
    vector). Zero-activation first login (works with NULL password)."""
    throttle = ThrottleService(db)
    ip = client_ip(request)
    _enforce_portal_throttle(throttle, ip)
    throttle.record_portal(ip=ip)

    PortalAuthService(db).request_otp(payload.email, payload.tenantSlug)
    return {"message": _OTP_MESSAGE}


@router.post("/login-otp", response_model=PortalLoginResponse)
def login_otp(
    payload: PortalOtpLoginRequest, request: Request, db: Session = Depends(get_db)
) -> PortalLoginResponse:
    throttle = ThrottleService(db)
    ip = client_ip(request)
    _enforce_portal_throttle(throttle, ip)

    service = PortalAuthService(db)
    try:
        profile, token = service.login_otp(
            payload.email, payload.code, payload.tenantSlug, payload.rememberMe
        )
    except InvalidToken:
        throttle.record_portal(ip=ip)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _INVALID_TOKEN)
    except TenantInactive:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _TENANT_SUSPENDED)
    except InvalidCredentials:
        # Unknown slug surfaces as a uniform 401 (mirrors core resolve_tenant).
        throttle.record_portal(ip=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _INVALID_CREDENTIALS)
    return PortalLoginResponse(access_token=token, profile=_profile_out(profile))


@router.post("/forgot-password")
def forgot_password(
    payload: PortalForgotPasswordRequest, request: Request, db: Session = Depends(get_db)
) -> dict:
    throttle = ThrottleService(db)
    ip = client_ip(request)
    _enforce_portal_throttle(throttle, ip)
    throttle.record_portal(ip=ip)

    PortalAuthService(db).forgot_password(payload.email, payload.tenantSlug)
    return {"message": _FORGOT_MESSAGE}


@router.post("/set-password", response_model=PortalLoginResponse)
def set_password(
    payload: PortalSetPasswordRequest, request: Request, db: Session = Depends(get_db)
) -> PortalLoginResponse:
    """Redeem a SET_PASSWORD token (single-use + expiry + policy). Failed redeems
    pump the portal throttle (token guessing). Issues a session on success."""
    throttle = ThrottleService(db)
    ip = client_ip(request)
    _enforce_portal_throttle(throttle, ip)

    service = PortalAuthService(db)
    try:
        profile = service.set_password(payload.token, payload.password, payload.tenantSlug)
    except InvalidToken:
        throttle.record_portal(ip=ip)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _INVALID_LINK)
    except TenantInactive:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _TENANT_SUSPENDED)
    except InvalidCredentials:
        throttle.record_portal(ip=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _INVALID_CREDENTIALS)
    except ValueError as exc:
        # Password-policy violation (validate_password_strength).
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    token = service.issue_token(profile)
    return PortalLoginResponse(access_token=token, profile=_profile_out(profile))


@router.get("/me", response_model=ProfileAuthOut)
def me(profile: Profile = Depends(current_profile)) -> ProfileAuthOut:
    return _profile_out(profile)
