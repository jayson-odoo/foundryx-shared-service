"""Day pull of SO / PO / SPO documents from the db3 wrapper (plan 55 S4,
AC-55-30/31).

SO days run first so a PO line can resolve its SO ref, then PO days. A failed
day stops the run (earlier documents stay). Each document is upserted into
``ac_staged_record`` by ``source_ref``, mapped through the wrapper preset and
pushed once; a document unchanged since its last push is not pushed again. No
transaction is open during a GET.

CLI (counts only, never URLs)::

    python -m modules.autocount.write_back.pull_docs --tenant-slug <slug> \\
        --company-id <uuid> --from YYYY-MM-DD --to YYYY-MM-DD \\
        [--mode last_modified|doc_date]
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from modules.autocount.models import AcCompany
from modules.autocount.provider import PROVIDER_KEY
from modules.autocount.repositories import CompanyRepository, ConnectionRepository
from modules.autocount.write_back import auth, call_log
from modules.autocount.write_back.doc_mapping import KIND_PO, KIND_SO, detect_kind
from modules.autocount.write_back.guard import assert_write_allowed
from modules.autocount.write_back.reader import AutoCountDocReader, DocReadError
from modules.autocount.write_back.staging import DocStager

logger = logging.getLogger("foundryx.autocount")

MAX_RANGE_DAYS = 31
MODE_LAST_MODIFIED = "last_modified"
MODE_DOC_DATE = "doc_date"

Doc = Dict[str, Any]


class PullDocsError(Exception):
    """A refused pull; ``code`` is stable and the text carries no URL."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RangeTooLong(PullDocsError):
    def __init__(self) -> None:
        super().__init__("RANGE_TOO_LONG")


class WriteDisabled(PullDocsError):
    def __init__(self) -> None:
        super().__init__("WRITE_DISABLED")


@dataclass
class PullDocsResult:
    docs_seen: int = 0
    staged: int = 0
    pushed: int = 0
    failed: bool = False
    error_code: Optional[str] = None


def _days(date_from: date, date_to: date) -> List[date]:
    span = (date_to - date_from).days + 1
    if span < 1 or span > MAX_RANGE_DAYS:
        raise RangeTooLong()
    return [date_from + timedelta(days=i) for i in range(span)]


def _write_connection(db: Session, company: AcCompany) -> Any:
    conn = None
    if company.is_active and company.write_connection_id:
        conn = ConnectionRepository(db).get_for_provider(
            company.tenant_id, company.write_connection_id, PROVIDER_KEY
        )
    if conn is None or not conn.is_active:
        raise WriteDisabled()
    return conn


def write_base_url(db: Session, company: AcCompany) -> str:
    conn = _write_connection(db, company)
    base_url = str((conn.config_json or {}).get("baseUrl") or "")
    assert_write_allowed(base_url)  # writable books only, read or write
    return base_url


def write_auth_headers(db: Session, company: AcCompany) -> Tuple[Dict[str, str], Dict[str, str]]:
    """``(write_headers, read_headers)`` of the company's write connection, read fresh;
    ``AuthConfigInvalid`` when its key settings cannot produce a header."""
    conn = _write_connection(db, company)
    return auth.write_headers(conn), auth.read_headers(conn)


def pull_documents(
    db: Session,
    *,
    tenant_id: str,
    company_id: str,
    date_from: date,
    date_to: date,
    mode: str = MODE_LAST_MODIFIED,
    reader_factory: Optional[Callable[[str], AutoCountDocReader]] = None,
    sink_factory: Optional[Callable[..., Any]] = None,
    actor: str = call_log.ACTOR_SYSTEM,
) -> PullDocsResult:
    days = _days(date_from, date_to)
    company = CompanyRepository(db).get(tenant_id, company_id)
    if company is None:
        raise WriteDisabled()
    reader = (reader_factory or AutoCountDocReader)(write_base_url(db, company))
    try:
        auth.attach_headers(reader, auth.read_headers(_write_connection(db, company)))
    except auth.AuthConfigInvalid as exc:
        return PullDocsResult(failed=True, error_code=exc.code)
    log = call_log.CallLog(db.get_bind(), call_log.CallContext(company.tenant_id, company.id, actor=actor))
    call_log.attach_call_log(reader, log)  # plan 61 section 4.8: every GET is one log row
    stager = DocStager(db, sink_factory)
    result = PullDocsResult()
    by_last_modified = mode == MODE_LAST_MODIFIED
    for kind in (KIND_SO, KIND_PO):  # SO days first: PO line refs resolve through staged SOs
        for day in days:
            db.commit()  # no transaction open during the GET
            try:
                docs = reader.list_day(kind, day, by_last_modified=by_last_modified)
            except DocReadError as exc:
                result.failed = True
                result.error_code = exc.code
                return result
            _stage_day(stager, company, kind, docs, result)
    return result


def _stage_day(
    stager: DocStager, company: AcCompany, kind: str, docs: Sequence[Doc], result: PullDocsResult
) -> None:
    for doc in docs:
        if doc.get("DocKey") is None:
            continue
        result.docs_seen += 1
        outcome = stager.stage_and_push(
            company, doc, detect_kind(doc, KIND_SO if kind == KIND_SO else None),
            skip_unchanged=True,
        )
        result.staged += int(outcome.staged)
        result.pushed += int(outcome.pushed)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Pull db3 SO/PO/SPO documents by day.")
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--from", dest="date_from", required=True, type=date.fromisoformat)
    parser.add_argument("--to", dest="date_to", required=True, type=date.fromisoformat)
    parser.add_argument(
        "--mode", choices=(MODE_LAST_MODIFIED, MODE_DOC_DATE), default=MODE_LAST_MODIFIED
    )
    args = parser.parse_args(argv)

    from app.database import SessionLocal
    from app.models.tenant import Tenant

    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.slug == args.tenant_slug).first()
        if tenant is None:
            print("error: unknown tenant")
            return 2
        try:
            result = pull_documents(
                db, tenant_id=tenant.id, company_id=args.company_id,
                date_from=args.date_from, date_to=args.date_to, mode=args.mode,
            )
        except PullDocsError as exc:
            print(f"error: {exc.code}")
            return 2
        print(
            f"docs_seen={result.docs_seen} staged={result.staged} pushed={result.pushed} "
            f"failed={result.failed} error_code={result.error_code or ''}"
        )
        return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
