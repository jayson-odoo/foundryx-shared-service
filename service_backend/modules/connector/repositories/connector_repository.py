"""Connector repositories - pure SQLAlchemy, EVERY query tenant-scoped.

The tenant is the product registry's owning tenant (never client input).
Atomic "claim" updates (``used_at IS NULL``) make single-use rows race-safe.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import func, or_, update
from sqlalchemy.orm import Session

from ..models import (
    AssertionJti,
    AuthCode,
    Grant,
    GrantEvent,
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
