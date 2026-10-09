"""Tenant-settings routes (S0 plan §5).

HTTP + Pydantic only, gated on ``meetings.settings.manage`` - a user who may
manage their own capture still has no business over the tenant's configuration.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import SettingsIn, SettingsOut
from ..services.settings import (
    MeetingsSettingsService,
    calendar_service_account_email,
)

router = APIRouter()


def _out(row, service_account_email=None) -> SettingsOut:
    return SettingsOut(
        calendarServiceAccountEmail=service_account_email,
        minutesLanguage=row.minutes_language,
        audioRetentionDays=row.audio_retention_days,
        llmConnectionId=row.llm_connection_id,
        botDisplayName=row.bot_display_name,
        consentMessage=row.consent_message,
    )


@router.get("", response_model=SettingsOut)
def get_settings(
    current_user: User = Depends(require_permission("meetings.settings.manage")),
    db: Session = Depends(get_db),
) -> SettingsOut:
    return _out(
        MeetingsSettingsService(db).get(current_user.tenant_id),
        calendar_service_account_email(db, current_user.tenant_id),
    )


@router.put("", response_model=SettingsOut)
def update_settings(
    body: SettingsIn,
    current_user: User = Depends(require_permission("meetings.settings.manage")),
    db: Session = Depends(get_db),
) -> SettingsOut:
    # An omitted key keeps its stored value; a key SENT as null clears it - told
    # apart by what the client actually sent, never by the value being None.
    return _out(
        MeetingsSettingsService(db).update(
            current_user.tenant_id, body.model_dump(exclude_unset=True)
        ),
        calendar_service_account_email(db, current_user.tenant_id),
    )
