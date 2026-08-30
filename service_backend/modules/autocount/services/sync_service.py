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

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.jobs.repository import BackgroundJobRepository
from app.jobs.service import JobService
from app.models.background_job import (
    JOB_DONE,
    JOB_NEEDS_REVIEW,
    JOB_RUNNING,
    BackgroundJob,
)

from ..activity import ACTIVITY_ERROR, ACTIVITY_SUCCESS, record_activity
from ..canonical.grn import CanonicalGrn, ENTITY_GOODS_RECEIVED_NOTE
from ..canonical.masters import (
    ENTITY_CUSTOMER,
    ENTITY_SUPPLIER,
    CanonicalCustomer,
    CanonicalSupplier,
)
from ..models import (
    SINK_IMPL_LOGGING,
    SINK_IMPL_SORENTO,
    STAGED_DISCARDED,
    STAGED_PUSHED,
    AcStagedRecord,
    AcSyncRun,
)
from ..repositories import (
    CompanyRepository,
    EntityConfigRepository,
    StagedRecordRepository,
    SyncJobRepository,
    SyncRunRepository,
)
from ..sinks import EntitySink, WriteResult
from ..sinks_sorento import SinkAnchorError, SorentoSinkError, sorento_supports_entity
from ..sync import AUTOCOUNT_SYNC
from .company_service import AutocountServiceError, CompanyService

logger = logging.getLogger("foundryx.autocount")

# Canonical entity → its canonical model, so a staged record's ``canonical_json``
# can be rehydrated into the typed shape the sink needs (``sink_payload`` /
# ``source_ref``). Hop 2 adds the two master shapes beside slice 1's GRN.
CANONICAL_MODELS = {
    ENTITY_GOODS_RECEIVED_NOTE: CanonicalGrn,
    ENTITY_SUPPLIER: CanonicalSupplier,
    ENTITY_CUSTOMER: CanonicalCustomer,
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
            "pushFailures": [],
            "delivered": False,
            "autoPushed": True,
            "error": None,
            "errorCode": None,
        }
        try:
            company = self.companies.get(tenant_id, company_id)
            sink = self.companies.sink_for_company(tenant_id, company, entity_type)
        except AutocountServiceError as exc:
            summary["error"] = exc.message
            return summary
        summary["sink"] = sink.name

        pending = self.staged.list_pending_for_entity(tenant_id, company_id, entity_type)
        if not pending:
            return summary

        rows, records, failures = self._rehydrate_pushable(pending)
        pushed: List[AcStagedRecord] = []
        try:
            if hasattr(sink, "write_batch"):
                results = sink.write_batch(records, request_id=str(job_id)) if records else []
            else:
                results = [
                    sink.write(record, request_id=f"{job_id}:{row.id}")
                    for row, record in zip(rows, records)
                ]
            for row, result in zip(rows, results):
                if result.ok:
                    pushed.append(row)
                    summary["delivered"] = summary["delivered"] or result.delivered
                else:
                    # A ``retryable`` verdict leaves the row STAGED - the next
                    # run re-offers it once its dependency lands (AC-22-20).
                    failures.append({"sourceRef": row.source_ref, "error": result.message})
        except SinkAnchorError as exc:
            # TASK-level, never per record (Appendix A6): the company anchor is
            # wrong, so no record was even looked at. Everything stays STAGED.
            self.db.rollback()
            summary["error"] = exc.sorento_message
            summary["errorCode"] = exc.code
            return summary
        except SorentoSinkError as exc:
            self.db.rollback()
            summary["error"] = str(exc)[:2000]
            return summary
        except Exception as exc:  # noqa: BLE001 - a run must never die on delivery
            self.db.rollback()
            logger.exception("autocount auto-push failed for job %s", job_id)
            summary["error"] = f"The push failed before the consumer resolved it: {exc}"[:2000]
            return summary

        self.staged.mark(pushed, status=STAGED_PUSHED, pushed_at=datetime.now(timezone.utc))
        summary["pushed"] = len(pushed)
        summary["pushFailures"] = failures
        if failures:
            # Repeated delivery failures must surface on the task, never
            # silently (AC-22-19) - the first one names itself.
            summary["error"] = str(failures[0].get("error") or "")[:2000]
        return summary

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
                    "currently accepts suppliers and customers only. There is "
                    "nothing to dry-run; these records are staged and logged, "
                    "not delivered to Sorento."
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
            result = sink.dry_run(records)
        except SorentoSinkError as exc:
            # The gate must SHOW this and refuse to offer approval (plan §D4) -
            # an operator must never approve blind. Nothing was written.
            raise PreviewFailed(
                "The dry run against the consumer failed, so no prediction is "
                "available and this batch cannot be approved yet. Nothing was "
                "written - resolve the consumer error first."
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
