"""Sync service - trigger a run, read what is staged, approve or discard.

Slice 1 is **MANUAL trigger only**. No scheduling, no beat entry: a scheduled
pull that nobody has yet watched approve a single batch is a data-integrity risk
running unattended. Scheduling lands once the pipeline has been exercised by
hand (plan §9).

**Approval is idempotent (AC-13-13).** The mechanism is an ATOMIC guarded status
claim on the job row - the same ``UPDATE … WHERE status=?`` the import engine
and storage migration use - so a double-click, a retry or a replay races into
exactly ONE winner. The loser does not error and does not push: it returns the
original result, because from the operator's point of view the approval DID
happen and a scary error on the second click of a successful action is its own
kind of bug.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Any, Dict, List, Optional, Sequence, Tuple

import httpx

from sqlalchemy.orm import Session

from app.jobs.repository import BackgroundJobRepository
from app.jobs.service import JobService
from app.models.background_job import (
    JOB_DONE,
    JOB_NEEDS_REVIEW,
    JOB_RUNNING,
    BackgroundJob,
    JOB_ABORTED,
    JOB_FAILED,
)

from ..activity import ACTIVITY_ERROR, ACTIVITY_SUCCESS, record_activity
from ..canonical.base import CanonicalRecord
from ..canonical.documents import (
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
    CanonicalPurchaseOrder,
    CanonicalSalesOrder,
    CanonicalShippingOrder,
)
from ..canonical.grn import CanonicalGrn, ENTITY_GOODS_RECEIVED_NOTE
from ..canonical.masters import (
    ENTITY_CUSTOMER,
    ENTITY_PRODUCT,
    ENTITY_PRODUCT_CATEGORY,
    ENTITY_SALES_AGENT,
    ENTITY_SUPPLIER,
    ENTITY_UNIT_OF_MEASURE,
    ENTITY_WAREHOUSE,
    CanonicalCustomer,
    CanonicalProduct,
    CanonicalProductCategory,
    CanonicalSalesAgent,
    CanonicalSupplier,
    CanonicalUnitOfMeasure,
    CanonicalWarehouse,
)
from ..models import (
    SINK_IMPL_LOGGING,
    SINK_IMPL_SORENTO,
    STAGED_DISCARDED,
    STAGED_FAILED,
    STAGED_OP_DELETE,
    STAGED_PUSHED,
    AcStagedRecord,
    AcSyncRun,
)
from ..repositories import (
    CompanyRepository,
    EntityConfigRepository,
    RowHashRepository,
    StagedRecordRepository,
    SyncJobRepository,
    SyncRunRepository,
)
from ..sinks import EntitySink, WriteResult
from ..sinks_sorento import (
    SinkAnchorError,
    SorentoSinkError,
    sorento_supported_entities_label,
    sorento_supports_entity,
    describe_consumer_failure,
)
from ..sync import AUTOCOUNT_SYNC
from .company_service import AutocountServiceError, CompanyService

logger = logging.getLogger("foundryx.autocount")

# Canonical entity → its canonical model, so a staged record's ``canonical_json``
# can be rehydrated into the typed shape the sink needs (``sink_payload`` /
# ``source_ref``). Hop 2 adds the two master shapes beside slice 1's GRN; plan
# 22 S4 (AC-22-23) adds the five masters fan-out shapes.
CANONICAL_MODELS = {
    ENTITY_GOODS_RECEIVED_NOTE: CanonicalGrn,
    ENTITY_SUPPLIER: CanonicalSupplier,
    ENTITY_CUSTOMER: CanonicalCustomer,
    ENTITY_PRODUCT_CATEGORY: CanonicalProductCategory,
    ENTITY_UNIT_OF_MEASURE: CanonicalUnitOfMeasure,
    ENTITY_WAREHOUSE: CanonicalWarehouse,
    ENTITY_PRODUCT: CanonicalProduct,
    ENTITY_SALES_AGENT: CanonicalSalesAgent,
    ENTITY_SALES_ORDER: CanonicalSalesOrder,
    ENTITY_PURCHASE_ORDER: CanonicalPurchaseOrder,
    ENTITY_SHIPPING_ORDER: CanonicalShippingOrder,
}


class EntityNotConfigured(AutocountServiceError):
    pass


class JobNotFound(AutocountServiceError):
    pass


class NotAwaitingApproval(AutocountServiceError):
    pass


class PushFailed(AutocountServiceError):
    """The push raised part-way through. The batch is back in ``needs_review``
    and is re-approvable - it is NOT stranded and NOT silently half-delivered."""


class JobLeaseLost(RuntimeError):
    """A push heartbeat found its job no longer RUNNING (orphan-swept or
    aborted mid-push): stop at the chunk boundary, write nothing more."""

    def __init__(self, job_id: str) -> None:
        super().__init__(
            f"Interrupted: job {job_id} is no longer running (swept or aborted); "
            "the push stopped at a chunk boundary."
        )


class _ChunkCommitFailed(RuntimeError):
    """A chunk's own per-chunk COMMIT raised (S3, review round 2 - e.g. a
    real NOT NULL violation flushed with the marks). Already rolled back
    and accounted (``_account_failure``) by the time this is raised - the
    caller's existing exception handling just needs to stop the push
    without double-counting or leaving the session in ``PendingRollbackError``
    for every later statement."""


class PreviewFailed(AutocountServiceError):
    """The dry run itself failed (a transport / contract fault talking to the
    consumer). The gate must SHOW this and refuse to offer approval - an operator
    must never approve blind (plan §D4). Nothing was written either way."""


# The Review list's status segments (plan 15 §2, AC-15-02) → the job status they
# filter on. ``all`` = no status filter. Anything else is a clean 422, never a
# silent empty list.
JOB_STATUS_FILTERS: Dict[str, Optional[str]] = {
    "all": None,
    "needs_review": JOB_NEEDS_REVIEW,
    "done": JOB_DONE,
}


@dataclass
class JobBatch:
    """One sync batch for the Review list (AC-15-02). Flat + snake_cased so
    ``SyncJobBatchItem.model_validate`` maps it straight through
    ``from_attributes``."""

    job_id: str
    company_id: str
    company_name: str
    database_name: str
    entity_type: str
    status: str
    progress_total: int
    progress_done: int
    progress_failed: int
    created_at: Optional[datetime]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    updated_at: Optional[datetime]


class SyncService:
    def __init__(self, db: Session):
        self.db = db
        self.companies = CompanyService(db)
        self.company_repo = CompanyRepository(db)
        self.configs = EntityConfigRepository(db)
        self.staged = StagedRecordRepository(db)
        self.runs = SyncRunRepository(db)
        self.sync_jobs = SyncJobRepository(db)
        self.jobs = JobService(db)

    # ── trigger ──────────────────────────────────────────────────────────────

    def sync_now(
        self,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        *,
        actor_user_id: Optional[str] = None,
    ) -> BackgroundJob:
        """"Sync now" - MANUAL only this slice."""
        company = self.companies.get(tenant_id, company_id)  # tenant-scope guard
        config = self.configs.get(tenant_id, company_id, entity_type)
        if config is None or not config.enabled:
            raise EntityNotConfigured(
                f"'{entity_type}' is not enabled for sync on {company.database_name}."
            )
        return self.jobs.create_and_enqueue(
            type=AUTOCOUNT_SYNC,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            payload={"companyId": company_id, "entityType": entity_type},
        )

    # ── reads ────────────────────────────────────────────────────────────────

    def _job(self, tenant_id: str, job_id: str) -> BackgroundJob:
        """Tenant-scoped job lookup, restricted to OUR job type - a job id from
        another feature must never be steerable into this service."""
        job = self.jobs.get(tenant_id, job_id)
        if job is None or job.type != AUTOCOUNT_SYNC:
            raise JobNotFound("That sync job was not found.")
        return job

    def _company_id_for(self, job: BackgroundJob) -> str:
        return str((job.payload_json or {}).get("companyId") or "")

    def _entity_type_for(self, job: BackgroundJob) -> str:
        # A job syncs exactly ONE entity, so all its staged rows share this type
        # - read it from the job's own payload, never from client input.
        return str((job.payload_json or {}).get("entityType") or "")

    def _rehydrate_pushable(
        self, pending: List[AcStagedRecord]
    ) -> Tuple[List[AcStagedRecord], List[Any], List[Dict[str, Any]]]:
        """Split staged rows into (pushable rows, rehydrated records, failures).

        A FAILED row has no canonical payload by design (D13) and can never be
        pushed; reaching here with one means it was mis-selected, so it is a
        named failure rather than a silent drop.
        """
        rows: List[AcStagedRecord] = []
        records: List[Any] = []
        failures: List[Dict[str, Any]] = []
        for row in pending:
            model = CANONICAL_MODELS.get(row.entity_type)
            if model is None or not row.canonical_json:
                failures.append({"sourceRef": row.source_ref, "error": "not pushable"})
                continue
            rows.append(row)
            records.append(model(**row.canonical_json))
        return rows, records, failures

    def staged_records(
        self, tenant_id: str, job_id: str
    ) -> Tuple[BackgroundJob, List[AcStagedRecord]]:
        job = self._job(tenant_id, job_id)
        company_id = self._company_id_for(job)
        # Company scope comes from the JOB's payload, never from client input -
        # a caller cannot ask for another company's staged rows (AC-13-41).
        return job, self.staged.list_for_job(tenant_id, company_id, job_id)

    def runs_for_company(
        self,
        tenant_id: str,
        company_id: str,
        *,
        entity_type: Optional[str] = None,
        page: int = 0,
        page_size: int = 25,
    ) -> Tuple[List[AcSyncRun], int]:
        self.companies.get(tenant_id, company_id)  # tenant-scope guard
        return self.runs.list(
            tenant_id, company_id, entity_type=entity_type, page=page, page_size=page_size
        )

    def list_jobs(
        self,
        tenant_id: str,
        *,
        status: str = "all",
        entity_type: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 0,
        page_size: int = 25,
    ) -> Tuple[List[JobBatch], int]:
        """The Review list - sync batches for THIS tenant, newest first (AC-15-02).

        Reads core ``background_jobs`` filtered to ``type='autocount_sync'`` and
        the caller's tenant (never client input), paginated at the DB level (no
        unbounded fetch). Company labels are batch-joined from ``ac_company`` in
        ONE tenant-scoped query, so a page never fans out per row.
        """
        if status not in JOB_STATUS_FILTERS:
            raise AutocountServiceError(
                f"Unknown status filter '{status}'. Choose "
                f"{', '.join(JOB_STATUS_FILTERS)}."
            )
        # A label search resolves to a company-id set here (the jobs table holds
        # only a companyId); an empty set → no rows, in SQL, so the total stays
        # honest. None = no search filter at all.
        company_ids = (
            self.company_repo.search_ids(tenant_id, search)
            if search and search.strip()
            else None
        )
        jobs, total = self.sync_jobs.list(
            tenant_id,
            AUTOCOUNT_SYNC,
            status=JOB_STATUS_FILTERS[status],
            entity_type=entity_type,
            company_ids=company_ids,
            page=page,
            page_size=page_size,
        )
        company_ids = [self._company_id_for(job) for job in jobs]
        companies = self.company_repo.get_map(tenant_id, company_ids)

        batches: List[JobBatch] = []
        for job in jobs:
            company_id = self._company_id_for(job)
            company = companies.get(company_id)
            batches.append(
                JobBatch(
                    job_id=job.id,
                    company_id=company_id,
                    # A company hard-deleted after its job ran leaves the label
                    # blank rather than 500-ing the whole list.
                    company_name=(company.name if company else ""),
                    database_name=(company.database_name if company else ""),
                    entity_type=self._entity_type_for(job),
                    status=job.status,
                    progress_total=job.progress_total or 0,
                    progress_done=job.progress_done or 0,
                    progress_failed=job.progress_failed or 0,
                    created_at=job.created_at,
                    started_at=job.started_at,
                    finished_at=job.finished_at,
                    # There is no ``updated_at`` column on ``background_jobs``;
                    # the most-recent activity is the last lifecycle stamp.
                    updated_at=job.finished_at or job.started_at or job.created_at,
                )
            )
        return batches, total

    def staged_page(
        self,
        tenant_id: str,
        job_id: str,
        *,
        changed: Optional[bool] = None,
        page: int = 0,
        page_size: int = 25,
    ) -> Tuple[BackgroundJob, List[AcStagedRecord], int, int, int]:
        """A PAGE of a job's staged records + counts (AC-15-10/11).

        Returns ``(job, rows, batch_total, filtered_total, no_change_count)``.
        Company scope comes from the JOB's payload, never from client input (a
        caller cannot ask for another company's staged rows). ``changed`` filters
        to the records whose mapped fields did (``True``) or did not (``False``)
        change; the counts let the FE render the collapsed "N records with no
        field changes" summary without fetching them all.
        """
        job = self._job(tenant_id, job_id)
        company_id = self._company_id_for(job)
        rows, batch_total, filtered_total, no_change = self.staged.page_for_job(
            tenant_id,
            company_id,
            job_id,
            changed=changed,
            page=page,
            page_size=page_size,
        )
        return job, rows, batch_total, filtered_total, no_change

    # ── approve / discard ────────────────────────────────────────────────────

    def _claim_review(self, job: BackgroundJob) -> bool:
        """Atomically claim ``needs_review`` → ``running``. Exactly one winner.

        This IS the idempotency mechanism (AC-13-13) - not a flag check, which
        would race two concurrent approvals straight through.
        """
        claimed = BackgroundJobRepository(self.db).claim(
            job.id, from_status=JOB_NEEDS_REVIEW
        )
        self.db.commit()
        return claimed

    def _release_claim(
        self,
        job: BackgroundJob,
        pushed: List[AcStagedRecord],
        exc: BaseException,
    ) -> None:
        """The push raised mid-loop. Do NOT leave the job in ``running``.

        ``_claim_review`` moved ``needs_review`` → ``running``; a raise between
        that and ``finish`` would strand the job forever - non-terminal so the
        pruner never reaps it, and no longer ``needs_review`` so ``_claim_review``
        can never succeed again. No re-approve, no retry, an approved batch dead
        in the water. Today only ``model(**row.canonical_json)`` can raise, but
        the moment a real network sink lands, ONE timeout does this.

        **Returned to ``needs_review``, not finished ``failed``** - because the
        approval genuinely did not complete, and ``needs_review`` is precisely
        "a human must act on this". Finishing ``failed`` would be the stranding
        bug in different clothes: a terminal job whose staged rows sit ``STAGED``
        forever with no path to push them.

        Rows already accepted by the sink are committed ``PUSHED`` FIRST, so the
        retry's ``list_pending_for_job`` (``status == STAGED``) skips them and
        nothing is delivered twice.
        """
        self.db.rollback()
        if pushed:
            # Re-attach by id - the rollback expired the objects held above.
            ids = {row.id for row in pushed}
            fresh = [
                row
                for row in self.staged.list_pending_for_job(
                    job.tenant_id, self._company_id_for(job), job.id
                )
                if row.id in ids
            ]
            self.staged.mark(
                fresh, status=STAGED_PUSHED, pushed_at=datetime.now(timezone.utc)
            )
        BackgroundJobRepository(self.db).release(
            job.id, from_status=JOB_RUNNING, to_status=JOB_NEEDS_REVIEW
        )
        self.db.commit()
        logger.error(
            "autocount push failed for job %s; %d record(s) already pushed, batch "
            "returned to review.",
            job.id,
            len(pushed),
            exc_info=exc,
        )

    def _push_per_record(
        self, job: BackgroundJob, sink: EntitySink, pending: List[AcStagedRecord]
    ) -> Tuple[List[AcStagedRecord], List[Dict[str, Any]], bool]:
        """Per-record push (the logging no-op path). Preserves slice 1's exact
        partial-failure recovery: a raise mid-loop commits the rows already
        accepted as PUSHED and returns the batch to review, re-approvable."""
        pushed: List[AcStagedRecord] = []
        failures: List[Dict[str, Any]] = []
        delivered = False
        try:
            for row in pending:
                model = CANONICAL_MODELS.get(row.entity_type)
                if model is None or not row.canonical_json:
                    failures.append(
                        {"sourceRef": row.source_ref, "error": "not pushable"}
                    )
                    continue
                record = model(**row.canonical_json)
                # Deterministic request id from (job, staged row) - a lower-layer
                # replay maps to the SAME id for the sink to dedupe on.
                result: WriteResult = sink.write(
                    record, request_id=f"{job.id}:{row.id}"
                )
                if result.ok:
                    pushed.append(row)
                    delivered = delivered or result.delivered
                else:
                    failures.append(
                        {"sourceRef": row.source_ref, "error": result.message}
                    )
        except Exception as exc:  # noqa: BLE001
            self._release_claim(job, pushed, exc)
            raise PushFailed(
                "The push failed part-way through, so this batch was returned to "
                "review. Records already delivered will not be sent again - "
                "approve it again to push the rest."
            ) from exc
        return pushed, failures, delivered

    def _push_batch(
        self, job: BackgroundJob, sink: EntitySink, pending: List[AcStagedRecord]
    ) -> Tuple[List[AcStagedRecord], List[Dict[str, Any]], bool]:
        """Batch push (the Sorento path). ONE ingest call (chunked below the
        vendor ceiling) rather than N HTTP calls sharing one rate-limit bucket.

        Per-record success/failure is preserved from the sink's per-record
        verdicts. A BATCH-level fault (``SorentoSinkError`` / ``SorentoRateLimited``)
        means NOTHING resolved - the whole batch returns to review with nothing
        marked pushed, exactly like any push failure. It is never stranded in
        ``running`` and never half-delivered.
        """
        pushed: List[AcStagedRecord] = []
        try:
            rows, records, failures = self._rehydrate_pushable(pending)
            results = (
                sink.write_batch(records, request_id=str(job.id)) if records else []
            )
            delivered = False
            for row, result in zip(rows, results):
                if result.ok:
                    pushed.append(row)
                    delivered = delivered or result.delivered
                else:
                    failures.append(
                        {"sourceRef": row.source_ref, "error": result.message}
                    )
        except SorentoSinkError as exc:
            # Batch-level: unresolved. Nothing delivered → release with pushed=[].
            self._release_claim(job, [], exc)
            raise PushFailed(
                "The consumer rejected the whole batch, so it was returned to "
                "review. Nothing was delivered - resolve the error and approve "
                "again."
            ) from exc
        except Exception as exc:  # noqa: BLE001
            self._release_claim(job, [], exc)
            raise PushFailed(
                "The push failed before the consumer resolved it, so the batch "
                "was returned to review. Nothing was delivered - approve again."
            ) from exc
        return pushed, failures, delivered

    # ── auto-push (plan 22 §2.6, AC-22-20) ───────────────────────────────────

    def auto_push(
        self, tenant_id: str, company_id: str, entity_type: str, *, job_id: str
    ) -> Dict[str, Any]:
        """Deliver an ACTIVE DB task's staged records with NO review gate.

        Called by the sync handler, inside its own run, for a ``sql_db`` task in
        ``etl_status='active'`` only. Three properties are what make it safe to
        run unattended:

        * **It pushes the ENTITY's undelivered rows, not just this job's.**
          A record the consumer called ``retryable`` (a master it depends on is
          not synced yet) stays ``STAGED`` and is re-offered by the NEXT run,
          which is a different job (AC-22-20). Nothing is lost and nothing needs
          a human to re-drive it.
        * **It never raises into the run.** The batch either delivers or it does
          not; a transport fault, an anchor 422 or an undecryptable credential
          comes back as ``error``/``errorCode`` on the summary, which the
          handler stamps onto the TASK (AC-22-19). Raising would fail a run that
          genuinely fetched and staged its data correctly.
        * **It reuses the SAME per-record delivery path as the review gate** -
          the sink's own verdicts, never inferred from an HTTP status.

        The review-gated ``approve`` path is untouched: it still claims the job,
        still pushes per batch, and the API path still stops at ``needs_review``.
        """
        summary: Dict[str, Any] = {
            "pushed": 0,
            "quarantined": 0,
            "pushFailures": [],
            "delivered": False,
            "autoPushed": True,
            "error": None,
            "errorCode": None,
            # ── chunk-level request accounting (fix/push-marks-per-chunk,
            # prod finding 2026-09-07: a lone 502 from Sorento's own nginx on
            # 1 of 25 chunk POSTs discarded a whole clean run - marks are now
            # per-chunk, so the run needs its own account of how many
            # requests it made and which one failed first) ─────────────────
            "requests": 0,
            "requestsFailed": 0,
            "firstFailure": None,
            # ── delete-push verdicts (plan 22 S3, AC-22-21) ──────────────────
            "deletedHandled": 0,
            "deleteFailures": [],
        }
        try:
            company = self.companies.get(tenant_id, company_id)
            sink = self.companies.sink_for_company(tenant_id, company, entity_type)
        except AutocountServiceError as exc:
            summary["error"] = exc.message
            return summary
        summary["sink"] = sink.name

        pending = self.staged.list_pending_for_entity(
            tenant_id, company_id, entity_type, job_type=AUTOCOUNT_SYNC
        )
        if not pending:
            return summary

        # Starvation guard (fix/push-marks-per-chunk, AC-style prod finding):
        # stamp every offered row NOW, committed BEFORE the sink is ever
        # called - so a permanently ``retryable`` head's OWN offer is
        # recorded even if the push that follows fails outright, and
        # ``list_pending_for_entity``'s ``last_offered_at`` NULLS FIRST
        # ordering gives a never-offered row priority on the very next run.
        self.staged.mark_offered(pending, now=datetime.now(timezone.utc))
        self.db.commit()

        # A reconcile delete intent carries NO canonical payload (op='delete',
        # models.py) - it must never reach `_rehydrate_pushable`, which would
        # misclassify it as "not pushable" (it has no `canonical_json`). Split
        # FIRST, route each half to its own sink call.
        upserts = [row for row in pending if row.op != STAGED_OP_DELETE]
        deletes = [row for row in pending if row.op == STAGED_OP_DELETE]

        if upserts and not self._auto_push_upserts(upserts, sink=sink, job_id=job_id, summary=summary):
            return summary
        if deletes and not self._auto_push_deletes(
            deletes,
            sink=sink,
            tenant_id=tenant_id,
            company_id=company_id,
            entity_type=entity_type,
            job_id=job_id,
            summary=summary,
        ):
            return summary

        self.db.commit()
        return summary

    def _account_failure(
        self, summary: Dict[str, Any], exc: BaseException, *, sink: EntitySink
    ) -> None:
        """Chunk-level push-failure accounting shared by every failure path
        (fix/push-marks-per-chunk, prod finding 2026-09-07): counts this as
        ONE request/failure and records the FIRST failure's status + a
        bounded snippet (``describe_consumer_failure`` style - status +
        message, never the request/URL) - later failures in the SAME
        ``auto_push`` call (a transient chunk fails, the loop continues, a
        LATER chunk then hits a stopping fault) still bump the counters but
        never overwrite the first one, matching ``firstFailure``'s name."""
        summary["requests"] = int(summary.get("requests") or 0) + 1
        summary["requestsFailed"] = int(summary.get("requestsFailed") or 0) + 1
        try:
            line, status, _detail = describe_consumer_failure(exc, sink=sink)
        except Exception:  # noqa: BLE001 - never let the describer break accounting
            line, status = str(exc)[:300], None
        if not summary.get("firstFailure"):
            summary["firstFailure"] = {"status": status, "message": line[:300]}
        if not summary.get("error"):
            summary["error"] = line[:2000]

    def _commit_chunk(self, summary: Dict[str, Any], *, sink: EntitySink) -> None:
        """COMMIT a chunk's marks, defensively (S3, review round 2). A real
        flush/commit failure (a NOT NULL violation, a constraint fault) puts
        SQLAlchemy's session into a state where every LATER statement raises
        ``PendingRollbackError`` unless something calls ``rollback()`` first
        - which would otherwise strand the caller (the run row itself could
        never be written). Rolls back, accounts the failure exactly like a
        chunk-level sink fault, and raises ``_ChunkCommitFailed`` so the
        caller's existing exception handling stops the push with a USABLE
        session, never a poisoned one."""
        try:
            self.db.commit()
        except Exception as exc:  # noqa: BLE001 - a commit fault must never poison the caller's session
            self.db.rollback()
            self._account_failure(summary, exc, sink=sink)
            raise _ChunkCommitFailed(str(exc)) from exc

    def _chunk_beat(self, job_id: str) -> Callable[[], None]:
        """The per-chunk heartbeat for a push (fix/job-lease-orphan-sweep).
        Called AFTER a chunk's own outcome is already durable (marked +
        committed on success, accounted on a chunk-level fault - see
        ``apply_chunk`` in both ``_auto_push_upserts``/``_auto_push_
        deletes``), never before - the fence below can only stop the NEXT
        chunk, so it must never race the current one's own commit.

        Best-effort on failure (a beat that errors is logged, the push
        continues); a beat that lands on ZERO rows is a FENCE - the job is
        re-read fresh and, if it is no longer RUNNING (swept as an orphan,
        aborted), ``JobLeaseLost`` stops the push at this chunk boundary
        (S5). A 0-row beat on a still-RUNNING row (Postgres ``SKIP LOCKED``)
        is not a fence."""
        jid = str(job_id)

        def beat() -> None:
            try:
                alive = self.jobs.heartbeat(jid)
            except Exception:  # noqa: BLE001 - advisory, never fails the push
                logger.warning("auto_push: heartbeat for job %s failed", jid, exc_info=True)
                return
            if alive:
                return
            status = self.jobs.fresh_status(jid)
            # The lost lease is the sweep's own verdict: ``failed``. An
            # operator ABORT mid-push is left to the run's existing abort
            # bookkeeping (checked between pages / before finish, never
            # mid-chunk - pre-existing behaviour); PENDING (a push driven
            # before its claim), DONE (a push re-driven under a finished job,
            # as the round-6b suite does) or an unknown id are still ours.
            if status == JOB_FAILED:
                raise JobLeaseLost(jid)

        return beat

    def _auto_push_upserts(
        self,
        pending: List[AcStagedRecord],
        *,
        sink: EntitySink,
        job_id: str,
        summary: Dict[str, Any],
    ) -> bool:
        """The upsert half of ``auto_push``. Marks + COMMITS per CHUNK as the
        sink resolves each one (fix/push-marks-per-chunk, prod finding
        2026-09-07: one ``write_batch`` call for up to 5,000 rows applied NO
        verdict at all on a single chunk-level fault, so a lone Sorento nginx
        502 discarded 24 other already-delivered chunks and the next run
        re-offered everything). Returns ``False`` only on a STOPPING fault
        (``summary["error"]`` already set) - the caller skips the delete half
        and the redundant final commit, same as before this method was
        split out. A TRANSIENT chunk fault that exhausted its retries
        (``SorentoSink._post_with_retry``) does NOT stop the push - that
        chunk's rows stay STAGED and every other chunk still resolves; this
        method still returns ``True``."""
        rows, records, failures = self._rehydrate_pushable(pending)
        # S4 (review round 2, defence in depth): a ``dict`` keyed by
        # ``source_ref`` keeps only the LAST row for a duplicate ref, so a
        # successful push marked one of the two rows and left the other a
        # ghost, re-offered forever. ``records``/``chunk_results`` repeat a
        # duplicated ref once PER physical row (``_rehydrate_pushable`` is
        # 1:1 with ``pending``, never deduped), so popping one row per
        # occurrence keeps every occurrence matched to its OWN row.
        by_ref: Dict[str, List[AcStagedRecord]] = {}
        for row in rows:
            by_ref.setdefault(row.source_ref, []).append(row)
        beat = self._chunk_beat(job_id)

        def apply_chunk(
            chunk_records: Sequence[CanonicalRecord],
            chunk_results: Optional[List[WriteResult]],
            error: Optional[BaseException],
        ) -> None:
            if error is not None:
                # A chunk-level fault (a transient 5xx that exhausted its
                # retries) - nothing of ours to commit for THIS chunk, but
                # the attempt still took real time (backoff sleeps included),
                # so it still beats (fix/job-lease-orphan-sweep) exactly like
                # a delivered chunk does.
                self._account_failure(summary, error, sink=sink)
                beat()
                return
            summary["requests"] = int(summary.get("requests") or 0) + 1
            chunk_pushed: List[AcStagedRecord] = []
            chunk_quarantined: List[AcStagedRecord] = []
            for record, result in zip(chunk_records, chunk_results or []):
                ref = getattr(record, "source_ref", "")
                bucket = by_ref.get(ref)
                if not bucket:
                    continue
                row = bucket.pop(0)
                if result.ok:
                    chunk_pushed.append(row)
                    summary["delivered"] = summary["delivered"] or result.delivered
                    continue
                failures.append({"sourceRef": row.source_ref, "error": result.message})
                #     !!  RETRY ``retryable``; QUARANTINE ``failed``.  !!
                # A ``retryable`` verdict means nothing was written and a
                # dependency is missing, so the row stays STAGED and the next
                # run re-offers it (AC-22-20). A ``failed`` verdict means the
                # DATA was rejected - re-offering it re-fails on every run
                # forever and pins the task permanently red (seen live: a
                # customer code already linked to another source in Sorento).
                # Quarantining matches D13's "FAILED is never pushable".
                if result.outcome and result.outcome != "retryable":
                    chunk_quarantined.append(row)
            if chunk_pushed:
                self.staged.mark(
                    chunk_pushed, status=STAGED_PUSHED, pushed_at=datetime.now(timezone.utc)
                )
            if chunk_quarantined:
                self.staged.mark(chunk_quarantined, status=STAGED_FAILED)
            if chunk_pushed or chunk_quarantined:
                # COMMIT per chunk - not the caller's final commit - so a
                # LATER chunk's fault (or a lost lease) can never undo THIS
                # chunk's already-delivered rows. ``_commit_chunk`` (S3)
                # rolls back and stops the push cleanly if the commit ITSELF
                # fails, rather than leaving the session unusable.
                self._commit_chunk(summary, sink=sink)
            summary["pushed"] = int(summary.get("pushed") or 0) + len(chunk_pushed)
            summary["quarantined"] = int(summary.get("quarantined") or 0) + len(chunk_quarantined)
            # Liveness (fix/job-lease-orphan-sweep): beat ONLY AFTER this
            # chunk's marks are committed above - JobLeaseLost (raised by
            # ``beat()``) must stop the push AFTER a chunk is durable, never
            # instead of committing it.
            beat()

        try:
            # Sequencing (fix/push-marks-per-chunk + fix/job-lease-orphan-
            # sweep): ``auto_push`` runs INSIDE the caller's
            # (``run_autocount_sync``) still-open session. By the time this
            # method runs, that caller's own watermark/cursor advance AND
            # this run's starvation-guard offer stamp (``mark_offered``) are
            # both ALREADY COMMITTED (S10/S2 review BLOCKER 1 no longer
            # applies - the pre-push commit moved earlier, before the sink is
            # ever called) - so there is nothing of the CALLER's left
            # uncommitted here to protect with a bare try/except. What
            # matters at THIS level is narrower: the sink call below writes
            # NOTHING local of its own (it is a network round-trip; the only
            # local writes are the ``staged.mark(...)`` calls inside
            # ``apply_chunk``, each already committed by the time this
            # ``try`` could ever roll it back), so a fault here - a chunk
            # exhausting its retries, an anchor error, a lost lease - never
            # needs a rollback to protect anything: every already-applied
            # chunk stands, and the still-open session carries no partial
            # write of its own past that point.
            if records and hasattr(sink, "write_batch"):
                kwargs: Dict[str, Any] = {}
                if "on_chunk" in inspect.signature(sink.write_batch).parameters:
                    kwargs["on_chunk"] = apply_chunk
                    sink.write_batch(records, request_id=str(job_id), **kwargs)
                else:
                    # No per-chunk callback on this sink - one synthetic
                    # "chunk" covering the whole batch (the old all-or-nothing
                    # shape, still correct for a sink that cannot report less).
                    apply_chunk(records, sink.write_batch(records, request_id=str(job_id)), None)
            elif records:
                # Per-record path (the slice-1 logging no-op sink) - one
                # synthetic chunk per record, so a raise mid-loop still keeps
                # every already-written row PUSHED and committed.
                for row, record in zip(rows, records):
                    result = sink.write(record, request_id=f"{job_id}:{row.id}")
                    apply_chunk([record], [result], None)
        except JobLeaseLost as exc:
            # The job is no longer ours (swept as an orphan, or aborted) -
            # every chunk ``apply_chunk`` already ran for is durable; the
            # caller bails without overwriting the terminal status.
            summary["leaseLost"] = True
            summary["error"] = str(exc)
            return False
        except _ChunkCommitFailed:
            # Already rolled back and accounted inside apply_chunk
            # (S3) - stop the push, session is usable.
            return False
        except SinkAnchorError as exc:
            # TASK-level, never per record (Appendix A6): the company anchor is
            # wrong, so no record was even looked at. Everything stays STAGED.
            self._account_failure(summary, exc, sink=sink)
            summary["error"] = exc.sorento_message
            summary["errorCode"] = exc.code
            return False
        except SorentoSinkError as exc:
            self._account_failure(summary, exc, sink=sink)
            return False
        except Exception as exc:  # noqa: BLE001 - a run must never die on delivery
            logger.exception("autocount auto-push failed for job %s", job_id)
            self._account_failure(summary, exc, sink=sink)
            return False

        summary["pushFailures"] = failures
        if failures and not summary.get("error"):
            # Repeated delivery failures must surface on the task, never
            # silently (AC-22-19) - the first one names itself.
            summary["error"] = str(failures[0].get("error") or "")[:2000]
        return True

    def _auto_push_deletes(
        self,
        pending: List[AcStagedRecord],
        *,
        sink: EntitySink,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        job_id: str,
        summary: Dict[str, Any],
    ) -> bool:
        """The delete half of ``auto_push`` (plan 22 S3, AC-22-21). Routes
        ``op='delete'`` staged rows to the sink's ``delete_batch`` (both
        ``SorentoSink`` and the ``LoggingSink`` no-op carry one); per-ref
        verdict ``deleted|deactivated|not_found`` marks the row PUSHED and
        drops its row-hash (a later re-appearance at source stages as a fresh
        add); ``failed`` quarantines it (D13's rule, mirrored for deletes); no
        verdict at all (an unrecognised outcome, or a sink with no delete
        support) leaves the row STAGED to retry next run - the same
        ``retryable`` posture an upsert gets.

        Marks + COMMITS per CHUNK exactly like the upsert half
        (fix/push-marks-per-chunk) - a fault on a LATER deletions chunk can
        never undo an earlier one's already-handled refs; each chunk beats
        (fix/job-lease-orphan-sweep) AFTER its own marks are committed.
        Returns ``False`` only on a STOPPING fault, same contract as the
        upsert half."""
        # S4 (review round 2, defence in depth - mirrors the upsert half): a
        # ``dict`` keyed by ``source_ref`` would keep only the LAST row for a
        # duplicate ref. ``refs``/``chunk_refs`` repeat a duplicated ref once
        # PER physical row (built straight from ``pending``, never deduped),
        # so popping one row per occurrence keeps every occurrence matched
        # to its OWN row.
        by_ref: Dict[str, List[AcStagedRecord]] = {}
        for row in pending:
            by_ref.setdefault(row.source_ref, []).append(row)
        beat = self._chunk_beat(job_id)

        def apply_chunk(
            chunk_refs: List[str],
            chunk_records: Optional[List[Dict[str, Any]]],
            error: Optional[BaseException],
        ) -> None:
            if error is not None:
                self._account_failure(summary, error, sink=sink)
                beat()
                return
            summary["requests"] = int(summary.get("requests") or 0) + 1
            by_verdict = {str(r.get("source_ref") or ""): r for r in (chunk_records or [])}
            handled: List[AcStagedRecord] = []
            failed: List[AcStagedRecord] = []
            for ref in chunk_refs:
                bucket = by_ref.get(ref)
                if not bucket:
                    continue
                row = bucket.pop(0)
                outcome = str((by_verdict.get(ref) or {}).get("outcome") or "")
                if outcome in ("deleted", "deactivated", "not_found"):
                    handled.append(row)
                elif outcome == "failed":
                    failed.append(row)
                # else: no / unrecognised verdict → leave STAGED, retry next run.
            if handled:
                self.staged.mark(handled, status=STAGED_PUSHED, pushed_at=datetime.now(timezone.utc))
            if failed:
                self.staged.mark(failed, status=STAGED_FAILED)
            if handled:
                RowHashRepository(self.db).delete_many(
                    tenant_id, company_id, entity_type, [row.source_ref for row in handled]
                )
            if handled or failed:
                # ONE commit per chunk - the marks AND the row-hash drop
                # together (S7, review round 3): two separate commits meant
                # a failure in the SECOND one double-accounted the failure
                # (``_account_failure`` ran twice for one POST) while
                # rolling back only the hash deletion - the PUSHED marks
                # from the FIRST commit stayed durable, an inconsistent
                # half-applied chunk. ``_commit_chunk`` (S3) still rolls
                # back and stops the push cleanly if THIS commit fails.
                self._commit_chunk(summary, sink=sink)
            summary["deletedHandled"] = int(summary.get("deletedHandled") or 0) + len(handled)
            if failed:
                summary["deleteFailures"] = (summary.get("deleteFailures") or []) + [
                    {"sourceRef": row.source_ref, "error": "the consumer rejected this delete"}
                    for row in failed
                ]
            # Liveness (fix/job-lease-orphan-sweep): beat only after this
            # chunk's marks (and the row-hash drop) are committed above.
            beat()

        refs = [row.source_ref for row in pending]
        try:
            if hasattr(sink, "delete_batch"):
                kwargs: Dict[str, Any] = {}
                if "on_chunk" in inspect.signature(sink.delete_batch).parameters:
                    kwargs["on_chunk"] = apply_chunk
                    sink.delete_batch(refs, **kwargs)
                else:
                    result = sink.delete_batch(refs)
                    apply_chunk(refs, (result or {}).get("records") or [], None)
            # else: no delete support on this sink at all - every ref stays
            # STAGED, same posture as a `retryable` upsert.
        except JobLeaseLost as exc:
            summary["leaseLost"] = True
            summary["error"] = str(exc)
            return False
        except _ChunkCommitFailed:
            # Already rolled back and accounted inside apply_chunk
            # (S3) - stop the push, session is usable.
            return False
        except SinkAnchorError as exc:
            self._account_failure(summary, exc, sink=sink)
            summary["error"] = exc.sorento_message
            summary["errorCode"] = exc.code
            return False
        except SorentoSinkError as exc:
            self._account_failure(summary, exc, sink=sink)
            return False
        except Exception as exc:  # noqa: BLE001 - a run must never die on delivery
            logger.exception("autocount auto-push delete failed for %s/%s", company_id, entity_type)
            self._account_failure(summary, exc, sink=sink)
            return False

        if summary.get("deleteFailures") and not summary.get("error"):
            summary["error"] = summary["deleteFailures"][0]["error"]
        return True

    def preview(self, tenant_id: str, job_id: str) -> Dict[str, Any]:
        """Ask the consumer what approving WOULD do, writing nothing (AC-14-20/21).

        The prediction is Sorento's own ``?dry_run=true`` resolution rolled back
        - adoption matching included - NEVER a local reconstruction (AC-14-21).
        This never claims the job or mutates any row: it is a read plus one
        dry-run call, so it is safe to call repeatedly before approval.

        For a logging-sink company there is no consumer to ask, so it returns a
        clear "nothing to preview" shape rather than erroring.
        """
        job = self._job(tenant_id, job_id)
        company_id = self._company_id_for(job)
        company = self.companies.get(tenant_id, company_id)
        entity_type = self._entity_type_for(job)
        sink = self.companies.sink_for_company(tenant_id, company, entity_type)

        if not hasattr(sink, "dry_run"):
            # Two ways to land on a dry-run-less sink: the company is genuinely
            # configured to log, OR it targets Sorento but Sorento does not
            # ingest THIS entity yet (a document - GRN/PO/…). The second is not a
            # misconfiguration, so it gets its own honest explanation instead of
            # the misleading "no consumer configured".
            if company.sink_impl == SINK_IMPL_SORENTO and not sorento_supports_entity(
                entity_type
            ):
                reason = (
                    f"Sorento does not yet ingest '{entity_type}' records - it "
                    f"currently accepts {sorento_supported_entities_label()} "
                    "only. There is nothing to dry-run; these records are "
                    "staged and logged, not delivered to Sorento."
                )
            else:
                reason = (
                    "No consumer is configured for this company, so there is "
                    "nothing to preview."
                )
            return {"previewable": False, "sink": sink.name, "reason": reason}

        pending = self.staged.list_pending_for_job(tenant_id, company_id, job_id)
        _rows, records, _failures = self._rehydrate_pushable(pending)
        try:
            # Liveness (fix/job-lease-orphan-sweep): this gate runs INSIDE a
            # real job (unlike EtlService's activation preview, which is a
            # plain request with no job to beat for) - a large batch's dry
            # run is the same multi-minute stretch a real push is, so it
            # gets the SAME per-chunk heartbeat, zero-arg shape (dry_run
            # never marks/commits anything, so there is nothing to sequence
            # the beat after).
            dry_run_kwargs: Dict[str, Any] = {}
            if "on_chunk" in inspect.signature(sink.dry_run).parameters:
                dry_run_kwargs["on_chunk"] = self._chunk_beat(job_id)
            result = sink.dry_run(records, **dry_run_kwargs)
        except (SorentoSinkError, httpx.HTTPError) as exc:
            # The gate must SHOW this and refuse to offer approval (plan §D4) -
            # an operator must never approve blind. Nothing was written. The
            # message quotes what the consumer said (or why it was
            # unreachable - the sink does not wrap transport faults) through
            # the SAME helper the activation preview uses, so both gates word
            # a failure identically (prod 2026-09-06).
            line, status, detail = describe_consumer_failure(exc, sink=sink)
            logger.warning(
                "autocount approve-gate dry run failed: company_id=%s job_id=%s status=%s detail=%s",
                company_id, job_id, status, detail,
            )
            raise PreviewFailed(
                "The dry run against the consumer failed, so no prediction is "
                "available and this batch cannot be approved yet. Nothing was "
                f"written - resolve the consumer error first. {line}"
            ) from exc

        return {
            "previewable": True,
            "sink": sink.name,
            "summary": result.summary,
            "predictions": [
                {
                    "sourceRef": p.source_ref,
                    "outcome": p.outcome,
                    "entityId": p.entity_id,
                    "diff": p.diff,
                    "errors": p.errors,
                    "changesLiveData": p.changes_live_data,
                }
                for p in result.predictions
            ],
        }

    def approve(
        self, tenant_id: str, job_id: str, *, actor_user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Push every STAGED record through the configured sink, exactly once."""
        job = self._job(tenant_id, job_id)
        company_id = self._company_id_for(job)

        if not self._claim_review(job):
            # Lost the race (or the job was never in review).
            self.db.refresh(job)
            if job.status == JOB_DONE:
                # Second click of a completed approval: a NO-OP returning the
                # original result. Records were pushed exactly once.
                return dict(job.result_json or {})
            if job.status == JOB_RUNNING:
                # The winner is mid-push. Report progress; never push in parallel.
                return {"status": JOB_RUNNING, "message": "This batch is being pushed."}
            raise NotAwaitingApproval(
                "This sync is not awaiting approval, so there is nothing to approve."
            )

        # The claim moved needs_review → running. From here ANY failure must
        # return the job to needs_review, or it strands in ``running`` forever
        # (non-terminal so the pruner never reaps it, no longer ``needs_review``
        # so the claim can never win again). Sink RESOLUTION runs AFTER the claim
        # - deliberately, so the double-click no-op above returns the cached
        # result WITHOUT touching a connection that may since have been deleted -
        # so a resolution failure (no target, undecryptable creds, unknown impl)
        # must release the claim, then propagate its own clean error.
        try:
            company = self.companies.get(tenant_id, company_id)
            entity_type = self._entity_type_for(job)
            sink = self.companies.sink_for_company(tenant_id, company, entity_type)
        except Exception as exc:  # noqa: BLE001
            self._release_claim(job, [], exc)
            raise

        pending = self.staged.list_pending_for_job(tenant_id, company_id, job_id)

        if hasattr(sink, "write_batch"):
            pushed, failures, delivered = self._push_batch(job, sink, pending)
        else:
            pushed, failures, delivered = self._push_per_record(job, sink, pending)

        now = datetime.now(timezone.utc)
        self.staged.mark(pushed, status=STAGED_PUSHED, pushed_at=now)

        run = self.runs.get_for_job(tenant_id, company_id, job_id)
        if run is not None:
            run.pushed_count = len(pushed)

        summary = dict(job.result_json or {})
        summary.update(
            {
                "approved": True,
                "approvedAt": now.isoformat().replace("+00:00", "Z"),
                "approvedBy": actor_user_id,
                "pushed": len(pushed),
                "pushFailures": failures,
                "sink": sink.name,
                # Honest per sink (AC-14-41): the logging sink DELIVERS NOTHING,
                # a real consumer sink reports actual delivery. Never inferred
                # from ``ok`` alone.
                "delivered": delivered,
            }
        )
        if sink.name == SINK_IMPL_LOGGING:
            # The slice-1 sink is a tagged seam, not a consumer - say so.
            summary["sinkNote"] = (
                "Records were accepted by the slice-1 logging sink; no consumer "
                "is wired for this company, so nothing left the ESB."
            )
        self.jobs.finish(job, status=JOB_DONE, result=summary)
        self.db.commit()

        record_activity(
            self.db,
            tenant_id=tenant_id,
            operation=f"approve {job.id}",
            status=ACTIVITY_SUCCESS if not failures else ACTIVITY_ERROR,
            external_ref=company_id,
            response={"pushed": len(pushed), "failures": len(failures)},
        )
        return summary

    def discard(
        self, tenant_id: str, job_id: str, *, actor_user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Close the job WITHOUT pushing. Staged rows are marked discarded, not
        deleted - the raw payloads stay for audit and retroactive re-mapping
        (AC-13-07)."""
        job = self._job(tenant_id, job_id)
        company_id = self._company_id_for(job)

        if not self._claim_review(job):
            self.db.refresh(job)
            if job.status == JOB_DONE:
                return dict(job.result_json or {})
            raise NotAwaitingApproval(
                "This sync is not awaiting approval, so there is nothing to discard."
            )

        pending = self.staged.list_pending_for_job(tenant_id, company_id, job_id)
        self.staged.mark(pending, status=STAGED_DISCARDED)

        summary = dict(job.result_json or {})
        summary.update(
            {
                "approved": False,
                "discarded": len(pending),
                "discardedBy": actor_user_id,
                "pushed": 0,
            }
        )
        self.jobs.finish(job, status=JOB_DONE, result=summary)
        self.db.commit()
        return summary
