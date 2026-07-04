"""View-preference repository — per-user, per-view column prefs (upsert)."""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.tenant import DEFAULT_TENANT_ID
from app.models.view_preference import UserViewPreference


class PreferenceRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(
        self, user_id: str, view_key: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> Optional[UserViewPreference]:
        return (
            self.db.query(UserViewPreference)
            .filter(
                UserViewPreference.tenant_id == tenant_id,
                UserViewPreference.user_id == user_id,
                UserViewPreference.view_key == view_key,
            )
            .first()
        )

    def upsert(
        self, user_id: str, view_key: str, prefs: dict, tenant_id: str = DEFAULT_TENANT_ID
    ) -> UserViewPreference:
        row = self.get(user_id, view_key, tenant_id)
        if row is None:
            row = UserViewPreference(
                user_id=user_id,
                tenant_id=tenant_id,
                view_key=view_key,
                prefs=prefs,
            )
            self.db.add(row)
        else:
            row.prefs = prefs
        self.db.commit()
        self.db.refresh(row)
        return row
