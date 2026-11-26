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
# Claude connector OAuth endpoints (plan sprint-4/19): DCR + token failures per IP
# and tools/call per grant - own bucket, never shares login.
THROTTLE_SCOPE_CONNECTOR = "connector"
# tools/call per grant (key = grant id).
THROTTLE_SCOPE_CONNECTOR_CALL = "connector_call"
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
# Ideation BR build write-back gateway per IP (plan ideation-br-send-to-build,
# AC-STB-16) - own bucket, the pull-gateway pattern: only a 401 (missing/
# malformed/unknown/revoked key) records a failure.
THROTTLE_SCOPE_BUILD = "build"
# Ideation public status-page comments (plan 19, AC-19-30) - TWO own buckets, never
# the login/form buckets: per token (key = sha256 of the token, never the raw
# credential) and per client IP. Every successful post counts.
THROTTLE_SCOPE_IDEA_COMMENT_TOKEN = "idea_comment_token"
THROTTLE_SCOPE_IDEA_COMMENT_IP = "idea_comment_ip"
# Ideation idea portal (lane IDEA-PORTAL): comment posts and idea submits per
# signed-in principal (key = sha256 of tenant + voter id).
THROTTLE_SCOPE_IDEA_PORTAL_COMMENT = "idea_portal_comment"
THROTTLE_SCOPE_IDEA_PORTAL_SUBMIT = "idea_portal_submit"
THROTTLE_SCOPE_IDEA_PORTAL_UPLOAD = "idea_portal_upload"
# Personal feedback link exchange (lane PUBLIC-IDEAS-BOARD): failed exchanges
# per client IP (an own bucket; a guessing run never touches the login buckets).
THROTTLE_SCOPE_IDEA_FEEDBACK_LINK = "idea_feedback_link"
# Follow / comment from a feedback share link (lane FEEDBACK-SUBSCRIBE): every
# send-code / verify-code request, keyed per client IP and per phone digits.
THROTTLE_SCOPE_IDEA_FOLLOW_PHONE = "idea_follow_phone"
# Files read through a feedback share link (lane FEEDBACK-IMAGE-PREVIEW): every
# read counts, per client IP - the route is public and re-serves the bytes.
THROTTLE_SCOPE_IDEA_SHARE_FILE = "idea_share_file"
# Omnichannel replace-token attempts per channel (plan 42): every attempt counts,
# refused ones included (key = channel id).
THROTTLE_SCOPE_CHANNEL_TOKEN = "channel_token"
# Lead Capture gateway (plan 64 AC-64-72) - own buckets, the pull-gateway
# pattern: per IP counts 401s only; per key counts every authenticated call.
THROTTLE_SCOPE_LEAD_GATEWAY = "lead_gateway"
THROTTLE_SCOPE_LEAD_GATEWAY_KEY = "lead_gateway_key"
# Hub Connector hub read API: failed keys per IP, and the request budget per key.
THROTTLE_SCOPE_HUB_API = "hub_api"
THROTTLE_SCOPE_HUB_API_KEY = "hub_api_key"


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
