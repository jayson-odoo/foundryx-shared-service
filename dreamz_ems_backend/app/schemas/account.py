"""Account self-service schemas — the change-email ceremony (plan sprint-2/04)."""
from datetime import datetime

from pydantic import ConfigDict, EmailStr, Field

from app.schemas.base import ApiModel


class ChangeEmailRequest(ApiModel):
    newEmail: EmailStr
    # The EXISTING password (fresh proof of possession) — no strength policy.
    password: str = Field(min_length=1)


class EmailChangeTokenRequest(ApiModel):
    token: str


class PendingEmailChangeOut(ApiModel):
    model_config = ConfigDict(from_attributes=True)

    newEmail: str = Field(validation_alias="new_email")
    status: str
    expiresAt: datetime = Field(validation_alias="expires_at")
    createdAt: datetime = Field(validation_alias="created_at")


class AvatarOut(ApiModel):
    """Fresh display URL after an avatar mutation (plan 06 D4/D5)."""

    avatar: str | None


class ProfileUpdateRequest(ApiModel):
    """Self-editable profile fields (plan 06) — name only; email rides the
    ceremony, never this."""

    name: str = Field(min_length=1, max_length=200)


class ProfileOut(ApiModel):
    name: str
