"""Connector repositories - pure SQLAlchemy, EVERY query tenant-scoped.

The tenant is the product registry's owning tenant (never client input).
Atomic "claim" updates (``used_at IS NULL``) make single-use rows race-safe.
"""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, or_, update
from sqlalchemy.orm import Session

from ..models import (
    AssertionJti,
    AuthCode,
    CallLog,
    Grant,
    GrantEvent,
    ManifestCache,
    OAuthClient,
    PendingRequest,
    Token,
)


class ConnectorRepository:
    def __init__(self, db: Session, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

    # --- clients -------------------------------------------------------------
    def add_client(self, client: OAuthClient) -> OAuthClient:
        client.tenant_id = self.tenant_id
        self.db.add(client)
        self.db.flush()
        return client

    def get_client(self, product: str, client_id: str) -> Optional[OAuthClient]:
        return (
            self.db.query(OAuthClient)
            .filter(OAuthClient.tenant_id == self.tenant_id, OAuthClient.product == product,
                    OAuthClient.id == client_id)
            .first()
        )

    # --- pending requests ------------------------------------------------------
    def add_pending(self, row: PendingRequest) -> PendingRequest:
        row.tenant_id = self.tenant_id
        self.db.add(row)
        self.db.flush()
        return row

    def get_pending(self, product: str, request_id: str) -> Optional[PendingRequest]:
        return (
            self.db.query(PendingRequest)
            .filter(PendingRequest.tenant_id == self.tenant_id, PendingRequest.product == product,
                    PendingRequest.id == request_id)
            .first()
        )

    def claim_pending(self, request_id: str, now: datetime) -> bool:
        res = self.db.execute(
            update(PendingRequest)
            .where(PendingRequest.tenant_id == self.tenant_id, PendingRequest.id == request_id,
                   PendingRequest.used_at.is_(None))
            .values(used_at=now)
        )
        return res.rowcount == 1

    # --- assertion jti ledger ---------------------------------------------------
    def prune_jti(self, now: datetime) -> None:
        self.db.query(AssertionJti).filter(AssertionJti.tenant_id == self.tenant_id,
                                           AssertionJti.expires_at < now).delete(synchronize_session=False)

    def add_jti(self, product: str, jti: str, expires_at: datetime) -> None:
        """Flushes; a duplicate raises IntegrityError (replay)."""
        self.db.add(AssertionJti(tenant_id=self.tenant_id, product=product, jti=jti,
                                 expires_at=expires_at))
        self.db.flush()

    # --- grants ------------------------------------------------------------------
    def find_active_grant(self, product: str, sub: str, client_id: str) -> Optional[Grant]:
        return (
            self.db.query(Grant)
            .filter(Grant.tenant_id == self.tenant_id, Grant.product == product,
                    Grant.product_user_id == sub, Grant.client_id == client_id,
                    Grant.status == "active")
            .first()
        )

    def add_grant(self, grant: Grant) -> Grant:
        grant.tenant_id = self.tenant_id
        self.db.add(grant)
        self.db.flush()
        return grant

    def get_grant(self, grant_id: str) -> Optional[Grant]:
        return (
            self.db.query(Grant)
            .filter(Grant.tenant_id == self.tenant_id, Grant.id == grant_id)
            .first()
        )

    def list_grants(self, *, status: Optional[str], product: Optional[str], search: Optional[str],
                    page: int, page_size: int) -> tuple[list[Grant], int]:
        q = self.db.query(Grant).filter(Grant.tenant_id == self.tenant_id)
        if status:
            q = q.filter(Grant.status == status)
        if product:
            q = q.filter(Grant.product == product)
        if search:
            like = f"%{search.strip().lower()}%"
            q = q.filter(or_(func.lower(Grant.name).like(like), func.lower(Grant.email).like(like),
                             func.lower(Grant.product_user_id).like(like)))
        total = q.count()
        rows = q.order_by(Grant.created_at.desc(), Grant.id).offset(page * page_size).limit(page_size).all()
        return rows, total

    # --- auth codes ---------------------------------------------------------------
    def add_code(self, row: AuthCode) -> AuthCode:
        row.tenant_id = self.tenant_id
        self.db.add(row)
        self.db.flush()
        return row

    def get_code_by_hash(self, code_hash: str) -> Optional[AuthCode]:
        return (
            self.db.query(AuthCode)
            .filter(AuthCode.tenant_id == self.tenant_id, AuthCode.code_hash == code_hash)
            .first()
        )

    def claim_code(self, code_id: str, now: datetime) -> bool:
        res = self.db.execute(
            update(AuthCode)
            .where(AuthCode.tenant_id == self.tenant_id, AuthCode.id == code_id,
                   AuthCode.used_at.is_(None))
            .values(used_at=now)
        )
        return res.rowcount == 1

    # --- tokens ---------------------------------------------------------------------
    def add_token(self, row: Token) -> Token:
        row.tenant_id = self.tenant_id
        self.db.add(row)
        self.db.flush()
        return row

    def get_token_by_hash(self, token_hash: str) -> Optional[Token]:
        return (
            self.db.query(Token)
            .filter(Token.tenant_id == self.tenant_id, Token.token_hash == token_hash)
            .first()
        )

    def claim_token(self, token_id: str, now: datetime) -> bool:
        res = self.db.execute(
            update(Token)
            .where(Token.tenant_id == self.tenant_id, Token.id == token_id, Token.used_at.is_(None))
            .values(used_at=now)
        )
        return res.rowcount == 1

    def delete_family(self, family_id: str) -> None:
        self.db.query(Token).filter(Token.tenant_id == self.tenant_id,
                                    Token.family_id == family_id).delete(synchronize_session=False)

    def delete_grant_tokens(self, grant_id: str) -> None:
        self.db.query(Token).filter(Token.tenant_id == self.tenant_id,
                                    Token.grant_id == grant_id).delete(synchronize_session=False)

    # --- events -----------------------------------------------------------------------
    def add_event(self, *, product: str, event: str, grant_id: Optional[str] = None,
                  reason: Optional[str] = None, actor_user_id: Optional[str] = None) -> None:
        self.db.add(GrantEvent(tenant_id=self.tenant_id, product=product, event=event,
                               grant_id=grant_id, reason=reason, actor_user_id=actor_user_id))

    # --- revoke (caller commits) ------------------------------------------------------------
    def revoke_grant(self, grant: Grant, *, reason: str, event: str = "revoked",
                     actor_user_id: Optional[str] = None, now: Optional[datetime] = None) -> None:
        from datetime import timezone

        grant.status = "revoked"
        grant.revoked_reason = reason
        grant.revoked_at = now or datetime.now(timezone.utc)
        self.delete_grant_tokens(grant.id)
        self.add_event(product=grant.product, event=event, grant_id=grant.id, reason=reason,
                       actor_user_id=actor_user_id)

    # --- call log / events reads -------------------------------------------------------------
    def calls_since(self, grant_ids: list[str], since: datetime) -> dict[str, int]:
        if not grant_ids:
            return {}
        q = (
            self.db.query(CallLog.grant_id, func.count(CallLog.id))
            .filter(CallLog.tenant_id == self.tenant_id, CallLog.grant_id.in_(grant_ids),
                    CallLog.created_at >= since)
            .group_by(CallLog.grant_id)
        )
        return {gid: n for gid, n in q.all()}

    def client_names(self, client_ids: list[str]) -> dict[str, str]:
        if not client_ids:
            return {}
        q = self.db.query(OAuthClient.id, OAuthClient.client_name).filter(
            OAuthClient.tenant_id == self.tenant_id, OAuthClient.id.in_(client_ids))
        return {i: n for i, n in q.all()}

    def list_calls(self, grant_id: str, limit: int = 200) -> list[CallLog]:
        return (
            self.db.query(CallLog)
            .filter(CallLog.tenant_id == self.tenant_id, CallLog.grant_id == grant_id)
            .order_by(CallLog.created_at.desc(), CallLog.id).limit(limit).all()
        )

    def list_events(self, grant_id: str, limit: int = 200) -> list[GrantEvent]:
        return (
            self.db.query(GrantEvent)
            .filter(GrantEvent.tenant_id == self.tenant_id, GrantEvent.grant_id == grant_id)
            .order_by(GrantEvent.created_at.desc(), GrantEvent.id).limit(limit).all()
        )

    # --- manifest cache ------------------------------------------------------------------------
    def get_manifest(self, product: str) -> Optional[ManifestCache]:
        return (
            self.db.query(ManifestCache)
            .filter(ManifestCache.tenant_id == self.tenant_id, ManifestCache.product == product)
            .first()
        )

    def new_manifest(self, product: str) -> ManifestCache:
        row = ManifestCache(tenant_id=self.tenant_id, product=product)
        self.db.add(row)
        self.db.flush()
        return row


class MaintenanceRepository:
    """Cross-tenant housekeeping (system job, no request tenant). Deletes only
    rows past their own retention horizon."""

    def __init__(self, db: Session):
        self.db = db

    def expire_idle_grants(self, cutoff: datetime, now: datetime) -> int:
        idle = (
            self.db.query(Grant)
            .filter(Grant.status == "active",
                    or_(Grant.last_used_at < cutoff,
                        (Grant.last_used_at.is_(None)) & (Grant.created_at < cutoff)))
            .all()
        )
        for g in idle:
            g.status = "expired"
            g.revoked_reason = "idle"
            g.revoked_at = now
            self.db.query(Token).filter(Token.tenant_id == g.tenant_id,
                                        Token.grant_id == g.id).delete(synchronize_session=False)
            self.db.add(GrantEvent(tenant_id=g.tenant_id, grant_id=g.id, product=g.product,
                                   event="expired", reason="idle"))
        return len(idle)

    def prune_call_log(self, cutoff: datetime) -> int:
        return self.db.query(CallLog).filter(CallLog.created_at < cutoff).delete(synchronize_session=False)

    def prune_ephemeral(self, now: datetime) -> None:
        horizon = now - timedelta(days=1)
        self.db.query(PendingRequest).filter(PendingRequest.expires_at < horizon).delete(synchronize_session=False)
        self.db.query(AuthCode).filter(AuthCode.expires_at < horizon).delete(synchronize_session=False)
        self.db.query(Token).filter(Token.expires_at < horizon).delete(synchronize_session=False)
        self.db.query(AssertionJti).filter(AssertionJti.expires_at < now).delete(synchronize_session=False)

