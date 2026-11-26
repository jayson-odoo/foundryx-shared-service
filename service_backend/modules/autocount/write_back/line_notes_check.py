"""Plan 73 B2: the release guard behind ``admin check-line-notes``.

Every active company with a write connection (all tenants) must have a line notes source that answers a one row
read-only probe, resolved exactly as a write resolves it. A line per company: its id and a code. Never a host,
database name, value or credential.
"""

from __future__ import annotations

import logging
from typing import List, Tuple

from sqlalchemy.orm import Session

from modules.autocount.models import AcCompany
from modules.autocount.write_back.frame import WriteFrame

logger = logging.getLogger("foundryx.autocount")

OK = "OK"
NO_CONNECTION = "NO_CONNECTION"
READ_FAILED = "READ_FAILED"


def check_line_notes(db: Session) -> List[Tuple[str, str]]:
    """``[(company id, code)]`` for every write-enabled company."""
    frame = WriteFrame(db)
    out: List[Tuple[str, str]] = []
    companies = (
        db.query(AcCompany)
        .filter(AcCompany.is_active.is_(True), AcCompany.write_connection_id.isnot(None))
        .order_by(AcCompany.id)
        .all()
    )
    for company in companies:
        source = frame._line_notes_source(company)
        if source is None:
            out.append((company.id, NO_CONNECTION))
            continue
        try:
            ok = bool(source.probe())
        except Exception as exc:  # noqa: BLE001 - never the driver text: it can hold a host or a value
            logger.warning("autocount line notes check failed (%s) company=%s", type(exc).__name__, company.id)
            ok = False
        out.append((company.id, OK if ok else READ_FAILED))
    return out
