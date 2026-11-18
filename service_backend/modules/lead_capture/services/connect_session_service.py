"""Connect sessions + Facebook login for the hosted wizard (plan 64 L-C,
AC-64-06/07/08/20/21).

Two doors, ONE set of functions:

- the hosted wizard: ``create_session`` (gateway key or staff user) makes a
  single-use URL valid 10 minutes; ``redeem`` swaps its secret ONCE for a
  scoped ``lead_capture_embed`` token (30 minutes) bound to the session row.
  Every wizard route resolves that token with ``resolve_wizard``.
- a product's own wizard (owner 17 Nov: every step is an API too):
  ``create_login`` runs the same Facebook code exchange through the gateway
  and answers an opaque ``loginId`` the product passes to ``POST
  /sources/facebook``.

Facebook (AC-64-20/21): the code is exchanged server-side with core
``exchange_code`` + ``exchange_long_lived_token`` (``app/integrations/meta/
pages.py``); the token is Fernet-encrypted on the session row and never
crosses the wire; the Page list comes from core ``list_pages``. When the
login config issues a business system-user token the same path applies:
``connect_service.connect_facebook`` derives the Page token from it (S-META
F4: the Page must be an asset of that system user).

The URL secret travels in the URL FRAGMENT (``#s=``), so it never reaches a
server access log or a ``Referer`` header; only its sha256 is stored.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import settings
from app.integrations.meta.errors import CodeExchangeError
from app.integrations.meta.pages import MetaPages
from app.models.tenant import Tenant
from app.repositories.module_repository import ModuleRepository
from app.scoped_tokens import decode_scoped_token, mint_scoped_token
from app.secrets import decrypt_secret, encrypt_secret

from .. import meta_leads
from ..meta_leads import LOGIN_SCOPES, MetaLeadClient, MetaLeadError
from ..models import (
    PLATFORM_FACEBOOK,
    SESSION_KIND_LOGIN,
    SESSION_KIND_WIZARD,
    LcApiKey,
    LcConnectSession,
    LcSource,
)
from . import source_service

logger = logging.getLogger(__name__)

MODULE_NAME = "lead_capture"
EMBED_TYP = "lead_capture_embed"
URL_TTL = timedelta(minutes=10)
EMBED_TTL_MINUTES = 30
LOGIN_TTL = timedelta(minutes=30)
MAX_ORIGINS = 10
REQUIRED_SCOPE = "leads_retrieval"
WIZARD_PATH = "/public/lead-capture/connect"
DEV_PAGES = meta_leads.DEV_PAGES
_ORIGIN_HOST_RE = re.compile(r"^[a-z0-9.-]{1,253}$")


class SessionError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ── origins ─────────────────────────────────────────────────────────────────

def normalize_origin(value: Optional[str]) -> Optional[str]:
    """``scheme://host[:port]`` lower-cased, or None when ``value`` is not a
    bare web origin (a path, query, fragment, user info or other scheme = not
    an origin). ``http`` only for localhost, or any host outside production
    (test copies on a private address)."""
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        return None
    raw = value.strip()
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return None
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if scheme not in ("https", "http") or not host or not _ORIGIN_HOST_RE.match(host):
        return None
    if parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
        return None
    if scheme == "http" and not (
        host == "localhost" or host.endswith(".localhost") or host == "127.0.0.1" or _plain_http_allowed()
    ):
        return None
    return f"{scheme}://{host}" + (f":{port}" if port else "")


def _plain_http_allowed() -> bool:
    """Test copies on a private address (e.g. a tailnet IP over plain http)
    may list http origins; production never does."""
    return settings.environment in ("development", "test")


def clean_origins(values: List[str]) -> List[str]:
    out: List[str] = []
    for value in values or []:
        origin = normalize_origin(value)
        if origin is None:
            raise SessionError(422, "invalid_origin", "Each allowed origin must look like https://crm.example.com.")
        if origin not in out:
            out.append(origin)
    if len(out) > MAX_ORIGINS:
        raise SessionError(422, "invalid_origin", f"At most {MAX_ORIGINS} allowed origins.")
    return out


def gateway_key(db: Session, tenant_id: str, key_id: str) -> Optional[LcApiKey]:
    """The calling gateway key's row, tenant-scoped (None = gone/revoked)."""
    row = db.query(LcApiKey).filter(LcApiKey.id == key_id, LcApiKey.tenant_id == tenant_id).first()
    return row if row is not None and row.revoked_at is None else None


