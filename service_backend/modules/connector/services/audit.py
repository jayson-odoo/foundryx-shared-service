"""Fail-closed call audit: the row is committed BEFORE any result is returned."""

from __future__ import annotations
import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import CallLog, Grant

ARGS_CAP = 4096


def cap_args(args: Any) -> str:
    try:
        text = json.dumps(args, separators=(",", ":"), default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        text = "{}"
    return text[:ARGS_CAP]


def write_call_log(db: Session, *, grant: Grant, tool: str, args: Any, status: str,
                   duration_ms: int, rows: Optional[int], chars: Optional[int],
                   error_code: Optional[str], http_status: Optional[int],
                   truncated: bool) -> None:
    db.add(CallLog(
        tenant_id=grant.tenant_id, grant_id=grant.id, product=grant.product,
        product_user_id=grant.product_user_id, tool=tool[:128], args_json=cap_args(args),
        status=status, duration_ms=duration_ms, rows=rows, chars=chars,
        error_code=error_code, http_status=http_status, truncated=truncated))
    db.commit()
