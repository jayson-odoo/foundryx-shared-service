"""Brute-force throttle counters (plan 10 §5).

One row per (scope, key): scope "email" tracks failed logins per account,
scope "ip" tracks failures per client address. Postgres-backed by design (D5)
— auth traffic is low-QPS and on-prem stays one-service; the Redis adapter is
BL-040. Stale rows are pruned by the email-dispatcher housekeeping pass.
"""
import uuid

from sqlalchemy import Column, Integer, String, UniqueConstraint
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base

THROTTLE_SCOPE_EMAIL = "email"
THROTTLE_SCOPE_IP = "ip"
# Public form submissions — own per-IP bucket so anonymous form spam never
# locks the login/forgot-password IP bucket and vice versa (plan sprint-3/02 D12).
THROTTLE_SCOPE_FORM_PUBLIC = "form_public"
# Public document-share access (unlock attempts + anonymous uploads) — own
# per-IP bucket, never shares login/form buckets (plan sprint-3/05 D6).
THROTTLE_SCOPE_DOC_SHARE = "doc_share"
# Profile Portal auth (EMS, sprint-4/06 slice 0a) — own per-IP bucket so portal
# login/OTP/forgot/set-password spam never locks the staff login bucket and
# vice versa (AC-06-16). Distinct from THROTTLE_SCOPE_IP.
THROTTLE_SCOPE_PORTAL = "portal"


class AuthThrottle(Base):
    __tablename__ = "auth_throttle"
    __table_args__ = (UniqueConstraint("scope", "key", name="uq_auth_throttle_scope_key"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    scope = Column(String, nullable=False)  # "email" | "ip"
    key = Column(String, nullable=False, index=True)  # normalized email / client IP
    window_start = Column(UTCDateTime(), nullable=False)
    fail_count = Column(Integer, nullable=False, default=0)
    locked_until = Column(UTCDateTime(), nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
