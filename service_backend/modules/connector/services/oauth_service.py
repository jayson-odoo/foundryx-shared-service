"""Connector OAuth authorization server logic (plan sprint-4/19, S3).

Per-product (``/mcp/<product>``). The tenant is the product registry entry's
owning tenant. Fail closed: every refusal on the consent / token paths is
opaque, tokens/codes/assertions are never logged or stored in plaintext.
"""
from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional
from urllib.parse import urlencode, urlparse

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.repositories.module_repository import ModuleRepository
from app.repositories.tenant_repository import TenantRepository

from .. import crypto, registry
from ..models import AuthCode, Grant, OAuthClient, PendingRequest, Token
from ..repositories.connector_repository import ConnectorRepository

MODULE_NAME = "connector"
BIND_COOKIE = "fx_connector_bind"
PENDING_TTL = timedelta(minutes=10)
CODE_TTL = timedelta(seconds=60)
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)
MAX_REDIRECT_URIS = 5
_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9\-_]{43}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProductNotFound(Exception):
    """Unknown / misconfigured product, inactive module or non-signin tenant (uniform 404)."""


class InvalidRedirect(Exception):
    pass


class InvalidClientMetadata(Exception):
    pass


class AuthorizeRefused(Exception):
    """Browser-facing refusal - the router shows an error page, NEVER a redirect."""


class ConsentRefused(Exception):
    """Browser-facing refusal on consent-return (opaque)."""


class TokenError(Exception):
    def __init__(self, error: str, description: str = ""):
        super().__init__(error)
        self.error = error
        self.description = description


class Unauthorized(Exception):
    pass


@dataclass(frozen=True)
class ProductContext:
    product: registry.Product
    tenant_id: str


def resolve_context(db: Session, key: str) -> ProductContext:
    product = registry.get_product(key, db)
    if product is None:
        raise ProductNotFound()
    repo = TenantRepository(db)
    tenant = repo.get_by_id(product.tenant_id) if product.tenant_id else repo.get_by_slug(product.tenant_slug)
    if tenant is None or tenant.is_platform or not tenant.signin_allowed:
        raise ProductNotFound()
    if not ModuleRepository(db).is_active(tenant.id, MODULE_NAME):  # no row / INACTIVE = 404
        raise ProductNotFound()
    return ProductContext(product=product, tenant_id=tenant.id)


def _redirect_with(uri: str, params: Mapping[str, Optional[str]]) -> str:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    sep = "&" if urlparse(uri).query else "?"
    return f"{uri}{sep}{query}"


