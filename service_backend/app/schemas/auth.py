"""Auth request/response schemas.

JSON keys match what the frontend NextAuth `authorize()` expects:
  { access_token, token_type, user: { id, email, name, avatar, roles[], status } }
(`tenantId` is additive groundwork - the frontend ignores unknown fields.)
"""
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.password import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    validate_password_strength,
)
from app.schemas.role import RoleOut


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    # Subdomain-derived tenant slug (plan 07 §6); absent = default tenant.
    tenantSlug: Optional[str] = None
    # Long session (30d) vs the 24h default - the backend JWT exp is the real
    # boundary (plan 10 D4).
    rememberMe: bool = False


class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    # Same tenant resolution as login (plan 07 §6); absent = default tenant.
    tenantSlug: Optional[str] = None


class UserOut(BaseModel):
    id: str
    tenantId: str
    # True for platform-tenant users - gates the Platform Console menu (UX only;
    # require_platform_permission is the real boundary). Plan 07 §5/§9.
    isPlatformTenant: bool = False
    email: EmailStr
    name: Optional[str] = None
    avatar: Optional[str] = None
    roles: List[RoleOut] = []
    # Flattened effective permission keys (union over the user's roles) - the
    # frontend `can(key)` source. UX gating only; backend is the real boundary.
    permissions: List[str] = []
    status: str
    # IANA timezone preference (plan sprint-2/05); null = browser tz.
    timezone: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class SignupRequest(BaseModel):
    email: EmailStr
    # Server-side password policy (defense-in-depth; frontend also validates).
    # Cap at 72 - bcrypt hashes only the first 72 bytes and raises on longer.
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    name: Optional[str] = None

    _password_policy = field_validator("password")(validate_password_strength)
