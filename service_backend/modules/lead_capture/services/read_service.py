"""Reads for the staff API and the gateway: sources, settings, keys, endpoints,
deliveries and the lead pull (AC-64-65). Every query is tenant-scoped; the
tenant comes from the JWT or the gateway key, never from the request."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from .. import schemas
from ..mapping import parse_meta_time
from ..models import LcApiKey, LcDelivery, LcLead, LcSource, LcWebhookEndpoint
from . import key_service
from .connect_service import get_settings
from .leadgen_service import lead_item

MAX_PAGE = 100


class ReadError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def source_item(row: LcSource) -> schemas.SourceItem:
    notices = [
        schemas.FormNotice(**n) for n in (row.needs_mapping_json or {}).values() if isinstance(n, dict)
    ]
    return schemas.SourceItem(
        id=row.id,
        platform=row.platform,
        name=row.name,
        status=row.status,
        pageId=row.account_ref,
        pageName=row.account_name,
        formsMode=(row.config_json or {}).get("formsMode"),
        needsMapping=notices,
        lastLeadAt=row.last_lead_at,
        createdAt=row.created_at,
    )


def settings_item(db: Session, tenant_id: str) -> schemas.SettingsItem:
    row = get_settings(db, tenant_id)
    return schemas.SettingsItem(allowSharedPages=bool(row.allow_shared_pages), updatedAt=row.updated_at)


def key_item(row: LcApiKey) -> schemas.KeyItem:
    return schemas.KeyItem(
        id=row.id,
        name=row.name,
        keyMasked=key_service.masked(row),
        createdAt=row.created_at,
        lastUsedAt=row.last_used_at,
        revokedAt=row.revoked_at,
    )


def webhook_item(row: LcWebhookEndpoint) -> schemas.WebhookItem:
    return schemas.WebhookItem(
        id=row.id,
        url=row.url,
        events=list(row.events_json or []),
        createdAt=row.created_at,
        lastSuccessAt=row.last_success_at,
    )


def delivery_item(row: LcDelivery) -> schemas.DeliveryItem:
    return schemas.DeliveryItem(
        id=row.id,
        leadId=row.lead_id,
        event=row.event,
        status=row.status,
        attempt=row.attempt,
        nextAttemptAt=row.next_at,
        lastStatusCode=row.last_code,
        lastError=row.last_error,
    )


def _encode_cursor(received_at: datetime, lead_id: str) -> str:
    raw = json.dumps([received_at.astimezone(timezone.utc).isoformat(), lead_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> Tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        when, lead_id = json.loads(raw)
        parsed = datetime.fromisoformat(when)
        if parsed.tzinfo is None or not isinstance(lead_id, str):
            raise ValueError
        return parsed, lead_id
    except Exception:  # noqa: BLE001
        raise ReadError(422, "invalid_cursor", "The cursor is not valid.") from None


def _parse_since(since: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError:
        parsed = parse_meta_time(since)
    if parsed is None:
        raise ReadError(422, "invalid_since", "since must be an ISO-8601 time, e.g. 2026-11-15T00:00:00Z.")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def pull_leads(
    db: Session,
    tenant_id: str,
    *,
    since: Optional[str] = None,
    cursor: Optional[str] = None,
    source_id: Optional[str] = None,
    limit: int = 50,
) -> schemas.LeadPage:
    """Leads in (received_at, id) order. ``cursor`` (from the previous page)
    wins over ``since``. Each item has the webhook ``data`` shape."""
    limit = max(1, min(int(limit or 50), MAX_PAGE))
    q = db.query(LcLead, LcSource).join(
        LcSource, and_(LcSource.id == LcLead.source_id, LcSource.tenant_id == tenant_id)
    ).filter(LcLead.tenant_id == tenant_id)
    if source_id:
        q = q.filter(LcLead.source_id == source_id)
    if cursor:
        after_at, after_id = _decode_cursor(cursor)
        q = q.filter(or_(LcLead.received_at > after_at, and_(LcLead.received_at == after_at, LcLead.id > after_id)))
    elif since:
        q = q.filter(LcLead.received_at >= _parse_since(since))
    rows = q.order_by(LcLead.received_at.asc(), LcLead.id.asc()).limit(limit + 1).all()
    page = rows[:limit]
    data: List[Dict[str, Any]] = [lead_item(lead, source) for lead, source in page]
    # The cursor always points after the last lead returned, so a consumer
    # polls with it and resumes exactly there (an empty page keeps its cursor).
    next_cursor = _encode_cursor(page[-1][0].received_at, page[-1][0].id) if page else cursor
    return schemas.LeadPage(data=data, nextCursor=next_cursor, hasMore=len(rows) > limit)
