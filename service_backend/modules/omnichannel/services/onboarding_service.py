"""Embedded Signup onboarding — exchange the auth code, provision the channel.

FoundryX = Tech Provider: the frontend's Meta popup returns an auth code + WABA/
phone ids; this service exchanges the code for a permanent token (via the channel
adapter), encrypts it, creates the channel, and subscribes the webhook
(best-effort). Plan 04 §5.2.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
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


class PhoneNumberInUse(Exception):
    """The phone_number_id is already bound to another (live) channel service-wide."""


class OnboardingResolveError(Exception):
    """Token exchanged, but no WhatsApp number could be resolved from it."""


def _digits(value: str) -> str:
    return "".join(c for c in (value or "") if c.isdigit())


class OnboardingService:
    def __init__(self, db: Session):
        self.db = db

    def _assert_phone_available(self, phone_number_id: Optional[str]) -> None:
        """A phone_number_id must be unique service-wide (AC-01-20) so inbound
        routing is O(1). This guard is deliberately NOT tenant-scoped."""
        if not phone_number_id:
            return
        clash = (
            self.db.query(Channel)
            .filter(
                Channel.phone_number_id == phone_number_id,
                Channel.is_trashed.is_(False),
            )
            .first()
        )
        if clash is not None:
            raise PhoneNumberInUse(
                "This WhatsApp number is already connected to another workspace."
            )

    def _persist_channel(self, channel: Channel) -> None:
        """Commit a new channel; the partial-unique phone index is the race-proof
        backstop behind ``_assert_phone_available`` — translate its violation to a
        clean 409 instead of a 500."""
        self.db.add(channel)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise PhoneNumberInUse(
                "This WhatsApp number is already connected to another workspace."
            ) from exc
        self.db.refresh(channel)

    def complete(
        self, payload: OnboardingCallbackRequest, tenant_id: str = DEFAULT_TENANT_ID
    ) -> ChannelItem:
        ws = WorkspaceRepository(self.db).get_by_id(payload.workspaceId, tenant_id)
        if ws is None:
            raise WorkspaceNotFound()

        statuses.ensure_statuses(self.db, tenant_id)
        adapter = get_adapter("WHATSAPP")
        credentials = adapter.exchange_code(payload.code, payload.redirectUri)

        # The self-hosted redirect flow sends no waba/phone ids (no postMessage
        # session info) — discover them from the exchanged token. The simulated
        # popup (dev) supplies both, so we only resolve what's missing.
        waba_id = payload.wabaId or None
        phone_number_id = payload.phoneNumberId or None
        resolved: dict = {}
        if not waba_id or not phone_number_id:
            resolved = adapter.resolve_onboarded_assets(credentials)
            waba_id = waba_id or resolved.get("waba_id")
            phone_number_id = phone_number_id or resolved.get("phone_number_id")
        if not phone_number_id:
            raise OnboardingResolveError(
                "Connected to Meta, but no WhatsApp number was found on this account. "
                "Finish WhatsApp setup in Meta Business, then try again."
            )

        # Resolve display number + verified name from Meta when the client didn't
        # supply them (real Embedded Signup hands back only ids).
        details = adapter.fetch_phone_details(credentials, phone_number_id)
        display = (
            payload.displayPhoneNumber
            or details.get("display_phone_number")
            or resolved.get("display_phone_number")
            or phone_number_id
        )
        name = (payload.businessName or details.get("verified_name") or display or "WhatsApp").strip()

        self._assert_phone_available(phone_number_id)

        channel = Channel(
            tenant_id=tenant_id,
            workspace_id=payload.workspaceId,
            channel_type="WHATSAPP",
            name=name,
            credentials_json=encrypt_credentials(credentials),
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            display_phone_number=display,
            is_active=True,
            status_id=statuses.status_id_for(self.db, tenant_id, "CHANNEL", "ACTIVE"),
            last_verified_at=datetime.now(timezone.utc),
        )
        self._persist_channel(channel)

        # Best-effort webhook subscription (no-op in dev / when unconfigured).
        if waba_id:
            callback_url = f"/omnichannel/webhooks/{channel.id}"
            try:
                adapter.subscribe_webhook(credentials, waba_id, callback_url)
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

        self._assert_phone_available(phone_number_id)

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
        self._persist_channel(channel)

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
