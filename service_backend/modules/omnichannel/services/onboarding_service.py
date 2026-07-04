"""Embedded Signup onboarding — exchange the auth code, provision the channel.

FoundryX = Tech Provider: the frontend's Meta popup returns an auth code + WABA/
phone ids; this service exchanges the code for a permanent token (via the channel
adapter), encrypts it, creates the channel, and subscribes the webhook
(best-effort). Plan 04 §5.2.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.tenant import DEFAULT_TENANT_ID
from ..adapters.whatsapp_cloud import get_adapter
from ..models import Channel
from ..repositories.workspace_repository import WorkspaceRepository
from ..schemas import ChannelItem, ManualConnectRequest, OnboardingCallbackRequest
from ..security import encrypt_credentials
from .channel_service import ChannelService
from . import statuses


class WorkspaceNotFound(Exception):
    pass


class ManualConnectError(Exception):
    """Manual connect failed (bad token, unresolved number, or failed validation)."""


def _digits(value: str) -> str:
    return "".join(c for c in (value or "") if c.isdigit())


class OnboardingService:
    def __init__(self, db: Session):
        self.db = db

    def complete(
        self, payload: OnboardingCallbackRequest, tenant_id: str = DEFAULT_TENANT_ID
    ) -> ChannelItem:
        ws = WorkspaceRepository(self.db).get_by_id(payload.workspaceId, tenant_id)
        if ws is None:
            raise WorkspaceNotFound()

        statuses.ensure_statuses(self.db, tenant_id)
        adapter = get_adapter("WHATSAPP")
        credentials = adapter.exchange_code(payload.code)

        # Resolve display number + verified name from Meta when the client didn't
        # supply them (real Embedded Signup hands back only ids).
        details = adapter.fetch_phone_details(credentials, payload.phoneNumberId)
        display = payload.displayPhoneNumber or details.get("display_phone_number") or payload.phoneNumberId
        name = (payload.businessName or details.get("verified_name") or display or "WhatsApp").strip()

        channel = Channel(
            tenant_id=tenant_id,
            workspace_id=payload.workspaceId,
            channel_type="WHATSAPP",
            name=name,
            credentials_json=encrypt_credentials(credentials),
            waba_id=payload.wabaId,
            phone_number_id=payload.phoneNumberId,
            display_phone_number=display,
            is_active=True,
            status_id=statuses.status_id_for(self.db, tenant_id, "CHANNEL", "ACTIVE"),
            last_verified_at=datetime.now(timezone.utc),
        )
        self.db.add(channel)
        self.db.commit()
        self.db.refresh(channel)

        # Best-effort webhook subscription (no-op in dev / when unconfigured).
        callback_url = f"/omnichannel/webhooks/{channel.id}"
        try:
            adapter.subscribe_webhook(credentials, payload.wabaId, callback_url)
        except Exception:  # noqa: BLE001 — subscription failure shouldn't block onboarding
            pass

        return ChannelService(self.db)._items([channel], tenant_id)[0]

    def manual_connect(
        self, payload: ManualConnectRequest, tenant_id: str = DEFAULT_TENANT_ID
    ) -> ChannelItem:
        ws = WorkspaceRepository(self.db).get_by_id(payload.workspaceId, tenant_id)
        if ws is None:
            raise WorkspaceNotFound()

        statuses.ensure_statuses(self.db, tenant_id)
        adapter = get_adapter("WHATSAPP")
        credentials = {"access_token": payload.accessToken}

        # Resolve the phone_number_id: provided directly, or from wabaId + phone.
        phone_number_id = payload.phoneNumberId
        if not phone_number_id and payload.wabaId and payload.phoneNumber:
            wanted = _digits(payload.phoneNumber)
            for num in adapter.list_waba_numbers(credentials, payload.wabaId):
                if _digits(num.get("display_phone_number", "")) == wanted:
                    phone_number_id = num.get("id")
                    break
        if not phone_number_id:
            raise ManualConnectError(
                "Provide a Phone Number ID (or a WABA ID + phone number we can resolve)."
            )

        # Validate the token + number actually reach Meta before storing.
        status = adapter.test_connection(credentials, phone_number_id)
        if not status.ok:
            raise ManualConnectError(status.message)

        details = adapter.fetch_phone_details(credentials, phone_number_id)
        display = details.get("display_phone_number") or payload.phoneNumber or phone_number_id
        name = (details.get("verified_name") or display or "WhatsApp").strip()

        channel = Channel(
            tenant_id=tenant_id,
            workspace_id=payload.workspaceId,
            channel_type="WHATSAPP",
            name=name,
            credentials_json=encrypt_credentials(credentials),
            waba_id=payload.wabaId,
            phone_number_id=phone_number_id,
            display_phone_number=display,
            is_active=True,
            status_id=statuses.status_id_for(self.db, tenant_id, "CHANNEL", "ACTIVE"),
            last_verified_at=datetime.now(timezone.utc),
        )
        self.db.add(channel)
        self.db.commit()
        self.db.refresh(channel)

        # Best-effort WABA webhook subscription (same as the ES path) — without
        # it Meta never delivers inbound messages for this number.
        if payload.wabaId:
            try:
                adapter.subscribe_webhook(
                    credentials, payload.wabaId, f"/omnichannel/webhooks/{channel.id}"
                )
            except Exception:  # noqa: BLE001 — subscription failure shouldn't block onboarding
                pass

        return ChannelService(self.db)._items([channel], tenant_id)[0]
