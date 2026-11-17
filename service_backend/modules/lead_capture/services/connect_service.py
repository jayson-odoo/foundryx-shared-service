"""Connect a Facebook Page as a lead source (plan 64 AC-64-25/36/71, owner D2/D13).

``connect_facebook`` is the ONE connect function: the staff API calls it now and
the hosted wizard (lane 5) calls it later.

1. Derive the Page token from the business system-user token (S-META F4:
   ``GET /{page}?fields=access_token``). The system-user token is used for that
   one call and never stored; the Page token is stored Fernet-encrypted.
2. Under a Postgres advisory lock on (platform, Page id), apply the sharing
   rule: a Page live under ANOTHER tenant may join only when this tenant AND
   every tenant already live on it allow shared Pages; otherwise
   ``PAGE_IN_USE``, worded the same whatever the reason (AC-64-36). The same
   tenant reconnecting replaces its token in place (AC-64-25) and keeps its
   status. A source still ``WAITING_FOR_TEST`` counts as on the Page.
4. A new source is saved ``WAITING_FOR_TEST``; its first test lead flips it to
   ``LIVE`` (AC-64-16, ``leadgen_service``). It already receives leads.
3. Subscribe ``leadgen`` through core ``subscribe_page_fields`` (reads the
   app's current fields, posts the union - never drops omnichannel's).

No token reaches a log line, an error text or an answer.
"""
from __future__ import annotations

import logging
import re
import zlib
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.integrations.meta.pages import subscribe_page_fields
from app.secrets import encrypt_secret

from ..meta_leads import MetaLeadClient, MetaLeadError
from ..models import PLATFORM_FACEBOOK, SOURCE_ROUTING_STATES, SOURCE_WAITING_FOR_TEST, LcSettings, LcSource

logger = logging.getLogger(__name__)

LEADGEN_FIELD = "leadgen"
FORMS_MODES = ("all",)
_PAGE_ID_RE = re.compile(r"^[0-9]{1,32}$")
PAGE_IN_USE_MESSAGE = "This Facebook Page is already connected to another account."


class ConnectError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def get_settings(db: Session, tenant_id: str) -> LcSettings:
    row = db.get(LcSettings, tenant_id)
    return row if row is not None else LcSettings(tenant_id=tenant_id, allow_shared_pages=False)


def set_allow_shared_pages(db: Session, tenant_id: str, allow: bool, user_id: Optional[str]) -> LcSettings:
    row = db.get(LcSettings, tenant_id)
    if row is None:
        row = LcSettings(tenant_id=tenant_id)
        db.add(row)
    row.allow_shared_pages = bool(allow)
    row.updated_by = user_id
    db.commit()
    db.refresh(row)
    return row


def _lock_page(db: Session, platform: str, page_id: str) -> None:
    """Transaction-scoped advisory lock on (platform, Page). SQLite (tests)
    serialises writers on its own, so there it is a no-op."""
    if db.get_bind().dialect.name != "postgresql":
        return
    key = zlib.crc32(f"lead_capture:{platform}:{page_id}".encode("utf-8"))
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})


def _allows_sharing(db: Session, tenant_id: str) -> bool:
    return bool(get_settings(db, tenant_id).allow_shared_pages)


def live_sources_for_page(db: Session, platform: str, page_id: str) -> list:
    """Every source on a Page that receives leads (``WAITING_FOR_TEST`` or
    ``LIVE``), ALL tenants (D13). Only the ingest and the sharing rule may call
    this - nothing tenant-facing."""
    return (
        db.query(LcSource)
        .filter(
            LcSource.platform == platform,
            LcSource.account_ref == page_id,
            LcSource.status.in_(SOURCE_ROUTING_STATES),
        )
        .order_by(LcSource.created_at.asc(), LcSource.id.asc())
        .all()
    )


def connect_facebook(
    db: Session,
    tenant_id: str,
    *,
    page_id: str,
    system_user_token: str,
    forms_mode: str = "all",
    user_id: Optional[str] = None,
    client: Optional[MetaLeadClient] = None,
) -> LcSource:
    page_id = (page_id or "").strip()
    if not _PAGE_ID_RE.match(page_id):
        raise ConnectError(422, "invalid_page_id", "Enter the Facebook Page id (digits only).")
    if forms_mode not in FORMS_MODES:
        raise ConnectError(422, "invalid_forms_mode", "Forms mode must be \"all\".")
    token = (system_user_token or "").strip()
    if not token:
        raise ConnectError(422, "invalid_token", "Enter the system user token.")

    meta = client or MetaLeadClient()
    dev = not meta.configured
    try:
        page = meta.page_token(token, page_id, dev=dev)
    except MetaLeadError as exc:
        raise ConnectError(
            400, "meta_refused" if not exc.token_invalid else "token_invalid", exc.message
        ) from None

    _lock_page(db, PLATFORM_FACEBOOK, page_id)
    live = live_sources_for_page(db, PLATFORM_FACEBOOK, page_id)
    own = next((s for s in live if s.tenant_id == tenant_id), None)
    others = [s for s in live if s.tenant_id != tenant_id]
    if others and own is None:
        tenants = {s.tenant_id for s in others}
        if not _allows_sharing(db, tenant_id) or not all(_allows_sharing(db, t) for t in tenants):
            db.rollback()
            raise ConnectError(409, "PAGE_IN_USE", PAGE_IN_USE_MESSAGE)

    try:
        posted = subscribe_page_fields(page["pageToken"], page_id, [LEADGEN_FIELD], dev=dev)
    except Exception as exc:  # noqa: BLE001 - transport error: refuse cleanly
        db.rollback()
        logger.warning("leadgen subscribe for a Page failed: %s", type(exc).__name__)
        raise ConnectError(502, "subscribe_failed", "Meta could not be reached. Try again.") from None
    if posted is None and not dev:
        db.rollback()
        raise ConnectError(502, "subscribe_failed", "Meta refused the lead subscription for this Page.")

    credentials = encrypt_secret({"pageToken": page["pageToken"], "dev": dev})
    if own is not None:
        own.credentials_encrypted = credentials
        own.account_name = page.get("pageName") or own.account_name
        own.config_json = {**(own.config_json or {}), "formsMode": forms_mode}
        source = own
    else:
        source = LcSource(
            tenant_id=tenant_id,
            platform=PLATFORM_FACEBOOK,
            mode="auto",
            name=page.get("pageName") or f"Facebook Page {page_id}",
            status=SOURCE_WAITING_FOR_TEST,  # LIVE after its first test lead (AC-64-16)
            account_ref=page_id,
            account_name=page.get("pageName") or None,
            config_json={"formsMode": forms_mode},
            credentials_encrypted=credentials,
            created_by=user_id,
        )
        db.add(source)
    db.commit()
    db.refresh(source)
    return source


def list_sources(db: Session, tenant_id: str) -> list:
    return (
        db.query(LcSource)
        .filter(LcSource.tenant_id == tenant_id)
        .order_by(LcSource.created_at.desc(), LcSource.id.asc())
        .all()
    )
