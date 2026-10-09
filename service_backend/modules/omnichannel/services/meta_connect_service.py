"""Messenger + Instagram connect flow - plan 32 S3 (A7a).

Two calls (D-A7-15): ``list_pages`` exchanges the popup's OAuth code
server-side and returns the connectable pages (never the token itself - it is
Fernet-encrypted into a short-lived, single-use, tenant-and-user-bound
``MetaConnectSession``, and only its opaque id crosses the wire);
``connect`` spends that session, provisions the channel and subscribes the
app to the page's webhook fields best-effort.

Sources (cited per CLAUDE.md, section 10 of the plan):
- Facebook Login for Business / long-lived token exchange:
  https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived
- `GET /me/accounts` (Pages + linked `instagram_business_account`):
  https://developers.facebook.com/docs/graph-api/reference/user/accounts/
- `POST /{page-id}/subscribed_apps`:
  https://developers.facebook.com/docs/graph-api/reference/page/subscribed_apps/
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.tenant import DEFAULT_TENANT_ID
from ..adapters import get_adapter
from ..models import Channel, MetaConnectSession
from ..repositories.workspace_repository import WorkspaceRepository
from ..schemas import ChannelItem, MetaConnectRequest, MetaPageOption, MetaPagesRequest, MetaPagesResult
from ..security import decrypt_credentials, encrypt_credentials
from . import statuses
from .channel_service import ChannelService
from .onboarding_service import WorkspaceNotFound

# Single-use, 5-minute TTL (D-A7-15) - long enough for a user to pick a page,
# short enough that a stale session is not a meaningful attack surface.
SESSION_TTL_MINUTES = 5

__all__ = [
    "MetaConnectService",
    "WorkspaceNotFound",
    "ConnectSessionNotFound",
    "ConnectSessionExpired",
    "ConnectSessionConsumed",
    "ExternalAccountInUse",
    "PageNotFound",
]


class ConnectSessionNotFound(Exception):
    """No session for this id/tenant/user - a uniform 404 (never leaks that a
    DIFFERENT tenant's or user's session exists)."""


class ConnectSessionExpired(Exception):
    """Typed 400 reason `connect_session_expired`. `str(exc)` (plan 32 / A7a
    S6) is a real human message - the router forwards it verbatim as the
    `detail` string so `ApiError.message` on the frontend is never a bare
    status-line fallback; `.reason` stays available for a future consumer
    that wants to branch on the code instead of the copy."""

    reason = "connect_session_expired"

    def __init__(self) -> None:
        super().__init__("This connection attempt has expired - start again.")


class ConnectSessionConsumed(Exception):
    """Typed 400 reason `connect_session_consumed` (single-use, AC-CHN-33)."""

    reason = "connect_session_consumed"

    def __init__(self) -> None:
        super().__init__("This connection attempt has already been used - start again.")


class ExternalAccountInUse(Exception):
    """Typed 409 reason `external_account_in_use` (AC-CHN-34) - the same
    page/IG account is already bound to a LIVE channel service-wide."""

    reason = "external_account_in_use"

    def __init__(self) -> None:
        super().__init__("This page is already connected to another channel.")


class PageNotFound(Exception):
    """The chosen page (or its linked IG account) is no longer present in the
    re-derived page list - e.g. access was revoked between the two calls."""

    def __init__(self) -> None:
        super().__init__("That page is no longer available - start again.")


class MetaConnectService:
    def __init__(self, db: Session):
        self.db = db

    # ---- helpers ------------------------------------------------------------
    def _sweep_expired(self, tenant_id: str) -> None:
        """Delete this tenant's expired sessions (D-A7-15: "swept on every
        `/pages` call"). A tiny table - no batching needed."""
        now = datetime.now(timezone.utc)
        self.db.query(MetaConnectSession).filter(
            MetaConnectSession.tenant_id == tenant_id,
            MetaConnectSession.expires_at < now,
        ).delete(synchronize_session=False)
        self.db.commit()

    def _assert_external_account_available(self, external_account_id: str) -> None:
        """Service-wide uniqueness (AC-CHN-34), deliberately NOT tenant-scoped
        - byte-for-byte `OnboardingService._assert_phone_available`'s
        `phone_number_id` guard, so inbound routing stays O(1) and
        unambiguous no matter which tenant already owns the page."""
        clash = (
            self.db.query(Channel)
            .filter(
                Channel.external_account_id == external_account_id,
                Channel.is_trashed.is_(False),
            )
            .first()
        )
        if clash is not None:
            raise ExternalAccountInUse()

    def _persist_channel(self, channel: Channel) -> None:
        """Commit; the partial-unique `external_account_id` index (migration
        0017) is the race-proof backstop behind `_assert_external_account_
        available` - translate its violation to a clean 409, not a 500."""
        self.db.add(channel)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ExternalAccountInUse() from exc
        self.db.refresh(channel)

    def _page_options(
        self, raw_pages: List[Dict[str, Any]], channel_type: str
    ) -> List[MetaPageOption]:
        in_use = self._external_ids_in_use()
        options: List[MetaPageOption] = []
        for p in raw_pages:
            ig = p.get("instagram_business_account") or {}
            ig_id = ig.get("id")
            if channel_type == "INSTAGRAM" and not ig_id:
                # D-A7-14/44: only page-linked IG accounts are offered - a
                # page missing one is not offered at all for Instagram.
                continue
            account_id = ig_id if channel_type == "INSTAGRAM" else p.get("id")
            options.append(
                MetaPageOption(
                    id=p.get("id", ""),
                    name=p.get("name", ""),
                    connected=bool(account_id) and account_id in in_use,
                    igAccountId=ig_id,
                    igUsername=ig.get("username"),
                )
            )
        return options

    def _external_ids_in_use(self) -> set:
        rows = (
            self.db.query(Channel.external_account_id)
            .filter(Channel.external_account_id.isnot(None), Channel.is_trashed.is_(False))
            .all()
        )
        return {r[0] for r in rows}

    # ---- the two calls --------------------------------------------------------
    def list_pages(
        self, payload: MetaPagesRequest, tenant_id: str = DEFAULT_TENANT_ID, user_id: str = ""
    ) -> MetaPagesResult:
        self._sweep_expired(tenant_id)

        adapter = get_adapter(payload.channelType)
        credentials = adapter.exchange_code(payload.code, payload.redirectUri)
        if not credentials.get("dev"):
            # Long-lived so the Page tokens `list_pages` returns are
            # effectively non-expiring (see module docstring). Dev/
            # unconfigured is already a no-op inside the adapter method.
            credentials = adapter.exchange_long_lived_token(credentials)
        raw_pages = adapter.list_pages(credentials)

        now = datetime.now(timezone.utc)
        session = MetaConnectSession(
            tenant_id=tenant_id,
            user_id=user_id,
            channel_type=payload.channelType,
            credentials_json=encrypt_credentials(credentials),
            created_at=now,
            expires_at=now + timedelta(minutes=SESSION_TTL_MINUTES),
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        return MetaPagesResult(
            sessionId=session.id,
            expiresAt=session.expires_at,
            pages=self._page_options(raw_pages, payload.channelType),
        )

    def connect(
        self, payload: MetaConnectRequest, tenant_id: str = DEFAULT_TENANT_ID, user_id: str = ""
    ) -> ChannelItem:
        ws = WorkspaceRepository(self.db).get_by_id(payload.workspaceId, tenant_id)
        if ws is None:
            raise WorkspaceNotFound()

        session = (
            self.db.query(MetaConnectSession)
            .filter(
                MetaConnectSession.id == payload.sessionId,
                MetaConnectSession.tenant_id == tenant_id,
                MetaConnectSession.user_id == user_id,
            )
            .first()
        )
        if session is None:
            raise ConnectSessionNotFound()
        now = datetime.now(timezone.utc)
        if session.consumed_at is not None:
            raise ConnectSessionConsumed()
        if session.expires_at < now:
            raise ConnectSessionExpired()

        # Atomic single-use claim (AC-CHN-33; security review round 1,
        # should-fix). `_persist_channel()` used to be the ONLY place
        # `consumed_at` got stamped, at the very end - two concurrent
        # `/meta/connect` calls on one session could both pass the read
        # above before either committed, and (naming DIFFERENT pages) both
        # succeed: two channels from one single-use session. Claim it with a
        # conditional UPDATE BEFORE any provisioning work; a rowcount of 0
        # means another request already claimed it. Cleared on the error
        # path below (a FAILED attempt - e.g. `external_account_in_use` -
        # still allows a retry with a different page; only a SUCCESSFUL
        # connect actually spends the session).
        claimed = (
            self.db.query(MetaConnectSession)
            .filter(
                MetaConnectSession.id == session.id,
                MetaConnectSession.consumed_at.is_(None),
            )
            .update({"consumed_at": now}, synchronize_session=False)
        )
        self.db.commit()
        if claimed == 0:
            raise ConnectSessionConsumed()

        try:
            statuses.ensure_statuses(self.db, tenant_id)
            user_credentials = decrypt_credentials(session.credentials_json)
            adapter = get_adapter(payload.channelType)
            raw_pages = adapter.list_pages(user_credentials)
            page = next((p for p in raw_pages if p.get("id") == payload.pageId), None)
            if page is None:
                raise PageNotFound()

            ig = page.get("instagram_business_account") or {}
            if payload.channelType == "INSTAGRAM":
                # The server-derived page is the ONLY source of truth for
                # which IG account is being connected (polymorphic-stored-id
                # rule - this id becomes the unauthenticated webhook routing
                # key, `InboundService._resolve_channel`). A client
                # `igAccountId` is accepted only when it MATCHES the page's
                # own linked account; anything else (including one the
                # caller does not administer) is refused rather than
                # trusted - never let it win over the server-derived value.
                external_account_id = ig.get("id")
                if not external_account_id or (
                    payload.igAccountId and payload.igAccountId != external_account_id
                ):
                    raise PageNotFound()
                external_account_name = ig.get("username") or page.get("name") or "Instagram"
            else:
                external_account_id = page.get("id")
                external_account_name = page.get("name") or "Facebook Page"

            self._assert_external_account_available(external_account_id)

            # The channel's OWN credentials are the PAGE access token (never
            # the connect session's user token) - `send`/`test_connection`/
            # `subscribe_webhook` all take a page-scoped credential from
            # here on.
            channel_credentials: Dict[str, Any] = {"access_token": page.get("access_token", "")}
            if user_credentials.get("dev"):
                channel_credentials["dev"] = True

            channel = Channel(
                tenant_id=tenant_id,
                workspace_id=payload.workspaceId,
                channel_type=payload.channelType,
                name=external_account_name,
                credentials_json=encrypt_credentials(channel_credentials),
                external_account_id=external_account_id,
                external_account_name=external_account_name,
                is_active=True,
                status_id=statuses.status_id_for(self.db, tenant_id, "CHANNEL", "ACTIVE"),
                last_verified_at=now,
            )
            self._persist_channel(channel)
        except Exception:
            session.consumed_at = None
            self.db.commit()
            raise

        # Best-effort subscribed_apps (AC-CHN-33) - ALWAYS the Facebook Page
        # id, even for an Instagram channel (IG messaging is page-linked,
        # D-A7-14/45); a failure never blocks the connect, and never spends
        # the session back to unconsumed - the channel already exists.
        try:
            adapter.subscribe_webhook(
                channel_credentials, payload.pageId, f"/omnichannel/webhooks/{channel.id}"
            )
        except Exception:  # noqa: BLE001 - subscription failure shouldn't block onboarding
            pass

        return ChannelService(self.db)._items([channel], tenant_id)[0]
