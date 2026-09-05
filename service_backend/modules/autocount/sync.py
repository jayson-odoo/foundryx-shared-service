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
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
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
from .mapping import (
    UNQUALIFIED_REF_ENTITIES,
    MappedDocument,
    MappingEngine,
    build_mapping_rows_for_run,
    flat_profile,
)
from .models import (
    ETL_STATUS_ACTIVE,
    RUN_ABORTED,
    RUN_FAILED,
    RUN_MODE_MANUAL,
    RUN_MODE_RECONCILE,
    RUN_SUCCESS,
    SOURCE_IMPL_SQL_DB,
    STAGED,
    STAGED_FAILED,
    STAGED_OP_DELETE,
    AcEntityConfig,
    AcStagedRecord,
    AcSyncRun,
    AcWatermark,
)
from .repositories import (
    CompanyRepository,
    EntityConfigRepository,
    RowHashRepository,
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
from .sql_source.errors import (
    SqlDeleteGuardExceeded,
    SqlDocumentCapExceeded,
    SqlFilterFormulaError,
)

#     !!  IMPORTING THIS MODULE IS WHAT MAKES ``sql_db`` RUNNABLE.  !!
# The DB source registers itself here rather than in ``sources.py`` (which it
# imports from - registering there would be an import cycle). Every process
# that can execute a sync job imports THIS module: the API process through the
# services, the Celery worker through its explicit import. A process that had
# the handler but not the factory would fail every DB run with "no source
# implementation registered", which reads like a config fault and is not one.
from .sql_source.source import (
    CURSOR_COLUMN,
    CURSOR_MARK,
    DELETE_GUARD_MIN_ABSOLUTE,
    DELETE_GUARD_RATIO,
    PageCursor,
    decode_mark,
    register_sql_db_source,
)

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


def _advance_mark_and_ties(
    existing_mark: Any,
    existing_ties: List[str],
    candidate_mark: Any,
    candidate_ties: List[str],
) -> Tuple[Any, List[str]]:
    """The MAX of two stored marks, never backwards (F3, review round 2) -
    and the tie-ref set that travels WITH whichever mark wins.

    A tie-ref list belongs to the EXACT mark it was recorded against - if a
    just-completed pass's own frontier LOSES the monotonic compare (the
    public position was already ahead, left there by a different mode's
    pass), its tie group must NOT overwrite the winning mark's own tie
    group with one for a DIFFERENT mark value entirely. That silent
    cross-contamination (an earlier version of this fix always replaced the
    root ``tieRefs`` with whatever the CURRENT page produced, regardless of
    mode) is exactly what makes a fresh incremental pass wrongly exclude an
    unrelated ref merely because it once sat in some OTHER pass's tie group.

    Both sides are whatever ``sql_source.source._encode_mark`` already
    produced (a JSON-safe ISO string for a datetime, or the value as-is for
    anything else) - decoded back to a comparable type before the compare so
    an ISO string's own lexical order is never relied on. A type mismatch (a
    task whose column type changed) falls back to keeping the CANDIDATE
    rather than raising - this is bookkeeping for a display/resume position,
    never a safety gate, so failing loud here would be the wrong trade.
    """
    if candidate_mark is None:
        return existing_mark, existing_ties
    if existing_mark is None:
        return candidate_mark, list(candidate_ties)
    try:
        decoded_candidate = decode_mark(candidate_mark)
        decoded_existing = decode_mark(existing_mark)
    except TypeError:
        return candidate_mark, list(candidate_ties)
    if decoded_candidate > decoded_existing:
        return candidate_mark, list(candidate_ties)
    if decoded_candidate == decoded_existing:
        # An EXACT tie between two independent passes' frontiers - merge
        # rather than let either one silently evict the other's tie group.
        return existing_mark, sorted(set(existing_ties) | set(candidate_ties))
    return existing_mark, existing_ties


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

    #     !!  A WATERMARKED ``sql_db`` TASK RUNS THE PAGED LOOP (plan
    #         sprint-5/03 S1/S2/S3) - EVERYTHING ELSE (the vendor/API path,
    #         a no-watermark master) STAYS ON THE OLDER, UNCHANGED PATH
    #         BELOW.  !!
    if config.source_impl == SOURCE_IMPL_SQL_DB and getattr(source, "watermark_column", None):
        _run_paged_sql_db(
            db, service, job, run, watermark_row, config, companies, source,
            tenant_id=tenant_id, company_id=company_id, entity_type=entity_type,
            mode=mode, started=started, trace_id=trace_id, company=company,
        )
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
    except SqlDeleteGuardExceeded as exc:
        # S5 review SHOULD-FIX 5: a guard TRIP is a deliberate safety stop,
        # not a transport/driver fault - it must never read as one. WARNING
        # (no stack trace, unlike the generic branch below), the message
        # UNPREFIXED (no "Fetch failed:" noise), and a distinct error code so
        # the task surface can tell "the delete guard fired" apart from every
        # other kind of failure.
        logger.warning(
            "autocount delete guard tripped for job %s: %s", job.id, exc.message
        )
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
            config=config,
            error_code="DELETE_GUARD",
        )
        return
    except SqlDocumentCapExceeded as exc:
        # S5 review SHOULD-FIX 3 - same treatment as the delete guard above:
        # a document task's per-header line-query fan-out cap tripped is a
        # deliberate safety stop, not a transport/driver fault. WARNING (no
        # stack trace), the message UNPREFIXED, a distinct error code.
        logger.warning(
            "autocount document cap tripped for job %s: %s", job.id, exc.message
        )
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
            config=config,
            error_code="DOCUMENT_CAP",
        )
        return
    except SqlFilterFormulaError as exc:
        # F2/B3, sprint-5/02 review round - same treatment as the delete
        # guard/document cap above: a filter that fails to evaluate at run
        # time is a deliberate safety stop, not a transport/driver fault.
        # WARNING (no stack trace), the message UNPREFIXED, a distinct error
        # code so the task surface can tell this apart from a source outage.
        logger.warning(
            "autocount filter formula failed for job %s: %s", job.id, exc.message
        )
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
            config=config,
            error_code="FILTER_FORMULA",
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
    # A document's LINE rows are operator-persisted ``ac_field_mapping`` rows
    # (scope='line', sprint-5/02) - ``mapping_rows`` already returns header AND
    # line scope together. ``build_mapping_rows_for_run`` is the ONE gate for
    # this (S5 review NIT - shared with ``etl_service.py``'s preview path so
    # the two can never drift).
    mapping_rows = build_mapping_rows_for_run(
        entity_type,
        companies.mapping_rows(tenant_id, company_id, entity_type),
        is_sql_db_source=config.source_impl == SOURCE_IMPL_SQL_DB,
        source_config=config.source_config,
    )
    engine = MappingEngine(
        mapping_rows,
        # ``None`` = the entity profile's own key (masters have none, being flat).
        detail_key=VENDOR_DETAIL_KEYS.get(entity_type),
        entity_type=entity_type,
        #     !!  THE PROFILE MUST MATCH THE SOURCE THAT PRODUCED THE ROWS.  !!
        # The API path's rows are the vendor envelope, so identity reads
        # ``Data.0.AutoKey``; a DB task's rows are FLAT, so identity is minted
        # from the task's key columns (AC-22-09/10). Using the API profile on
        # flat rows fails EVERY record with "carries no Data.0.AutoKey" - which
        # reads like a mapping mistake and is not one.
        profile=(
            flat_profile(entity_type, (config.source_config or {}).get("keyColumns") or [])
            if config.source_impl == SOURCE_IMPL_SQL_DB
            else None
        ),
        # Masters mint a COMPANY-QUALIFIED ``source_ref`` (AC-14-10). The name
        # comes from the discovered company, never from operator input - and it
        # is what stops company B's ``AutoKey=1`` overwriting company A's.
        database_name=company.database_name,
    )
    staged_count, failed_count, _failed_refs = _stage_documents(
        db,
        service,
        job,
        result.records,
        engine=engine,
        tenant_id=tenant_id,
        company_id=company_id,
        entity_type=entity_type,
    )
    # Reconcile's delete intents (plan 22 §2.5, AC-22-16) - absent-but-known
    # refs stage as their OWN op='delete' rows, no canonical payload. Counted
    # into `staged_count` (an entity-level "records this run put in front of
    # the sink", the same meaning adds/updates already carry); the run row's
    # `deleted_count` is reserved for PUSH VERDICTS (deleted/deactivated),
    # stamped once auto-push resolves them below.
    delete_staged = _stage_deletes(
        db,
        job,
        result.delete_refs,
        tenant_id=tenant_id,
        company_id=company_id,
        entity_type=entity_type,
        current_refs=result.current_refs,
    )
    run.staged_count = staged_count + delete_staged
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
        # S2 review SHOULD-FIX 10: a quarantined push failure must be VISIBLE
        # on the RUN ROW, not just buried in the job's result JSON - the Runs
        # list has no other failure column. Extends failed_count (a document
        # that fails to MAP and a record that fails to PUSH are both "this
        # run did not fully succeed") rather than adding a new column, for
        # frontend simplicity - the count that was 0 documents-failed-to-map
        # is now ALSO carrying quarantined-records-failed-to-push.
        quarantined_count = int(push_summary.get("quarantined") or 0)
        if quarantined_count:
            run.failed_count = (run.failed_count or 0) + quarantined_count
        # Delete-push verdicts (AC-22-21): `deletedHandled` = deleted +
        # deactivated + not_found (all three mean "the sink resolved it", per
        # the schema comment on `AcSyncRun.deleted_count`). A `failed` verdict
        # quarantines the same way an upsert failure does.
        run.deleted_count = int(push_summary.get("deletedHandled") or 0)
        delete_failed_count = len(push_summary.get("deleteFailures") or [])
        if delete_failed_count:
            run.failed_count = (run.failed_count or 0) + delete_failed_count
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
    ref_fn: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
    check_abort: bool = True,
) -> Tuple[int, int, List[str]]:
    """Map + persist each document independently. Returns
    ``(staged, failed, failed_refs)``.

    Per-document commit + abort checkpoint: one document's failure can never
    contaminate a sibling, and an abort stops at the next document boundary
    rather than after the whole batch.

    ``ref_fn`` (plan sprint-5/03 S2, AC-03-11/12) - the SAME identity
    function a paged ``sql_db`` run's ``fetch_page`` used to key
    ``ac_row_hash`` (``SqlDbSource.source_ref``), so the caller can drop a
    failed row's hash and let the next full pass retry it fresh (D1: a
    failed row keeps NO hash). ``None`` for every other caller - a failed
    document's ref is meaningless there (the API path stores no hashes).

    ``check_abort=False`` (plan sprint-5/03 S1, AC-03-08) - a PAGED run
    already fetched this whole page's rows before an abort could possibly
    land; the page in flight finishes staging regardless, and the run loop
    itself is the one that checks for an abort BETWEEN pages, never mid-page.
    """
    staged_repo = StagedRecordRepository(db)
    staged = failed = 0
    failed_refs: List[str] = []

    for position, source_record in enumerate(records, start=1):
        if check_abort and _aborted(db, job.id):
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
            if ref_fn is not None:
                ref = ref_fn(source_record.raw)
                if ref is not None:
                    failed_refs.append(ref)
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

    return staged, failed, failed_refs


