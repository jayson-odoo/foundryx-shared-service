"""The sync job handler - fetch → map → stage → hold for approval.

Rides the EXISTING ``background_jobs`` table + ``register_job_handler`` (plan §5
"do not build these"). ``needs_review`` is a deliberately NON-terminal status the
retention pruner never touches - that IS the approval gate (AC-13-11). No new
job table, no bespoke worker.

Three behaviours here are the ones most likely to regress, so they are stated
plainly:

1. **Per-document all-or-nothing** (D13 / AC-13-10). A GRN whose line 3 fails
   validation is staged ``FAILED`` with **no canonical payload at all** - there
   is no half-record in existence to push by accident. Its siblings in the same
   batch are entirely unaffected, and the error names document, line and field.

2. **Watermark advances only on a clean batch** (AC-13-05, D18). Any failed
   document, any truncation, any abort → the watermark HOLDS. Re-reading a
   window is cheap and idempotent; skipping one loses documents silently, and
   nobody finds out until a reconciliation months later.

3. **Cooperative abort re-reads status FRESH from the DB** before the terminal
   step. A held ORM object says ``running`` forever - the operator's abort was
   committed on a DIFFERENT session. Eager mode (dev/test) runs this handler
   inline with no interleave, so this class of bug is INVISIBLE unless the test
   forces a real one.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.jobs.registry import JobHandlerDef, register_job_handler
from app.jobs.service import JobService
from app.models.background_job import (
    JOB_ABORTED,
    JOB_DONE,
    JOB_FAILED,
    JOB_NEEDS_REVIEW,
    BackgroundJob,
)

from .activity import (
    ACTIVITY_ERROR,
    ACTIVITY_SUCCESS,
    record_activity,
    record_client_calls,
    trace_id_for_job,
)
from .canonical.grn import (
    ENTITY_GOODS_RECEIVED_NOTE,
    VENDOR_DETAIL_KEY,
    VENDOR_ENTITY,
)
from .canonical.masters import (
    ENTITY_CUSTOMER,
    ENTITY_SUPPLIER,
    VENDOR_ENTITY_CUSTOMER,
    VENDOR_ENTITY_SUPPLIER,
    VENDOR_LAST_MODIFIED_PATH,
)
from .client import AutoCountError
from .mapping import MappedDocument, MappingEngine
from .models import (
    ETL_STATUS_ACTIVE,
    RUN_ABORTED,
    RUN_FAILED,
    RUN_MODE_MANUAL,
    RUN_SUCCESS,
    SOURCE_IMPL_SQL_DB,
    STAGED,
    STAGED_FAILED,
    AcStagedRecord,
    AcSyncRun,
)
from .repositories import (
    CompanyRepository,
    EntityConfigRepository,
    StagedRecordRepository,
    SyncRunRepository,
    WatermarkRepository,
)
from .sources import (
    FetchResult,
    SourceContext,
    SourceRecord,
    TruncatedWindowError,
    Watermark,
    source_factory,
)

#     !!  IMPORTING THIS MODULE IS WHAT MAKES ``sql_db`` RUNNABLE.  !!
# The DB source registers itself here rather than in ``sources.py`` (which it
# imports from - registering there would be an import cycle). Every process
# that can execute a sync job imports THIS module: the API process through the
# services, the Celery worker through its explicit import. A process that had
# the handler but not the factory would fail every DB run with "no source
# implementation registered", which reads like a config fault and is not one.
from .sql_source.source import register_sql_db_source

register_sql_db_source()

logger = logging.getLogger("foundryx.autocount")

# The registered ``background_jobs.type``.
AUTOCOUNT_SYNC = "autocount_sync"

# Vendor entity per canonical entity - the URL grammar is uniform
# (``POST /api/{Entity}/Get{Entity}``), only the name varies.
VENDOR_ENTITIES = {
    ENTITY_GOODS_RECEIVED_NOTE: VENDOR_ENTITY,
    ENTITY_SUPPLIER: VENDOR_ENTITY_SUPPLIER,  # Creditor
    ENTITY_CUSTOMER: VENDOR_ENTITY_CUSTOMER,  # Debtor
}

# The nested detail-array key PER ENTITY. It is not derivable from the entity
# name - GRN's is ``GRDTL``, NOT ``GRNDTL`` (plan §4a hazard table) - so it is
# looked up, never constructed. Getting it wrong yields a header with zero lines
# and NO error at all, which is the worst possible shape of failure.
# Masters are FLAT and are deliberately ABSENT here: ``None`` means "no detail
# array", which the mapping engine reads off the entity profile.
VENDOR_DETAIL_KEYS = {ENTITY_GOODS_RECEIVED_NOTE: VENDOR_DETAIL_KEY}

# The entity's natural list-valued identifier in a read filter. Masters key on
# ``AccNo``, documents on ``DocNo``.
VENDOR_IDENTIFIER_KEYS = {
    ENTITY_SUPPLIER: "AccNo",
    ENTITY_CUSTOMER: "AccNo",
}

# Where ``LastModified`` actually LIVES per entity. Masters nest their real DB
# row under ``Data[0]`` (AC-14-02), so the top-level lookup finds nothing - which
# would fail the window assertion on every row AND leave the watermark stuck.
VENDOR_LAST_MODIFIED_PATHS = {
    ENTITY_SUPPLIER: VENDOR_LAST_MODIFIED_PATH,
    ENTITY_CUSTOMER: VENDOR_LAST_MODIFIED_PATH,
}


class SyncConfigError(Exception):
    """The job cannot run as configured - a setup problem, not a vendor fault."""


# ── cooperative abort ─────────────────────────────────────────────────────────


def _aborted(db: Session, job_id: str) -> bool:
    """Re-read the job's status FRESH from the DB.

    A concurrent abort committed ``JOB_ABORTED`` on a DIFFERENT session, so the
    handler's own in-memory ``job`` object is stale and will happily report
    ``running`` right up to the terminal write that overwrites the abort. Copied
    from ``app/storage_migration/service.py`` - same reason, same shape.
    """
    return (
        db.query(BackgroundJob.status).filter(BackgroundJob.id == job_id).scalar()
        == JOB_ABORTED
    )


# ── diffing (AC-13-12) ────────────────────────────────────────────────────────


# Bookkeeping fields excluded from a diff. ``last_modified`` in particular
# changes on EVERY re-fetch by definition - it is the reason the record came
# back at all - so reporting it as a change is tautological noise on every
# single diff, and noise is what turns review into rubber-stamping.
# Identity fields are excluded because a diff is BETWEEN two versions of ONE
# document; if they differed, the rows would not have been paired.
DIFF_IGNORED_FIELDS = frozenset(
    {
        "last_modified",
        "last_modified_user_id",
        "source_system",
        "source_ref",
        "entity_type",
    }
)


def compute_diff(
    before: Optional[Dict[str, Any]], after: Dict[str, Any]
) -> Dict[str, Any]:
    """Per-field before → after, **changed fields only**.

    Unchanged fields are omitted entirely - a "diff" that lists every field
    makes a reviewer scan noise to find the one thing that moved, which is how
    review degrades into rubber-stamping (the exact failure D20 warns about at
    scale).
    """
    if before is None:
        return {"__new__": True}
    changed: Dict[str, Any] = {}
    for key in sorted(set(before) | set(after)):
        if key in DIFF_IGNORED_FIELDS:
            continue
        old, new = before.get(key), after.get(key)
        if old != new:
            changed[key] = {"from": old, "to": new}
    return changed


# ── the handler ───────────────────────────────────────────────────────────────


def run_autocount_sync(db: Session, job: BackgroundJob) -> None:
    """``background_jobs`` handler for ``autocount_sync``.

    Failures are isolated by ``run_job`` (job → failed, logged, never
    propagated), so nothing here can break a triggering request (AC-13-43).
    """
    service = JobService(db)
    payload = dict(job.payload_json or {})
    tenant_id = job.tenant_id
    company_id = str(payload.get("companyId") or "")
    entity_type = str(payload.get("entityType") or ENTITY_GOODS_RECEIVED_NOTE)
    # How this run started (plan 22 §2.7, AC-22-17): ``manual`` for every
    # operator-triggered run (and every pre-plan-22 payload, which carries no
    # mode at all); the S3 sweep enqueues ``incremental``/``reconcile``.
    mode = str(payload.get("mode") or RUN_MODE_MANUAL)
    started = time.monotonic()
    # ONE trace ties every leg of this run together - the login, the read, and
    # the run summary - so the Developer Logs console can show the whole
    # interaction rather than three unrelated rows.
    trace_id = trace_id_for_job(job.id)

    # ── resolve config (tenant- AND company-scoped, AC-13-41) ────────────────
    company = CompanyRepository(db).get(tenant_id, company_id)
    if company is None:
        service.finish(
            job, status=JOB_FAILED, error="The AutoCount company no longer exists."
        )
        return
    config = EntityConfigRepository(db).get(tenant_id, company_id, entity_type)
    if config is None or not config.enabled:
        service.finish(
            job,
            status=JOB_FAILED,
            error=f"'{entity_type}' is not configured for sync on this company.",
        )
        return

    watermarks = WatermarkRepository(db)
    watermark_row = watermarks.get_or_create(tenant_id, company_id, entity_type)
    watermark = Watermark(
        last_modified_at=watermark_row.last_modified_at,
        cursor=watermark_row.cursor_json,
    )

    run = SyncRunRepository(db).add(
        AcSyncRun(
            tenant_id=tenant_id,
            company_id=company_id,
            entity_type=entity_type,
            job_id=job.id,
            mode=mode,
        )
    )
    watermark_row.last_attempt_at = datetime.now(timezone.utc)
    db.commit()

    service.log(job, f"Syncing {entity_type} for company {company.database_name}.")

    # ── fetch ────────────────────────────────────────────────────────────────
    # Deferred import: ``services`` imports the sync service, which imports THIS
    # module for the job type - a module-level import here would be a cycle.
    from .services.company_service import CompanyService

    companies = CompanyService(db)
    # The factory contract (plan 22 §2.1, AC-22-08): each implementation builds
    # its OWN transport from the context - the HTTP client is constructed inside
    # ``autocount_read``, the DB engine inside ``sql_db``. A construction fault
    # (bad credentials, unknown impl, unconfigured task) is a SETUP fault,
    # reported cleanly with the watermark held.
    ctx = SourceContext(
        db=db,
        tenant_id=tenant_id,
        company=company,
        entity_config=config,
        company_service=companies,
    )
    try:
        source = source_factory(config.source_impl)(
            ctx,
            entity_type=entity_type,
            vendor_entity=VENDOR_ENTITIES.get(entity_type, VENDOR_ENTITY),
            record_cap=config.record_cap,
            lookback_days=config.initial_lookback_days,
            # Per-entity from CONFIG (AC-14-03/14-25), never branched on here.
            envelope=config.envelope,
            initial_load=config.initial_load,
            identifier_key=VENDOR_IDENTIFIER_KEYS.get(entity_type, "DocNo"),
            last_modified_path=VENDOR_LAST_MODIFIED_PATHS.get(
                entity_type, "LastModified"
            ),
            mode=mode,
        )
    except Exception as exc:  # noqa: BLE001 - a setup fault, reported cleanly
        _fail(db, service, job, run, watermark_row, str(exc), started, config=config)
        return

    try:
        result: FetchResult = source.fetch_changes(watermark)
    except AutoCountError as exc:
        # Includes TruncatedWindowError - a truncated read must NEVER read as a
        # complete one (AC-13-46), so it fails the run and holds the watermark.
        # The ``truncated`` FLAG is set only for an actual truncation: an
        # operator reads it to decide whether to narrow the window, so marking
        # every vendor error truncated would make the signal meaningless.
        # The HTTP legs FIRST: a failed call is exactly the one a diagnostician
        # needs, and it is the path that used to store no request payload at
        # all. Safe here - the last write committed above, nothing is pending.
        record_client_calls(
            db,
            source,
            tenant_id=tenant_id,
            trace_id=trace_id,
            external_ref=company.database_name,
        )
        record_activity(
            db,
            tenant_id=tenant_id,
            operation=f"sync {entity_type}",
            status=ACTIVITY_ERROR,
            trace_id=trace_id,
            external_ref=company.database_name,
            latency_ms=int((time.monotonic() - started) * 1000),
            error_message=exc.message,
        )
        _fail(
            db,
            service,
            job,
            run,
            watermark_row,
            exc.message,
            started,
            truncated=isinstance(exc, TruncatedWindowError),
            config=config,
        )
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("autocount sync fetch failed for job %s", job.id)
        record_client_calls(
            db,
            source,
            tenant_id=tenant_id,
            trace_id=trace_id,
            external_ref=company.database_name,
        )
        _fail(
            db, service, job, run, watermark_row, f"Fetch failed: {exc}", started,
            config=config,
        )
        return
    finally:
        source.close()

    # The real request/response of every transport leg (masked + bounded).
    record_client_calls(
        db,
        source,
        tenant_id=tenant_id,
        trace_id=trace_id,
        external_ref=company.database_name,
    )
    # …and the domain-level summary of the run, sharing the trace. The two are
    # complementary, not duplicates: the legs say what went over the wire, this
    # says what the window and the record count meant.
    record_activity(
        db,
        tenant_id=tenant_id,
        operation=f"sync {entity_type}",
        status=ACTIVITY_SUCCESS,
        trace_id=trace_id,
        external_ref=company.database_name,
        latency_ms=int((time.monotonic() - started) * 1000),
        request={
            "window": [
                # ``None`` here is meaningful, not missing: an unbounded initial
                # master load deliberately sends no lower bound (AC-14-25).
                result.window_from.isoformat() if result.window_from else None,
                result.window_to.isoformat() if result.window_to else None,
            ],
            "recordCap": config.record_cap,
            "initialLookbackDays": config.initial_lookback_days,
            "initialLoad": config.initial_load,
            "envelope": config.envelope,
        },
        response={
            "records": len(result.records),
            # What the vendor says exists, beside what we actually got
            # (AC-14-26). Advisory - it is computed AFTER the record cap, so it
            # is never used to decide truncation.
            "vendorReportedTotal": result.reported_total,
        },
    )

    run.window_from = result.window_from
    run.window_to = result.window_to
    run.fetched_count = len(result.records)
    # Cost + change-detection columns (plan 22 §2.7, AC-22-17). ``rows_scanned``
    # falls back to the emitted count, which is what every API-path fetch means.
    run.rows_scanned = (
        result.rows_scanned if result.rows_scanned is not None else len(result.records)
    )
    run.added_count = result.added_count
    run.updated_count = result.updated_count
    service.set_total(job, len(result.records))
    db.commit()

    if _aborted(db, job.id):
        _abort(db, service, run, started)
        return

    # ── map + stage, ONE DOCUMENT AT A TIME ──────────────────────────────────
    engine = MappingEngine(
        companies.mapping_rows(tenant_id, company_id, entity_type),
        # ``None`` = the entity profile's own key (masters have none, being flat).
        detail_key=VENDOR_DETAIL_KEYS.get(entity_type),
        entity_type=entity_type,
        # Masters mint a COMPANY-QUALIFIED ``source_ref`` (AC-14-10). The name
        # comes from the discovered company, never from operator input - and it
        # is what stops company B's ``AutoKey=1`` overwriting company A's.
        database_name=company.database_name,
    )
    staged_count, failed_count = _stage_documents(
        db,
        service,
        job,
        result.records,
        engine=engine,
        tenant_id=tenant_id,
        company_id=company_id,
        entity_type=entity_type,
    )
    run.staged_count = staged_count
    run.failed_count = failed_count
    db.commit()

    # Fresh status re-read BEFORE the terminal step - the whole point of
    # cooperative abort (an abort committed mid-loop must not be overwritten).
    if _aborted(db, job.id):
        _abort(db, service, run, started)
        return

    # ── watermark: advance ONLY on a clean batch ─────────────────────────────
    #
    # ``last_success_at`` and ``consecutive_failures`` are the STALE-SYNC SIGNAL
    # (AC-13-19, plan §7 "a blocked sync is always visible"). Stamping success
    # unconditionally would make a permanently-stalled entity - watermark held,
    # every document failing to map, forever - present as perfectly healthy:
    # fresh success timestamp, zero consecutive failures. The monitor would then
    # never fire on the one case it exists for. So a batch with ANY failed
    # document counts as a FAILURE here, exactly as a fetch fault does in
    # ``_fail``.
    advanced_to: Optional[datetime] = None
    if failed_count == 0:
        if result.max_last_modified is not None:
            advanced_to = result.max_last_modified
            watermark_row.last_modified_at = advanced_to
        # A source may keep its OWN resume point (the DB source's watermark
        # value, which need not be a datetime). Same rule as the timestamp: it
        # advances only on a clean batch.
        if result.cursor is not None:
            watermark_row.cursor_json = result.cursor
        watermark_row.consecutive_failures = 0
        watermark_row.last_error = None
        watermark_row.last_success_at = datetime.now(timezone.utc)
    else:
        # D18: a failed document HOLDS the watermark for the entity, so the next
        # run re-reads the same window and the document gets another chance
        # after the mapping is fixed - no manual re-drive, no lost document.
        watermark_row.consecutive_failures = (
            watermark_row.consecutive_failures or 0
        ) + 1
        watermark_row.last_error = (
            f"{failed_count} document(s) failed to map; watermark held."
        )

    # ── auto-push (plan 22 §2.6, AC-22-20) ───────────────────────────────────
    #
    #     !!  AN ACTIVATED DB TASK HAS NO REVIEW GATE - BY DESIGN.  !!
    # The activate-once ceremony (AC-22-18) IS the human approval: a successful
    # Sorento dry-run of the initial load, then an explicit Activate. After it,
    # scheduled runs deliver without a per-run click - otherwise a minutely task
    # would build a queue nobody can drain. The API path's ``needs_review`` gate
    # is untouched; this branch is entered only for an ACTIVE ``sql_db`` task.
    pushed_count = 0
    push_summary: Optional[Dict[str, Any]] = None
    if (
        config.source_impl == SOURCE_IMPL_SQL_DB
        and config.etl_status == ETL_STATUS_ACTIVE
    ):
        from .services.sync_service import SyncService

        push_summary = SyncService(db).auto_push(
            tenant_id, company_id, entity_type, job_id=job.id
        )
        pushed_count = int(push_summary.get("pushed") or 0)
        run.pushed_count = pushed_count
        # A delivery failure surfaces ON THE TASK (AC-22-19) - never silently.
        config.last_run_error = push_summary.get("error")
        config.last_run_error_code = push_summary.get("errorCode")
    else:
        config.last_run_error = None
        config.last_run_error_code = None
    config.last_run_at = datetime.now(timezone.utc)

    run.outcome = RUN_SUCCESS
    run.truncated = False
    run.watermark_advanced_to = advanced_to
    run.finished_at = datetime.now(timezone.utc)
    run.duration_ms = int((time.monotonic() - started) * 1000)

    summary = {
        "companyId": company_id,
        "entityType": entity_type,
        "fetched": run.fetched_count,
        "staged": staged_count,
        "failed": failed_count,
        "watermarkAdvancedTo": advanced_to.isoformat() if advanced_to else None,
        "awaitingApproval": staged_count > 0,
        #     !!  A COUNT WITHOUT ITS DENOMINATOR IS NOT A RESULT (AC-14-26).  !!
        # "2 records" alone cannot be told apart from "nothing changed" and
        # "the window excluded 170 of 172 records" - and the second one looks
        # exactly like success while being near-total data loss. So the vendor's
        # own availability marker travels beside the fetched count, and the
        # policy that produced the window travels with both.
        "vendorReportedTotal": result.reported_total,
        "initialLoad": config.initial_load,
        "unboundedInitialLoad": result.window_from is None,
        "mode": mode,
        "rowsScanned": run.rows_scanned,
        "added": run.added_count,
        "updated": run.updated_count,
    }
    if push_summary is not None:
        summary.update(push_summary)
        # An auto-pushed batch was never "awaiting approval" - it is delivered.
        summary["awaitingApproval"] = False
    service.log(
        job,
        f"Staged {staged_count} document(s), {failed_count} failed"
        + (
            f" (fetched {run.fetched_count} of {result.reported_total} the vendor "
            f"reports available)."
            if result.reported_total is not None
            else "."
        )
        + (
            f" Pushed {pushed_count} record(s) automatically (the task is active)."
            if push_summary is not None
            else (
                " Awaiting approval - nothing has been pushed."
                if staged_count
                else " Nothing to review."
            )
        ),
    )
    # needs_review with zero staged rows would strand a job nobody can act on
    # (and which the pruner will never clean up), so an empty batch closes. An
    # auto-pushing task has no review gate at all, so its job always closes.
    holds_for_review = staged_count > 0 and push_summary is None
    service.finish(
        job,
        status=JOB_NEEDS_REVIEW if holds_for_review else JOB_DONE,
        result=summary,
    )
    db.commit()


def _stage_documents(
    db: Session,
    service: JobService,
    job: BackgroundJob,
    records: List[SourceRecord],
    *,
    engine: MappingEngine,
    tenant_id: str,
    company_id: str,
    entity_type: str,
) -> Tuple[int, int]:
    """Map + persist each document independently. Returns (staged, failed).

    Per-document commit + abort checkpoint: one document's failure can never
    contaminate a sibling, and an abort stops at the next document boundary
    rather than after the whole batch.
    """
    staged_repo = StagedRecordRepository(db)
    staged = failed = 0

    for position, source_record in enumerate(records, start=1):
        if _aborted(db, job.id):
            break

        mapped: MappedDocument = engine.map_document(source_record.raw)
        raw_json = source_record.raw  # retained verbatim (AC-13-07)

        if not mapped.ok:
            # D13: NO canonical payload is stored for a failed transaction -
            # there is nothing half-formed for a later step to pick up.
            doc_no = None
            doc_key = ""
            for err in mapped.errors:
                doc_no = doc_no or err.doc_no
                doc_key = doc_key or (err.doc_key or "")
            staged_repo.add(
                AcStagedRecord(
                    tenant_id=tenant_id,
                    company_id=company_id,
                    entity_type=entity_type,
                    job_id=job.id,
                    # A document that failed BEFORE yielding a DocKey still
                    # needs a stable, reproducible handle - its position in the
                    # run. (``id(obj)`` would be a memory address: different on
                    # every run and meaningless to a human.)
                    source_ref=doc_key or f"unmapped:{job.id}:{position}",
                    doc_no=doc_no,
                    source_last_modified=source_record.last_modified,
                    raw_json=raw_json,
                    canonical_json=None,
                    errors_json=[err.as_dict() for err in mapped.errors],
                    status=STAGED_FAILED,
                    # Names document, line and field (AC-13-10).
                    error="; ".join(err.message() for err in mapped.errors)[:4000],
                )
            )
            failed += 1
            service.advance(job, failed=1)
            db.commit()
            continue

        record = mapped.record
        canonical = record.comparable()
        previous = staged_repo.last_pushed(
            tenant_id, company_id, entity_type, record.source_ref
        )
        diff = compute_diff(
            previous.canonical_json if previous is not None else None, canonical
        )
        staged_repo.add(
            AcStagedRecord(
                tenant_id=tenant_id,
                company_id=company_id,
                entity_type=entity_type,
                job_id=job.id,
                source_ref=record.source_ref,
                # From the MAPPED result, not ``record.doc_no``: the attribute
                # name differs per entity (a master's is ``source_doc_no``), and
                # reaching for the document one on a master silently yields None.
                doc_no=mapped.doc_no,
                source_last_modified=source_record.last_modified,
                raw_json=raw_json,
                canonical_json=canonical,
                diff_json=diff,
                status=STAGED,
            )
        )
        staged += 1
        service.advance(job, done=1)
        db.commit()

    return staged, failed


def _fail(
    db: Session,
    service: JobService,
    job: BackgroundJob,
    run: AcSyncRun,
    watermark_row,
    message: str,
    started: float,
    *,
    truncated: bool = False,
    config=None,
    error_code: Optional[str] = None,
) -> None:
    """Run failed: watermark HOLDS, failures counted, job marked failed."""
    run.outcome = RUN_FAILED
    run.error = message[:4000]
    run.truncated = truncated
    run.finished_at = datetime.now(timezone.utc)
    run.duration_ms = int((time.monotonic() - started) * 1000)
    watermark_row.consecutive_failures = (watermark_row.consecutive_failures or 0) + 1
    watermark_row.last_error = message[:4000]
    if config is not None:
        # The TASK surface must show the last failure (AC-22-19) - the watermark
        # row is the delta bookkeeping, the task is what an operator looks at.
        config.last_run_at = datetime.now(timezone.utc)
        config.last_run_error = message[:4000]
        config.last_run_error_code = error_code
    db.commit()
    # Same cooperative-abort rule as ``_abort``: an operator's committed
    # ``JOB_ABORTED`` MUST stand. An abort landing while a fetch was in flight
    # (the fetch then errors, because the abort raced a real fault) would
    # otherwise be overwritten with ``failed`` here, erasing the fact that a
    # human stopped this. The run's own bookkeeping above is kept either way -
    # the fetch genuinely did fail, and that is why the run stopped.
    if _aborted(db, job.id):
        logger.info("autocount sync failed after an abort was committed; abort stands.")
        return
    service.finish(job, status=JOB_FAILED, error=message)


def _abort(db: Session, service: JobService, run: AcSyncRun, started: float) -> None:
    """Aborted: record the outcome but NEVER touch the job's status - the
    operator's ``JOB_ABORTED`` already stands, and overwriting it (even with
    ``failed``) would erase the fact that a human stopped this.

    Known, accepted: documents staged before the abort landed stay on the
    aborted job and are never approvable. That is deliberate - the watermark
    HELD, so the next run re-reads the same window and re-stages them under a
    fresh job. The cost is a little duplicate staging; the alternative (letting
    a partial batch be approved) would push a half-read window as if it were
    complete.
    """
    run.outcome = RUN_ABORTED
    run.finished_at = datetime.now(timezone.utc)
    run.duration_ms = int((time.monotonic() - started) * 1000)
    db.commit()
    logger.info("autocount sync aborted; watermark held.")


# ── boot registration (idempotent) ────────────────────────────────────────────
# The SAME def object re-registers cleanly (the registry tolerates identity).
_HANDLER_DEF = JobHandlerDef(AUTOCOUNT_SYNC, run_autocount_sync, "AutoCount sync")


def register_autocount_sync_handler() -> None:
    """Register the ``autocount_sync`` handler.

    !!  The Celery worker boots NO FastAPI lifespan.  !!
    A worker only sees handlers whose MODULE was imported, so
    ``app/workflow_engine/worker.py`` imports this module explicitly. Omitting
    that import leaves every sync job Pending forever with NO error - the
    single nastiest footgun in this codebase.
    """
    register_job_handler(_HANDLER_DEF)


register_autocount_sync_handler()
