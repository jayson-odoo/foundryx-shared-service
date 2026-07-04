"""Profile-portal auth wire schemas (sprint-4/06 slice 0a). camelCase via ApiModel."""
from typing import List, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import ApiModel


class PortalLoginRequest(ApiModel):
    email: str
    password: str
    tenantSlug: Optional[str] = None
    rememberMe: bool = False


class PortalOtpRequest(ApiModel):
    email: str
    tenantSlug: Optional[str] = None


class PortalOtpLoginRequest(ApiModel):
    email: str
    code: str
    tenantSlug: Optional[str] = None
    rememberMe: bool = False


class PortalForgotPasswordRequest(ApiModel):
    email: str
    tenantSlug: Optional[str] = None


class PortalSetPasswordRequest(ApiModel):
    token: str
    password: str
    tenantSlug: Optional[str] = None


class ProfileAuthOut(ApiModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenantId: str = Field(validation_alias="tenant_id")
    email: str
    fullName: Optional[str] = Field(default=None, validation_alias="full_name")
    # Empty in 0a (personas land in 0b) — present so the wire contract is stable.
    portalPerms: List[str] = Field(default_factory=list)
    personas: List[str] = Field(default_factory=list)


class PortalLoginResponse(ApiModel):
    access_token: str
    token_type: str = "bearer"
    profile: ProfileAuthOut
