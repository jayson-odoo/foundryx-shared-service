"""Consumer webhook endpoints - CRUD + signing-secret issuance (Slice 4, AC-01-22).

A consumer registers one or more callback URLs per CHANNEL (number). We POST a
signed event to each on inbound messages / delivery receipts / contact updates.
The signing secret is Fernet-encrypted at rest (reversible - we sign every
delivery with it) and revealed to the consumer ONLY on create + rotate.

Security invariants:
- Every query is tenant-scoped; the channel must belong to the caller's tenant.
- Callback URLs must be HTTPS and must not target private/loopback hosts (SSRF).

SSRF guard (plan sprint-4/31 S5, D-A5-11/F5): the actual check moved VERBATIM
to ``app/services/url_guard.py`` so the core ``http.request`` workflow action
can share it without core importing a module - this file only DELEGATES and
re-wraps the core error as this module's own ``WebhookError`` so every
existing caller/test keeps working unchanged. ``socket``/``ipaddress`` stay
imported here (not just re-exported) because they are the SAME stdlib module
objects ``url_guard`` uses - a test monkeypatching ``webhook_service.socket``
patches the one shared module, so the guard sees it wherever it runs.
"""
import ipaddress  # noqa: F401 - kept for `ws.ipaddress`-shaped test access + parity
import secrets
import socket  # noqa: F401 - `assert_deliverable`'s DNS guard is monkeypatched via this name
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.services.url_guard import UrlGuardError
from app.services.url_guard import assert_deliverable as _core_assert_deliverable
from app.services.url_guard import validate_public_https_url as _core_validate_url

from ..models import Channel, WebhookDelivery, WebhookEndpoint
from ..security import encrypt_secret

SECRET_SCHEME = "whsec_"

# The event types a consumer can subscribe to (mirrors the forwarder + FE).
EVENT_TYPES = ("message.inbound", "message.status", "contact.updated", "message.reaction")

# Auto-disable after this many consecutive dead-lettered deliveries.
AUTO_DISABLE_THRESHOLD = 10

# Max endpoints per channel. Every inbound message and status receipt fans out
# to ALL of them, so an unbounded count is self-inflicted worker amplification
# - and, on the key-authed public surface, an outbound-request amplifier.
MAX_ENDPOINTS_PER_CHANNEL = 10


class WebhookError(Exception):
    """Validation failure (bad URL, unknown event, channel not found)."""


class WebhookNotFound(Exception):
    pass


def _new_secret() -> str:
    return SECRET_SCHEME + secrets.token_urlsafe(32)


def validate_callback_url(url: str, *, strict_dns: bool = False) -> str:
    """Delegates to the shared core guard (``app/services/url_guard.py``),
    re-raising its ``UrlGuardError`` as this module's own ``WebhookError`` -
    ``subject="Callback URL"`` keeps every pre-extraction 422 message
    byte-identical (review S5; pinned by ``tests/test_omnichannel_consumer_
    webhooks.py``)."""
    try:
        return _core_validate_url(url, strict_dns=strict_dns, subject="Callback URL")
    except UrlGuardError as exc:
        raise WebhookError(str(exc)) from exc


def assert_deliverable(url: str) -> None:
    """Re-check the target IMMEDIATELY before POSTing to it (delegates to the
    shared core guard - see its docstring for the full rationale)."""
    try:
        _core_assert_deliverable(url, subject="Callback URL")
    except UrlGuardError as exc:
        raise WebhookError(str(exc)) from exc


def webhook_endpoint_item(row: "WebhookEndpoint"):
    """Row → wire item. Lives in the service layer so the operator router and
    the public gateway map identically, and neither imports the other."""
    from ..schemas import WebhookEndpointItem

    return WebhookEndpointItem(
        id=row.id,
        tenantId=row.tenant_id,
        workspaceId=row.workspace_id,
        channelId=row.channel_id,
        name=row.name,
        url=row.url,
        events=list(row.events_json or []),
        status=row.status,
        consecutiveFailures=row.consecutive_failures,
        lastSuccessAt=row.last_success_at,
        disabledAt=row.disabled_at,
        disabledReason=row.disabled_reason,
        createdAt=row.created_at,
        updatedAt=row.updated_at,
    )


def _validate_events(events: List[str]) -> List[str]:
    if not events:
        raise WebhookError("Select at least one event type.")
    unknown = [e for e in events if e not in EVENT_TYPES]
    if unknown:
        raise WebhookError(f"Unknown event type(s): {', '.join(unknown)}.")
    # De-dup, preserve canonical order.
    return [e for e in EVENT_TYPES if e in events]


