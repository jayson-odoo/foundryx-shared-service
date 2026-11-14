"""AutoCount call-log reads (plan 63 section 3.4) - pure SQLAlchemy, no business logic.

    !!  EVERY query filters ``tenant_id``; the company is joined WITH ``tenant_id``.  !!
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import AcApiCallLog, AcCompany

_COMPANY_NAME = func.coalesce(AcCompany.name, AcCompany.company_name)

# wire sort field -> column expression (the only sortable things; anything else never reaches SQL)
SORT_COLUMNS: Dict[str, Any] = {
    "createdAt": AcApiCallLog.created_at,
    "companyName": _COMPANY_NAME,
    "book": AcApiCallLog.book,
    "actingUserName": AcApiCallLog.acting_user_name,
    "method": AcApiCallLog.method,
    "path": AcApiCallLog.path,
    "docType": AcApiCallLog.doc_type,
    "docNo": AcApiCallLog.doc_no,
    "outcome": AcApiCallLog.outcome,
    "responseStatus": AcApiCallLog.response_status,
    "durationMs": AcApiCallLog.duration_ms,
    "errorCode": AcApiCallLog.error_code,
    "requestId": AcApiCallLog.request_id,
}


@dataclass
class CallFilters:
    company_ids: Sequence[str] = field(default_factory=list)
    books: Sequence[str] = field(default_factory=list)
    doc_types: Sequence[str] = field(default_factory=list)
    outcomes: Sequence[str] = field(default_factory=list)
    persons: Sequence[str] = field(default_factory=list)
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    search: Optional[str] = None


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class CallLogRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _base(self, tenant_id: str, *columns: Any):
        return (
            self.db.query(*columns)
            .select_from(AcApiCallLog)
            .outerjoin(
                AcCompany,
                (AcCompany.id == AcApiCallLog.company_id) & (AcCompany.tenant_id == AcApiCallLog.tenant_id),
            )
            .filter(AcApiCallLog.tenant_id == tenant_id)
        )

    @staticmethod
    def _filtered(query, f: CallFilters):
        if f.company_ids:
            query = query.filter(AcApiCallLog.company_id.in_(list(f.company_ids)))
        if f.books:
            query = query.filter(AcApiCallLog.book.in_(list(f.books)))
        if f.doc_types:
            query = query.filter(AcApiCallLog.doc_type.in_(list(f.doc_types)))
        if f.outcomes:
            query = query.filter(AcApiCallLog.outcome.in_(list(f.outcomes)))
        if f.persons:
            query = query.filter(AcApiCallLog.acting_user_id.in_(list(f.persons)))
        if f.date_from is not None:
            query = query.filter(AcApiCallLog.created_at >= f.date_from)
        if f.date_to is not None:
            query = query.filter(AcApiCallLog.created_at <= f.date_to)
        if f.search:
            like = _like(f.search)
            query = query.filter(
                or_(
                    AcApiCallLog.doc_no.ilike(like, escape="\\"),
                    AcApiCallLog.request_id.ilike(like, escape="\\"),
                    AcApiCallLog.path.ilike(like, escape="\\"),
                )
            )
        return query

    def search(
        self, tenant_id: str, filters: CallFilters, *, sort: str, descending: bool, page: int, page_size: int
    ) -> Tuple[List[Tuple[AcApiCallLog, Optional[str]]], int]:
        total = self._filtered(self._base(tenant_id, func.count(AcApiCallLog.id)), filters).scalar() or 0
        column = SORT_COLUMNS[sort]
        primary = column.desc() if descending else column.asc()
        rows = (
            self._filtered(self._base(tenant_id, AcApiCallLog, _COMPANY_NAME), filters)
            .order_by(primary.nulls_last(), AcApiCallLog.created_at.desc(), AcApiCallLog.id.asc())
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return [(row, name) for row, name in rows], int(total)

    def get(self, tenant_id: str, call_id: str) -> Optional[Tuple[AcApiCallLog, Optional[str]]]:
        found = (
            self._base(tenant_id, AcApiCallLog, _COMPANY_NAME).filter(AcApiCallLog.id == call_id).first()
        )
        return None if found is None else (found[0], found[1])

    def _distinct(self, tenant_id: str, column: Any) -> List[str]:
        rows = (
            self.db.query(column)
            .filter(AcApiCallLog.tenant_id == tenant_id, column.isnot(None))
            .distinct()
            .order_by(column)
            .all()
        )
        return [r[0] for r in rows]

    def books(self, tenant_id: str) -> List[str]:
        return self._distinct(tenant_id, AcApiCallLog.book)

    def doc_types(self, tenant_id: str) -> List[str]:
        return self._distinct(tenant_id, AcApiCallLog.doc_type)

    def outcomes(self, tenant_id: str) -> List[str]:
        return self._distinct(tenant_id, AcApiCallLog.outcome)

    def persons(self, tenant_id: str) -> List[Tuple[str, Optional[str]]]:
        """Each acting user id once, with the latest name any of its rows carries."""
        log = AcApiCallLog
        newest = (
            self.db.query(log.acting_user_id.label("uid"), func.max(log.created_at).label("at"))
            .filter(log.tenant_id == tenant_id, log.acting_user_id.isnot(None), log.acting_user_name.isnot(None))
            .group_by(log.acting_user_id)
            .subquery()
        )
        named = (
            self.db.query(log.acting_user_id, func.max(log.acting_user_name))
            .join(newest, (log.acting_user_id == newest.c.uid) & (log.created_at == newest.c.at))
            .filter(log.tenant_id == tenant_id)
            .group_by(log.acting_user_id)
            .all()
        )
        names: Dict[str, Optional[str]] = {user_id: name for user_id, name in named}
        ids = (
            self.db.query(log.acting_user_id)
            .filter(log.tenant_id == tenant_id, log.acting_user_id.isnot(None))
            .distinct()
            .all()
        )
        return sorted((row[0], names.get(row[0])) for row in ids)
