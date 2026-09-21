"""``PreviewJobService`` - request / claim / poll / cancel for the
``autocount_source_preview`` background job (sprint-5/11 S4, AC-11-21..31).

Business logic only - the HTTP layer (``routers/http.py``, ``routers/
companies.py``, ``routers/previews.py``) stays thin: create/enqueue, or read
back the wire shape this service already built. The ACTUAL extraction never
runs here - ``preview_job.run_autocount_source_preview`` (the registered job
handler) owns that, reusing ``EtlService.preview_http``/``preview_task``
unchanged (D5, R3).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import settings
from app.jobs.registry import handler_for
from app.jobs.service import JobService, close_module_bookkeeping
from app.models.background_job import (
    JOB_ABORTED,
    JOB_DONE,
    JOB_FAILED,
    JOB_PENDING,
    JOB_RUNNING,
    JOB_TERMINAL_STATUSES,
    BackgroundJob,
)

from ..models import AcEntityConfig
from ..preview_job import PREVIEW_JOB_TYPE, _release_claim, run_autocount_source_preview
from ..repositories import CompanyRepository, EntityConfigRepository
from ..schemas import PreviewJobOut, PreviewJobProgressOut, PreviewJobTaskErrorOut
from .company_service import CompanyNotFound

logger = logging.getLogger("foundryx.autocount")

PREVIEW_SCOPE_SAMPLE = "sample"
PREVIEW_SCOPE_FULL = "full"

# sprint-5/11 review round 1 (S1) - the SAME two keys each scope's own start
# route already requires (``routers/http.py``'s ``companies.manage``,
# ``routers/companies.py``'s ``sync.run`` for the full-scope preview route) -
# the poll route's own withheld-``result`` gate reuses them rather than
# inventing a third key.
SAMPLE_START_PERMISSION = "autocount.companies.manage"
FULL_START_PERMISSION = "autocount.sync.run"

# AC-11-22/27 - the wire status vocabulary translation. The backend's own
# statuses (``app/models/background_job.py``) are ``pending/running/
# needs_review/done/failed/aborted``; the FE's ``AutocountPreviewJobStatus``
# is ``queued/running/done/failed/cancelled``. ``pending`` -> ``queued`` and
# ``aborted`` -> ``cancelled`` are the only two that differ.
_WIRE_STATUS = {
    JOB_PENDING: "queued",
    JOB_RUNNING: "running",
    JOB_DONE: "done",
    JOB_FAILED: "failed",
    JOB_ABORTED: "cancelled",
}


def wire_status(backend_status: str) -> str:
    return _WIRE_STATUS.get(backend_status, backend_status)


class PreviewJobService:
    def __init__(self, db: Session):
        self.db = db
        self.jobs = JobService(db)
        self.configs = EntityConfigRepository(db)
        self.companies = CompanyRepository(db)

    # ── start (sample / full) ────────────────────────────────────────────────

    def start_sample(
        self,
        tenant_id: str,
        *,
        company_id: str,
        entity_type: str,
        connection_id: str,
        path: str,
        distinct_of: Optional[list] = None,
        lookups: Optional[list] = None,
        combine: Optional[Dict[str, Any]] = None,
        transport: Any = None,
    ) -> Tuple[str, str]:
        """AC-11-21/22 - the Source tab's Test. Validates BEFORE any job row
        exists (never queued-then-failed); returns ``(jobId, wireStatus)``.

        sprint-5/11 review round 1 (S5) - a ``companyId`` is OPTIONAL here
        (a bare connection/path probe with no task context passes none), but
        when one IS given it must be tenant-scoped BEFORE a job is minted -
        otherwise a foreign ``companyId`` sails straight through into the
        payload and only fails later, INSIDE the job (a 202 the caller has
        to poll to discover was never going to work), instead of the SAME
        uniform 404 every other autocount route gives a cross-tenant id."""
        from .etl_service import EtlService

        if company_id and self.companies.get(tenant_id, company_id) is None:
            raise CompanyNotFound("Company not found.")
        EtlService(self.db).validate_http_preview_request(
            tenant_id, connection_id, path, lookups=lookups,
        )
        request = {
            "connectionId": connection_id,
            "path": path,
            "distinctOf": distinct_of,
            "lookups": lookups,
            "combine": combine,
        }
        return self._start(
            tenant_id,
            scope=PREVIEW_SCOPE_SAMPLE,
            company_id=company_id,
            entity_type=entity_type,
            request=request,
            transport=transport,
        )

    def start_full(
        self, tenant_id: str, *, company_id: str, entity_type: str,
    ) -> Tuple[str, str]:
        """AC-11-21/22 - Review & Activate's Run preview. Validates BEFORE
        any job row exists (a never-configured task still refuses
        SYNCHRONOUSLY, unchanged); returns ``(jobId, wireStatus)``."""
        from .etl_service import EtlService

        EtlService(self.db).validate_task_previewable(tenant_id, company_id, entity_type)
        return self._start(
            tenant_id,
            scope=PREVIEW_SCOPE_FULL,
            company_id=company_id,
            entity_type=entity_type,
            request={},
        )

    def _start(
        self,
        tenant_id: str,
        *,
        scope: str,
        company_id: str,
        entity_type: str,
        request: Dict[str, Any],
        transport: Any = None,
    ) -> Tuple[str, str]:
        handler_for(PREVIEW_JOB_TYPE)  # loud if this module never registered

        config = None
        if company_id and entity_type:
            config = self.configs.get(tenant_id, company_id, entity_type)
            if config is not None and config.preview_job_id:
                job = self._get_job(tenant_id, config.preview_job_id)
                if job is not None and job.status not in JOB_TERMINAL_STATUSES:
                    # AC-11-23 - re-attach: a second click while a preview is
                    # already claimed shares the winner's job id, never a
                    # second walk.
                    return job.id, wire_status(job.status)
                # sprint-5/11 S4 review round 1 (B1) - a dangling claim: EITHER
                # the job row is gone entirely (should never happen under the
                # invariant every terminal path releases it), OR the job is
                # ALREADY terminal (done/failed/cancelled) but its own
                # release never landed on this claim - a stale ``cancel()``
                # commit ordering, a crash, or any other gap. Either way the
                # claim must never block the next Test forever: release it
                # defensively and fall through to start a fresh job.
                config.preview_job_id = None
                self.db.commit()

        payload = {
            "scope": scope,
            "companyId": company_id or "",
            "entityType": entity_type or "",
            "request": request,
        }

        if config is not None:
            job, won = self._claim_and_create(tenant_id, config, payload)
            if not won:
                return job.id, wire_status(job.status)
        else:
            job = BackgroundJob(
                tenant_id=tenant_id, type=PREVIEW_JOB_TYPE, status=JOB_PENDING,
                payload_json=payload,
            )
            self.db.add(job)
            self.db.commit()

        self._run(job, transport=transport)
        self.db.refresh(job)
        return job.id, wire_status(job.status)

    def _claim_and_create(
        self, tenant_id: str, config: AcEntityConfig, payload: Dict[str, Any],
    ) -> Tuple[BackgroundJob, bool]:
        """AC-11-23 - the atomic claim: a job id is minted BEFORE any row
        exists, and the ``UPDATE ... WHERE preview_job_id IS NULL`` decides
        who wins BEFORE the job row is created at all - the loser never
        creates (then discards) a second row. Returns ``(job, won)``."""
        table = AcEntityConfig.__table__
        new_id = str(uuid.uuid4())
        stmt = (
            update(table)
            .where(table.c.id == config.id, table.c.preview_job_id.is_(None))
            .values(preview_job_id=new_id)
        )
        result = self.db.execute(stmt)
        if result.rowcount and result.rowcount > 0:
            job = BackgroundJob(
                id=new_id, tenant_id=tenant_id, type=PREVIEW_JOB_TYPE,
                status=JOB_PENDING, payload_json=payload,
            )
            self.db.add(job)
            self.db.commit()
            return job, True

        # Lost the race (another request claimed between our earlier read
        # and this UPDATE) - re-read the WINNING job id fresh.
        #
        # sprint-5/11 review round 2 (item 6, nit) - the winner may ALREADY
        # be terminal by the time this loser's own request reaches here
        # (eager mode, or a genuinely fast real worker): this is fine by
        # design, never a race to "fix" - the loser's own 202 response still
        # carries the SAME job id, and the FE simply renders whatever
        # terminal result the poll route returns (S1's own result gate still
        # applies to THIS caller's permissions, same as any other poller).
        self.db.commit()
        self.db.refresh(config)
        winner = self._get_job(tenant_id, config.preview_job_id) if config.preview_job_id else None
        if winner is not None:
            return winner, False
        # Vanishingly unlikely (the winner's own claim released between our
        # failed UPDATE and this re-read) - start unclaimed rather than
        # leave the operator stuck.
        job = BackgroundJob(
            tenant_id=tenant_id, type=PREVIEW_JOB_TYPE, status=JOB_PENDING,
            payload_json=payload,
        )
        self.db.add(job)
        self.db.commit()
        return job, True

    def _run(self, job: BackgroundJob, *, transport: Any = None) -> None:
        """Eager (dev/test) runs INLINE; Celery otherwise - the SAME
        contract ``JobService.enqueue`` already offers, widened ONLY for the
        one case it has no room for: a TEST-ONLY transport (never a
        production call site - ``get_http_transport`` always resolves
        ``None`` outside a dependency-override test) threaded through to
        the sample-scope handler. Production always takes the plain
        ``enqueue`` path below."""
        if settings.celery_task_always_eager and transport is not None:
            self._run_eager_with_transport(job, transport=transport)
        else:
            self.jobs.enqueue(job.id)

    def _run_eager_with_transport(self, job: BackgroundJob, *, transport: Any) -> None:
        """Mirrors ``app.jobs.service.run_job``'s own claim + exception
        isolation - a handler crash here can never break the triggering
        request - widened only to pass ``transport`` through to the
        registered handler directly (``run_job``'s generic 2-arg dispatch
        has no room for it)."""
        if not self.jobs.claim(job.id):
            return
        self.db.refresh(job)
        try:
            run_autocount_source_preview(self.db, job, transport=transport)
        except Exception as exc:  # noqa: BLE001 - isolated, mirrors run_job
            logger.exception("autocount_source_preview job %s crashed", job.id)
            self.db.rollback()
            job = self.jobs.repo.get_unscoped(job.id)
            if job is not None and job.status not in JOB_TERMINAL_STATUSES:
                self.jobs.finish(job, status=JOB_FAILED, error=f"Job crashed: {exc}")
                close_module_bookkeeping(self.db, job, now=job.finished_at)
                self.db.commit()

    # ── poll / cancel ─────────────────────────────────────────────────────────

    def _get_job(self, tenant_id: str, job_id: str) -> Optional[BackgroundJob]:
        return (
            self.db.query(BackgroundJob)
            .filter(
                BackgroundJob.id == job_id,
                BackgroundJob.tenant_id == tenant_id,
                BackgroundJob.type == PREVIEW_JOB_TYPE,
            )
            .first()
        )

    def get(self, tenant_id: str, job_id: str, *, current_user: Any = None) -> Optional[PreviewJobOut]:
        """AC-11-22/27. ``current_user`` (sprint-5/11 review round 1, S1) -
        ``result`` (the walked rows / dry-run predictions) is withheld unless
        the caller holds the SCOPE's own start key (``companies.manage`` for
        ``sample``, ``autocount.sync.run`` for ``full``) - status/progress/
        error stay visible to any ``companies.read`` caller regardless, so
        the poll route stays on its existing permission."""
        job = self._get_job(tenant_id, job_id)
        if job is None:
            return None
        return _to_wire(job, include_result=self._can_see_result(job, current_user))

    def _can_see_result(self, job: BackgroundJob, current_user: Any) -> bool:
        if current_user is None:
            return False
        from app.dependencies import effective_permission_keys

        payload = job.payload_json or {}
        scope = str(payload.get("scope") or "")
        required = (
            SAMPLE_START_PERMISSION if scope == PREVIEW_SCOPE_SAMPLE else FULL_START_PERMISSION
        )
        return required in effective_permission_keys(current_user)

    def cancel(
        self, tenant_id: str, job_id: str, *, current_user: Any = None
    ) -> Optional[PreviewJobOut]:
        """AC-11-24 - a no-op 200 carrying the terminal status against an
        already-terminal job; a live job flips to ``aborted`` and the
        handler's own cooperative checkpoint (or the final pre-finish
        recheck) stops the walk and releases the claim.

        sprint-5/11 S4 review round 1 (BLOCKER B1) - a PENDING job has no
        handler running to release the claim on its own cooperative
        checkpoint (``app/jobs/service.py``'s ``run_job`` returns early for a
        non-PENDING/RUNNING job once it flips ``aborted``, so the worker will
        now SKIP it entirely) - the claim is released HERE, in the SAME
        transaction that stamps ``aborted``, so the next Test never finds a
        dead claim.

        sprint-5/11 review round 2 (item 1) - ``current_user`` (the SAME
        S1 gate ``get()`` applies): cancelling an ALREADY-DONE job is a
        no-op 200 that still carries ``result`` unless withheld - a
        ``companies.manage``-only caller cancelling a FULL scope job must
        not read the whole dry-run result through the cancel route when the
        poll route itself would have withheld it."""
        job = self._get_job(tenant_id, job_id)
        if job is None:
            return None
        if job.status in (JOB_PENDING, JOB_RUNNING):
            job.status = JOB_ABORTED
            payload = job.payload_json or {}
            _release_claim(
                self.db, tenant_id,
                str(payload.get("companyId") or ""), str(payload.get("entityType") or ""),
                job.id,
            )
            self.db.commit()
            self.db.refresh(job)
        return _to_wire(job, include_result=self._can_see_result(job, current_user))


def _to_wire(job: BackgroundJob, *, include_result: bool = True) -> PreviewJobOut:
    """``include_result`` (S1) - the ONLY thing a missing scope-start key
    withholds; every other key (status/progress/error/taskError/
    fieldErrors) stays exactly as it always did."""
    payload = job.payload_json or {}
    result_json = job.result_json or {}
    progress: Optional[PreviewJobProgressOut] = None
    if job.progress_total or job.progress_done or (
        isinstance(job.cursor_json, dict) and job.cursor_json.get("stage")
    ):
        cursor = job.cursor_json if isinstance(job.cursor_json, dict) else {}
        progress = PreviewJobProgressOut(
            stage=cursor.get("stage"),
            pagesDone=job.progress_done or None,
            pagesTotal=job.progress_total or None,
        )
    task_error = None
    field_errors = None
    result: Optional[Dict[str, Any]] = None
    if job.status == JOB_DONE and include_result:
        result = result_json or None
    elif job.status == JOB_FAILED:
        raw_task_error = result_json.get("taskError")
        if isinstance(raw_task_error, dict) and raw_task_error.get("code"):
            task_error = PreviewJobTaskErrorOut(
                code=str(raw_task_error["code"]), message=str(raw_task_error.get("message") or ""),
            )
        raw_field_errors = result_json.get("fieldErrors")
        if isinstance(raw_field_errors, dict) and raw_field_errors:
            field_errors = {str(k): str(v) for k, v in raw_field_errors.items()}
    return PreviewJobOut(
        id=job.id,
        scope=str(payload.get("scope") or ""),
        status=wire_status(job.status),
        progress=progress,
        result=result,
        error=job.error,
        taskError=task_error,
        fieldErrors=field_errors,
        createdAt=job.created_at,
    )


def snapshot_job_progress(
    db: Session, tenant_id: str, job_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """sprint-5/11 S5 (AC-11-41/42) - the pull-snapshot build's OWN progress
    projection, living right next to ``_to_wire``'s preview-job rule above
    ON PURPOSE so the two sit side by side: this rule is STRICTER - present
    ONLY once ``pagesTotal`` is known (a bare ``stage``/``done`` with no
    total, e.g. a bare-array endpoint's very first beat, is not enough).
    ``_to_wire`` can lean on the wire STATUS (``queued``/``running``) to
    signal "something is happening"; a snapshot header has no such phase of
    its own (`building` covers the whole build) - so ``pagesTotal`` alone is
    what tells an unattended caller (the public gateway, a third party) "a
    real number is coming", never a guess, never a bare 0/0.

    Tenant-scoped: a job belonging to a DIFFERENT tenant than the resolved
    snapshot never leaks its numbers (AC-11-71) - the caller passes the
    ALREADY-resolved tenant (the snapshot's own, or the API key row's), never
    client input.

    Shared by BOTH surfaces (the public gateway's ``gateway_snapshot_header``
    and the operator's ``pull_service.snapshot_header``) - one mechanism, two
    callers, each gating it on their own snapshot's ``status == building``
    first (this helper does not re-check status; a caller for a
    ready/failed snapshot must simply not call it).
    """
    if not job_id:
        return None
    job = (
        db.query(BackgroundJob)
        .filter(BackgroundJob.id == job_id, BackgroundJob.tenant_id == tenant_id)
        .first()
    )
    if job is None or not job.progress_total:
        return None
    cursor = job.cursor_json if isinstance(job.cursor_json, dict) else {}
    return {
        "pagesDone": job.progress_done or 0,
        "pagesTotal": job.progress_total,
        "stage": cursor.get("stage"),
    }
