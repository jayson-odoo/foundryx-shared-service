"""Company routes - thin: HTTP + Pydantic only.

No DB query and no raw SQL lives here (code-review hard-fail). Every handler
takes the tenant from the authenticated user - NEVER from client input - and
hands off to a service.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from ..schemas import (
    CompanyCreate,
    CompanyDetailResponse,
    CompanyItem,
    CompanyListResponse,
    CompanySinkUpdate,
    EntityConfigItem,
    EntityConfigUpdate,
    EtlPreviewResponse,
    EtlRunStartResponse,
    EtlTaskResponse,
    EtlTaskUpdate,
    FormulaTestRequest,
    FormulaTestResponse,
    MappingRowOut,
    MappingUpdateRequest,
    MappingViewResponse,
    SimulateRequest,
    SimulateResponse,
    SorentoFieldOut,
    SyncRunItem,
    SyncRunListResponse,
)
from ..services import (
    AutocountServiceError,
    CompanyAlreadyExists,
    CompanyNotFound,
    CompanyService,
    ConnectionNotFound,
    EntityConfigNotFound,
    EtlAnchorError,
    EtlService,
    EtlStateError,
    EtlTaskView,
    EtlValidationError,
    MappingView,
    MappingWriteRow,
    PreviewUnavailable,
    SinkTargetValidationError,
)
from ..sql_source.errors import SqlSourceError
from .sql import raise_sql_error

router = APIRouter()


def _raise(exc: AutocountServiceError) -> None:
    """ONE translator for every service error → HTTP. Messages are already
    operator-safe (no stack traces, no credentials)."""
    if isinstance(exc, (CompanyNotFound, ConnectionNotFound, EntityConfigNotFound)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    if isinstance(exc, CompanyAlreadyExists):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message)
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
    )


def _field_errors(field_errors: dict, message: str) -> JSONResponse:
    """ONE per-field 422 shape for every surface that has one.

    ``detail`` carries the map (the frontend hooks read
    ``ApiError.detail.fieldErrors``) and ``message`` is the human line the
    api-client falls back to when ``detail`` is not a string.
    """
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": {"fieldErrors": field_errors}, "message": message},
    )


@router.get("", response_model=CompanyListResponse)
def list_companies(
    current_user: User = Depends(require_permission("autocount.companies.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
) -> CompanyListResponse:
    rows, total = CompanyService(db).list(
        current_user.tenant_id, page=page, page_size=page_size
    )
    return CompanyListResponse(
        data=[CompanyItem.model_validate(row) for row in rows], total=total, page=page
    )


@router.post("", response_model=CompanyItem, status_code=status.HTTP_201_CREATED)
def create_company(
    body: CompanyCreate,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> CompanyItem:
    """Register an AutoCount company by DISCOVERING it from its connection."""
    try:
        company = CompanyService(db).create_from_connection(
            current_user.tenant_id, body.connectionId, name=body.name
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return CompanyItem.model_validate(company)


@router.get("/{company_id}", response_model=CompanyDetailResponse)
def get_company(
    company_id: str,
    current_user: User = Depends(require_permission("autocount.companies.read")),
    db: Session = Depends(get_db),
) -> CompanyDetailResponse:
    service = CompanyService(db)
    try:
        company = service.get(current_user.tenant_id, company_id)
        # Config JOINED with the watermark: the Entities surface needs the delta
        # state (last synced, failures, last error) to explain a zero-record run.
        entities = service.entity_states(current_user.tenant_id, company_id)
    except AutocountServiceError as exc:
        _raise(exc)
    return CompanyDetailResponse(
        company=CompanyItem.model_validate(company),
        entities=[EntityConfigItem.model_validate(row) for row in entities],
    )


@router.patch("/{company_id}/sink-target", response_model=CompanyItem)
def set_sink_target(
    company_id: str,
    body: CompanySinkUpdate,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> CompanyItem:
    """Point a company at its consumer push target (hop 2).

    ``logging`` keeps the no-op default; ``sorento`` requires a Sorento
    ``consumer`` connection id, validated to belong to this tenant. Reuses
    ``autocount.companies.manage`` - the same "configure the company" authority -
    so no new permission needs a grant sweep for existing tenants."""
    try:
        company = CompanyService(db).set_sink_target(
            current_user.tenant_id,
            company_id,
            sink_impl=body.sinkImpl,
            sink_connection_id=body.sinkConnectionId,
            # The per-company Sorento anchor (plan 22 Appendix A6) - required
            # with the Sorento sink, cleared with ``logging``.
            sorento_company_code=body.sorentoCompanyCode,
        )
    except SinkTargetValidationError as exc:
        return _field_errors(exc.field_errors, exc.message)
    except AutocountServiceError as exc:
        _raise(exc)
    return CompanyItem.model_validate(company)


@router.patch(
    "/{company_id}/entities/{entity_type}", response_model=EntityConfigItem
)
def update_entity_config(
    company_id: str,
    entity_type: str,
    body: EntityConfigUpdate,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> EntityConfigItem:
    """Adjust one entity's sync configuration (the initial lookback window).

    Reuses ``autocount.companies.manage`` rather than minting a permission: a
    new key would not reach existing tenants' Admin roles without a grant sweep,
    and this is the same "configure the company" authority.
    """
    try:
        state = CompanyService(db).update_entity_config(
            current_user.tenant_id,
            company_id,
            entity_type,
            initial_lookback_days=body.initialLookbackDays,
            source_impl=body.sourceImpl,
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return EntityConfigItem.model_validate(state)


@router.post(
    "/{company_id}/entities/{entity_type}/refetch", response_model=EntityConfigItem
)
def refetch_entity(
    company_id: str,
    entity_type: str,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> EntityConfigItem:
    """Re-open the first-run window by resetting the entity's watermark, so the
    next sync re-fetches history from scratch (AC-15-30).

    Deliberately a POST (a state change, not idempotent config) and distinct from
    the entity PATCH: a lookback edit must never silently re-fetch, and this must
    never be mistaken for one. Reuses ``autocount.companies.manage``.
    """
    try:
        state = CompanyService(db).refetch_entity(
            current_user.tenant_id, company_id, entity_type
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return EntityConfigItem.model_validate(state)


def _mapping_response(view: MappingView) -> MappingViewResponse:
    return MappingViewResponse(
        entityType=view.entity_type,
        rows=[MappingRowOut.model_validate(row) for row in view.rows],
        sorentoFields=[SorentoFieldOut.model_validate(f) for f in view.sorento_fields],
        acFields=list(view.ac_fields),
    )


@router.get(
    "/{company_id}/entities/{entity_type}/mapping",
    response_model=MappingViewResponse,
)
def get_entity_mapping(
    company_id: str,
    entity_type: str,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> MappingViewResponse:
    """The entity's current field mappings projected AutoCount→Sorento, plus the
    source/target catalogs the editor's pickers need (AC-15-40).

    Reuses ``autocount.companies.manage`` - the same "configure the company"
    authority - so no new permission needs a grant sweep for existing tenants.
    """
    try:
        view = CompanyService(db).mapping_view(
            current_user.tenant_id, company_id, entity_type
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return _mapping_response(view)


@router.put(
    "/{company_id}/entities/{entity_type}/mapping",
    response_model=MappingViewResponse,
)
def replace_entity_mapping(
    company_id: str,
    entity_type: str,
    body: MappingUpdateRequest,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> MappingViewResponse:
    """Replace the entity's deliverable field mappings (AC-15-41/42/43).

    The server GUARDS every row: the Sorento target must be an accepted field
    (else 422 naming it - a target Sorento would reject can never be stored), the
    source path is non-blank and the transform is known. Provenance/watermark
    rows are preserved; the write is seed-if-absent-safe (``update_tenant`` never
    reverts an operator edit).
    """
    try:
        view = CompanyService(db).replace_mapping(
            current_user.tenant_id,
            company_id,
            entity_type,
            [
                MappingWriteRow(
                    source_path=row.sourcePath,
                    transform=row.transform,
                    sorento_field=row.sorentoField,
                    formula=row.formula,
                )
                for row in body.rows
            ],
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return _mapping_response(view)


@router.get(
    "/{company_id}/entities/{entity_type}/mapping/functions",
)
def get_formula_catalog(
    company_id: str,
    entity_type: str,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> dict:
    """The formula function/operator/preset/date-token catalog the builder needs
    (AC-16-13/15). Entity-agnostic; gated behind the company/entity guard so it
    shares the mapping editor's auth. Reuses ``autocount.companies.manage``.
    """
    try:
        catalog = CompanyService(db).function_catalog(
            current_user.tenant_id, company_id, entity_type
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return catalog


@router.post(
    "/{company_id}/entities/{entity_type}/mapping/test-formula",
    response_model=FormulaTestResponse,
)
def test_formula(
    company_id: str,
    entity_type: str,
    body: FormulaTestRequest,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> FormulaTestResponse:
    """Server-authoritative single-formula eval (AC-16-21) - the parity check for
    the builder's live client preview. Writes NOTHING. A bad formula/value comes
    back as ``{ok: false, error}``, never a 500. Reuses ``autocount.companies.manage``.
    """
    try:
        result = CompanyService(db).test_formula(
            current_user.tenant_id, company_id, entity_type, body.formula, body.value
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return FormulaTestResponse(**result)


@router.post(
    "/{company_id}/entities/{entity_type}/mapping/simulate",
    response_model=SimulateResponse,
)
def simulate_mapping(
    company_id: str,
    entity_type: str,
    body: SimulateRequest,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> SimulateResponse:
    """Run the REAL MappingEngine over a MOCK AutoCount record → the projected
    Sorento record + per-field results (AC-16-30). Writes NOTHING - pure transform
    preview, distinct from the slice-14 Sorento dry-run. ``rows`` (optional) lets
    the operator simulate UNSAVED edits. Reuses ``autocount.companies.manage``.
    """
    try:
        draft = (
            [
                MappingWriteRow(
                    source_path=row.sourcePath,
                    transform=row.transform,
                    sorento_field=row.sorentoField,
                    formula=row.formula,
                )
                for row in body.rows
            ]
            if body.rows is not None
            else None
        )
        result = CompanyService(db).simulate_mapping(
            current_user.tenant_id, company_id, entity_type, body.record, draft
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return SimulateResponse(**result)


# ── direct-DB ETL task (plan 22 S1, AC-22-11) ─────────────────────────────────


def _task_response(view: EtlTaskView) -> EtlTaskResponse:
    return EtlTaskResponse(
        companyId=view.company_id,
        entityType=view.entity_type,
        etlStatus=view.etl_status,
        activatedAt=view.activated_at,
        sourceConfig=view.source_config,
        resultColumns=view.result_columns,
        lastPreviewAt=view.last_preview_at,
        lastPreviewFailedCount=view.last_preview_failed_count,
        lastRunAt=view.last_run_at,
        lastRunError=view.last_run_error,
        lastRunErrorCode=view.last_run_error_code,
        nextIncrementalAt=view.next_incremental_at,
        nextReconcileAt=view.next_reconcile_at,
    )


def _raise_task(exc: Exception):
    """Task-lifecycle errors → HTTP, in the ONE place they are translated.

    * ``EtlStateError``  → **409**. The request is well-formed; the TASK is
      somewhere else (already active, never previewed, a run in flight). A 422
      would tell the operator to fix their input, which is not the problem.
    * ``EtlAnchorError`` → **422** with a structured ``detail`` carrying
      Sorento's own code (Appendix A6) - the surface names the wiring that is
      wrong instead of showing a bare delivery failure.
    * ``PreviewUnavailable`` → **502**: the consumer, not us, failed.
    * Anything else (``SqlConnectError``/``SqlQueryError``/
      ``SqlTaskNotConfigured`` - the SOURCE side of a preview, S2 review
      SHOULD-FIX 4) falls through to the SAME translator ``routers/sql.py``
      uses, so a preview that fails reading the source is never a bare 500.
    """
    if isinstance(exc, EtlStateError):
        content = {"detail": exc.message, "message": exc.message}
        if exc.running_run_id:
            content["detail"] = {
                "message": exc.message,
                "runningRunId": exc.running_run_id,
            }
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=content)
    if isinstance(exc, EtlAnchorError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": {"code": exc.code, "message": exc.message},
                "message": exc.message,
            },
        )
    if isinstance(exc, PreviewUnavailable):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message
        )
    if isinstance(exc, AutocountServiceError):
        _raise(exc)
        return
    raise_sql_error(exc)


@router.get(
    "/{company_id}/entities/{entity_type}/etl-task", response_model=EtlTaskResponse
)
def get_etl_task(
    company_id: str,
    entity_type: str,
    current_user: User = Depends(require_permission("autocount.companies.read")),
    db: Session = Depends(get_db),
) -> EtlTaskResponse:
    """One entity's DB extraction task, anchored on ``ac_entity_config``. A
    never-configured entity returns a DRAFT with defaults (the editor is the
    create surface), not a 404."""
    try:
        view = EtlService(db).get_task(current_user.tenant_id, company_id, entity_type)
    except AutocountServiceError as exc:
        _raise(exc)
    return _task_response(view)


@router.put(
    "/{company_id}/entities/{entity_type}/etl-task", response_model=EtlTaskResponse
)
def update_etl_task(
    company_id: str,
    entity_type: str,
    body: EtlTaskUpdate,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
):
    """Draft-save the task's source config (replaces it). Validation
    (AC-22-11): picked columns must exist in a FRESH preview of the query, the
    watermark must be orderable, documents need a from-date, interval floors
    apply → ``422 {fieldErrors}``. ``connectionId`` is re-validated against
    the tenant on every use. Reuses ``autocount.companies.manage``."""
    try:
        view = EtlService(db).update_task(
            current_user.tenant_id,
            company_id,
            entity_type,
            body.sourceConfig.model_dump(),
        )
    except EtlValidationError as exc:
        return _field_errors(exc.field_errors, exc.message)
    except AutocountServiceError as exc:
        _raise(exc)
    return _task_response(view)


# ── task lifecycle (plan 22 S2, AC-22-18/19/20) ───────────────────────────────
#
# Permission split, using EXISTING keys only (a new key would silently 403 every
# tenant provisioned before it, so none is minted):
#   configure the task  → ``autocount.companies.manage``  (activate/pause/resume)
#   make it move data   → ``autocount.sync.run``          (preview/run)
#   read its history    → ``autocount.sync.read``


@router.post(
    "/{company_id}/entities/{entity_type}/etl-task/preview",
    response_model=EtlPreviewResponse,
)
def preview_etl_task(
    company_id: str,
    entity_type: str,
    current_user: User = Depends(require_permission("autocount.sync.run")),
    db: Session = Depends(get_db),
):
    """Dry-run the INITIAL LOAD against the consumer - writes NOTHING.

    Gated on ``sync.run`` rather than ``companies.manage``: it reaches the
    source database and the consumer, which is the "make data move" authority
    even though nothing is written.
    """
    try:
        view, preview = EtlService(db).preview_task(
            current_user.tenant_id, company_id, entity_type
        )
    except (AutocountServiceError, SqlSourceError) as exc:
        return _raise_task(exc)
    return EtlPreviewResponse(task=_task_response(view), preview=preview)


@router.post(
    "/{company_id}/entities/{entity_type}/etl-task/activate",
    response_model=EtlTaskResponse,
)
def activate_etl_task(
    company_id: str,
    entity_type: str,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
):
    """The activate-once gate (AC-22-18): draft|paused → active. 409 unless a
    successful preview exists AND the company carries a Sorento company code."""
    try:
        view = EtlService(db).activate_task(current_user.tenant_id, company_id, entity_type)
    except AutocountServiceError as exc:
        return _raise_task(exc)
    return _task_response(view)


@router.post(
    "/{company_id}/entities/{entity_type}/etl-task/pause",
    response_model=EtlTaskResponse,
)
def pause_etl_task(
    company_id: str,
    entity_type: str,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
):
    """active → paused: the sweep stops dispatching, in-flight runs finish."""
    try:
        view = EtlService(db).pause_task(current_user.tenant_id, company_id, entity_type)
    except AutocountServiceError as exc:
        return _raise_task(exc)
    return _task_response(view)


@router.post(
    "/{company_id}/entities/{entity_type}/etl-task/resume",
    response_model=EtlTaskResponse,
)
def resume_etl_task(
    company_id: str,
    entity_type: str,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
):
    """paused → active with NO re-preview ceremony (AC-22-19)."""
    try:
        view = EtlService(db).resume_task(current_user.tenant_id, company_id, entity_type)
    except AutocountServiceError as exc:
        return _raise_task(exc)
    return _task_response(view)


@router.post(
    "/{company_id}/entities/{entity_type}/etl-task/run",
    response_model=EtlRunStartResponse,
)
def run_etl_task(
    company_id: str,
    entity_type: str,
    current_user: User = Depends(require_permission("autocount.sync.run")),
    # The REAL user under impersonation (writes are never attributed to the
    # target) - a dependency, so FastAPI supplies the request it needs.
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
):
    """Enqueue ONE manual run - the SAME job the sweep enqueues (AC-22-13).
    409 unless the task is active, or while a run is still in flight (the
    conflict carries the running run's id so the surface can link to it)."""
    try:
        started = EtlService(db).run_task_now(
            current_user.tenant_id,
            company_id,
            entity_type,
            actor_user_id=actor_id,
        )
    except AutocountServiceError as exc:
        return _raise_task(exc)
    return EtlRunStartResponse(
        runId=started["run_id"],
        jobId=started["job_id"],
        status=started["status"],
        task=_task_response(started["task"]),
    )


@router.get(
    "/{company_id}/entities/{entity_type}/etl-task/runs",
    response_model=SyncRunListResponse,
)
def list_etl_runs(
    company_id: str,
    entity_type: str,
    current_user: User = Depends(require_permission("autocount.sync.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
) -> SyncRunListResponse:
    """This entity's run history, newest first (AC-22-17). Paginated at the DB
    level and capped at 200 - never an all-rows fetch."""
    try:
        rows, total = EtlService(db).list_task_runs(
            current_user.tenant_id,
            company_id,
            entity_type,
            page=page,
            page_size=page_size,
        )
    except AutocountServiceError as exc:
        return _raise_task(exc)
    return SyncRunListResponse(
        data=[SyncRunItem.model_validate(row) for row in rows],
        total=total,
        page=page,
    )
