"""Plan 16 (BL-SS-286) - the ``delivery_orders`` pull-gateway snapshot build.

A frozen, immutable snapshot of AutoCount delivery-order documents for a MYT
doc-date range (and / or one DO number), read through the SAME vendor door the
DO doc feed uses (``DocFeedVendor.day_by_doc_date``). It is a READ for the
CRM's own review + confirm flow: it never builds a sink, never probes the CRM
contract, never writes a feed run / ledger / issue row and never touches the
feed row's cursor or ``last_*`` columns.

Dispatched from ``sync._run_pull_snapshot`` (same ``autocount_pull_snapshot``
job type); the shared failure closure is passed in so the pinned failed-code
ladder stays in ONE place.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from app.jobs.service import JobService
from app.models.background_job import JOB_DONE, JOB_FAILED

from ..activity import record_client_calls, trace_id_for_job
from ..models import (
    PULL_SNAPSHOT_STATUS_BUILDING,
    RUN_FAILED,
    RUN_SUCCESS,
    AcCompany,
    AcDocFeed,
    AcPullSnapshot,
    AcSyncRun,
)
from ..repositories import PullSnapshotRepository
from .constants import FEED_DELIVERY_ORDERS
from .records import dedupe_latest, doc_date, doc_key, source_ref
from .runner import RunRefusal, resolve_vendor
from .vendor import DocFeedVendorError

logger = logging.getLogger("foundryx.autocount")

MAX_SNAPSHOT_DOCUMENTS = 10_000
ROW_INSERT_HEARTBEAT_INTERVAL = 200
MISSING_DOC_KEY_MESSAGE = (
    "DocKey is missing or not an integer; the record cannot be identified."
)


class _Abandoned(Exception):
    pass


def _doc_no_matches(record: Dict[str, Any], wanted: str) -> bool:
    value = record.get("DocNo")
    return isinstance(value, str) and value.strip().casefold() == wanted.casefold()


def _days_in_range(from_day: date, to_day: date) -> List[date]:
    return [from_day + timedelta(days=i) for i in range((to_day - from_day).days + 1)]


def build_delivery_orders_snapshot(
    db,
    job,
    snapshot: AcPullSnapshot,
    company: AcCompany,
    feed_row: AcDocFeed,
    scope: Dict[str, Any],
    *,
    run: AcSyncRun,
    started: float,
    fail_snapshot: Callable[[str, str], None],
) -> None:
    """Build the snapshot. ``fail_snapshot(message, code)`` stamps the
    snapshot failed (pinned codes only) AND finishes the job FAILED."""
    from ..services.pull_service import (
        AUTOCOUNT_PULL_SNAPSHOT_TTL_HOURS,
        SnapshotService,
        compute_content_hash,
    )
    from ..sync import (
        ERROR_CODE_ROW_LIMIT,
        ERROR_CODE_SOURCE_PAGE_FAILED,
    )

    tenant_id = job.tenant_id
    service = JobService(db)
    snapshot_service = SnapshotService(db)
    snap_repo = PullSnapshotRepository(db)
    trace_id = trace_id_for_job(job.id)
    snapshot_id = snapshot.id

    def finish_run_failed(message: str) -> None:
        run.outcome = RUN_FAILED
        run.error = message[:4000]
        run.finished_at = datetime.now(timezone.utc)
        run.duration_ms = int((time.monotonic() - started) * 1000)
        db.commit()

    def beat_and_check(stage: str, done: int, total: Optional[int]) -> None:
        try:
            service.beat_progress(job.id, done=done, total=total, stage=stage)
        except Exception:  # noqa: BLE001 - advisory, must never fail the run
            logger.warning(
                "autocount DO snapshot: beat_progress for job %s failed", job.id, exc_info=True
            )
        current = snap_repo.get(tenant_id, snapshot_id)
        if current is None or current.status != PULL_SNAPSHOT_STATUS_BUILDING:
            raise _Abandoned(
                f"This build was abandoned before it finished (snapshot "
                f"{snapshot_id} is no longer building)."
            )

    def abandon(exc: _Abandoned) -> None:
        message = str(exc)
        finish_run_failed(message)
        service.finish(job, status=JOB_FAILED, error=message)

    def fail(message: str, code: str) -> None:
        finish_run_failed(message)
        fail_snapshot(message, code)

    from_day = date.fromisoformat(str(scope["fromDay"]))
    to_day = date.fromisoformat(str(scope["toDay"]))
    doc_no: Optional[str] = scope.get("docNo")

    try:
        resolved = resolve_vendor(db, feed_row)
    except RunRefusal as exc:
        fail(exc.message, ERROR_CODE_SOURCE_PAGE_FAILED)
        return
    except Exception as exc:  # noqa: BLE001 - a setup fault, reported cleanly
        fail(f"Fetch failed: {exc}", ERROR_CODE_SOURCE_PAGE_FAILED)
        return

    book = resolved.book
    days = _days_in_range(from_day, to_day)
    fetched: List[Dict[str, Any]] = []
    try:
        try:
            for index, day in enumerate(days, start=1):
                fetched.extend(resolved.vendor.day_by_doc_date(FEED_DELIVERY_ORDERS, day))
                beat_and_check("source", index, len(days))
        except _Abandoned as exc:
            abandon(exc)
            return
        except DocFeedVendorError as exc:
            fail(str(exc), ERROR_CODE_SOURCE_PAGE_FAILED)
            return
        except Exception as exc:  # noqa: BLE001
            fail(f"Fetch failed: {exc}", ERROR_CODE_SOURCE_PAGE_FAILED)
            return
    finally:
        record_client_calls(
            db, resolved.vendor_client, tenant_id=tenant_id, trace_id=trace_id,
            external_ref=company.database_name,
        )
        resolved.vendor_client.close()

    excluded_rows: List[Dict[str, Any]] = []
    for record in fetched:
        if doc_key(record) is None and (doc_no is None or _doc_no_matches(record, doc_no)):
            code = record.get("DocNo")
            excluded_rows.append(
                {
                    "source_ref": None,
                    "code": code if isinstance(code, str) and code else None,
                    "reason": "missing_doc_key",
                    "message": MISSING_DOC_KEY_MESSAGE,
                }
            )

    documents = dedupe_latest(fetched)
    if doc_no is not None:
        documents = [r for r in documents if _doc_no_matches(r, doc_no)]
    documents.sort(key=lambda r: (doc_date(r) or date.min, doc_key(r) or 0))

    if len(documents) > MAX_SNAPSHOT_DOCUMENTS:
        fail(
            f"The range holds {len(documents)} documents; one snapshot carries at most "
            f"{MAX_SNAPSHOT_DOCUMENTS}.",
            ERROR_CODE_ROW_LIMIT,
        )
        return

    line_count = sum(
        len(r["Details"]) for r in documents if isinstance(r.get("Details"), list)
    )
    try:
        for index, record in enumerate(documents):
            if index and index % ROW_INSERT_HEARTBEAT_INTERVAL == 0:
                beat_and_check("storing", index, len(documents))
            snapshot_service.insert_row(
                tenant_id, snapshot, index,
                company_id=company.id,
                source_ref=source_ref(FEED_DELIVERY_ORDERS, book, record),
                payload=record,
            )
        metadata: Dict[str, Any] = {
            "fromDay": from_day.isoformat(),
            "toDay": to_day.isoformat(),
            "docNo": doc_no,
            "book": book,
            "daysRead": len(days),
            "fetchedCount": len(fetched),
            "lineCount": line_count,
            "excludedRows": excluded_rows,
            "excludedCount": len(excluded_rows),
            "sourcePageSize": None,
            "sourceConcurrency": None,
        }
        extracted_at = datetime.now(timezone.utc)
        snapshot_service.stamp_ready(
            tenant_id, snapshot,
            record_count=len(documents), complete=True,
            content_hash=compute_content_hash(documents), metadata=metadata,
            extracted_at=extracted_at,
            expires_at=extracted_at + timedelta(hours=AUTOCOUNT_PULL_SNAPSHOT_TTL_HOURS),
        )
    except _Abandoned as exc:
        abandon(exc)
        return

    run.outcome = RUN_SUCCESS
    run.rows_scanned = len(fetched)
    run.added_count = len(documents)
    run.finished_at = datetime.now(timezone.utc)
    run.duration_ms = int((time.monotonic() - started) * 1000)
    db.commit()
    service.finish(
        job, status=JOB_DONE,
        result={"snapshotId": snapshot.id, "recordCount": len(documents), "complete": True},
    )