def _run_paged_sql_db(
    db: Session,
    service: JobService,
    job: BackgroundJob,
    run: AcSyncRun,
    watermark_row: AcWatermark,
    config: AcEntityConfig,
    companies: "CompanyService",
    source,
    *,
    tenant_id: str,
    company_id: str,
    entity_type: str,
    mode: str,
    started: float,
    trace_id: str,
    company,
) -> None:
    """The paged run loop for a WATERMARKED ``sql_db`` task (plan sprint-5/03
    S1/S2/S3): paged extraction with a per-run time budget and continuation,
    change-only staging, the watermark advancing independent of mapping
    failures (D1), seen stamps, and deletes computed only when a reconcile
    pass completes. The vendor/API path and a no-watermark master stay on
    the OLDER ``fetch_changes``-based branch in ``run_autocount_sync`` above
    (unchanged - D18's "watermark holds on any failed document" rule still
    governs there).
    """
    mapping_rows = build_mapping_rows_for_run(
        entity_type,
        companies.mapping_rows(tenant_id, company_id, entity_type),
        is_sql_db_source=True,
        source_config=config.source_config,
    )
    engine = MappingEngine(
        mapping_rows,
        detail_key=VENDOR_DETAIL_KEYS.get(entity_type),
        entity_type=entity_type,
        profile=flat_profile(
            entity_type, (config.source_config or {}).get("keyColumns") or []
        ),
        database_name=company.database_name,
    )
    hashes_repo = RowHashRepository(db)
    staged_repo = StagedRecordRepository(db)
    # Refs THIS RUN introduced for the first time (R-S4, review round 2) -
    # accumulated from ``upsert_many``'s own return value (itself scoped to
    # only the refs each page just touched), NEVER a snapshot of the whole
    # known population taken up front. The guard-failure rollback below
    # needs to tell a genuinely PRE-EXISTING ref (whose hash a page may have
    # legitimately refreshed) apart from a brand-new one this run introduced
    # - loading the ENTIRE population just to answer that, on every tick,
    # success or not, is exactly the cost this refactor removes.
    new_this_run: set[str] = set()

    def _record_error_activity(message: str) -> None:
        # F7 (review round 2) - the paged branch used to write NO activity
        # rows at all; the legacy branch below in ``run_autocount_sync``
        # writes one per failure, so this mirrors it exactly.
        record_activity(
            db, tenant_id=tenant_id, operation=f"sync {entity_type}",
            status=ACTIVITY_ERROR, trace_id=trace_id,
            external_ref=company.database_name,
            latency_ms=int((time.monotonic() - started) * 1000),
            error_message=message,
        )

    def _clear_pass() -> None:
        # JSON columns need a FRESH dict on every write (SQLAlchemy misses
        # in-place mutation) - never just `del cursor["pass"]` on the ORM's
        # own live dict.
        watermark_row.cursor_json = {**(watermark_row.cursor_json or {}), "pass": None}

    def _discard_this_runs_staging() -> None:
        """A guard trip is fail-SAFE, not fail-partial: the OLD, unpaged
        guard fired BEFORE any staging or hash write happened at all (it ran
        on the whole population in one shot), so "nothing was staged or
        pushed, the known population untouched" was automatic. Paging
        stages/commits page by page, so an EARLIER page's genuine adds/
        updates may already sit in ``ac_staged_record``/``ac_row_hash`` by
        the time a LATER page (or the post-loop ratio check) trips the
        guard - this wipes every staged row THIS job wrote, and drops the
        hash of every ref THIS RUN introduced for the first time (a
        pre-existing ref's hash, legitimately refreshed by an earlier page,
        is left as the newest read rather than reverted - a smaller
        imperfection than leaving a PHANTOM new row behind), before
        ``_fail`` records the failure.
        """
        staged_repo.discard_for_job(tenant_id, company_id, job.id)
        if new_this_run:
            hashes_repo.delete_many(tenant_id, company_id, entity_type, list(new_this_run))
        run.staged_count = 0
        run.failed_count = 0
        run.added_count = 0
        run.updated_count = 0
        db.commit()

    cursor = PageCursor.from_watermark_row(
        watermark_row, mode, watermark_column=source.watermark_column
    )
    pass_started_at = cursor.pass_started_at or datetime.now(timezone.utc)
    deadline = time.monotonic() + float(settings.autocount_run_time_budget_seconds)

    # The public, monotonic top-level position (F3, review round 2) - read
    # ONCE here, straight off the stored row, never off ``cursor.mark``
    # (which for a fresh RECONCILE pass is deliberately ``None``, and for a
    # RESUMED pass is the PASS-scoped position, not this one). It only ever
    # moves forward (``_advance_mark_and_ties``), and for a reconcile it does
    # not move AT ALL until the whole pass completes - see the tail below.
    existing_cursor = watermark_row.cursor_json if isinstance(watermark_row.cursor_json, dict) else {}
    top_mark: Any = existing_cursor.get(CURSOR_MARK)
    top_tie_refs: List[str] = list(existing_cursor.get("tieRefs") or [])
    pass_rows_scanned_before = cursor.rows_scanned

    total_rows_scanned = total_added = total_updated = total_staged = total_failed = 0
    truncated = False
    pages_done = cursor.pages_done
    pass_mark: Any = cursor.mark
    cumulative_rows_scanned = pass_rows_scanned_before
    aborted_flag = False
    page = None

    try:
        while True:
            try:
                page = source.fetch_page(cursor)
            except SqlDeleteGuardExceeded as exc:
                # AC-03-19: a guard trip mid-pass must leave hashes/stamps
                # consistent AND clear the in-progress pass, so the NEXT
                # reconcile starts fresh rather than resuming a bad one.
                logger.warning(
                    "autocount delete guard tripped for job %s: %s", job.id, exc.message
                )
                _clear_pass()
                _discard_this_runs_staging()
                record_client_calls(
                    db, source, tenant_id=tenant_id, trace_id=trace_id,
                    external_ref=company.database_name,
                )
                _record_error_activity(exc.message)
                _fail(
                    db, service, job, run, watermark_row, exc.message, started,
                    config=config, error_code="DELETE_GUARD",
                )
                return
            except SqlDocumentCapExceeded as exc:
                logger.warning(
                    "autocount document cap tripped for job %s: %s", job.id, exc.message
                )
                _discard_this_runs_staging()
                record_client_calls(
                    db, source, tenant_id=tenant_id, trace_id=trace_id,
                    external_ref=company.database_name,
                )
                _record_error_activity(exc.message)
                _fail(
                    db, service, job, run, watermark_row, exc.message, started,
                    config=config, error_code="DOCUMENT_CAP",
                )
                return
            except SqlFilterFormulaError as exc:
                logger.warning(
                    "autocount filter formula failed for job %s: %s", job.id, exc.message
                )
                _discard_this_runs_staging()
                record_client_calls(
                    db, source, tenant_id=tenant_id, trace_id=trace_id,
                    external_ref=company.database_name,
                )
                _record_error_activity(exc.message)
                _fail(
                    db, service, job, run, watermark_row, exc.message, started,
                    config=config, error_code="FILTER_FORMULA",
                )
                return
            except AutoCountError as exc:
                record_client_calls(
                    db, source, tenant_id=tenant_id, trace_id=trace_id,
                    external_ref=company.database_name,
                )
                _record_error_activity(exc.message)
                _fail(db, service, job, run, watermark_row, exc.message, started, config=config)
                return
            except Exception as exc:  # noqa: BLE001
                logger.exception("autocount paged sync fetch failed for job %s", job.id)
                record_client_calls(
                    db, source, tenant_id=tenant_id, trace_id=trace_id,
                    external_ref=company.database_name,
                )
                _record_error_activity(f"Fetch failed: {exc}")
                _fail(
                    db, service, job, run, watermark_row, f"Fetch failed: {exc}", started,
                    config=config,
                )
                return

            # R-S7 (review round 2) - the RUNNING total is visible BEFORE
            # this page stages anything, exactly like the legacy branch
            # calls ``set_total`` before its own staging starts, rather than
            # only once at the very end of the whole (possibly many-page)
            # run.
            service.set_total(job, total_rows_scanned + page.rows_scanned)

            staged, failed, failed_refs = _stage_documents(
                db, service, job, page.records, engine=engine,
                tenant_id=tenant_id, company_id=company_id, entity_type=entity_type,
                ref_fn=source.source_ref, check_abort=False,
            )
            failed_ref_set = set(failed_refs)
            now = datetime.now(timezone.utc)
            # A row's hash is written only when it CHANGED and did not fail
            # to map (D1: a failed row keeps NO hash, so the next full pass
            # retries it fresh); an unchanged row's stamp is merely TOUCHED
            # (AC-03-15) - `upsert_many` never runs for it.
            changed_hashes = {
                ref: value
                for ref, value in page.hashes.items()
                if ref not in page.unchanged_refs and ref not in failed_ref_set
            }
            if changed_hashes:
                inserted_refs = hashes_repo.upsert_many(
                    tenant_id, company_id, entity_type, changed_hashes, seen_at=now
                )
                new_this_run.update(inserted_refs)
            if page.unchanged_refs:
                hashes_repo.touch_seen(
                    tenant_id, company_id, entity_type, page.unchanged_refs, seen_at=now
                )
            if failed_refs:
                hashes_repo.delete_many(tenant_id, company_id, entity_type, failed_refs)
            # R-S1 (review round 2) - a stale parked delete intent is
            # cancelled the MOMENT its ref reappears in ANY page of ANY
            # mode's run, not only once a full reconcile pass completes.
            # This was previously the ONLY cancellation path (the post-loop
            # reconcile-completion block below) - an INCREMENTAL run never
            # ran it at all, so a ref that reappeared between two reconciles
            # left its stale intent parked, ready to fire against a document
            # that had already come back.
            if page.hashes:
                staged_repo.discard_stale_deletes(
                    tenant_id, company_id, entity_type, list(page.hashes)
                )

            record_client_calls(
                db, source, tenant_id=tenant_id, trace_id=trace_id,
                external_ref=company.database_name,
            )

            pages_done += 1
            total_rows_scanned += page.rows_scanned
            total_added += page.added
            total_updated += page.updated
            total_staged += staged
            total_failed += failed
            cumulative_rows_scanned = pass_rows_scanned_before + total_rows_scanned
            if page.last_mark is not None:
                pass_mark = page.last_mark
            # The TOP-LEVEL public position advances per page for a plain
            # incremental/manual pass (unchanged, legacy-compatible
            # behaviour a truncated MANUAL/INCREMENTAL run's own tests
            # already pin) - a RECONCILE pass instead leaves it untouched
            # until the whole pass completes (F3, below the loop), so an
            # in-flight reconcile is never mistaken, mid-pass, for having
            # already advanced past work it has not finished yet.
            if mode != RUN_MODE_RECONCILE:
                top_mark, top_tie_refs = _advance_mark_and_ties(
                    top_mark, top_tie_refs, pass_mark, list(page.tie_refs)
                )

            service.log(
                job,
                f"Page {pages_done}: scanned {page.rows_scanned}, changed "
                f"{page.added + page.updated} ({page.added} new, {page.updated} "
                f"updated), {len(page.unchanged_refs)} unchanged, skipped, "
                f"{failed} failed.",
            )

            watermark_row.cursor_json = {
                # LEGACY keys, kept verbatim (coordinator fix-round): live
                # rows on the real company already carry
                # ``sqlWatermarkColumn``/``sqlWatermark`` - renaming them
                # would orphan every task's mark and force a full re-read.
                # ``tieRefs`` and ``pass`` are the only ADDED keys. This
                # TOP-LEVEL pair is the PUBLIC, monotonic position (F3) -
                # separate from ``pass.mark``/``pass.tieRefs`` below, which
                # is this SPECIFIC pass's own live per-page position.
                CURSOR_COLUMN: source.watermark_column,
                CURSOR_MARK: top_mark,
                "tieRefs": top_tie_refs,
                "pass": {
                    "kind": mode,
                    "startedAt": pass_started_at.isoformat(),
                    "pagesDone": pages_done,
                    "complete": page.complete,
                    # Scoped to THIS pass (plan sprint-5/03 §2.6, AC-03-21) -
                    # deliberately separate from the top-level mark above
                    # (which a DIFFERENT-kind pass, e.g. a plain incremental
                    # tick, also reads/writes to resume its OWN position):
                    # the wire's ``initialLoad.lastMark`` must show progress
                    # for the pass currently open, never a stale mark left
                    # behind by an unrelated, already-finished one. A brand
                    # new, pass-scoped field - not part of the legacy shape.
                    "mark": pass_mark,
                    "tieRefs": list(page.tie_refs),
                    # Cumulative across the WHOLE pass, not just this run
                    # (R-NIT, review round 2) - the zero-rows delete guard
                    # below reads this to tell "this pass never read
                    # anything at all" apart from "a LATER page's own read
                    # happened to be empty", which is normal completion.
                    "rowsScanned": cumulative_rows_scanned,
                },
            }
            run.rows_scanned = total_rows_scanned
            run.added_count = total_added
            run.updated_count = total_updated
            run.staged_count = total_staged
            run.failed_count = total_failed
            db.commit()

            if _aborted(db, job.id):
                aborted_flag = True
                break
            if page.complete:
                break
            if time.monotonic() >= deadline:
                truncated = True
                break

            cursor = PageCursor(
                mark=page.last_mark, tie_refs=page.tie_refs, pass_kind=mode,
                pass_started_at=pass_started_at, pages_done=pages_done,
                rows_scanned=cumulative_rows_scanned,
            )
    finally:
        source.close()

    if aborted_flag:
        _abort(db, service, run, started)
        return

    # ── deletes, ONLY when a RECONCILE pass just completed (D6) ─────────────
    delete_staged = 0
    if page is not None and page.complete:
        if mode == RUN_MODE_RECONCILE:
            known = hashes_repo.all_hashes(tenant_id, company_id, entity_type)
            known_count = len(known)
            #     !!  A WHOLE PASS THAT NEVER READ A SINGLE ROW IS NEVER A
            #         GENUINE TOTAL WIPE (R-NIT, review round 2).  !!
            # This is the completed-pass counterpart of ``fetch_page``'s own
            # (now removed) per-page zero-row guard: that version fired on
            # EVERY page of a full extract, including a perfectly normal
            # LATER page whose own read empties out near the end of a pass
            # (the previous page's own boundary row can genuinely be gone by
            # then) - not evidence of a wipe. Checking the PASS's cumulative
            # total instead of any one page's own count is what tells those
            # two apart.
            if cumulative_rows_scanned == 0 and known_count:
                message = (
                    f"This run returned 0 rows across the whole reconcile pass "
                    f"while {known_count} previously-known row(s) exist for "
                    f"this entity - nothing was staged or pushed. This looks "
                    f"like a broken query or connection, not a genuine full "
                    f"deletion. Check the query and the connection, then "
                    f"re-run reconcile."
                )
                logger.warning(
                    "autocount delete guard tripped for job %s: %s", job.id, message
                )
                _clear_pass()
                _discard_this_runs_staging()
                _record_error_activity(message)
                _fail(
                    db, service, job, run, watermark_row, message, started,
                    config=config, error_code="DELETE_GUARD",
                )
                return
            # The FULL known population, not just a count (S3 review
            # BLOCKER 1 mirror): a ref that is NOT stale reappeared/was
            # always current this pass, and ``_stage_deletes`` needs that
            # set as ``current_refs`` to cancel any STALE PARKED delete
            # intent whose ref came back - a delete intent must not
            # outlive the evidence that produced it.
            stale = hashes_repo.stale_refs(
                tenant_id, company_id, entity_type, before=pass_started_at
            )
            stale_set = set(stale)  # R-S2 (review round 2) - built ONCE
            current_refs = [ref for ref in known if ref not in stale_set]
            threshold = max(DELETE_GUARD_RATIO * known_count, DELETE_GUARD_MIN_ABSOLUTE)
            if stale and len(stale) > threshold:
                message = (
                    f"This reconcile would delete {len(stale)} of {known_count} "
                    f"previously-known row(s) - over the safety threshold "
                    f"({threshold:.0f}). Nothing was staged or pushed. Check the "
                    f"query and the connection, then re-run reconcile."
                )
                logger.warning(
                    "autocount delete guard tripped for job %s: %s", job.id, message
                )
                _clear_pass()
                _discard_this_runs_staging()
                _record_error_activity(message)
                _fail(
                    db, service, job, run, watermark_row, message, started,
                    config=config, error_code="DELETE_GUARD",
                )
                return
            delete_staged = _stage_deletes(
                db, job, stale, tenant_id=tenant_id, company_id=company_id,
                entity_type=entity_type, current_refs=current_refs,
            )
            # The reconcile's OWN public position advances only NOW that the
            # whole pass has genuinely finished (F3, review round 2) - never
            # per page, and never past whatever an incremental tick may have
            # already left ahead of it. Its tie-ref set travels WITH it (or
            # not at all) - never overwriting a DIFFERENT, winning mark's own
            # tie group (``_advance_mark_and_ties``).
            top_mark, top_tie_refs = _advance_mark_and_ties(
                top_mark, top_tie_refs, pass_mark, list(page.tie_refs)
            )
            watermark_row.cursor_json = {
                **(watermark_row.cursor_json or {}),
                CURSOR_COLUMN: source.watermark_column,
                CURSOR_MARK: top_mark,
                "tieRefs": top_tie_refs,
            }
        # A completed pass's ``pass`` dict is LEFT AS-IS (``complete: true``
        # already written per-page above) - plan sprint-5/03 §2.2: only a
        # GUARD FAILURE clears it outright (``_clear_pass`` above). A later
        # run of the SAME mode naturally starts a fresh pass anyway
        # (``PageCursor.from_watermark_row`` only resumes an INCOMPLETE
        # pass), and ``EtlService._initial_load`` reads ``initialLoad`` as
        # ``None`` once ``complete`` is true (AC-03-21) - two different
        # readers of the one flag, not two sources of truth.

    run.fetched_count = total_staged + total_failed
    run.rows_scanned = total_rows_scanned
    run.added_count = total_added
    run.updated_count = total_updated
    run.staged_count = total_staged + delete_staged
    run.failed_count = total_failed
    db.commit()

    #     !!  D1 REVERSAL: THE WATERMARK ADVANCES REGARDLESS OF MAPPING
    #         FAILURES (plan sprint-5/03 S2, AC-03-11) - a permanently bad
    #         document must never force a full re-extract every run.  !!
    decoded_max = decode_mark(pass_mark) if pass_mark is not None else None
    if isinstance(decoded_max, datetime):
        watermark_row.last_modified_at = decoded_max.astimezone(timezone.utc)
    watermark_row.cursor_json = {
        **(watermark_row.cursor_json or {}),
        CURSOR_COLUMN: source.watermark_column,
        CURSOR_MARK: top_mark,
        "tieRefs": top_tie_refs,
    }
    watermark_row.consecutive_failures = 0
    watermark_row.last_success_at = datetime.now(timezone.utc)
    watermark_row.last_error = (
        f"{total_failed} record(s) failed to map; see staged records"
        if total_failed
        else None
    )

    # ── auto-push (plan 22 §2.6, unchanged contract) ─────────────────────────
    pushed_count = 0
    push_summary: Optional[Dict[str, Any]] = None
    if config.etl_status == ETL_STATUS_ACTIVE:
        from .services.sync_service import SyncService

        push_summary = SyncService(db).auto_push(
            tenant_id, company_id, entity_type, job_id=job.id
        )
        pushed_count = int(push_summary.get("pushed") or 0)
        run.pushed_count = pushed_count
        config.last_run_error = push_summary.get("error")
        config.last_run_error_code = push_summary.get("errorCode")
        quarantined_count = int(push_summary.get("quarantined") or 0)
        if quarantined_count:
            run.failed_count = (run.failed_count or 0) + quarantined_count
        run.deleted_count = int(push_summary.get("deletedHandled") or 0)
        delete_failed_count = len(push_summary.get("deleteFailures") or [])
        if delete_failed_count:
            run.failed_count = (run.failed_count or 0) + delete_failed_count
    else:
        config.last_run_error = None
        config.last_run_error_code = None
    config.last_run_at = datetime.now(timezone.utc)

    run.outcome = RUN_SUCCESS
    run.truncated = truncated
    run.watermark_advanced_to = watermark_row.last_modified_at
    run.finished_at = datetime.now(timezone.utc)
    run.duration_ms = int((time.monotonic() - started) * 1000)
    if truncated:
        run.error = f"Budget reached after page {pages_done}; continues on the next tick."
        # The initial (or continuing) pass resumes on the VERY NEXT sweep
        # tick, not after a full `incrementalMinutes` wait (D3 - 148k SO
        # headers must finish in hours unattended, not overnight-per-page).
        #     !!  THE VERY NEXT TICK, REGARDLESS OF WHICH CADENCE FIRES IT
        #         (F3, review round 2 - the scheduler side of this fix).  !!
        # A truncated pass of ANY kind re-arms ``next_incremental_at`` (the
        # shorter of the two cadences, so the continuation lands soon) -
        # ``next_reconcile_at`` is left exactly where the sweep's own claim
        # step put it (already re-armed into the future when it was the one
        # due this tick). The MODE actually used on that next tick is not
        # decided here at all: ``scheduler._sweep_one``'s own open-pass
        # override (F3's other half) makes an in-progress pass's ``kind``
        # win over whichever schedule field happened to be due, so a
        # truncated RECONCILE is continued as a reconcile even though it is
        # the INCREMENTAL cadence that wakes the next tick. ``next_run_times``
        # never returns ``None`` today, but the guard (R-NIT) is kept
        # explicit rather than assumed.
        from .services.etl_service import EtlService

        next_incremental, _next_reconcile = EtlService.next_run_times(
            config.source_config or {}, now=datetime.now(timezone.utc)
        )
        if next_incremental is not None:
            config.next_incremental_at = datetime.now(timezone.utc)
    else:
        run.error = None

    record_activity(
        db, tenant_id=tenant_id, operation=f"sync {entity_type}", status=ACTIVITY_SUCCESS,
        trace_id=trace_id, external_ref=company.database_name,
        latency_ms=int((time.monotonic() - started) * 1000),
        request={"mode": mode, "pagesDone": pages_done, "rowsScanned": total_rows_scanned},
        response={"staged": total_staged, "failed": total_failed},
    )

    summary = {
        "companyId": company_id,
        "entityType": entity_type,
        "staged": total_staged,
        "failed": total_failed,
        "rowsScanned": total_rows_scanned,
        "added": total_added,
        "updated": total_updated,
        "truncated": truncated,
        "mode": mode,
        "watermarkAdvancedTo": (
            watermark_row.last_modified_at.isoformat()
            if watermark_row.last_modified_at
            else None
        ),
        "awaitingApproval": False,
    }
    if push_summary is not None:
        summary.update(push_summary)
        summary["awaitingApproval"] = False
    service.log(
        job,
        f"Staged {total_staged} document(s), {total_failed} failed."
        + (
            f" Pushed {pushed_count} record(s) automatically (the task is active)."
            if push_summary is not None
            else " Awaiting approval - nothing has been pushed."
        )
        + (
            f" Budget reached after page {pages_done}; continues on the next tick."
            if truncated
            else ""
        ),
    )
    # A delete intent is JUST AS MUCH a batch awaiting review as an upsert -
    # change-only staging (D2) means a steady-state reconcile's OWN
    # ``total_staged`` (upserts) is routinely 0 while it still parks a
    # delete intent, so that count alone would wrongly close the job.
    holds_for_review = (total_staged + delete_staged) > 0 and push_summary is None
    service.finish(
        job,
        status=JOB_NEEDS_REVIEW if holds_for_review else JOB_DONE,
        result=summary,
    )
    db.commit()


