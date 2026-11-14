"""Tenant-settings service (S0 plan §5).

Seed-if-absent on every read, so a tenant provisioned before this row existed
(or one whose install predates a new setting) is never left without one.
"""
from typing import Optional

from sqlalchemy.orm import Session

from ..models import MeetingsTenantSettings


def calendar_service_account_email(db: Session, tenant_id: str) -> Optional[str]:
    """The address a user has to share their calendar WITH, or None when the
    tenant has no Google connection yet.

    Read out of the stored key's ``client_email`` - the key itself never leaves
    the server, and a key that cannot be decrypted (rotated FERNET_KEY) is a
    missing address here, not a 500."""
    from cryptography.fernet import InvalidToken

    from app.models.connection import Connection
    from app.secrets import decrypt_secret

    from ..calendar.google_dwd import service_account_email
    from ..providers import GOOGLE_DWD_PROVIDER

    connection = (
        db.query(Connection)
        .filter(
            Connection.tenant_id == tenant_id,
            Connection.provider == GOOGLE_DWD_PROVIDER,
            Connection.is_active.is_(True),
        )
        .first()
    )
    if connection is None or not connection.credentials_json:
        return None
    try:
        credentials = decrypt_secret(connection.credentials_json)
    except InvalidToken:
        return None
    return service_account_email(str(credentials.get("serviceAccountJson") or ""))

DEFAULT_MINUTES_LANGUAGE = "en"
DEFAULT_AUDIO_RETENTION_DAYS = 90


class MeetingsSettingsService:
    def __init__(self, db: Session):
        self.db = db

    def ensure(self, tenant_id: str) -> MeetingsTenantSettings:
        """This tenant's settings row, created at platform defaults if absent.

        Owns its own commit, so a caller on a READ path (``get``, and the
        install/update hooks) never has to commit for it - a router must not."""
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
            self.db.commit()
            self.db.refresh(row)
        return row

    def get(self, tenant_id: str) -> MeetingsTenantSettings:
        return self.ensure(tenant_id)

    # Wire key -> column. The router hands over only the keys the client actually
    # SENT, so "absent" and "sent as null" never have to be told apart by value.
    _FIELDS = {
        "minutesLanguage": "minutes_language",
        "audioRetentionDays": "audio_retention_days",
        "llmConnectionId": "llm_connection_id",
        "botDisplayName": "bot_display_name",
        "consentMessage": "consent_message",
    }

    def update(self, tenant_id: str, sent: dict) -> MeetingsTenantSettings:
        """Partial update from the keys the client sent. An omitted key keeps its
        stored value; a key sent as null clears it."""
        row = self.ensure(tenant_id)
        for wire_key, column in self._FIELDS.items():
            if wire_key in sent:
                setattr(row, column, sent[wire_key])
        self.db.commit()
        self.db.refresh(row)
        return row
