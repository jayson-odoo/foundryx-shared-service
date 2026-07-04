"""WABA configuration + WhatsApp Business Profile logic (plan 06 Slice A).

Meta is system-of-record; FoundryX mirrors locally and syncs on demand. Editable
profile fields are write-through: POST to Meta first, refresh the local mirror
only on success (SEC-5 write-through atomicity). Tenant-scoped throughout.
"""
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.tenant import DEFAULT_TENANT_ID
from ..adapters.base import SendError
from ..adapters.whatsapp_cloud import get_adapter
from ..models import Channel
from ..repositories.channel_repository import ChannelRepository
from ..schemas import ChannelItem, ChannelProfileOut, ChannelProfileUpdate
from ..security import decrypt_credentials
from ..verticals import WHATSAPP_VERTICAL_SET
from .channel_service import ChannelNotFound, ChannelService

# Lightweight shapes — Meta does the authoritative validation; we reject the
# obvious garbage before spending a Graph call.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _field_error(field: str, message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"fieldErrors": {field: message}},
    )


class ChannelProfileService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ChannelRepository(db)

    # ---- helpers ----
    def _channel(self, channel_id: str, tenant_id: str) -> Channel:
        c = self.repo.get_by_id(channel_id, tenant_id)
        if c is None:
            raise ChannelNotFound()
        return c

    def _credentials(self, c: Channel) -> dict:
        return decrypt_credentials(c.credentials_json) if c.credentials_json else {}

    def _profile_out(self, c: Channel) -> ChannelProfileOut:
        return ChannelProfileOut(
            about=c.profile_about,
            address=c.profile_address,
            description=c.profile_description,
            email=c.profile_email,
            vertical=c.profile_vertical,
            website1=c.profile_website_1,
            website2=c.profile_website_2,
            profilePictureUrl=c.profile_picture_url,
            profileSyncedAt=c.profile_synced_at,
        )

    def _channel_item(self, c: Channel, tenant_id: str) -> ChannelItem:
        # Reuse the ChannelService mapper so a synced channel renders identically
        # everywhere (status/workspace resolution included).
        return ChannelService(self.db)._items([c], tenant_id)[0]

    # ---- configuration ----
    def sync_config(self, channel_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> ChannelItem:
        """Pull phone + WABA identity from Meta, stamp last_verified_at."""
        c = self._channel(channel_id, tenant_id)
        creds = self._credentials(c)
        adapter = get_adapter(c.channel_type)
        phone = adapter.fetch_phone_details(creds, c.phone_number_id or "")
        waba = adapter.fetch_waba_details(creds, c.waba_id or "")
        if phone.get("display_phone_number"):
            c.display_phone_number = phone["display_phone_number"]
        if phone.get("verified_name"):
            c.verified_name = phone["verified_name"]
        if waba.get("name"):
            c.business_account_name = waba["name"]
        c.last_verified_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(c)
        return self._channel_item(c, tenant_id)

    # ---- profile ----
    def get_profile(self, channel_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> ChannelProfileOut:
        """Render the mirrored profile from the DB — no Meta call (instant)."""
        return self._profile_out(self._channel(channel_id, tenant_id))

    def sync_profile(self, channel_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> ChannelProfileOut:
        """Pull the latest profile from Meta into the local mirror."""
        c = self._channel(channel_id, tenant_id)
        data = get_adapter(c.channel_type).get_business_profile(
            self._credentials(c), c.phone_number_id or ""
        )
        c.profile_about = data.get("about")
        c.profile_address = data.get("address")
        c.profile_description = data.get("description")
        c.profile_email = data.get("email")
        c.profile_vertical = data.get("vertical")
        websites = data.get("websites") or []
        c.profile_website_1 = websites[0] if len(websites) > 0 else None
        c.profile_website_2 = websites[1] if len(websites) > 1 else None
        c.profile_picture_url = data.get("profile_picture_url")
        c.profile_synced_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(c)
        return self._profile_out(c)

    def save_profile(
        self, channel_id: str, payload: ChannelProfileUpdate, tenant_id: str = DEFAULT_TENANT_ID
    ) -> ChannelProfileOut:
        """Validate → POST changed fields to Meta → refresh local on success."""
        c = self._channel(channel_id, tenant_id)

        # ── validation (422 per-field) ──
        if payload.vertical is not None and payload.vertical not in WHATSAPP_VERTICAL_SET:
            raise _field_error("vertical", "Not a valid WhatsApp business vertical.")
        if payload.email is not None and payload.email.strip() and not _EMAIL_RE.match(payload.email.strip()):
            raise _field_error("email", "Enter a valid email address.")
        for fld in ("website1", "website2"):
            val = getattr(payload, fld)
            if val is not None and val.strip() and not _URL_RE.match(val.strip()):
                raise _field_error(fld, "Enter a valid URL starting with http:// or https://.")

        # ── diff: only send what changed (BR-6) ──
        current = {
            "about": c.profile_about,
            "address": c.profile_address,
            "description": c.profile_description,
            "email": c.profile_email,
            "vertical": c.profile_vertical,
            "website1": c.profile_website_1,
            "website2": c.profile_website_2,
        }
        provided = payload.model_dump(exclude_unset=True)

        def _norm(v: Optional[str]) -> Optional[str]:
            if v is None:
                return None
            v = v.strip()
            return v or None

        changed = {k: _norm(v) for k, v in provided.items() if _norm(v) != current.get(k)}
        if not changed:
            return self._profile_out(c)

        # ── Meta write-through: build the Graph payload (websites → list) ──
        # A cleared field (v is None) must be sent as "" so Graph CLEARS it —
        # omitting it would leave Meta's old value while we null it locally,
        # diverging the mirror (SEC-5). Websites are handled as a list below.
        meta_fields: dict = {}
        for k, v in changed.items():
            if k in ("website1", "website2"):
                continue
            meta_fields[k] = v if v is not None else ""
        if "website1" in changed or "website2" in changed:
            w1 = changed.get("website1", current.get("website1"))
            w2 = changed.get("website2", current.get("website2"))
            meta_fields["websites"] = [w for w in (w1, w2) if w]

        try:
            get_adapter(c.channel_type).update_business_profile(
                self._credentials(c), c.phone_number_id or "", meta_fields
            )
        except SendError as exc:
            # Meta rejected — leave the local mirror untouched (SEC-5), surface
            # the reason as a recoverable 502 (GP-5).
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))

        # ── Meta confirmed → refresh local mirror ──
        col_map = {
            "about": "profile_about",
            "address": "profile_address",
            "description": "profile_description",
            "email": "profile_email",
            "vertical": "profile_vertical",
            "website1": "profile_website_1",
            "website2": "profile_website_2",
        }
        for k, v in changed.items():
            setattr(c, col_map[k], v)
        self.db.commit()
        self.db.refresh(c)
        return self._profile_out(c)
