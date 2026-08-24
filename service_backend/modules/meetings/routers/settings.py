"""Tenant-settings routes (S0 plan §5).

HTTP + Pydantic only, gated on ``meetings.settings.manage`` — a user who may
manage their own capture still has no business over the tenant's configuration.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import SettingsIn, SettingsOut
from ..services.settings import MeetingsSettingsService

router = APIRouter()


def _out(row) -> SettingsOut:
    return SettingsOut(
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
    service = MeetingsSettingsService(db)
    row = service.get(current_user.tenant_id)
    db.commit()
    return _out(row)


@router.put("", response_model=SettingsOut)
def update_settings(
    body: SettingsIn,
    current_user: User = Depends(require_permission("meetings.settings.manage")),
    db: Session = Depends(get_db),
) -> SettingsOut:
    # An omitted key keeps its stored value; a key SENT as null clears it. The
    # two cases are told apart by what the client actually sent, never by None.
    sent = body.model_dump(exclude_unset=True)
    row = MeetingsSettingsService(db).update(
        current_user.tenant_id,
        minutes_language=body.minutesLanguage,
        audio_retention_days=body.audioRetentionDays,
        llm_connection_id=body.llmConnectionId,
        bot_display_name=body.botDisplayName,
        consent_message=body.consentMessage,
        clear=tuple(k for k, v in sent.items() if v is None),
    )
    return _out(row)