def set_key_origins(db: Session, tenant_id: str, key_id: str, origins: List[str]) -> LcApiKey:
    row = db.query(LcApiKey).filter(LcApiKey.id == key_id, LcApiKey.tenant_id == tenant_id).first()
    if row is None:
        raise SessionError(404, "key_not_found", "Key not found.")
    row.allowed_origins_json = clean_origins(origins)
    db.commit()
    db.refresh(row)
    return row


def _staff_origin_allowed(db: Session, tenant_id: str, origin: str) -> bool:
    """A staff session posts back to this app's own frontend only: a listed
    app origin, or THIS tenant's own subdomain of it (never another
    tenant's)."""
    allowed = {normalize_origin(o) for o in settings.cors_origins_list}
    allowed.add(normalize_origin(settings.frontend_url))
    if origin in allowed:
        return True
    pattern = settings.cors_origin_regex
    if not pattern or re.fullmatch(pattern, origin) is None:
        return False
    tenant = db.get(Tenant, tenant_id)
    host = urlsplit(origin).hostname or ""
    return tenant is not None and bool(tenant.slug) and host.split(".", 1)[0] == tenant.slug


# ── sessions ────────────────────────────────────────────────────────────────

def _prune(db: Session, tenant_id: str) -> None:
    """Drop this tenant's sessions dead for a day (the URL, login and wizard
    are all long gone by then)."""
    cutoff = _now() - timedelta(days=1)
    db.query(LcConnectSession).filter(
        LcConnectSession.tenant_id == tenant_id, LcConnectSession.expires_at < cutoff
    ).delete(synchronize_session=False)


