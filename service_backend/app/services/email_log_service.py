"""Email log — outbox surfacing + retry/cancel (plan 07 D14).

Tenant-scoped: a workspace sees ONLY its own outbox rows (bodies carry live
reset/invite links — capability-bearing). Cross-tenant operator view is
deliberately not v1.
"""

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from app.models.email_outbox import (
    OUTBOX_CANCELLED,
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    EmailOutbox,
)
from app.schemas.filters import FilterGroup
from app.services.filter_translator import translate_filter


class EmailLogError(Exception):
    """422-class problem."""


class EmailLogConflict(Exception):
    """409 — lost the race against the dispatcher (or wrong state)."""


class EmailLogNotFound(Exception):
    pass


_FILTER_COLUMNS = {
    "toEmail": EmailOutbox.to_email,
    "subject": EmailOutbox.subject,
    "templateKey": EmailOutbox.template_key,
    "status": EmailOutbox.status,
}

_SORT_MAP = {
    "toEmail": EmailOutbox.to_email,
    "subject": EmailOutbox.subject,
    "templateKey": EmailOutbox.template_key,
    "status": EmailOutbox.status,
    "attempts": EmailOutbox.attempts,
    "createdAt": EmailOutbox.created_at,
    "sentAt": EmailOutbox.sent_at,
}

# Wire segment ids (lowercase) — 'all' = no status filter.
SEGMENTS = {"pending", "sending", "sent", "failed", "cancelled"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EmailLogService:
    def __init__(self, db: Session):
        self.db = db

    def list(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "desc",
        filter_group: Optional[FilterGroup] = None,
        segment: Optional[str] = None,
    ) -> Tuple[List[EmailOutbox], int]:
        query = self.db.query(EmailOutbox).filter(EmailOutbox.tenant_id == tenant_id)
        if segment and segment != "all":
            if segment not in SEGMENTS:
                raise EmailLogError(f'Unknown segment "{segment}".')
            query = query.filter(EmailOutbox.status == segment)
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(
                    EmailOutbox.to_email.ilike(like),
                    EmailOutbox.subject.ilike(like),
                    EmailOutbox.template_key.ilike(like),
                )
            )
        clause = translate_filter(filter_group, _FILTER_COLUMNS)
        if clause is not None:
            query = query.filter(clause)

        total = query.count()
        column = _SORT_MAP.get(sort_by or "createdAt", EmailOutbox.created_at)
        query = query.order_by(column.asc() if sort_dir == "asc" else column.desc())
        rows = query.offset(page * page_size).limit(page_size).all()
        return rows, total

    def get_at(self, index: int, tenant_id: str, **list_kwargs) -> Tuple[Optional[EmailOutbox], int]:
        rows, total = self.list(tenant_id, page=max(index, 0), page_size=1, **list_kwargs)
        return (rows[0] if rows else None), total

    def get(self, email_id: str, tenant_id: str) -> EmailOutbox:
        row = (
            self.db.query(EmailOutbox)
            .filter(EmailOutbox.id == email_id, EmailOutbox.tenant_id == tenant_id)
            .first()
        )
        if row is None:
            raise EmailLogNotFound()
        return row

    def retry(self, email_id: str, tenant_id: str) -> EmailOutbox:
        """FAILED|CANCELLED → PENDING, next attempt now; attempts PRESERVED
        (history honest — each manual retry buys one more dispatcher pass)."""
        row = self.get(email_id, tenant_id)
        if row.status not in (OUTBOX_FAILED, OUTBOX_CANCELLED):
            raise EmailLogError("Only failed or cancelled emails can be retried.")
        row.status = OUTBOX_PENDING
        row.next_attempt_at = _now()
        row.last_error = None
        self.db.commit()
        self.db.refresh(row)
        return row

    def cancel(self, email_id: str, tenant_id: str) -> EmailOutbox:
        """PENDING → CANCELLED via atomic conditional UPDATE — if the
        dispatcher's lease claim already flipped the row to SENDING, the
        rowcount is 0 and the caller gets a 409 (it was too late)."""
        row = self.get(email_id, tenant_id)  # 404 before 409
        result = self.db.execute(
            update(EmailOutbox)
            .where(
                EmailOutbox.id == email_id,
                EmailOutbox.tenant_id == tenant_id,
                EmailOutbox.status == OUTBOX_PENDING,
            )
            # next_attempt_at stays (NOT NULL column) — only PENDING rows are
            # ever claimed, so a cancelled row's timestamp is inert.
            .values(status=OUTBOX_CANCELLED)
        )
        if result.rowcount == 0:
            self.db.rollback()
            raise EmailLogConflict("Email is already sending or sent — too late to cancel.")
        self.db.commit()
        self.db.refresh(row)
        return row
