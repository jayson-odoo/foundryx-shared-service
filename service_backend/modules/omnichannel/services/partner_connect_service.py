"""Partner connect sessions (FSS-1): a partner key starts a hosted WhatsApp
connect for one workspace of its client app, and finishes it in two steps.

1. ``create`` checks the return URL against the calling key's
   ``allowed_return_origins`` and returns the Meta Embedded Signup dialog URL,
   built here on the server with a fresh single-use ``state`` (only its sha256
   is stored).
2. ``callback`` (public, the existing ``/wa-callback`` page posts to it)
   claims the state once, exchanges the code with the redirect URI from server
   config (never from the request), stores the token Fernet-encrypted, sets
   ``AUTHORIZED`` and answers the redirect built from the STORED return URL.
   No channel is created here.
3. ``complete`` (partner key) creates one channel per number of the Meta
   account that is not connected anywhere yet, then clears the token.

The feature is off (``ConnectNotConfigured`` -> 503) until
``OMNI_PARTNER_WA_REDIRECT_URI`` is set. With ``META_APP_ID`` unset the flow
runs as a LOCAL SIMULATION: the dialog URL points straight at the redirect URI
with ``code=dev``, the adapter's existing dev token is used and
``list_onboarded_numbers`` returns one fake number. The simulation can never
run while ``META_APP_ID`` is set: real mode then needs every Meta setting, and
dev credentials are refused at callback and at completion.

Nothing here changes ``OnboardingService`` or the adapter's existing methods;
``_assert_phone_available`` and ``_persist_channel`` are called as they are.
Logs carry session ids and outcomes only, never a state, code or token.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.config import settings

from ..adapters.whatsapp_cloud import get_adapter
from ..models import Channel, PartnerConnectSession
from ..origins import InvalidOrigin, _validate_origin
from ..partner_auth import partner_tenant_enabled
from ..repositories.partner_connect_session_repository import PartnerConnectSessionRepository
from ..schemas import (
    PartnerConnectSessionCompleteResponse,
    PartnerConnectSessionCreated,
    PartnerConnectSessionItem,
    PublicChannelItem,
)
from ..security import decrypt_credentials, encrypt_credentials
from . import statuses
from .channel_events import emit_channel_updated
from .client_app_service import STATUS_ACTIVE
from .onboarding_service import OnboardingService, PhoneNumberInUse
from .partner_workspace_service import PartnerScope, PartnerWorkspaceService
from .public_gateway_service import PublicGatewayService

logger = logging.getLogger(__name__)

ES_EXTRAS = '{"setup":{},"featureType":"","sessionInfoVersion":"3"}'
SIM_CODE = "dev"
MAX_RETURN_URL = 2048
COMPLETE_LEASE = timedelta(minutes=5)
CALLBACK_OUTCOMES = {"AUTHORIZED": "authorized", "CANCELLED": "cancelled", "FAILED": "failed"}


class ConnectNotConfigured(Exception):
    pass


class ConnectSessionNotFound(Exception):
    pass


class InvalidReturnUrl(Exception):
    pass


class ConnectSessionNotAuthorized(Exception):
    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_state(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _stale_before(now: datetime) -> datetime:
    """A completion claim older than this has died; another may take it over."""
    return now - COMPLETE_LEASE


def simulation_active() -> bool:
    """The local simulation runs only while the Meta app id is unset."""
    return not settings.meta_app_id


def assert_configured() -> None:
    """Raise ``ConnectNotConfigured`` unless the feature is switched on."""
    if not settings.omni_partner_wa_redirect_uri:
        raise ConnectNotConfigured()
    if simulation_active():
        return
    if not (
        settings.meta_app_secret and settings.meta_es_config_id and settings.meta_es_dialog_version
    ):
        raise ConnectNotConfigured()


def check_return_url(raw: str, allowed: Optional[list]) -> str:
    """The return URL, unchanged, when its exact origin is on the key's
    allow-list (an empty or missing list refuses everything)."""
    value = raw or ""
    if not value or len(value) > MAX_RETURN_URL or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise InvalidReturnUrl()
    parts = urlsplit(value)
    if parts.username is not None or parts.password is not None or parts.fragment:
        raise InvalidReturnUrl()
    try:
        origin = _validate_origin(f"{parts.scheme}://{parts.netloc}")
    except (InvalidOrigin, ValueError):
        raise InvalidReturnUrl()
    permitted = set()
    for item in allowed or []:
        try:
            permitted.add(_validate_origin(str(item)))
        except InvalidOrigin:
            continue
    if origin not in permitted:
        raise InvalidReturnUrl()
    return value


def build_redirect(return_url: str, session_id: str, outcome: str, client_state: Optional[str]) -> str:
    """The stored return URL with ``session``, ``status`` and (when set)
    ``state`` merged into its query; any earlier values of those keys go."""
    parts = urlsplit(return_url)
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in ("session", "status", "state")
    ]
    query.append(("session", session_id))
    query.append(("status", outcome))
    if client_state:
        query.append(("state", client_state))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def build_dialog_url(raw_state: str) -> str:
    redirect_uri = settings.omni_partner_wa_redirect_uri
    if simulation_active():
        sep = "&" if "?" in redirect_uri else "?"
        return f"{redirect_uri}{sep}{urlencode({'state': raw_state, 'code': SIM_CODE})}"
    return (
        f"https://www.facebook.com/{quote(settings.meta_es_dialog_version, safe='.')}/dialog/oauth"
        f"?client_id={quote(settings.meta_app_id, safe='')}"
        f"&config_id={quote(settings.meta_es_config_id, safe='')}"
        "&response_type=code"
        "&override_default_response_type=true"
        f"&redirect_uri={quote(redirect_uri, safe='')}"
        f"&state={quote(raw_state, safe='')}"
        f"&extras={quote(ES_EXTRAS, safe='')}"
    )


class PartnerConnectService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = PartnerConnectSessionRepository(db)

    # ---- shapes ----
    def item(self, row: PartnerConnectSession) -> PartnerConnectSessionItem:
        return PartnerConnectSessionItem(**self._fields(row))

    def _fields(self, row: PartnerConnectSession) -> dict:
        return {
            "id": row.id,
            "workspaceId": row.workspace_id,
            "channelType": row.channel_type,
            "status": row.status,
            "channelIds": list(row.result_channel_ids or []),
            "errorCode": row.error_code,
            "createdAt": row.created_at,
            "expiresAt": row.expires_at,
            # Set while a completion runs; only shown once the session ended.
            "completedAt": row.completed_at
            if row.status in ("COMPLETED", "FAILED", "CANCELLED")
            else None,
        }

    def _channels(self, row: PartnerConnectSession) -> List[PublicChannelItem]:
        gateway = PublicGatewayService(self.db)
        rows = self.repo.get_channels(row.result_channel_ids or [], row.tenant_id, row.workspace_id)
        return [gateway.public_channel_item(c) for c in rows if not c.is_trashed]

    def completion(self, row: PartnerConnectSession) -> PartnerConnectSessionCompleteResponse:
        return PartnerConnectSessionCompleteResponse(**self._fields(row), channels=self._channels(row))

    # ---- partner: create / get / cancel ----
    def create(
        self,
        scope: PartnerScope,
        key_id: str,
        workspace_id: str,
        channel_type: str,
        return_url: str,
        client_state: Optional[str],
    ) -> PartnerConnectSessionCreated:
        assert_configured()
        ws = PartnerWorkspaceService(self.db).require(scope, workspace_id)
        key = self.repo.get_partner_key(key_id, scope.tenant_id)
        allowed = key.allowed_return_origins if key is not None else None
        url = check_return_url(return_url, allowed)
        now = _now()
        self.repo.expire_due(now, tenant_id=scope.tenant_id, stale_before=_stale_before(now))
        raw_state = secrets.token_urlsafe(32)
        ttl = max(1, int(settings.partner_connect_session_ttl_minutes or 30))
        row = self.repo.add(
            PartnerConnectSession(
                tenant_id=scope.tenant_id,
                client_app_id=scope.client_app_id,
                workspace_id=ws.id,
                partner_key_id=key_id,
                state_hash=_hash_state(raw_state),
                channel_type=channel_type,
                return_url=url,
                client_state=client_state or None,
                status="OPEN",
                expires_at=now + timedelta(minutes=ttl),
            )
        )
        logger.info("partner connect session %s created (simulation=%s)", row.id, simulation_active())
        return PartnerConnectSessionCreated(
            id=row.id,
            workspaceId=row.workspace_id,
            status=row.status,
            url=build_dialog_url(raw_state),
            expiresAt=row.expires_at,
        )

    def get(self, scope: PartnerScope, session_id: str) -> PartnerConnectSession:
        assert_configured()
        row = self.repo.get_scoped(session_id, scope.tenant_id, scope.client_app_id)
        if row is None:
            raise ConnectSessionNotFound()
        now = _now()
        if self.repo.expire_due(now, session_id=row.id, stale_before=_stale_before(now)):
            self.db.refresh(row)
        return row

    def cancel(self, scope: PartnerScope, session_id: str) -> PartnerConnectSession:
        row = self.get(scope, session_id)
        now = _now()
        if self.repo.cancel_live(row.id, now, stale_before=_stale_before(now)):
            logger.info("partner connect session %s cancelled", row.id)
        self.db.refresh(row)
        return row

    # ---- public: the Meta callback ----
    def callback(self, state: str, code: Optional[str], error: Optional[str]) -> str:
        """Claim the state once and answer the redirect. Raises
        ``ConnectSessionNotFound`` for an unknown, used or expired state and
        for a session whose scope is no longer usable."""
        assert_configured()
        row = self.repo.get_by_state_hash(_hash_state(state))
        if row is None or row.status != "OPEN" or row.claimed_at is not None:
            raise ConnectSessionNotFound()
        now = _now()
        if _aware(row.expires_at) <= now:
            self.repo.expire_due(now, session_id=row.id)
            raise ConnectSessionNotFound()
        if not self._scope_usable(row):
            raise ConnectSessionNotFound()
        if not self.repo.claim_callback(row.id, now):
            raise ConnectSessionNotFound()
        self.db.refresh(row)

        if error or not code:
            self._finish_callback(row, {"status": "CANCELLED", "error_code": None, "completed_at": _now()})
            logger.info("partner connect session %s cancelled at Meta", row.id)
            return self._callback_redirect(row)

        try:
            credentials = get_adapter("WHATSAPP").exchange_code(
                code, settings.omni_partner_wa_redirect_uri
            )
        except Exception as exc:  # noqa: BLE001 - any exchange failure ends the session
            logger.warning("partner connect session %s code exchange failed (%s)", row.id, type(exc).__name__)
            credentials = None
        if credentials and credentials.get("dev") and not simulation_active():
            # Never store a dev token while a real Meta app is configured.
            credentials = None
        if not credentials or not credentials.get("access_token"):
            self._finish_callback(
                row, {"status": "FAILED", "error_code": "code_exchange_failed", "completed_at": _now()}
            )
            return self._callback_redirect(row)

        if credentials.get("dev"):
            credentials = {**credentials, "dev_seed": row.id}
        if self._finish_callback(
            row, {"status": "AUTHORIZED", "credentials_json": encrypt_credentials(credentials)}
        ):
            logger.info("partner connect session %s authorized", row.id)
        return self._callback_redirect(row)

    def _finish_callback(self, row: PartnerConnectSession, values: dict) -> bool:
        """The callback's outcome, written only while the session is still OPEN
        and claimed. A session cancelled or expired meanwhile keeps that end
        and never receives a token."""
        written = self.repo.finish_callback(row.id, {"credentials_json": None, **values})
        if not written:
            logger.info("partner connect session %s ended during the callback", row.id)
        self.db.refresh(row)
        return written

    def _callback_redirect(self, row: PartnerConnectSession) -> str:
        outcome = CALLBACK_OUTCOMES.get(row.status)
        if outcome is None:
            raise ConnectSessionNotFound()
        return build_redirect(row.return_url, row.id, outcome, row.client_state)

    def _scope_usable(self, row: PartnerConnectSession) -> bool:
        app = self.repo.get_client_app(row.client_app_id, row.tenant_id)
        if app is None or app.status != STATUS_ACTIVE:
            return False
        if self.repo.get_live_workspace(row.workspace_id, row.tenant_id, row.client_app_id) is None:
            return False
        return partner_tenant_enabled(self.db, row.tenant_id)

    def _finish(self, row: PartnerConnectSession, status: str, error_code: Optional[str]) -> None:
        row.status = status
        row.error_code = error_code
        row.credentials_json = None
        row.completed_at = _now()
        self.repo.save(row)

    # ---- partner: complete ----
    def complete(self, scope: PartnerScope, session_id: str) -> PartnerConnectSession:
        row = self.get(scope, session_id)
        if row.status == "COMPLETED":
            return row  # idempotent: a retry gets the same result
        if row.status != "AUTHORIZED":
            raise ConnectSessionNotAuthorized(row.status)
        if not self._scope_usable(row):
            raise ConnectSessionNotFound()
        now = _now()
        if not self.repo.claim_complete(row.id, now, stale_before=_stale_before(now)):
            self.db.refresh(row)
            if row.status == "COMPLETED":
                return row
            raise ConnectSessionNotAuthorized(row.status)
        self.db.refresh(row)
        try:
            self._provision(row)
        except Exception:
            self.db.rollback()
            self.repo.release_complete(row.id)
            raise
        self.db.refresh(row)
        return row

    def _provision(self, row: PartnerConnectSession) -> None:
        credentials = decrypt_credentials(row.credentials_json) if row.credentials_json else {}
        if not credentials or (credentials.get("dev") and not simulation_active()):
            self._finish(row, "FAILED", "code_exchange_failed")
            return
        channel_credentials = {k: v for k, v in credentials.items() if k != "dev_seed"}
        adapter = get_adapter("WHATSAPP")
        numbers = adapter.list_onboarded_numbers(credentials)
        # Channels an earlier, interrupted attempt of this session already made.
        created: List[Channel] = [
            c
            for c in self.repo.get_channels(row.result_channel_ids or [], row.tenant_id, row.workspace_id)
            if not c.is_trashed
        ]
        if not numbers and not created:
            self._finish(row, "FAILED", "no_number_found")
            logger.info("partner connect session %s found no number", row.id)
            return

        statuses.ensure_statuses(self.db, row.tenant_id)
        onboarding = OnboardingService(self.db)
        skipped = 0
        seen = {c.phone_number_id for c in created if c.phone_number_id}
        for num in numbers or []:
            phone_number_id = num.get("phone_number_id")
            if not phone_number_id or phone_number_id in seen:
                continue
            seen.add(phone_number_id)
            try:
                onboarding._assert_phone_available(phone_number_id)
            except PhoneNumberInUse:
                skipped += 1
                continue
            details = adapter.fetch_phone_details(channel_credentials, phone_number_id) or {}
            display = (
                details.get("display_phone_number")
                or num.get("display_phone_number")
                or phone_number_id
            )
            name = (details.get("verified_name") or num.get("verified_name") or display or "WhatsApp").strip()
            channel = Channel(
                tenant_id=row.tenant_id,
                workspace_id=row.workspace_id,
                channel_type="WHATSAPP",
                name=name,
                credentials_json=encrypt_credentials(channel_credentials),
                waba_id=num.get("waba_id"),
                phone_number_id=phone_number_id,
                display_phone_number=display,
                is_active=True,
                status_id=statuses.status_id_for(self.db, row.tenant_id, "CHANNEL", "ACTIVE"),
                last_verified_at=_now(),
            )
            try:
                onboarding._persist_channel(channel)
            except PhoneNumberInUse:
                skipped += 1
                continue
            self.repo.record_channel(row.id, channel.id)
            created.append(channel)

        subscribed = set()
        for channel in created:
            if channel.waba_id and channel.waba_id not in subscribed:
                subscribed.add(channel.waba_id)
                try:
                    adapter.subscribe_webhook(
                        channel_credentials, channel.waba_id, f"/omnichannel/webhooks/{channel.id}"
                    )
                except Exception:  # noqa: BLE001 - subscription failure never blocks the connect
                    pass
        for channel in created:
            emit_channel_updated(self.db, channel)

        if not created:
            self._finish(row, "FAILED", "phone_number_in_use")
            logger.info("partner connect session %s: every number already connected", row.id)
            return
        self.db.refresh(row)
        row.result_channel_ids = [c.id for c in created]
        self._finish(row, "COMPLETED", None)
        logger.info(
            "partner connect session %s completed: %d channel(s), %d skipped",
            row.id,
            len(created),
            skipped,
        )
