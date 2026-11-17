"""Reads for the staff API and the gateway: sources, settings, keys, endpoints,
deliveries and the lead pull (AC-64-65). Every query is tenant-scoped; the
tenant comes from the JWT or the gateway key, never from the request."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from .. import schemas
from ..mapping import parse_meta_time
from ..models import LcApiKey, LcDelivery, LcLead, LcSource, LcWebhookEndpoint
from . import key_service
from .connect_service import get_settings
from .leadgen_service import lead_item
from .source_service import forms_mode, picked_forms

MAX_PAGE = 100
# Leads younger than this are held back from the pull: the time a lead is
# stamped and the time its transaction commits differ slightly, and a cursor
# must never move past a lead that is still committing (it would be skipped).
PULL_SETTLE_SECONDS = 5


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
        formsMode=forms_mode(row),
        formIds=picked_forms(row),
        needsMapping=notices,
        fieldMap=dict(row.field_map_json or {}),
        lastLeadAt=row.last_lead_at,
        backfillLastRunAt=row.backfill_last_run_at,
        backfillLastError=row.backfill_last_error,
        createdAt=row.created_at,
    )


def fields_item(db: Session, tenant_id: str) -> schemas.ConsumerFieldList:
    from ..mapping import DEFAULT_FIELDS
    from .field_service import list_fields

    rows = list_fields(db, tenant_id)
    if not rows:
        labels = {"name": "Name", "phone": "Phone", "email": "Email", "notes": "Lead notes"}
        return schemas.ConsumerFieldList(
            data=[schemas.ConsumerField(key=k, label=labels[k], type=t) for k, t in DEFAULT_FIELDS], isDefault=True
        )
    return schemas.ConsumerFieldList(data=[schemas.ConsumerField(key=r.key, label=r.label, type=r.type) for r in rows])


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
        return _bounded_utc(parsed), lead_id
    except Exception:  # noqa: BLE001
        raise ReadError(422, "invalid_cursor", "The cursor is not valid.") from None


def _parse_since(since: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError:
        parsed = parse_meta_time(since)
    except OverflowError:
        parsed = None
    try:
        if parsed is None:
            raise ValueError
        return _bounded_utc(parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc))
    except (ValueError, OverflowError):
        raise ReadError(422, "invalid_since", "since must be an ISO-8601 time, e.g. 2026-11-15T00:00:00Z.") from None


def _bounded_utc(value: datetime) -> datetime:
    """Aware UTC within 1970-9000; an edge date that would overflow on the
    UTC conversion is a ValueError (a 422), never a 500."""
    utc = value.astimezone(timezone.utc)
    if not 1970 <= utc.year <= 9000:
        raise ValueError("out of range")
    return utc


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
    q = q.filter(LcLead.received_at <= datetime.now(timezone.utc) - timedelta(seconds=PULL_SETTLE_SECONDS))
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
