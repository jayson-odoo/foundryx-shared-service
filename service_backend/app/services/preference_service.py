"""View-preference business logic (keeps the router out of the repository)."""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.tenant import DEFAULT_TENANT_ID
from app.models.user import User
from app.repositories.preference_repository import PreferenceRepository
from app.schemas.preference import ProfilePreferences, ViewPreferenceData


class PreferenceService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = PreferenceRepository(db)

    def save_profile(self, user: User, prefs: ProfilePreferences) -> ProfilePreferences:
        """User-level display preferences (plan sprint-2/05) - currently just
        the timezone; schema-validated upstream (IANA or null)."""
        user.timezone = prefs.timezone
        self.db.commit()
        return ProfilePreferences(timezone=user.timezone)

    def get(
        self, user_id: str, view_key: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> Optional[ViewPreferenceData]:
        row = self.repo.get(user_id, view_key, tenant_id)
        return ViewPreferenceData(**row.prefs) if row else None

    def save(
        self,
        user_id: str,
        view_key: str,
        prefs: ViewPreferenceData,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> ViewPreferenceData:
        self.repo.upsert(user_id, view_key, prefs.model_dump(), tenant_id)
        return prefs