def create_session(
    db: Session,
    tenant_id: str,
    *,
    return_origin: Optional[str],
    key: Optional[LcApiKey] = None,
    user_id: Optional[str] = None,
    source_id: Optional[str] = None,
) -> Tuple[LcConnectSession, str]:
    """A single-use hosted-wizard URL (AC-64-06). Gateway: ``returnOrigin``
    must be on the key's allowed origins. Staff: optional, and only this
    app's own frontend. ``source_id`` (optional) reopens the wizard for one
    of the tenant's sources (Reconnect, Map fields)."""
    origin = normalize_origin(return_origin) if return_origin else None
    if key is not None:
        allowed = set(key.allowed_origins_json or [])
        if origin is None or origin not in allowed:
            raise SessionError(422, "ORIGIN_NOT_ALLOWED", "returnOrigin is not on this key's allowed origins.")
    elif return_origin and (origin is None or not _staff_origin_allowed(db, tenant_id, origin)):
        raise SessionError(422, "ORIGIN_NOT_ALLOWED", "returnOrigin is not this app's origin.")
    if source_id:
        source_service.get_source(db, tenant_id, source_id)  # 404 when not this tenant's
    _prune(db, tenant_id)
    secret = secrets.token_urlsafe(32)
    row = LcConnectSession(
        tenant_id=tenant_id,
        kind=SESSION_KIND_WIZARD,
        key_id=key.id if key is not None else None,
        user_id=user_id,
        return_origin=origin,
        source_id=source_id or None,
        token_hash=_hash(secret),
        expires_at=_now() + URL_TTL,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    url = f"{settings.frontend_url.rstrip('/')}{WIZARD_PATH}#s={secret}"
    return row, url


def _tenant_usable(db: Session, tenant_id: str) -> bool:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or not tenant.signin_allowed:
        return False
    return ModuleRepository(db).is_active(tenant_id, MODULE_NAME)


def _key_usable(db: Session, row: LcConnectSession) -> bool:
    """A session a gateway key opened dies with the key (revoked, or its
    origin taken off the allowed list since)."""
    if not row.key_id:
        return True
    key = db.query(LcApiKey).filter(LcApiKey.id == row.key_id, LcApiKey.tenant_id == row.tenant_id).first()
    if key is None or key.revoked_at is not None:
        return False
    return row.return_origin in set(key.allowed_origins_json or [])


def redeem(db: Session, secret: Optional[str]) -> Dict[str, Any]:
    """Swap the URL secret for the wizard token, ONCE (AC-64-06/07). A used,
    expired, unknown or disabled session answers the same 410 with no tenant
    data at all."""
    expired = SessionError(410, "SESSION_EXPIRED", "This link has expired. Start again from your app.")
    if not isinstance(secret, str) or not 20 <= len(secret) <= 200:
        raise expired
    now = _now()
    token_hash = _hash(secret)
    claimed = db.execute(
        update(LcConnectSession)
        .where(
            LcConnectSession.token_hash == token_hash,
            LcConnectSession.kind == SESSION_KIND_WIZARD,
            LcConnectSession.consumed_at.is_(None),
            LcConnectSession.expires_at > now,
        )
        .values(consumed_at=now)
    ).rowcount
    db.commit()
    if claimed != 1:
        raise expired
    row = db.query(LcConnectSession).filter(LcConnectSession.token_hash == token_hash).first()
    if row is None or not _tenant_usable(db, row.tenant_id) or not _key_usable(db, row):
        raise expired
    token = mint_scoped_token(
        EMBED_TYP,
        {"sub": row.id, "sid": row.id, "tenant_id": row.tenant_id},
        ttl_minutes=EMBED_TTL_MINUTES,
    )
    return {
        "accessToken": token,
        "expiresAt": now + timedelta(minutes=EMBED_TTL_MINUTES),
        "returnOrigin": row.return_origin,
        "sourceId": row.source_id,
    }


@dataclass
class WizardPrincipal:
    tenant_id: str
    session: LcConnectSession

    @property
    def actor(self) -> "source_service.Actor":
        if self.session.key_id:
            return source_service.Actor.key(self.session.key_id)
        return source_service.Actor.user(self.session.user_id)

    def require_source(self, db: Session, source_id: str) -> LcSource:
        """Scope (AC-64-07): the wizard token reaches only the source this
        session works on, never the tenant's other sources."""
        if not self.session.source_id or source_id != self.session.source_id:
            raise SessionError(404, "source_not_found", "Source not found.")
        try:
            return source_service.get_source(db, self.tenant_id, source_id)
        except source_service.SourceError:
            raise SessionError(404, "source_not_found", "Source not found.") from None


def resolve_wizard(db: Session, token: Optional[str]) -> WizardPrincipal:
    """The wizard token -> its tenant + session. 401 for anything that is not
    a live ``lead_capture_embed`` token of a redeemed session; 403 when the
    tenant or the module was switched off since."""
    claims = decode_scoped_token(token, EMBED_TYP)
    denied = SessionError(401, "invalid_token", "This session has ended. Start again from your app.")
    if claims is None or not claims.get("sid") or not claims.get("tenant_id"):
        raise denied
    row = (
        db.query(LcConnectSession)
        .filter(
            LcConnectSession.id == claims["sid"],
            LcConnectSession.tenant_id == claims["tenant_id"],
            LcConnectSession.kind == SESSION_KIND_WIZARD,
        )
        .first()
    )
    if row is None or row.consumed_at is None or not _key_usable(db, row):
        raise denied
    if not _tenant_usable(db, row.tenant_id):
        raise SessionError(403, "service_not_enabled", "Lead Capture is not enabled for this account.")
    return WizardPrincipal(tenant_id=row.tenant_id, session=row)


# ── channels + Facebook login ───────────────────────────────────────────────

def login_config() -> Dict[str, Any]:
    """What a page needs to open Facebook Login for Business (AC-64-20).
    ``simulated`` = no Meta app on this server (dev + tests): any code works."""
    simulated = not settings.meta_app_id
    return {
        "available": simulated or bool(settings.lead_capture_login_config_id),
        "simulated": simulated,
        "appId": settings.meta_app_id or None,
        "configId": settings.lead_capture_login_config_id or None,
        "graphVersion": settings.meta_graph_version,
        "scopes": list(LOGIN_SCOPES),
    }


def channels() -> List[Dict[str, Any]]:
    """Channels that work for this server right now (AC-64-13). Release 1 =
    Facebook only; a channel whose app is not configured is left out."""
    out: List[Dict[str, Any]] = []
    if login_config()["available"]:
        out.append({"key": PLATFORM_FACEBOOK, "label": "Facebook", "setup": "automatic"})
    return out


def _facebook_login(
    db: Session, row: LcConnectSession, code: str, redirect_uri: Optional[str], *, client=None
) -> List[Dict[str, str]]:
    """Exchange ``code``, check the lead permission, store the token (Fernet)
    on ``row`` and return the granted Pages. Errors: ``LOGIN_FAILED`` (code
    refused), ``PERMISSION_DECLINED`` (E1)."""
    code = (code or "").strip()
    if not code or len(code) > 2048:
        raise SessionError(422, "invalid_code", "The Facebook sign-in did not finish. Try again.")
    if not login_config()["available"]:
        raise SessionError(409, "channel_unavailable", "Facebook is not available right now.")
    pages_api = MetaPages(client=client)
    try:
        creds = pages_api.exchange_code(code, redirect_uri)
    except CodeExchangeError:
        logger.info("lead capture facebook code exchange refused")
        raise SessionError(400, "LOGIN_FAILED", "Facebook did not finish the sign-in. Try again.") from None
    creds = pages_api.exchange_long_lived_token(creds)
    user_token = creds.get("access_token") or ""
    dev = bool(creds.get("dev"))
    if not user_token:
        raise SessionError(400, "LOGIN_FAILED", "Facebook did not finish the sign-in. Try again.")
    try:
        granted = MetaLeadClient(client=client).granted_permissions(user_token, dev=dev)
    except MetaLeadError as exc:
        logger.info("permission read refused (code %s)", exc.code)
        raise SessionError(400, "LOGIN_FAILED", "Facebook did not finish the sign-in. Try again.") from None
    if REQUIRED_SCOPE not in granted:
        raise SessionError(
            400,
            "PERMISSION_DECLINED",
            "Facebook did not give permission to read leads. Leave every permission ticked on the Facebook screen.",
        )
    row.meta_encrypted = encrypt_secret({"userToken": user_token, "dev": dev})
    row.meta_expires_at = _now() + LOGIN_TTL
    db.commit()
    return _pages(user_token, dev, client=client)


def _pages(user_token: str, dev: bool, *, client=None) -> List[Dict[str, str]]:
    """Only the Pages the person granted (AC-64-21), ids + names only (the
    Page tokens core returns are dropped here)."""
    if dev:
        return [dict(p) for p in DEV_PAGES]
    rows = MetaPages(client=client).list_pages({"access_token": user_token})
    out = []
    for page in rows or []:
        page_id, name = str(page.get("id") or ""), str(page.get("name") or "")
        if page_id.isdigit():
            out.append({"id": page_id, "name": name or page_id})
    return out


def _user_token(row: LcConnectSession) -> Tuple[str, bool]:
    """The stored login token, or ``LOGIN_REQUIRED`` when absent / expired."""
    expires = _aware(row.meta_expires_at)
    if not row.meta_encrypted or expires is None or expires <= _now():
        raise SessionError(409, "LOGIN_REQUIRED", "Sign in to Facebook again.")
    try:
        data = decrypt_secret(row.meta_encrypted)
    except Exception:  # noqa: BLE001 - undecryptable: sign in again
        raise SessionError(409, "LOGIN_REQUIRED", "Sign in to Facebook again.") from None
    return str(data.get("userToken") or ""), bool(data.get("dev"))


def wizard_login(db: Session, principal: WizardPrincipal, code: str, redirect_uri: Optional[str], *, client=None):
    return _facebook_login(db, principal.session, code, redirect_uri, client=client)


def wizard_pages(principal: WizardPrincipal, *, client=None) -> List[Dict[str, str]]:
    token, dev = _user_token(principal.session)
    return _pages(token, dev, client=client)


def create_login(
    db: Session, tenant_id: str, key_id: str, code: str, redirect_uri: Optional[str], *, client=None
) -> Dict[str, Any]:
    """Gateway door to the same login (a product's own wizard)."""
    _prune(db, tenant_id)
    row = LcConnectSession(tenant_id=tenant_id, kind=SESSION_KIND_LOGIN, key_id=key_id, expires_at=_now() + LOGIN_TTL)
    db.add(row)
    db.flush()
    pages = _facebook_login(db, row, code, redirect_uri, client=client)
    return {"loginId": row.id, "pages": pages, "expiresAt": _aware(row.meta_expires_at)}


def login_token(db: Session, tenant_id: str, login_id: str, key_id: Optional[str] = None) -> str:
    """The token behind a gateway ``loginId``: tenant-scoped (and key-scoped
    when given). Unknown and expired answer the same."""
    q = db.query(LcConnectSession).filter(
        LcConnectSession.id == login_id,
        LcConnectSession.tenant_id == tenant_id,
        LcConnectSession.kind == SESSION_KIND_LOGIN,
    )
    if key_id is not None:
        q = q.filter(LcConnectSession.key_id == key_id)
    row = q.first()
    if row is None:
        raise SessionError(409, "LOGIN_REQUIRED", "Sign in to Facebook again.")
    return _user_token(row)[0]


def login_pages(db: Session, tenant_id: str, login_id: str, key_id: Optional[str] = None, *, client=None):
    q = db.query(LcConnectSession).filter(
        LcConnectSession.id == login_id,
        LcConnectSession.tenant_id == tenant_id,
        LcConnectSession.kind == SESSION_KIND_LOGIN,
    )
    if key_id is not None:
        q = q.filter(LcConnectSession.key_id == key_id)
    row = q.first()
    if row is None:
        raise SessionError(409, "LOGIN_REQUIRED", "Sign in to Facebook again.")
    token, dev = _user_token(row)
    return _pages(token, dev, client=client)


def wizard_connect(db: Session, principal: WizardPrincipal, page_id: str) -> LcSource:
    """Connect the chosen Page with the ONE connect function, then bind the
    source to this session (its later steps reach only this source)."""
    from . import connect_service

    token, _dev = _user_token(principal.session)
    session = principal.session
    if session.source_id:
        bound = source_service.get_source(db, principal.tenant_id, session.source_id)
        if bound.account_ref and bound.account_ref != page_id:
            raise SessionError(409, "wrong_page", "Pick the Page this source was connected with.")
    else:
        # A "new source" session never takes over a source the tenant already
        # has on this Page: reconnecting it is a session opened for it.
        existing = (
            db.query(LcSource.id)
            .filter(
                LcSource.tenant_id == principal.tenant_id,
                LcSource.platform == PLATFORM_FACEBOOK,
                LcSource.account_ref == page_id,
            )
            .first()
        )
        if existing is not None:
            raise SessionError(
                409, "source_exists", "This Page is already a source here. Reconnect it from the sources list."
            )
    source = connect_service.connect_facebook(
        db,
        principal.tenant_id,
        page_id=page_id,
        system_user_token=token,
        forms_mode="all",
        user_id=session.user_id,
        actor=principal.actor,
    )
    session.source_id = source.id
    db.commit()
    return source


def finish(db: Session, principal: WizardPrincipal) -> Dict[str, Any]:
    """Done screen data (AC-64-17): what was connected, by whom, when, the
    test lead, and what is still open."""
    session = principal.session
    if not session.source_id:
        raise SessionError(409, "not_connected", "Connect a Page first.")
    source = source_service.get_source(db, principal.tenant_id, session.source_id)
    if session.finished_at is None:
        session.finished_at = _now()
        db.commit()
    from ..models import LcLead

    test_lead = (
        db.query(LcLead)
        .filter(LcLead.tenant_id == principal.tenant_id, LcLead.source_id == source.id, LcLead.is_test.is_(True))
        .order_by(LcLead.received_at.desc(), LcLead.id.desc())
        .first()
    )
    real_lead = (
        db.query(LcLead.id)
        .filter(LcLead.tenant_id == principal.tenant_id, LcLead.source_id == source.id, LcLead.is_test.is_(False))
        .first()
    )
    events = source_service.history(db, principal.tenant_id, source.id).data
    connected = next((e for e in events if e.action in ("connected", "reconnected")), None)
    return {
        "source": source,
        "connectedBy": connected.actor.name if connected else None,
        "connectedAt": connected.createdAt if connected else source.created_at,
        "testLeadAt": test_lead.received_at if test_lead else None,
        "testLeadFormName": test_lead.form_name if test_lead else None,
        "waitingForRealLead": real_lead is None,
    }


def wizard_branding(db: Session, tenant_id: str) -> Dict[str, Optional[str]]:
    """The tenant's own name and logo for the hosted wizard (AC-64-11: never
    the platform's)."""
    from app.services.branding_service import BrandingService

    tenant = db.get(Tenant, tenant_id)
    data = BrandingService(db).get(tenant_id)
    name = (data.get("appName") or "").strip() or (tenant.name if tenant else "") or "Connect a lead source"
    return {"name": name, "logoUrl": data.get("logoUrl")}


def last_test_lead(db: Session, principal: WizardPrincipal, source_id: str) -> Dict[str, Optional[Any]]:
    """The newest test lead stored for this session's source: the wizard's
    Test step passes when a NEW one arrives after it asked (a reconnected
    source is LIVE already, so its status proves nothing)."""
    from ..models import LcLead

    source = principal.require_source(db, source_id)
    row = (
        db.query(LcLead.id, LcLead.received_at)
        .filter(LcLead.tenant_id == principal.tenant_id, LcLead.source_id == source.id, LcLead.is_test.is_(True))
        .order_by(LcLead.received_at.desc(), LcLead.id.desc())
        .first()
    )
    return {"leadId": row.id if row else None, "receivedAt": row.received_at if row else None}
