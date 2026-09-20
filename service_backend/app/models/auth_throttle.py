"""Brute-force throttle counters (plan 10 §5).

One row per (scope, key): scope "email" tracks failed logins per account,
scope "ip" tracks failures per client address. Postgres-backed by design (D5)
- auth traffic is low-QPS and on-prem stays one-service; the Redis adapter is
BL-040. Stale rows are pruned by the email-dispatcher housekeeping pass.
"""
import uuid

from sqlalchemy import Column, Integer, String, UniqueConstraint
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base

THROTTLE_SCOPE_EMAIL = "email"
THROTTLE_SCOPE_IP = "ip"
# Public form submissions - own per-IP bucket so anonymous form spam never
# locks the login/forgot-password IP bucket and vice versa (plan sprint-3/02 D12).
THROTTLE_SCOPE_FORM_PUBLIC = "form_public"
# Public document-share access (unlock attempts + anonymous uploads) - own
# per-IP bucket, never shares login/form buckets (plan sprint-3/05 D6).
THROTTLE_SCOPE_DOC_SHARE = "doc_share"
# Profile Portal auth (EMS, sprint-4/06 slice 0a) - own per-IP bucket so portal
# login/OTP/forgot/set-password spam never locks the staff login bucket and
# vice versa (AC-06-16). Distinct from THROTTLE_SCOPE_IP.
THROTTLE_SCOPE_PORTAL = "portal"
# Omnichannel embed session exchange (plan sprint-4/11H, AC-11H-08) - own per-IP
# bucket so embed assertion-exchange spam never locks the staff login bucket and
# vice versa. Window-throttle (no permanent lock).
THROTTLE_SCOPE_EMBED = "embed_session"
# Omnichannel web chat public visitor API (plan sprint-4/34 / A7b S2,
# AC-WEB-30, D-A7B-22) - own bucket, shared by TWO independent key namespaces
# within it (`ip:<ip>`, `v:<visitorId>` - see `throttle.py`'s
# `enforce_webchat`/`record_webchat`), never the login/form/doc-share/portal/
# embed bucket. Window-throttle (no permanent lock).
THROTTLE_SCOPE_WEBCHAT = "webchat"
# AutoCount pull gateway (sprint-5/10 S4, AC-10-35) - own per-IP bucket for
# the PUBLIC `/api/v1/autocount/*` gateway so a bad-key spray never locks the
# staff login bucket and vice versa. Window-throttle like IP (no permanent
# lock) - a legitimate integration client retrying a stale key must self-heal.
THROTTLE_SCOPE_PULL = "pull"
# AutoCount pull gateway - PER-KEY request budget (sprint-5/10 S4 security
# round 1, MEDIUM 4). AC-10-35 itself only asks for the per-IP `pull` scope
# above (a failure-only counter); this is ADDITIVE, settings-driven, generous
# defaults - a valid-but-narrowly-scoped key could otherwise probe unlimited
# out-of-scope ids (403/404/409, never a 401) at zero throttle cost, since
# THROTTLE_SCOPE_PULL only ever counts 401s. Counted on every authenticated
# call regardless of outcome (mirrors `record_webchat`'s IP bucket - "not a
# failed credential attempt", same reused counter mechanism).
THROTTLE_SCOPE_PULL_KEY = "pull_key"


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
