"""Sync service — trigger a run, read what is staged, approve or discard.

Slice 1 is **MANUAL trigger only**. No scheduling, no beat entry: a scheduled
pull that nobody has yet watched approve a single batch is a data-integrity risk
running unattended. Scheduling lands once the pipeline has been exercised by
hand (plan §9).

**Approval is idempotent (AC-13-13).** The mechanism is an ATOMIC guarded status
claim on the job row — the same ``UPDATE … WHERE status=?`` the import engine
and storage migration use — so a double-click, a retry or a replay races into
exactly ONE winner. The loser does not error and does not push: it returns the
original result, because from the operator's point of view the approval DID
happen and a scary error on the second click of a successful action is its own
kind of bug.
"""
from __future__ import annotations

import logging
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
from ..models import (
    STAGED_DISCARDED,
    STAGED_PUSHED,
    AcStagedRecord,
    AcSyncRun,
)
from ..repositories import (
    EntityConfigRepository,
    StagedRecordRepository,
    SyncRunRepository,
)
from ..sinks import SINK_LOGGING, WriteResult, sink_for
from ..sync import AUTOCOUNT_SYNC
from .company_service import AutocountServiceError, CompanyService

logger = logging.getLogger("foundryx.autocount")

# Canonical entity → its canonical model. Slice 1 is GRN only.
CANONICAL_MODELS = {ENTITY_GOODS_RECEIVED_NOTE: CanonicalGrn}


class EntityNotConfigured(AutocountServiceError):
    pass


class JobNotFound(AutocountServiceError):
    pass


class NotAwaitingApproval(AutocountServiceError):
    pass


class PushFailed(AutocountServiceError):
    """The push raised part-way through. The batch is back in ``needs_review``
    and is re-approvable — it is NOT stranded and NOT silently half-delivered."""


class SyncService:
    def __init__(self, db: Session):
        self.db = db
        self.companies = CompanyService(db)
        self.configs = EntityConfigRepository(db)
        self.staged = StagedRecordRepository(db)
        self.runs = SyncRunRepository(db)
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
        """"Sync now" — MANUAL only this slice."""
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
        """Tenant-scoped job lookup, restricted to OUR job type — a job id from
        another feature must never be steerable into this service."""
        job = self.jobs.get(tenant_id, job_id)
        if job is None or job.type != AUTOCOUNT_SYNC:
            raise JobNotFound("That sync job was not found.")
        return job

    def _company_id_for(self, job: BackgroundJob) -> str:
        return str((job.payload_json or {}).get("companyId") or "")

    def staged_records(
        self, tenant_id: str, job_id: str
    ) -> Tuple[BackgroundJob, List[AcStagedRecord]]:
        job = self._job(tenant_id, job_id)
        company_id = self._company_id_for(job)
        # Company scope comes from the JOB's payload, never from client input —
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

    # ── approve / discard ────────────────────────────────────────────────────

    def _claim_review(self, job: BackgroundJob) -> bool:
        """Atomically claim ``needs_review`` → ``running``. Exactly one winner.

        This IS the idempotency mechanism (AC-13-13) — not a flag check, which
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
        that and ``finish`` would strand the job forever — non-terminal so the
        pruner never reaps it, and no longer ``needs_review`` so ``_claim_review``
        can never succeed again. No re-approve, no retry, an approved batch dead
        in the water. Today only ``model(**row.canonical_json)`` can raise, but
        the moment a real network sink lands, ONE timeout does this.

        **Returned to ``needs_review``, not finished ``failed``** — because the
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
            # Re-attach by id — the rollback expired the objects held above.
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

        pending = self.staged.list_pending_for_job(tenant_id, company_id, job_id)
        sink = sink_for(SINK_LOGGING)
        pushed: List[AcStagedRecord] = []
        failures: List[Dict[str, Any]] = []

        try:
            for row in pending:
                model = CANONICAL_MODELS.get(row.entity_type)
                if model is None or not row.canonical_json:
                    # A FAILED row has no canonical payload by design (D13); it
                    # can never be pushed, and reaching here means it was
                    # mis-selected.
                    failures.append(
                        {"sourceRef": row.source_ref, "error": "not pushable"}
                    )
                    continue
                record = model(**row.canonical_json)
                # Deterministic request id from (job, staged row) — a replay at a
                # lower layer maps to the SAME id, which is what a real sink needs
                # to deduplicate on its side.
                result: WriteResult = sink.write(record, request_id=f"{job.id}:{row.id}")
                if result.ok:
                    pushed.append(row)
                else:
                    failures.append(
                        {"sourceRef": row.source_ref, "error": result.message}
                    )
        except Exception as exc:  # noqa: BLE001
            self._release_claim(job, pushed, exc)
            raise PushFailed(
                "The push failed part-way through, so this batch was returned to "
                "review. Records already delivered will not be sent again — "
                "approve it again to push the rest."
            ) from exc

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
                # The slice-1 sink DELIVERS NOTHING. Saying so explicitly is the
                # difference between a tagged seam and a mock pretending to work.
                "delivered": False,
                "sinkNote": (
                    "Records were accepted by the slice-1 logging sink; no consumer "
                    "is wired yet, so nothing left the ESB."
                ),
            }
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
        deleted — the raw payloads stay for audit and retroactive re-mapping
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
