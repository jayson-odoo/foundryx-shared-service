"""Staff Sources and Leads lists (plan 64 L-C, AC-64-05/53).

Server-side search, filter, sort and paging (owner rule: a sort runs on the
server, not the loaded page). Every query is tenant-scoped from the signed-in
user (AC-64-70). Lead answers are Fernet at rest; a list page decrypts only
the rows it returns, and only to show the name.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.secrets import decrypt_secret

from .. import schemas
from ..models import (
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    DELIVERY_SUCCESS,
    LcDelivery,
    LcLead,
    LcSource,
    LcWebhookEndpoint,
)
from .leadgen_service import lead_item
from .read_service import ReadError, delivery_item, source_item

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 200
RECENT_DAYS = 7


def _page(page: int, page_size: int):
    size = max(1, min(int(page_size or 25), MAX_PAGE_SIZE))
    return max(0, int(page or 0)) * size, size


def _like(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").lower() + "%"


def _multi(values: Optional[Sequence[str]]) -> List[str]:
    out: List[str] = []
    for value in values or []:
        for part in str(value).split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


# ── sources ─────────────────────────────────────────────────────────────────

_SOURCE_SORT = {
    "name": LcSource.name,
    "platform": LcSource.platform,
    "pageName": LcSource.account_name,
    "status": LcSource.status,
    "lastLeadAt": LcSource.last_lead_at,
    "createdAt": LcSource.created_at,
}


def list_sources(
    db: Session,
    tenant_id: str,
    *,
    search: Optional[str] = None,
    statuses: Optional[Sequence[str]] = None,
    platforms: Optional[Sequence[str]] = None,
    sort: Optional[str] = None,
    order: str = "desc",
    page: int = 0,
    page_size: int = 25,
) -> schemas.StaffSourcePage:
    since = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    recent = (
        db.query(LcLead.source_id.label("source_id"), func.count(LcLead.id).label("n"))
        .filter(LcLead.tenant_id == tenant_id, LcLead.received_at >= since, LcLead.is_test.is_(False))
        .group_by(LcLead.source_id)
        .subquery()
    )
    leads7d = func.coalesce(recent.c.n, 0)
    q = (
        db.query(LcSource, leads7d.label("leads7d"))
        .outerjoin(recent, recent.c.source_id == LcSource.id)
        .filter(LcSource.tenant_id == tenant_id)
    )
    if search and search.strip():
        pattern = _like(search.strip())
        q = q.filter(
            or_(
                func.lower(LcSource.name).like(pattern, escape="\\"),
                func.lower(func.coalesce(LcSource.account_name, "")).like(pattern, escape="\\"),
            )
        )
    status_list = _multi(statuses)
    if status_list:
        q = q.filter(LcSource.status.in_(status_list))
    platform_list = _multi(platforms)
    if platform_list:
        q = q.filter(LcSource.platform.in_(platform_list))
    total = q.count()
    column = leads7d if sort == "leads7d" else _SOURCE_SORT.get(sort or "", LcSource.created_at)
    primary = column.asc() if order == "asc" else column.desc()
    offset, size = _page(page, page_size)
    rows = q.order_by(primary, LcSource.id.asc()).offset(offset).limit(size).all()
    data = [schemas.StaffSourceItem(**source_item(src).model_dump(), leads7d=int(n or 0)) for src, n in rows]
    return schemas.StaffSourcePage(data=data, total=total)


# ── leads ───────────────────────────────────────────────────────────────────

_LEAD_SORT = {
    "receivedAt": LcLead.received_at,
    "sourceName": LcSource.name,
    "platform": LcLead.platform,
    "formName": LcLead.form_name,
    "email": LcLead.email,
    "phone": LcLead.phone_e164,
    "isTest": LcLead.is_test,
}


def _parse_day(value: Optional[str], end: bool = False) -> Optional[datetime]:
    if not value:
        return None
    try:
        day = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ReadError(422, "invalid_date", "Dates must look like 2026-11-15.") from None
    if day.tzinfo is None:
        day = day.replace(tzinfo=timezone.utc)
    if end and len(value) <= 10:
        day = day + timedelta(days=1)  # whole end day included
    return day


def _lead_name(lead: LcLead) -> Optional[str]:
    if not lead.fields_encrypted or lead.purged_at is not None:
        return None
    try:
        fields = (decrypt_secret(lead.fields_encrypted) or {}).get("fields") or {}
    except Exception:  # noqa: BLE001 - undecryptable: no name shown
        return None
    if fields.get("name"):
        return str(fields["name"])[:200]
    for key, value in fields.items():
        if "name" in str(key).lower() and value:
            return str(value)[:200]
    return None


def _delivery_status(statuses: List[str]) -> Optional[str]:
    if not statuses:
        return None
    if DELIVERY_FAILED in statuses:
        return DELIVERY_FAILED
    if DELIVERY_PENDING in statuses:
        return DELIVERY_PENDING
    return DELIVERY_SUCCESS


def list_leads(
    db: Session,
    tenant_id: str,
    *,
    search: Optional[str] = None,
    source_ids: Optional[Sequence[str]] = None,
    platforms: Optional[Sequence[str]] = None,
    is_test: Optional[bool] = None,
    received_from: Optional[str] = None,
    received_to: Optional[str] = None,
    sort: Optional[str] = None,
    order: str = "desc",
    page: int = 0,
    page_size: int = 25,
) -> schemas.StaffLeadPage:
    q = (
        db.query(LcLead, LcSource)
        .join(LcSource, and_(LcSource.id == LcLead.source_id, LcSource.tenant_id == tenant_id))
        .filter(LcLead.tenant_id == tenant_id)
    )
    if search and search.strip():
        pattern = _like(search.strip())
        q = q.filter(
            or_(
                func.lower(func.coalesce(LcLead.email, "")).like(pattern, escape="\\"),
                func.lower(func.coalesce(LcLead.phone_e164, "")).like(pattern, escape="\\"),
                func.lower(func.coalesce(LcLead.form_name, "")).like(pattern, escape="\\"),
                func.lower(LcSource.name).like(pattern, escape="\\"),
            )
        )
    ids = _multi(source_ids)
    if ids:
        q = q.filter(LcLead.source_id.in_(ids))
    platform_list = _multi(platforms)
    if platform_list:
        q = q.filter(LcLead.platform.in_(platform_list))
    if is_test is not None:
        q = q.filter(LcLead.is_test.is_(bool(is_test)))
    start, end = _parse_day(received_from), _parse_day(received_to, end=True)
    if start is not None:
        q = q.filter(LcLead.received_at >= start)
    if end is not None:
        q = q.filter(LcLead.received_at < end)
    total = q.count()
    column = _LEAD_SORT.get(sort or "", LcLead.received_at)
    primary = column.asc() if order == "asc" else column.desc()
    offset, size = _page(page, page_size)
    rows = q.order_by(primary, LcLead.id.asc()).offset(offset).limit(size).all()
    lead_ids = [lead.id for lead, _ in rows]
    by_lead: Dict[str, List[str]] = {}
    if lead_ids:
        for lead_id, status in (
            db.query(LcDelivery.lead_id, LcDelivery.status)
            .filter(LcDelivery.tenant_id == tenant_id, LcDelivery.lead_id.in_(lead_ids))
            .all()
        ):
            by_lead.setdefault(lead_id, []).append(status)
    data = [
        schemas.StaffLeadItem(
            id=lead.id,
            sourceId=src.id,
            sourceName=src.name,
            platform=lead.platform,
            formId=lead.form_id,
            formName=lead.form_name,
            name=_lead_name(lead),
            email=lead.email,
            phone=lead.phone_e164,
            isTest=bool(lead.is_test),
            duplicateOf=lead.duplicate_of,
            receivedAt=lead.received_at,
            deliveryStatus=_delivery_status(by_lead.get(lead.id, [])),
        )
        for lead, src in rows
    ]
    return schemas.StaffLeadPage(data=data, total=total)


def lead_detail(db: Session, tenant_id: str, lead_id: str) -> schemas.StaffLeadDetail:
    """Mapped fields, attribution, answers and every delivery attempt
    (AC-64-53). The raw platform payload is not echoed (AC-64-71)."""
    row = (
        db.query(LcLead, LcSource)
        .join(LcSource, and_(LcSource.id == LcLead.source_id, LcSource.tenant_id == tenant_id))
        .filter(LcLead.tenant_id == tenant_id, LcLead.id == lead_id)
        .first()
    )
    if row is None:
        raise ReadError(404, "lead_not_found", "Lead not found.")
    lead, source = row
    deliveries = (
        db.query(LcDelivery, LcWebhookEndpoint)
        .outerjoin(
            LcWebhookEndpoint,
            and_(LcWebhookEndpoint.id == LcDelivery.endpoint_id, LcWebhookEndpoint.tenant_id == tenant_id),
        )
        .filter(LcDelivery.tenant_id == tenant_id, LcDelivery.lead_id == lead.id)
        .order_by(LcDelivery.created_at.desc(), LcDelivery.id.asc())
        .all()
    )
    items: List[schemas.DeliveryAttemptItem] = []
    for delivery, endpoint in deliveries:
        base: Dict[str, Any] = delivery_item(delivery).model_dump()
        items.append(
            schemas.DeliveryAttemptItem(
                **base,
                endpointUrl=endpoint.url if endpoint is not None else None,
                lastAttemptAt=delivery.last_attempt_at,
                createdAt=delivery.created_at,
            )
        )
    return schemas.StaffLeadDetail(lead=lead_item(lead, source), deliveries=items)