class OAuthService:
    def __init__(self, db: Session, ctx: ProductContext, public_base_url: Optional[str] = None):
        self.db = db
        self.ctx = ctx
        self.product = ctx.product
        self.repo = ConnectorRepository(db, ctx.tenant_id)
        self.config = registry.tenant_config(db, ctx.tenant_id)
        if public_base_url is None:
            public_base_url = self.config.public_base_url
        self.base = public_base_url.rstrip("/")

    @property
    def issuer(self) -> str:
        return f"{self.base}/mcp/{self.product.key}"

    # --- discovery ----------------------------------------------------------------
    def protected_resource_metadata(self) -> dict:
        return {"resource": self.issuer, "authorization_servers": [self.issuer],
                "bearer_methods_supported": ["header"]}

    def authorization_server_metadata(self) -> dict:
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/oauth/authorize",
            "token_endpoint": f"{self.issuer}/oauth/token",
            "registration_endpoint": f"{self.issuer}/oauth/register",
            "revocation_endpoint": f"{self.issuer}/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
        }

    # --- DCR ----------------------------------------------------------------------
    def register_client(self, body: object) -> dict:
        if not isinstance(body, dict):
            raise InvalidClientMetadata()
        uris = body.get("redirect_uris")
        if not isinstance(uris, list) or not uris or len(uris) > MAX_REDIRECT_URIS:
            raise InvalidRedirect()
        allowed = self.config.redirect_allowlist
        if not all(isinstance(u, str) and crypto.redirect_allowed(u, allowed) for u in uris):
            raise InvalidRedirect()
        name = body.get("client_name")
        name = name.strip()[:120] if isinstance(name, str) and name.strip() else "MCP client"
        client = self.repo.add_client(OAuthClient(product=self.product.key, client_name=name,
                                                  redirect_uris=list(uris)))
        self.db.commit()
        return {
            "client_id": client.id,
            "client_name": name,
            "redirect_uris": list(uris),
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        }

    # --- authorize ------------------------------------------------------------------
    def begin_authorize(self, params: Mapping[str, str]) -> tuple[str, str]:
        """Returns (consent redirect URL, raw binding cookie value)."""
        client_id = params.get("client_id") or ""
        redirect_uri = params.get("redirect_uri") or ""
        challenge = params.get("code_challenge") or ""
        client = self.repo.get_client(self.product.key, client_id) if client_id else None
        if client is None or params.get("response_type") != "code":
            raise AuthorizeRefused()
        registered = [u for u in (client.redirect_uris or []) if isinstance(u, str)]
        if not (crypto.redirect_allowed(redirect_uri, registered)
                and crypto.redirect_allowed(redirect_uri, self.config.redirect_allowlist)):
            raise AuthorizeRefused()
        if params.get("code_challenge_method") != "S256" or not _CHALLENGE_RE.match(challenge):
            raise AuthorizeRefused()
        state = params.get("state")
        if state is not None and len(state) > 512:
            raise AuthorizeRefused()

        bind = crypto.new_token()
        now = _now()
        pending = self.repo.add_pending(PendingRequest(
            product=self.product.key, client_id=client.id, redirect_uri=redirect_uri,
            code_challenge=challenge, state=state, bind_hash=crypto.hash_token(bind),
            expires_at=now + PENDING_TTL))
        self.db.commit()
        req = crypto.sign_consent_request(
            self.product.ss_to_product_secret,
            connection_id=self.product.connection_id,
            audience=self.product.consent_audience,
            request_id=pending.id,
            client_name=client.client_name,
            redirect_host=urlparse(redirect_uri).hostname or "",
            return_url=f"{self.issuer}/oauth/consent-return",
            now=int(now.timestamp()),
        )
        return _redirect_with(self.product.consent_url, {"req": req}), bind

    # --- consent return ---------------------------------------------------------------
    def complete_consent(self, *, request_id: str, assertion: Optional[str], error: Optional[str],
                         bind_cookie: Optional[str]) -> str:
        """Returns the redirect URL back to the client. Raises ConsentRefused."""
        now = _now()
        pending = self.repo.get_pending(self.product.key, request_id) if request_id else None
        if pending is None or not bind_cookie:
            raise ConsentRefused()
        if not hmac.compare_digest(crypto.hash_token(bind_cookie), pending.bind_hash):
            raise ConsentRefused()
        if pending.used_at is not None or pending.expires_at <= now:
            raise ConsentRefused()

        if error is not None:
            if error != "access_denied" or not self.repo.claim_pending(pending.id, now):
                self.db.rollback()
                raise ConsentRefused()
            self.repo.add_event(product=self.product.key, event="denied")
            self.db.commit()
            return _redirect_with(pending.redirect_uri, {"error": "access_denied", "state": pending.state})

        if not assertion:
            raise ConsentRefused()
        try:
            claims = crypto.verify_assertion(
                assertion, self.product.product_to_ss_secret, issuer=self.product.issuer,
                connection_id=self.product.connection_id, request_id=pending.id,
                now=int(now.timestamp()))
        except crypto.AssertionInvalid:
            raise ConsentRefused() from None

        try:
            self.repo.prune_jti(now)
            self.repo.add_jti(self.product.key, claims["jti"],
                              datetime.fromtimestamp(claims["exp"], tz=timezone.utc))
        except IntegrityError:
            self.db.rollback()
            raise ConsentRefused() from None
        if not self.repo.claim_pending(pending.id, now):
            self.db.rollback()
            raise ConsentRefused()

        sub = claims["sub"]
        name = claims.get("name") if isinstance(claims.get("name"), str) else None
        email = claims.get("email") if isinstance(claims.get("email"), str) else None
        consented_at = datetime.fromtimestamp(claims["iat"], tz=timezone.utc)
        grant = self.repo.find_active_grant(self.product.key, sub, pending.client_id)
        if grant is None:
            grant = self.repo.add_grant(Grant(
                product=self.product.key, product_user_id=sub, name=name and name[:255],
                email=email and email[:320], client_id=pending.client_id,
                consented_at=consented_at, status="active"))
        else:  # re-consent refreshes the snapshot + consent time (never reactivates a revoked one)
            grant.name, grant.email = name and name[:255], email and email[:320]
            grant.consented_at = consented_at
        code = crypto.new_token()
        self.repo.add_code(AuthCode(
            code_hash=crypto.hash_token(code), grant_id=grant.id, client_id=pending.client_id,
            redirect_uri=pending.redirect_uri, code_challenge=pending.code_challenge,
            expires_at=now + CODE_TTL))
        self.repo.add_event(product=self.product.key, event="consented", grant_id=grant.id)
        self.db.commit()
        return _redirect_with(pending.redirect_uri, {"code": code, "state": pending.state})

    # --- token --------------------------------------------------------------------------
    def token(self, form: Mapping[str, str]) -> dict:
        grant_type = form.get("grant_type")
        if grant_type == "authorization_code":
            return self._exchange_code(form)
        if grant_type == "refresh_token":
            return self._refresh(form)
        raise TokenError("unsupported_grant_type")

    def _issue_pair(self, grant: Grant, family_id: str, now: datetime) -> dict:
        access, refresh = crypto.new_token(), crypto.new_token()
        self.repo.add_token(Token(token_hash=crypto.hash_token(access), kind="access",
                                  grant_id=grant.id, family_id=family_id,
                                  expires_at=now + ACCESS_TTL))
        self.repo.add_token(Token(token_hash=crypto.hash_token(refresh), kind="refresh",
                                  grant_id=grant.id, family_id=family_id,
                                  expires_at=now + REFRESH_TTL))
        grant.last_used_at = now
        return {"access_token": access, "token_type": "Bearer",
                "expires_in": int(ACCESS_TTL.total_seconds()), "refresh_token": refresh}

    def _exchange_code(self, form: Mapping[str, str]) -> dict:
        code = form.get("code") or ""
        verifier = form.get("code_verifier") or ""
        client_id = form.get("client_id") or ""
        redirect_uri = form.get("redirect_uri") or ""
        if not (code and verifier and client_id and redirect_uri):
            raise TokenError("invalid_request")
        row = self.repo.get_code_by_hash(crypto.hash_token(code))
        now = _now()
        if row is None:
            raise TokenError("invalid_grant")
        grant = self.repo.get_grant(row.grant_id)
        if grant is None or grant.product != self.product.key:
            raise TokenError("invalid_grant")
        if row.used_at is not None:
            # Replay of a spent code: whatever it minted dies with it.
            self.repo.delete_family(row.id)
            self.db.commit()
            raise TokenError("invalid_grant")
        if (row.expires_at <= now or grant.status != "active"
                or not hmac.compare_digest(row.client_id.encode(), client_id.encode())
                or not crypto.redirect_allowed(redirect_uri, [row.redirect_uri])
                or not crypto.pkce_verify(verifier, row.code_challenge, "S256")):
            raise TokenError("invalid_grant")
        if not self.repo.claim_code(row.id, now):
            self.db.rollback()
            raise TokenError("invalid_grant")
        pair = self._issue_pair(grant, row.id, now)
        self.db.commit()
        return pair

    def _refresh(self, form: Mapping[str, str]) -> dict:
        raw = form.get("refresh_token") or ""
        client_id = form.get("client_id") or ""
        if not raw or not client_id:
            raise TokenError("invalid_request")
        now = _now()
        row = self.repo.get_token_by_hash(crypto.hash_token(raw))
        if row is None or row.kind != "refresh" or row.revoked_at is not None:
            raise TokenError("invalid_grant")
        grant = self.repo.get_grant(row.grant_id)
        if grant is None or grant.product != self.product.key or grant.status != "active":
            raise TokenError("invalid_grant")
        if not hmac.compare_digest(grant.client_id.encode(), client_id.encode()):
            raise TokenError("invalid_grant")
        if row.used_at is not None:
            self.revoke_grant(grant, reason="refresh_reuse", event="refresh_reuse")
            self.db.commit()
            raise TokenError("invalid_grant")
        if row.expires_at <= now:
            raise TokenError("invalid_grant")
        if not self.repo.claim_token(row.id, now):
            self.revoke_grant(grant, reason="refresh_reuse", event="refresh_reuse")
            self.db.commit()
            raise TokenError("invalid_grant")
        pair = self._issue_pair(grant, row.family_id, now)
        self.repo.add_event(product=self.product.key, event="refreshed", grant_id=grant.id)
        self.db.commit()
        return pair

    # --- revoke (RFC 7009) ------------------------------------------------------------------
    def revoke(self, token: Optional[str], client_id: Optional[str]) -> None:
        if not token:
            return
        row = self.repo.get_token_by_hash(crypto.hash_token(token))
        if row is None:
            return
        grant = self.repo.get_grant(row.grant_id)
        if grant is None or grant.product != self.product.key or grant.status != "active":
            return
        if client_id and not hmac.compare_digest(grant.client_id.encode(), client_id.encode()):
            return
        self.revoke_grant(grant, reason="client_revoked", event="revoked")
        self.db.commit()

    def revoke_grant(self, grant: Grant, *, reason: str, event: str = "revoked",
                     actor_user_id: Optional[str] = None) -> None:
        """Mark revoked + kill every token (caller commits)."""
        self.repo.revoke_grant(grant, reason=reason, event=event, actor_user_id=actor_user_id)

    # --- bearer authentication (MCP) ----------------------------------------------------------
    def authenticate_access(self, token: str) -> Grant:
        if not token:
            raise Unauthorized()
        row = self.repo.get_token_by_hash(crypto.hash_token(token))
        now = _now()
        if row is None or row.kind != "access" or row.revoked_at is not None or row.expires_at <= now:
            raise Unauthorized()
        grant = self.repo.get_grant(row.grant_id)
        if grant is None or grant.product != self.product.key or grant.status != "active":
            raise Unauthorized()
        grant.last_used_at = now
        self.db.commit()
        return grant
