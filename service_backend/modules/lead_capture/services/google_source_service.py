"""Google Ads lead form source, guided path (card 68a, plan 64 AC-64-40/41/44).

Google only ever POSTs to us here: the customer pastes our inbound URL and the
source's Google key into each Google Ads lead form ("Lead delivery option" >
webhook). Google's body: https://developers.google.com/google-ads/webhook/docs/implementation

- ``create_guided_source``: ONE create function for the wizard, staff and the
  gateway (R1). The URL's ``source_key`` and the Google key are random; the
  key is Fernet in ``credentials_encrypted`` and returned only here and on a
  rotate.
- ``receive``: the public receiver (R2/R3/R5/R6). The ``sourceKey`` in the
  path picks the source; the body's ``google_key`` must match. An unknown
  source and a wrong key answer the same 403. Wrong keys count on the per-IP
  lead-gateway throttle; a right key is never throttled (Google's bursts must
  not lose leads). The lead goes through the ONE store path
  (``leadgen_service.store_for_sources``).
- ``rotate_key`` (R8): a new Google key, the old one refused at once.
No key and no answer value reaches a log line (AC-64-71).
"""
from __future__ import annotations

import hmac
import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.secrets import decrypt_secret, encrypt_secret
from app.services.throttle import Throttled, ThrottleService

from .. import mapping
from ..models import (
    MODE_GUIDED,
    PLATFORM_GOOGLE,
    SOURCE_DISCONNECTED,
    SOURCE_ROUTING_STATES,
    SOURCE_WAITING_FOR_TEST,
    LcLead,
    LcSource,
)
from . import leadgen_service, source_service
from .source_service import Actor, SourceError

logger = logging.getLogger(__name__)

INBOUND_PATH = "/public/lead-capture/in/"
MAX_BODY_BYTES = 64 * 1024
MAX_COLUMNS = 200
DEFAULT_NAME = "Google Ads"
ACTION_KEY_ROTATED = "key_rotated"
_KEY_BYTES = 24  # 32 url-safe characters


def _new_secret() -> str:
    return secrets.token_urlsafe(_KEY_BYTES)


def inbound_url(source: LcSource) -> str:
    return f"{settings.public_base_url.rstrip('/')}{INBOUND_PATH}{source.source_key}"


def _google_key(source: LcSource) -> Optional[str]:
    if not source.credentials_encrypted:
        return None
    try:
        return str(decrypt_secret(source.credentials_encrypted).get("googleKey") or "") or None
    except Exception:  # noqa: BLE001 - undecryptable = no usable key (403, never 500)
        return None


def create_guided_source(
    db: Session, tenant_id: str, *, actor: Actor, user_id: Optional[str] = None
) -> Tuple[LcSource, str, str]:
    """A new Google source waiting for its test lead. Returns
    ``(source, inbound URL, Google key)``; the key is shown only now."""
    key = _new_secret()
    source = LcSource(
        tenant_id=tenant_id,
        platform=PLATFORM_GOOGLE,
        mode=MODE_GUIDED,
        name=DEFAULT_NAME,
        status=SOURCE_WAITING_FOR_TEST,
        source_key=_new_secret(),
        credentials_encrypted=encrypt_secret({"googleKey": key}),
        created_by=user_id,
    )
    db.add(source)
    db.flush()
    source_service.record_event(db, source, source_service.ACTION_CONNECTED, actor, None, SOURCE_WAITING_FOR_TEST)
    db.commit()
    db.refresh(source)
    return source, inbound_url(source), key


def rotate_key(db: Session, tenant_id: str, source_id: str, *, actor: Actor) -> Tuple[str, str]:
    """A new Google key; the old one answers 403 from this commit on."""
    source = source_service.get_source(db, tenant_id, source_id)
    if source.platform != PLATFORM_GOOGLE:
        raise SourceError(409, "not_a_guided_source", "Only a Google source has a key.")
    if source.status == SOURCE_DISCONNECTED:
        raise SourceError(409, "source_disconnected", "This source is disconnected.")
    key = _new_secret()
    source.credentials_encrypted = encrypt_secret({"googleKey": key})
    source_service.record_event(db, source, ACTION_KEY_ROTATED, actor)
    db.commit()
    db.refresh(source)
    return inbound_url(source), key


# ── the receiver ───────────────────────────────────────────────────────────

class ReceiveError(SourceError):
    pass


_INVALID_KEY = ("invalid_key", "The key is not valid.")


