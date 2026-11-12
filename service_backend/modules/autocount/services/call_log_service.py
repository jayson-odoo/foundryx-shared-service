"""AutoCount calls view (plan 63 section 3.4): reads the call log of the caller's tenant.

The tenant always comes from the authenticated user (the router passes it in).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import AcApiCallLog
from ..repositories.call_log_repository import CallFilters, CallLogRepository


def _row(row: AcApiCallLog, company_name: Optional[str]) -> Dict[str, Any]:
    return {
        "id": row.id, "created_at": row.created_at, "company_id": row.company_id, "company_name": company_name,
        "book": row.book, "acting_user_id": row.acting_user_id, "acting_user_name": row.acting_user_name,
        "method": row.method, "path": row.path, "doc_type": row.doc_type, "doc_no": row.doc_no,
        "outcome": row.outcome, "response_status": row.response_status, "duration_ms": row.duration_ms,
        "error_code": row.error_code, "request_id": row.request_id,
    }


class CallLogService:
    def __init__(self, db: Session) -> None:
        self.calls = CallLogRepository(db)

    def list_calls(
        self, tenant_id: str, filters: CallFilters, *, sort: str, order: str, page: int, page_size: int
    ) -> Tuple[List[Dict[str, Any]], int]:
        rows, total = self.calls.search(
            tenant_id, filters, sort=sort, descending=order != "asc", page=page, page_size=page_size
        )
        return [_row(row, name) for row, name in rows], total

    def detail(self, tenant_id: str, call_id: str) -> Optional[Dict[str, Any]]:
        found = self.calls.get(tenant_id, call_id)
        if found is None:
            return None
        row, name = found
        return {
            **_row(row, name), "request_json": row.request_json, "response_body": row.response_body,
            "response_truncated": bool(row.response_truncated),
        }

    def filter_options(self, tenant_id: str) -> Dict[str, Any]:
        return {
            "books": self.calls.books(tenant_id),
            "docTypes": self.calls.doc_types(tenant_id),
            "outcomes": self.calls.outcomes(tenant_id),
            "persons": [{"id": user_id, "name": name} for user_id, name in self.calls.persons(tenant_id)],
        }
