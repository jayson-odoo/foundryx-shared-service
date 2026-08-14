"""Avatar service (plan sprint-2/06 D4/D5, BL-007).

Stores the client-cropped blob behind the connection-driven StorageService
(tenant → platform → local). The DB keeps a storage KEY + version; the wire
URL is the PUBLIC route (User.avatar property), resolved per request.

Gate = the SNIFFED type (declared content-type is client input): png/jpeg/webp
only - NO SVG (avatars render in many contexts; XSS surface, plan 03 lesson) -
and ≤ 2 MB. The client downscales to 512px, so real payloads are tiny.
"""
import logging
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models.user import User
from app.services.storage import UnresolvableKey, storage_for_tenant
from app.uploads import detect_mime

logger = logging.getLogger(__name__)

AVATAR_MAX_BYTES = 2 * 1024 * 1024
AVATAR_MIMES = ("image/png", "image/jpeg", "image/webp")


class AvatarError(Exception):
    """422 - invalid upload; message is user-safe."""


class AvatarService:
    def __init__(self, db: Session):
        self.db = db

    def set_avatar(self, user: User, content: bytes) -> User:
        if len(content) > AVATAR_MAX_BYTES:
            raise AvatarError("File too large - max 2 MB.")
        detected = detect_mime(content)
        if detected not in AVATAR_MIMES:
            raise AvatarError("Unsupported file type - use PNG, JPG or WebP.")

        storage = storage_for_tenant(self.db, user.tenant_id)
        old_key = user.avatar_key
        user.avatar_key = storage.save(f"avatars/{user.id}", content, detected)
        user.avatar_version = (user.avatar_version or 0) + 1
        self.db.commit()
        self.db.refresh(user)
        # Old blob removed best-effort AFTER commit - a storage hiccup must
        # not 500 a persisted write (branding convention).
        self._delete_blob(user.tenant_id, old_key)
        return user

    def remove_avatar(self, user: User) -> User:
        old_key = user.avatar_key
        user.avatar_key = None
        user.avatar_version = (user.avatar_version or 0) + 1
        self.db.commit()
        self.db.refresh(user)
        self._delete_blob(user.tenant_id, old_key)
        return user

    def resolve(self, user: User) -> Optional[Tuple[str, str]]:
        """Key → ('path'|'url', value) for the public route; None = no avatar
        (or its connection vanished - serve the initials fallback, never 500)."""
        if not user.avatar_key:
            return None
        try:
            return storage_for_tenant(self.db, user.tenant_id).resolve(user.avatar_key)
        except UnresolvableKey:
            logger.warning("avatar key %s unresolvable (connection gone)", user.avatar_key)
            return None

    def _delete_blob(self, tenant_id: str, key: Optional[str]) -> None:
        if not key:
            return
        try:
            storage_for_tenant(self.db, tenant_id).delete(key)
        except Exception:  # noqa: BLE001 - best-effort cleanup only
            logger.warning("could not delete old avatar blob %s", key, exc_info=True)
