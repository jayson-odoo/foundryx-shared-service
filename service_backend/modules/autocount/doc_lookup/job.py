"""The ``autocount_doc_lookup`` background-job handler (plan 17 section 4, D8).

Walks the step plan built by ``service.build_steps``, one vendor GET per step,
and stops at the first record whose number matches. Each step's outcome is
written to ``result_json`` as it lands so the page can show progress. A stop
committed on another session is seen at the next step boundary (cooperative
abort - the status is re-read fresh from the DB, the house rule for any long
abortable job). An error on one day is recorded on that step and the scan
goes on; the job fails only when every step errored.

Registered from ``sync.py`` so the Celery worker's existing import of
``modules.autocount.sync`` covers it (no FastAPI lifespan in the worker).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.jobs.registry import JobHandlerDef, register_job_handler
from app.jobs.service import JobService
from app.models.background_job import JOB_ABORTED, JOB_DONE, JOB_FAILED, BackgroundJob

from ..activity import record_client_calls, trace_id_for_job
from ..doc_feed.records import parse_doc_day
from ..doc_feed.runner import RunRefusal, resolve_vendor
from ..doc_feed.vendor import (
    VENDOR_HTTP,
    VENDOR_NOT_JSON,
    VENDOR_PAGED,
    VENDOR_SHAPE,
    VENDOR_TRANSPORT,
    DocFeedVendorError,
)
from ..repositories.doc_feed_repository import DocFeedRepository
from ..repositories.doc_lookup_repository import DocLookupRepository
from .reader import DocLookupReader
from .registry import AcDocType, get_doc_type
from .service import (
    DOC_LOOKUP_JOB_TYPE,
    DOOR_BY_DOC_DATE,
    DOOR_BY_LAST_MODIFIED,
    STEP_ERROR,
    STEP_HIT,
    STEP_MISS,
    STEP_PENDING,
    STEP_SKIPPED,
    DocLookupService,
    around_days,
    build_steps,
    norm_key,
    pick_latest,
    record_matches,
    record_view,
    searched_windows,
    today_myt,
)

logger = logging.getLogger("foundryx.autocount")

MAX_STEP_ERROR_LEN = 300


def _hint_days(stored: Dict[str, Any], hint) -> List[date]:
    days: List[date] = []
    if hint is not None and hint.doc_date is not None:
        days.append(hint.doc_date)
    ledger = stored.get("ledger")
    if ledger and ledger.get("docDate"):
        days.append(date.fromisoformat(ledger["docDate"]))
    snapshots = stored.get("snapshots") or []
    if snapshots and snapshots[0].get("docDate"):
        days.append(date.fromisoformat(snapshots[0]["docDate"]))
    return days


def _last_known(stored: Dict[str, Any], hint) -> Optional[Tuple[datetime, str, str]]:
    """The DocDate our PULLS last saw: (when, docDate, source), compared
    against the live DocDate to flag a re-date. Snapshot / ledger history
    wins over the finder's own hint - the hint is refreshed by every hit, so
    letting it win would hide the re-date from the second search on while
    the pulls still hold the old date (found in the live click-through). The
    hint is the fallback only when no pull ever saw the document."""
    external: List[Tuple[datetime, str, str]] = []
    for sighting in stored.get("snapshots") or []:
        if sighting.get("docDate") and sighting.get("createdAt"):
            external.append((sighting["createdAt"], sighting["docDate"], "snapshot"))
    ledger = stored.get("ledger")
    if ledger and ledger.get("docDate") and ledger.get("pushedAt"):
        external.append((ledger["pushedAt"], ledger["docDate"], "ledger"))
    if external:
        return max(external, key=lambda c: c[0])
    if hint is not None and hint.doc_date is not None and hint.found_at is not None:
        return (hint.found_at, hint.doc_date.isoformat(), "hint")
    return None


# Step errors are shown to every reader of the search; a transport message
# embeds the connection's base URL, so only these fixed sentences are stored
# (security round 1). ``VENDOR_HTTP``'s own message is built without the host
# ("AutoCount answered HTTP 404.") and is kept as-is.
_STEP_ERROR_SENTENCES = {
    VENDOR_TRANSPORT: "AutoCount could not be reached.",
    VENDOR_NOT_JSON: "AutoCount answered something that is not JSON.",
    VENDOR_SHAPE: "AutoCount answered in an unexpected shape.",
    VENDOR_PAGED: "AutoCount answered in an unexpected shape.",
}


def _step_error(exc: DocFeedVendorError) -> str:
    if exc.code == VENDOR_HTTP:
        return str(exc)[:MAX_STEP_ERROR_LEN]
    return _STEP_ERROR_SENTENCES.get(exc.code, "AutoCount could not be read for this day.")


def _path_for(doc_type: AcDocType, door: str) -> Tuple[str, str]:
    if door == DOOR_BY_LAST_MODIFIED:
        return doc_type.by_last_modified_path or "", doc_type.by_last_modified_param
    return doc_type.by_doc_date_path, doc_type.by_doc_date_param


def run_doc_lookup(db: Session, job: BackgroundJob) -> None:
    jobs = JobService(db)
    repo = DocLookupRepository(db)
    service = DocLookupService(db)
    payload = job.payload_json or {}
    tenant_id = job.tenant_id
    company_id = str(payload.get("companyId") or "")
    doc_no = str(payload.get("docNo") or "")
    wanted = norm_key(doc_no)

    doc_type = get_doc_type(str(payload.get("docType") or ""))
    if doc_type is None or not wanted:
        jobs.finish(job, status=JOB_FAILED, error="The search payload is not valid.")
        return

    stored = service.stored_history(tenant_id, company_id, doc_type, doc_no)
    hint = repo.get_hint(tenant_id, company_id, doc_type.key, wanted)
    last_known = _last_known(stored, hint)
    hint_days = _hint_days(stored, hint)
    if payload.get("aroundDay"):
        hint_days += around_days(date.fromisoformat(payload["aroundDay"]))

    today = today_myt()
    back_days, forward_days = service.windows(tenant_id, company_id)
    steps = build_steps(
        doc_type, hint_days=hint_days, today=today, back_days=back_days,
        forward_days=forward_days,
    )
    result: Dict[str, Any] = {
        "docType": doc_type.key,
        "docNo": doc_no,
        "found": False,
        "current": None,
        "foundBy": None,
        "redated": None,
        "steps": steps,
        "searched": searched_windows(doc_type, today, back_days, forward_days),
    }

    def save(done: int) -> None:
        # A fresh dict each time - a JSON column drops in-place mutation.
        job.result_json = {**result, "steps": [dict(s) for s in steps]}
        job.progress_done = done
        db.commit()

    job.progress_total = len(steps)
    save(0)

    feed_row = DocFeedRepository(db).get(tenant_id, company_id, doc_type.feed)
    if feed_row is None:
        jobs.finish(job, status=JOB_FAILED, error="This company has no AutoCount connection.")
        return
    try:
        resolved = resolve_vendor(db, feed_row)
    except RunRefusal as exc:
        jobs.finish(job, status=JOB_FAILED, error=exc.message)
        return

    reader = DocLookupReader(resolved.vendor_client)
    errors = 0
    found_record: Optional[Dict[str, Any]] = None
    aborted = False
    try:
        for index, step in enumerate(steps):
            path, param = _path_for(doc_type, step["door"])
            try:
                rows = reader.day(path, param, date.fromisoformat(step["day"]))
            except DocFeedVendorError as exc:
                errors += 1
                step["status"] = STEP_ERROR
                step["error"] = _step_error(exc)
            else:
                matches = [r for r in rows if isinstance(r, dict) and record_matches(doc_type, r, wanted)]
                step["count"] = len(rows)
                if matches:
                    step["status"] = STEP_HIT
                    found_record = pick_latest(doc_type, matches)
                else:
                    step["status"] = STEP_MISS
            save(index + 1)
            try:
                jobs.heartbeat(job.id)
            except Exception:  # noqa: BLE001 - advisory, never fails the search
                logger.warning("doc lookup %s: heartbeat failed", job.id, exc_info=True)
            if found_record is not None:
                break
            if repo.job_status(job.id) == JOB_ABORTED:
                aborted = True
                break
    finally:
        try:
            record_client_calls(
                db, resolved.vendor_client, tenant_id=tenant_id,
                trace_id=trace_id_for_job(job.id), external_ref=resolved.company.database_name,
            )
        finally:
            resolved.vendor_client.close()

    for step in steps:
        if step["status"] == STEP_PENDING:
            step["status"] = STEP_SKIPPED

    if found_record is not None:
        view = record_view(doc_type, found_record)
        hit = next(s for s in steps if s["status"] == STEP_HIT)
        result["found"] = True
        result["current"] = view
        result["foundBy"] = {"door": hit["door"], "day": hit["day"]}
        if last_known is not None and view["docDate"] and last_known[1] != view["docDate"]:
            result["redated"] = {"from": last_known[1], "to": view["docDate"], "source": last_known[2]}
        repo.save_hint(
            tenant_id, company_id, doc_type.key, wanted,
            doc_key=view["docKey"], doc_date=parse_doc_day(view["docDate"]),
            last_modified=view["lastModified"],
        )

    done = sum(1 for s in steps if s["status"] in (STEP_HIT, STEP_MISS, STEP_ERROR))
    save(done)
    # A stop can land while the LAST read (a hit) is in flight - re-read the
    # status so the final finish never overwrites it (review round 1).
    if aborted or repo.job_status(job.id) == JOB_ABORTED:
        return  # the stop already set the terminal status; keep the partial steps
    if found_record is None and errors and errors == done:
        first_error = next((s.get("error") for s in steps if s.get("error")), "")
        jobs.finish(job, status=JOB_FAILED, error=f"Every AutoCount read failed. {first_error}".strip())
        return
    jobs.finish(job, status=JOB_DONE)


_HANDLER_DEF = JobHandlerDef(
    DOC_LOOKUP_JOB_TYPE, run_doc_lookup, "AutoCount document search", heartbeats=True,
)


def register_doc_lookup_job_handler() -> None:
    register_job_handler(_HANDLER_DEF)