def _stage_deletes(
    db: Session,
    job: BackgroundJob,
    delete_refs: List[str],
    *,
    tenant_id: str,
    company_id: str,
    entity_type: str,
    current_refs: List[str],
) -> int:
    """Stage a reconcile's delete intents (plan 22 §2.5/§2.6, AC-22-16/21) -
    ONE ``AcStagedRecord`` per ref, ``op='delete'``, no canonical payload (a
    delete carries nothing to map).

    Two safety passes run BEFORE any new intent is staged (S3 review):

    * **BLOCKER 1 - stale-intent discard.** Any existing STAGED delete intent
      whose ref reappeared in THIS extract (``current_refs``) is cancelled
      first - a delete intent must not outlive the evidence that produced it.
      Runs on every call, including a draft/paused task whose push is gated,
      so a stale intent never survives to fire once the task is activated.
    * **S6 - no duplicate intents.** A ref that already carries a non-terminal
      delete intent (STAGED or STAGED_FAILED) is skipped - a reconcile that
      runs again before the first intent resolves must not pile up a second
      row for the same ref.

    **B2 (plan 22 S4 review, option (a)) - a SHARED entity is never deleted by
    ONE company's reconcile.** ``sales_agent`` rows are shared across
    companies in Sorento (``mapping.UNQUALIFIED_REF_ENTITIES`` - the ref
    itself carries no company qualifier), so a ref missing from THIS
    company's extract is not proof the agent is gone globally; another
    company may still use it. Staging (and eventually auto-pushing) a delete
    here would let one company silently retire a row a sibling depends on.
    So for those entities NO delete intent is staged at all - only this
    company's local ``ac_row_hash`` row for the missing ref is dropped, so
    local state stays honest about what THIS company's extract currently
    contains and a later re-appearance stages as a fresh add (never a
    phantom update). Retiring a shared agent is an operator action taken
    directly against Sorento, out of band - see ``canonical/masters.py``'s
    ``CanonicalSalesAgent`` docstring and plan 22 Appendix A6 item 6.

    **sprint-5/02 S3 (AC-02-13) - a DOCUMENT is no longer exempt.** Plan-22 S5
    exempted documents for the same reason as a shared entity: a header's
    ``fromDate`` floor made its known population look like a WINDOW rather
    than a standing set, so a missing header looked indistinguishable from
    one that simply aged out. That reasoning does not hold up - ``fromDate``
    is a PERMANENT scope boundary (never moved after go-live) and AutoCount
    dates do not travel backwards, so a header once inside the window stays
    inside it forever; its disappearance from a later extract IS genuine
    evidence of deletion (``sql_source.source.SqlDbSource.fetch_changes``
    mirrors this reversal - it no longer excludes documents from computing
    ``delete_refs`` either). A document therefore now stages an ordinary
    delete intent exactly like a master. Cancel-at-source (as opposed to a
    header genuinely vanishing from the extract) still arrives as an
    ordinary STATUS UPDATE via the header's own ``status`` mapping - nothing
    about that path changes.

    N7: a SINGLE commit for the whole batch (mirrors the auto-push upsert
    path) rather than one per row - the caller commits again immediately
    after this returns, so a per-row commit here bought nothing but extra
    round trips.
    """
    staged_repo = StagedRecordRepository(db)
    staged_repo.discard_stale_deletes(tenant_id, company_id, entity_type, current_refs)

    if entity_type in UNQUALIFIED_REF_ENTITIES:
        if delete_refs:
            dropped = RowHashRepository(db).delete_many(
                tenant_id, company_id, entity_type, delete_refs
            )
            logger.info(
                "autocount reconcile: %s is a shared entity - dropped %d local "
                "hash row(s) for missing ref(s) instead of staging deletes (%s).",
                entity_type, dropped, ", ".join(delete_refs),
            )
        db.commit()
        return 0

    count = 0
    if delete_refs:
        skip = staged_repo.pending_delete_refs(
            tenant_id, company_id, entity_type, delete_refs
        )
        for ref in delete_refs:
            if ref in skip:
                continue
            if _aborted(db, job.id):
                break
            staged_repo.add(
                AcStagedRecord(
                    tenant_id=tenant_id,
                    company_id=company_id,
                    entity_type=entity_type,
                    job_id=job.id,
                    source_ref=ref,
                    doc_no=None,
                    source_last_modified=None,
                    raw_json=None,
                    canonical_json=None,
                    status=STAGED,
                    op=STAGED_OP_DELETE,
                )
            )
            count += 1
    db.commit()
    return count


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