class WebhookService:
    def __init__(self, db: Session):
        self.db = db

    def _channel(self, tenant_id: str, channel_id: str) -> Channel:
        channel = (
            self.db.query(Channel)
            .filter(
                Channel.id == channel_id,
                Channel.tenant_id == tenant_id,
                Channel.is_trashed.is_(False),
            )
            .first()
        )
        if channel is None:
            raise WebhookError("Channel not found.")
        return channel

    def _get(self, tenant_id: str, endpoint_id: str) -> WebhookEndpoint:
        row = (
            self.db.query(WebhookEndpoint)
            .filter(
                WebhookEndpoint.id == endpoint_id,
                WebhookEndpoint.tenant_id == tenant_id,
            )
            .first()
        )
        if row is None:
            raise WebhookNotFound("Webhook endpoint not found.")
        return row

    # ── CRUD ─────────────────────────────────────────────────────────────────
    def create(
        self,
        tenant_id: str,
        channel_id: str,
        name: str,
        url: str,
        events: List[str],
        created_by: Optional[str],
        strict_dns: bool = False,
    ) -> Tuple[WebhookEndpoint, str]:
        """Register an endpoint. Returns (row, plaintext_secret) - the secret is
        shown ONCE for the consumer to configure signature verification."""
        channel = self._channel(tenant_id, channel_id)
        existing = (
            self.db.query(WebhookEndpoint)
            .filter(
                WebhookEndpoint.tenant_id == tenant_id,
                WebhookEndpoint.channel_id == channel.id,
            )
            .count()
        )
        if existing >= MAX_ENDPOINTS_PER_CHANNEL:
            raise WebhookError(
                f"This channel already has the maximum of {MAX_ENDPOINTS_PER_CHANNEL} "
                "webhook endpoints. Delete one before adding another."
            )
        clean_url = validate_callback_url(url, strict_dns=strict_dns)
        clean_events = _validate_events(events)
        secret = _new_secret()
        row = WebhookEndpoint(
            tenant_id=tenant_id,
            workspace_id=channel.workspace_id,
            channel_id=channel.id,
            name=(name or "").strip() or "Webhook",
            url=clean_url,
            secret_encrypted=encrypt_secret(secret),
            events_json=clean_events,
            status="ACTIVE",
            created_by=created_by,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row, secret

    def get_for_workspace(
        self, tenant_id: str, workspace_id: str, endpoint_id: str
    ) -> WebhookEndpoint:
        """Tenant + WORKSPACE scoped fetch - the authorization invariant for any
        caller scoped to one workspace (the gateway's API key).

        `_get` is tenant-scoped only, so a tenant with several workspaces could
        otherwise reach across. This lives in the SERVICE so the guard travels
        with the data access - a future non-HTTP caller inherits it instead of
        re-implementing it. Mismatch raises the SAME `WebhookNotFound` as a
        genuine miss, so the two are indistinguishable (no enumeration)."""
        row = self._get(tenant_id, endpoint_id)
        if row.workspace_id != workspace_id:
            raise WebhookNotFound("Webhook endpoint not found.")
        return row

    def list_for_workspace(self, tenant_id: str, workspace_id: str) -> List[WebhookEndpoint]:
        """Every endpoint in the workspace, across ALL its channels - matching
        what `get_for_workspace` can mutate. Listing by the workspace's active
        channel would hide an endpoint that the per-id routes still reach."""
        return (
            self.db.query(WebhookEndpoint)
            .filter(
                WebhookEndpoint.tenant_id == tenant_id,
                WebhookEndpoint.workspace_id == workspace_id,
            )
            .order_by(WebhookEndpoint.created_at.desc())
            .all()
        )

    def list_for_channel(self, tenant_id: str, channel_id: str) -> List[WebhookEndpoint]:
        self._channel(tenant_id, channel_id)
        return (
            self.db.query(WebhookEndpoint)
            .filter(
                WebhookEndpoint.tenant_id == tenant_id,
                WebhookEndpoint.channel_id == channel_id,
            )
            .order_by(WebhookEndpoint.created_at.desc())
            .all()
        )

    def get(self, tenant_id: str, endpoint_id: str) -> WebhookEndpoint:
        return self._get(tenant_id, endpoint_id)

    def update(
        self,
        tenant_id: str,
        endpoint_id: str,
        name: Optional[str] = None,
        url: Optional[str] = None,
        events: Optional[List[str]] = None,
        strict_dns: bool = False,
    ) -> WebhookEndpoint:
        row = self._get(tenant_id, endpoint_id)
        if name is not None:
            row.name = name.strip() or row.name
        if url is not None:
            row.url = validate_callback_url(url, strict_dns=strict_dns)
        if events is not None:
            row.events_json = _validate_events(events)
        self.db.commit()
        self.db.refresh(row)
        return row

    def rotate_secret(self, tenant_id: str, endpoint_id: str) -> Tuple[WebhookEndpoint, str]:
        row = self._get(tenant_id, endpoint_id)
        secret = _new_secret()
        row.secret_encrypted = encrypt_secret(secret)
        self.db.commit()
        self.db.refresh(row)
        return row, secret

    def set_status(self, tenant_id: str, endpoint_id: str, active: bool) -> WebhookEndpoint:
        """Manual enable/disable. Re-enabling clears the auto-disable state +
        resets the consecutive-failure counter."""
        row = self._get(tenant_id, endpoint_id)
        if active:
            row.status = "ACTIVE"
            row.consecutive_failures = 0
            row.disabled_at = None
            row.disabled_reason = None
        else:
            row.status = "DISABLED"
            row.disabled_at = datetime.now(timezone.utc)
            row.disabled_reason = "Disabled by user."
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, tenant_id: str, endpoint_id: str) -> None:
        row = self._get(tenant_id, endpoint_id)
        self.db.query(WebhookDelivery).filter(
            WebhookDelivery.endpoint_id == row.id,
            WebhookDelivery.tenant_id == tenant_id,
        ).delete(synchronize_session=False)
        self.db.delete(row)
        self.db.commit()

    def list_deliveries(
        self, tenant_id: str, endpoint_id: str, limit: int = 50
    ) -> List[WebhookDelivery]:
        self._get(tenant_id, endpoint_id)  # tenant-scope guard
        return (
            self.db.query(WebhookDelivery)
            .filter(
                WebhookDelivery.tenant_id == tenant_id,
                WebhookDelivery.endpoint_id == endpoint_id,
            )
            .order_by(WebhookDelivery.created_at.desc())
            .limit(min(limit, 200))
            .all()
        )
