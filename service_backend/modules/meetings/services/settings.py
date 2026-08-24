"""Tenant-settings service (S0 plan §5).

Seed-if-absent on every read, so a tenant provisioned before this row existed
(or one whose install predates a new setting) is never left without one.
"""
from typing import Optional

from sqlalchemy.orm import Session

from ..models import MeetingsTenantSettings

DEFAULT_MINUTES_LANGUAGE = "en"
DEFAULT_AUDIO_RETENTION_DAYS = 90


class MeetingsSettingsService:
    def __init__(self, db: Session):
        self.db = db

    def ensure(self, tenant_id: str) -> MeetingsTenantSettings:
        """This tenant's settings row, created at platform defaults if absent."""
        row = (
            self.db.query(MeetingsTenantSettings)
            .filter(MeetingsTenantSettings.tenant_id == tenant_id)
            .first()
        )
        if row is None:
            row = MeetingsTenantSettings(
                tenant_id=tenant_id,
                minutes_language=DEFAULT_MINUTES_LANGUAGE,
                audio_retention_days=DEFAULT_AUDIO_RETENTION_DAYS,
            )
            self.db.add(row)
            self.db.flush()
        return row

    def get(self, tenant_id: str) -> MeetingsTenantSettings:
        return self.ensure(tenant_id)

    def update(
        self,
        tenant_id: str,
        *,
        minutes_language: Optional[str] = None,
        audio_retention_days: Optional[int] = None,
        llm_connection_id: Optional[str] = None,
        bot_display_name: Optional[str] = None,
        consent_message: Optional[str] = None,
        clear: tuple = (),
    ) -> MeetingsTenantSettings:
        """Partial update. A key the caller did not send keeps its stored value;
        a key sent as null is cleared, which ``clear`` names explicitly so
        ``None`` cannot mean both "absent" and "blank"."""
        row = self.ensure(tenant_id)
        if minutes_language is not None:
            row.minutes_language = minutes_language
        if audio_retention_days is not None:
            row.audio_retention_days = audio_retention_days
        if llm_connection_id is not None or "llmConnectionId" in clear:
            row.llm_connection_id = llm_connection_id
        if bot_display_name is not None or "botDisplayName" in clear:
            row.bot_display_name = bot_display_name
        if consent_message is not None or "consentMessage" in clear:
            row.consent_message = consent_message
        self.db.commit()
        self.db.refresh(row)
        return row
