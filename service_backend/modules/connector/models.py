"""Connector module models - all live in ``app_connector`` (plan sprint-4/19).

Every table carries ``tenant_id`` (a plain indexed column, not a cross-schema FK -
BL-030). Tenant comes from the product registry entry, never from client input.
Tokens, auth codes and the browser-binding value are stored ONLY as SHA-256
hashes. Datetimes are aware-UTC (``UTCDateTime``); JSON uses ``none_as_null``.
"""

from __future__ import annotations
import uuid

from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.types import JSON

from app.models.utc_datetime import UTCDateTime

from .db import ConnectorBase


def _uuid() -> str:
    return str(uuid.uuid4())


def _created() -> Column:
    return Column(UTCDateTime(), server_default=func.now(), nullable=False)


class OAuthClient(ConnectorBase):
    __tablename__ = "oauth_clients"
    id = Column(String, primary_key=True, default=_uuid)  # = client_id
    tenant_id = Column(String, nullable=False, index=True)
    product = Column(String(32), nullable=False)
    client_name = Column(String(120), nullable=False)
    redirect_uris = Column(JSON(none_as_null=True), nullable=False)
    created_at = _created()


class PendingRequest(ConnectorBase):
    __tablename__ = "pending_requests"
    id = Column(String, primary_key=True, default=_uuid)  # = request_id
    tenant_id = Column(String, nullable=False, index=True)
    product = Column(String(32), nullable=False)
    client_id = Column(String, nullable=False)
    redirect_uri = Column(Text, nullable=False)
    code_challenge = Column(String(128), nullable=False)
    state = Column(String(512), nullable=True)
    bind_hash = Column(String(64), nullable=False)
    expires_at = Column(UTCDateTime(), nullable=False)
    used_at = Column(UTCDateTime(), nullable=True)
    created_at = _created()


class Grant(ConnectorBase):
    __tablename__ = "grants"
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    product = Column(String(32), nullable=False)
    product_user_id = Column(String(128), nullable=False)
    name = Column(String(255), nullable=True)
    email = Column(String(320), nullable=True)
    client_id = Column(String, nullable=False)
    consented_at = Column(UTCDateTime(), nullable=False)
    status = Column(String(16), nullable=False, default="active")  # active|revoked|expired
    revoked_reason = Column(String(64), nullable=True)
    revoked_at = Column(UTCDateTime(), nullable=True)
    last_used_at = Column(UTCDateTime(), nullable=True)
    created_at = _created()
    __table_args__ = (
        Index("ix_connector_grants_lookup", "tenant_id", "product", "product_user_id", "client_id"),
    )


class AuthCode(ConnectorBase):
    __tablename__ = "auth_codes"
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    code_hash = Column(String(64), nullable=False, unique=True)
    grant_id = Column(String, ForeignKey("grants.id"), nullable=False)
    client_id = Column(String, nullable=False)
    redirect_uri = Column(Text, nullable=False)
    code_challenge = Column(String(128), nullable=False)
    expires_at = Column(UTCDateTime(), nullable=False)
    used_at = Column(UTCDateTime(), nullable=True)
    created_at = _created()


class Token(ConnectorBase):
    __tablename__ = "tokens"
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    kind = Column(String(8), nullable=False)  # access|refresh
    grant_id = Column(String, ForeignKey("grants.id"), nullable=False, index=True)
    family_id = Column(String, nullable=False, index=True)
    expires_at = Column(UTCDateTime(), nullable=False)
    used_at = Column(UTCDateTime(), nullable=True)
    revoked_at = Column(UTCDateTime(), nullable=True)
    created_at = _created()


class AssertionJti(ConnectorBase):
    __tablename__ = "assertion_jti"
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    product = Column(String(32), nullable=False)
    jti = Column(String(255), nullable=False)
    expires_at = Column(UTCDateTime(), nullable=False, index=True)
    created_at = _created()
    __table_args__ = (UniqueConstraint("tenant_id", "product", "jti", name="uq_connector_jti"),)


class CallLog(ConnectorBase):
    __tablename__ = "call_log"
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    grant_id = Column(String, ForeignKey("grants.id"), nullable=False, index=True)
    product = Column(String(32), nullable=False)
    product_user_id = Column(String(128), nullable=False)
    tool = Column(String(128), nullable=False)
    args_json = Column(Text, nullable=True)  # capped at 4 KB by the writer
    status = Column(String(32), nullable=False)
    duration_ms = Column(Integer, nullable=False, default=0)
    rows = Column(Integer, nullable=True)
    chars = Column(Integer, nullable=True)
    error_code = Column(String(64), nullable=True)
    http_status = Column(Integer, nullable=True)
    truncated = Column(Boolean, nullable=False, default=False)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False, index=True)


class GrantEvent(ConnectorBase):
    __tablename__ = "grant_events"
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    grant_id = Column(String, ForeignKey("grants.id"), nullable=True, index=True)
    product = Column(String(32), nullable=False)
    event = Column(String(32), nullable=False)  # consented|denied|refreshed|revoked|...
    reason = Column(String(64), nullable=True)
    actor_user_id = Column(String, nullable=True)
    created_at = _created()


class ManifestCache(ConnectorBase):
    __tablename__ = "manifest_cache"
    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    product = Column(String(32), nullable=False)
    manifest_json = Column(JSON(none_as_null=True), nullable=True)
    version = Column(String(128), nullable=True)
    fetched_at = Column(UTCDateTime(), nullable=True)
    last_error = Column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("tenant_id", "product", name="uq_connector_manifest"),)
