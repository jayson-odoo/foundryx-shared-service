"""The ``autocount_source_preview`` background-job handler (sprint-5/11 S4,
plan section 2.2, AC-11-21..31).

ONE job kind, two scopes (D5, R3): ``sample`` runs ``EtlService.preview_http``
UNCHANGED (the Source tab's Test button); ``full`` runs
``EtlService.preview_task`` UNCHANGED (Review & Activate's Run preview).
Neither service function's logic changes here - only WHO calls it (a job
handler, never a request handler directly, AC-11-22's second pin) and what
happens around the call:

* the claim (``AcEntityConfig.preview_job_id``, AC-11-23) is released on
  EVERY terminal path this handler reaches directly - done, failed,
  cancelled. A crash/orphan/undispatched release is a DIFFERENT path (the
  bootstrap ``on_job_orphaned`` hook, mirroring ``autocount_sync``/
  ``autocount_pull_snapshot`` - see ``bootstrap.py``).
* cooperative cancel (AC-11-24) - the ``full`` scope's walk already beats
  once per page via ``HttpApiSource``'s own ``heartbeat`` callback
  (MUST-FIX 1, sprint-5/10 review round 1); this handler's own callback
  re-reads the job's status FRESH and raises ``_PreviewCancelled`` to stop
  the walk on that page, no further page requested.
* the stored result caps ``predictions`` at 500 with ``predictionsTruncated``
  (AC-11-30, R4) - summary counts stay whole.

Registered from ``sync.py`` so the EXISTING Celery worker import
(``app/workflow_engine/worker.py`` imports ``modules.autocount.sync``)
already covers it - forgetting a SEPARATE import here would leave every
preview job Pending forever, the same footgun ``sync.py``'s own docstring
names for ``autocount_sync``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.jobs.registry import JobHandlerDef, register_job_handler
from app.jobs.service import JobService
from app.models.background_job import JOB_ABORTED, JOB_DONE, JOB_FAILED, BackgroundJob

from .models import AcEntityConfig
from .schemas import (
    BrandContractGate,
    ContractGate,
    EtlTaskResponse,
    HttpPreviewColumnOut,
    HttpPreviewResponse,
    LookupPreviewCountOut,
)
from .services.etl_service import (
    AutocountServiceError,
    EtlAnchorError,
    EtlService,
    EtlStateError,
    EtlTaskView,
    EtlValidationError,
    PreviewUnavailable,
)
from .http_source.errors import HttpSourceError
from .sql_source.errors import SqlSourceError

logger = logging.getLogger("foundryx.autocount")

# The registered ``background_jobs.type``.
PREVIEW_JOB_TYPE = "autocount_source_preview"

PREVIEW_SCOPE_SAMPLE = "sample"
PREVIEW_SCOPE_FULL = "full"

# Owner ruling R4 (AC-11-30) - a `full` job's stored result caps its
# predictions; the summary counts stay authoritative and uncapped.
MAX_STORED_PREDICTIONS = 500


class _PreviewCancelled(Exception):
    """Internal signal ONLY (AC-11-24) - the cooperative-cancel checkpoint
    fired mid-walk. Caught inside ``run_autocount_source_preview`` itself:
    the job ends ``aborted``, nothing is stamped on the task."""


def _aborted(db: Session, job_id: str) -> bool:
    """Re-read the job's status FRESH from the DB - mirrors ``sync.py``'s
    own ``_aborted`` (a concurrent cancel committed on a DIFFERENT session,
    so a stale in-memory ``job`` object would otherwise never see it)."""
    return (
        db.query(BackgroundJob.status).filter(BackgroundJob.id == job_id).scalar()
        == JOB_ABORTED
    )


def _release_claim(
    db: Session, tenant_id: str, company_id: str, entity_type: str, job_id: str
) -> None:
    """Release THIS job's claim on ``ac_entity_config.preview_job_id``, only
    if it is still the one holding it (a stale/duplicate release is a
    harmless no-op - never clobbers a DIFFERENT job's claim)."""
    if not company_id or not entity_type:
        return
    table = AcEntityConfig.__table__
    stmt = (
        update(table)
        .where(
            table.c.tenant_id == tenant_id,
            table.c.company_id == company_id,
            table.c.entity_type == entity_type,
            table.c.preview_job_id == job_id,
        )
        .values(preview_job_id=None)
    )
    db.execute(stmt)


def _task_echo_model(view: EtlTaskView) -> EtlTaskResponse:
    """The SAME camelCase task shape ``routers/companies.py``'s own
    ``_task_response`` builds (AC-11-26's "job result carries the SAME task
    echo the route used to return") - built from the ONE wire schema so the
    two can never drift on field names, deliberately not importing the
    router (services never depend on routers). Returned as the PYDANTIC
    model (not a dump) so a caller that nests it in a SIBLING response
    model (``HttpPreviewResponse.task``) gets ONE encoder pass, never two -
    see ``_run_sample``'s own ``Decimal``-safety note.

    sprint-5/11 S4 review round 1 (S4) - ``previewJobId`` is ALWAYS forced to
    ``None`` here, never ``view.preview_job_id``: both call sites build this
    echo for a TERMINAL (``done``) result, read BEFORE ``_finish`` releases
    the claim - so ``view.preview_job_id`` still names THIS job. A stale
    non-null id shipped on the wire is exactly the bug: the FE `apply()`s it
    as if a preview were still in flight, and the OTHER tab's hook then
    attaches to a job that is already done."""
    return EtlTaskResponse(
        companyId=view.company_id,
        entityType=view.entity_type,
        etlStatus=view.etl_status,
        activatedAt=view.activated_at,
        sourceImpl=view.source_impl,
        sourceConfig=view.source_config,
        resultColumns=view.result_columns,
        lineResultColumns=view.line_result_columns,
        lastPreviewAt=view.last_preview_at,
        lastPreviewFailedCount=view.last_preview_failed_count,
        lastRunAt=view.last_run_at,
        lastRunError=view.last_run_error,
        lastRunErrorCode=view.last_run_error_code,
        nextIncrementalAt=view.next_incremental_at,
        nextReconcileAt=view.next_reconcile_at,
        initialLoad=view.initial_load,
        brandContractGate=(
            BrandContractGate(**view.brand_contract_gate) if view.brand_contract_gate else None
        ),
        contractGate=(ContractGate(**view.contract_gate) if view.contract_gate else None),
        deliveryMode=view.delivery_mode,
        combineOutputColumns=view.combine_output_columns,
        previewJobId=None,
    )


def _task_echo(view: EtlTaskView) -> Dict[str, Any]:
    """``_task_echo_model`` dumped to a plain JSON-safe dict - for a caller
    that stores the task echo directly (the ``full`` scope's own
    ``{scope, task, preview}`` result), never nested inside another
    response model."""
    return _task_echo_model(view).model_dump(mode="json")


def run_autocount_source_preview(
    db: Session, job: BackgroundJob, *, transport: Any = None
) -> None:
    """``background_jobs`` handler for ``autocount_source_preview``.

    ``transport`` - a TEST-ONLY seam (never a production call site): eager
    execution (the local/test default) runs this handler INLINE in the same
    request the router's own ``get_http_transport`` FastAPI dependency
    override resolved a stub transport for; a plain function call has no
    way to see that override on its own, so ``PreviewJobService`` threads it
    through explicitly for the ONE scope (``sample``) that reaches the
    network directly. Production (Celery, or eager with no override active)
    always passes ``None`` - a real ``httpx.Client`` is then built exactly
    as it always was.

    Failures are isolated by the caller (``run_job``/``PreviewJobService``,
    job -> failed, logged, never propagated), so nothing here can break the
    triggering request.
    """
    service = JobService(db)
    payload = dict(job.payload_json or {})
    tenant_id = job.tenant_id
    scope = str(payload.get("scope") or "")
    company_id = str(payload.get("companyId") or "")
    entity_type = str(payload.get("entityType") or "")
    request = dict(payload.get("request") or {})

    def _finish(
        *,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        service.finish(job, status=status, result=result, error=error)
        _release_claim(db, tenant_id, company_id, entity_type, job.id)
        db.commit()

    try:
        if scope == PREVIEW_SCOPE_SAMPLE:
            _run_sample(
                db, _finish, job_id=job.id,
                tenant_id=tenant_id, company_id=company_id, entity_type=entity_type,
                request=request, transport=transport,
            )
        elif scope == PREVIEW_SCOPE_FULL:
            _run_full(
                db, _finish, job_id=job.id,
                tenant_id=tenant_id, company_id=company_id, entity_type=entity_type,
            )
        else:
            _finish(status=JOB_FAILED, error=f"Unknown preview scope '{scope!r}'.")
    except _PreviewCancelled:
        _finish(status=JOB_ABORTED)


def _run_sample(
    db: Session,
    finish,
    *,
    job_id: str,
    tenant_id: str,
    company_id: str,
    entity_type: str,
    request: Dict[str, Any],
    transport: Any,
) -> None:
    etl = EtlService(db)
    service = JobService(db)

    def _on_page(stage: str, done: int, total: Optional[int]) -> None:
        """sprint-5/11 review round 2 (item 5, AC-11-40) - progress only
        (no cooperative-cancel check here, unlike ``_run_full``'s own
        callback): the sample scope's single request already has its own
        cancel recheck right before the terminal write, below."""
        try:
            service.beat_progress(job_id, done=done, total=total, stage=stage)
        except Exception:  # noqa: BLE001 - advisory, must never fail the run
            logger.warning(
                "autocount_source_preview: beat_progress for job %s failed",
                job_id, exc_info=True,
            )

    try:
        result, task_view = etl.preview_http(
            tenant_id,
            str(request.get("connectionId") or ""),
            str(request.get("path") or ""),
            distinct_of=request.get("distinctOf"),
            lookups=request.get("lookups"),
            combine=request.get("combine"),
            company_id=company_id or None,
            entity_type=entity_type or None,
            transport=transport,
            on_page=_on_page,
        )
    except EtlValidationError as exc:
        finish(status=JOB_FAILED, error=exc.message, result={"fieldErrors": exc.field_errors})
        return
    except (AutocountServiceError, HttpSourceError) as exc:
        logger.warning("autocount_source_preview (sample) failed: %s", exc.message)
        finish(status=JOB_FAILED, error=exc.message)
        return
    except Exception as exc:  # noqa: BLE001 - operator-safe, never silently swallowed
        logger.exception("autocount_source_preview (sample) crashed")
        finish(status=JOB_FAILED, error=f"The preview could not be run: {exc}")
        return

    funnel = result.combine_funnel or {}
    # sprint-5/11 review finding - a combine-carrying preview's grouped rows
    # can carry a ``Decimal`` measure (``apply_combine``'s own rounding
    # step), which the RAW ``json`` module behind ``result_json`` cannot
    # serialize (unlike the OLD synchronous route, which returned a Pydantic
    # ``HttpPreviewResponse`` whose own JSON encoder wire-serialises a
    # ``Decimal`` as a STRING). Building the SAME response model here, then
    # storing its OWN JSON-safe dump, keeps that exact wire shape - and the
    # ONE encoder every other consumer of this shape already agrees with.
    preview_payload: Dict[str, Any] = HttpPreviewResponse(
        envelope=result.envelope,
        totalCount=result.total_count,
        columns=[
            HttpPreviewColumnOut(
                name=name,
                sample=(str(result.rows[0][name]) if result.rows and name in result.rows[0] else None),
            )
            for name in result.columns
        ],
        rows=result.rows,
        durationMs=result.duration_ms,
        task=_task_echo_model(task_view) if task_view is not None else None,
        lookups=[
            LookupPreviewCountOut(alias=entry.alias, matched=entry.matched, missed=entry.missed)
            for entry in result.lookups
        ],
        rowsIn=funnel.get("rowsIn"),
        excludedCount=funnel.get("excludedCount"),
        groups=funnel.get("groups"),
        droppedByRule=funnel.get("droppedByRule"),
        rowsOut=funnel.get("rowsOut"),
        roundedCount=funnel.get("roundedCount"),
        preCombineColumns=result.pre_combine_columns,
        rawColumns=list(result.raw_columns),
    ).model_dump(mode="json")
    # AC-11-24 - the sample scope is a single request with no natural
    # per-page checkpoint of its own; this is the last chance to honour a
    # cancel that landed while the request was in flight, BEFORE the result
    # is stamped as done (mirrors ``sync.py``'s own "fresh status re-read
    # before the terminal write").
    if _aborted(db, job_id):
        finish(status=JOB_ABORTED)
        return
    finish(status=JOB_DONE, result={"scope": PREVIEW_SCOPE_SAMPLE, "preview": preview_payload})


def _run_full(
    db: Session,
    finish,
    *,
    job_id: str,
    tenant_id: str,
    company_id: str,
    entity_type: str,
) -> None:
    etl = EtlService(db)
    service = JobService(db)

    def _on_page(stage: str, done: int, total: Optional[int]) -> None:
        """AC-11-24's cooperative-cancel checkpoint, widened (S5, AC-11-40)
        to ALSO stamp progress through ``JobService.beat_progress`` - fired
        after every source/lookup page AND at the "mapping"/"dry_run" stage
        transitions (``EtlService.preview_task``'s own explicit calls,
        ``page``/``total`` unknown there - ``0``/``None``)."""
        try:
            service.beat_progress(job_id, done=done, total=total, stage=stage)
        except Exception:  # noqa: BLE001 - advisory, must never fail the run
            logger.warning(
                "autocount_source_preview: beat_progress for job %s failed",
                job_id, exc_info=True,
            )
        if _aborted(db, job_id):
            raise _PreviewCancelled()

    try:
        task_view, preview = etl.preview_task(
            tenant_id, company_id, entity_type, on_page=_on_page,
        )
    except _PreviewCancelled:
        raise
    except EtlAnchorError as exc:
        finish(
            status=JOB_FAILED,
            error=exc.message,
            result={"taskError": {"code": exc.code, "message": exc.message}},
        )
        return
    except (
        EtlStateError,
        PreviewUnavailable,
        HttpSourceError,
        SqlSourceError,
        AutocountServiceError,
    ) as exc:
        message = getattr(exc, "message", None) or str(exc)
        logger.warning("autocount_source_preview (full) failed: %s", message)
        finish(status=JOB_FAILED, error=message)
        return
    except Exception as exc:  # noqa: BLE001 - operator-safe, never silently swallowed
        logger.exception("autocount_source_preview (full) crashed")
        finish(status=JOB_FAILED, error=f"The dry run could not be completed: {exc}")
        return

    predictions = preview.get("predictions") if isinstance(preview, dict) else None
    if isinstance(predictions, list) and len(predictions) > MAX_STORED_PREDICTIONS:
        preview = dict(preview)
        preview["predictions"] = predictions[:MAX_STORED_PREDICTIONS]
        preview["predictionsTruncated"] = True

    # AC-11-24 - the SAME final recheck the sample scope applies above: the
    # per-page checkpoint already stops the WALK early, but the mapping/
    # dry-run tail after it has no checkpoint of its own.
    if _aborted(db, job_id):
        finish(status=JOB_ABORTED)
        return
    finish(
        status=JOB_DONE,
        result={"scope": PREVIEW_SCOPE_FULL, "task": _task_echo(task_view), "preview": preview},
    )


def register_preview_job_handler() -> None:
    """Register the ``autocount_source_preview`` handler - called from
    ``sync.py`` (its own module-level boot registration) so the EXISTING
    worker import covers this handler too."""
    register_job_handler(_HANDLER_DEF)


_HANDLER_DEF = JobHandlerDef(
    PREVIEW_JOB_TYPE, run_autocount_source_preview, "AutoCount source preview",
    heartbeats=True,
)