def _id(value: Any) -> Optional[str]:
    """Google ids arrive as numbers or strings; both are kept as strings."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, str)):
        text = str(value).strip()
        return text[:128] or None
    return None


def answers_from_google(columns: Any) -> List[Dict[str, Any]]:
    """``user_column_data`` -> the shared ``[{"key", "values"}]`` answers (R3):
    key = ``column_id``, else ``column_name``; a missing value stays empty."""
    out: List[Dict[str, Any]] = []
    if not isinstance(columns, list):
        return out
    for item in columns[:MAX_COLUMNS]:
        if not isinstance(item, dict):
            continue
        key = item.get("column_id") or item.get("column_name")
        if not isinstance(key, str) or not key.strip():
            continue
        value = item.get("string_value")
        out.append({"key": key.strip()[:200], "values": [str(value)] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else []})
    return out


def _parse(raw_body: bytes) -> Dict[str, Any]:
    if len(raw_body) > MAX_BODY_BYTES:
        raise ReceiveError(413, "invalid_body", "The body is too large.")
    try:
        body = json.loads(raw_body or b"")
    except (ValueError, UnicodeDecodeError):
        raise ReceiveError(400, "invalid_body", "The body is not valid JSON.") from None
    if not isinstance(body, dict):
        raise ReceiveError(400, "invalid_body", "The body is not a JSON object.")
    return body


def _refuse_key(throttle: ThrottleService, ip: str) -> ReceiveError:
    try:
        throttle.enforce_lead_gateway(ip=ip)
    except Throttled as exc:
        return ReceiveError(429, "rate_limited", "Too many failed attempts. Try again shortly.", exc.retry_after_seconds)
    throttle.record_lead_gateway_failure(ip=ip)
    return ReceiveError(403, *_INVALID_KEY)


def receive(db: Session, source_key: str, raw_body: bytes, *, ip: str) -> Optional[str]:
    """Store one Google lead for the source behind ``source_key``. Returns the
    lead id (None for a repeat). Raises ``ReceiveError``."""
    throttle = ThrottleService(db)
    body = _parse(raw_body)
    source = (
        db.query(LcSource)
        .filter(LcSource.source_key == (source_key or "")[:64], LcSource.platform == PLATFORM_GOOGLE)
        .first()
        if source_key
        else None
    )
    if source is not None and source.status == SOURCE_DISCONNECTED:
        raise ReceiveError(410, "source_disconnected", "This source is disconnected.")
    expected = _google_key(source) if source is not None else None
    presented = body.get("google_key")
    if not expected or not isinstance(presented, str) or not hmac.compare_digest(
        presented.encode(), expected.encode()
    ):
        raise _refuse_key(throttle, ip)
    if not leadgen_service._active(db, source.tenant_id):
        raise ReceiveError(403, "service_not_enabled", "Lead Capture is not enabled for this tenant.")
    lead_id = _id(body.get("lead_id"))
    if not lead_id:
        raise ReceiveError(400, "invalid_body", "The body has no lead_id.")
    return _store(db, source, lead_id, body)


def _store(db: Session, source: LcSource, lead_id: str, body: Dict[str, Any]) -> Optional[str]:
    source = source_service.locked_source(db, source.id)
    if source is None or source.status not in SOURCE_ROUTING_STATES:
        db.rollback()
        raise ReceiveError(410, "source_disconnected", "This source is disconnected.")
    exists = (
        db.query(LcLead.id)
        .filter(LcLead.source_id == source.id, LcLead.platform_lead_id == lead_id)
        .first()
    )
    if exists is not None:
        db.rollback()
        return None  # Google re-sent it (R6)
    form_id = _id(body.get("form_id")) or ""
    raw = {k: v for k, v in body.items() if k != "google_key"}
    attribution = {
        "formId": form_id or None,
        "campaignId": _id(body.get("campaign_id")),
        "adgroupId": _id(body.get("adgroup_id")),
        "creativeId": _id(body.get("creative_id")),
        "gclid": _id(body.get("gcl_id")),
    }
    created = leadgen_service.store_for_sources(
        db,
        [source],
        platform=PLATFORM_GOOGLE,
        platform_lead_id=lead_id,
        page_id=None,
        form_id=form_id,
        form_name=None,
        answers=answers_from_google(body.get("user_column_data")),
        raw=raw,
        platform_created_at=mapping.parse_meta_time(body.get("lead_submit_time")),
        attribution=attribution,
        is_test=body.get("is_test") is True,
        received_at=datetime.now(timezone.utc),
        live_on_any_lead=True,
    )
    return created[0] if created else None
