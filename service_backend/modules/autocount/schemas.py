"""AutoCount wire schemas - camelCase out, ``ApiModel`` for Z-suffixed UTC.

House shape (matches every other schema in the codebase): the field NAME is
camelCase and ``validation_alias`` names the snake_case ORM attribute, with
``from_attributes`` doing the mapping. Every schema carrying a datetime inherits
``ApiModel`` - aware-UTC columns already emit ``Z``, and the base is the
defensive net.

Nothing here echoes a credential. A company's identity is the DISCOVERED
``DatabaseName``/``CompanyName``; the connection's AppId, password and token
never appear in any response (AC-13-42).
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field, model_validator

from app.schemas.base import ApiModel


# ── companies ─────────────────────────────────────────────────────────────────


class CompanyCreate(ApiModel):
    """The operator supplies ONLY a connection (and an optional label).

    There is deliberately no company field: the vendor API resolves the company
    from the ``AppId`` header, so any value typed here would be silently
    overridden (AC-13-01, foolproof-UI - never ask for something we determine).
    """

    model_config = ConfigDict(populate_by_name=True)

    connectionId: str
    name: str = ""


class EntityConfigItem(ApiModel):
    """One configured entity plus its live delta state (``EntityState``).

    The watermark half is not decoration: without ``lastSuccessAt``/
    ``watermarkAt`` on the wire, a sync that legitimately finds nothing is
    indistinguishable from a broken one, and ``consecutiveFailures``/
    ``lastError`` were recorded by every run and shown to nobody.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    entityType: str = Field(validation_alias="entity_type")
    syncMode: str = Field(validation_alias="sync_mode")
    sourceImpl: str = Field(validation_alias="source_impl")
    # The vendor's outer response shape for this entity (AC-14-03).
    envelope: str = "status_dict"
    # ``full`` = the first sync is UNBOUNDED (masters must mirror a standing
    # set); ``windowed`` = it reaches back ``initialLookbackDays`` (documents).
    # Surfaced so ``initialLookbackDays`` can be shown only where it applies.
    initialLoad: str = Field(default="windowed", validation_alias="initial_load")
    recordCap: int = Field(validation_alias="record_cap")
    # The window the FIRST sync reaches back over when no watermark exists.
    # Default 30 - anything older is invisible until the supervised full initial
    # load (D20), so it is surfaced and editable rather than hidden in a column.
    initialLookbackDays: int = Field(validation_alias="initial_lookback_days")
    enabled: bool

    # ── delta state (absent until the entity has been synced at least once) ──
    lastSuccessAt: Optional[datetime] = Field(
        default=None, validation_alias="last_success_at"
    )
    lastAttemptAt: Optional[datetime] = Field(
        default=None, validation_alias="last_attempt_at"
    )
    # The high-water mark itself - "we have everything modified up to here".
    watermarkAt: Optional[datetime] = Field(default=None, validation_alias="watermark_at")
    consecutiveFailures: int = Field(default=0, validation_alias="consecutive_failures")
    lastError: Optional[str] = Field(default=None, validation_alias="last_error")


class EntityConfigUpdate(ApiModel):
    """Editable slice of an entity's sync configuration.

    Deliberately narrow. Changing the lookback does NOT re-fetch history - it
    only governs the window used when no watermark exists yet.

    ``sourceImpl`` (plan 22, AC-22-08) switches the entity between the vendor
    API path and the direct-DB task. The task's ``source_config`` survives the
    switch either way, and an ACTIVE task switched back to the API path is
    paused (never left auto-pushing under a source that no longer runs it).
    """

    model_config = ConfigDict(populate_by_name=True)

    initialLookbackDays: Optional[int] = None
    sourceImpl: Optional[str] = None


class CompanyItem(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    connectionId: str = Field(validation_alias="connection_id")
    databaseName: str = Field(validation_alias="database_name")
    companyName: str = Field(validation_alias="company_name")
    name: str
    isActive: bool = Field(validation_alias="is_active")
    # The consumer push target (hop 2). ``logging`` = the no-op default (nothing
    # leaves the ESB); ``sorento`` + ``sinkConnectionId`` = a real Sorento push.
    sinkImpl: str = Field(default="logging", validation_alias="sink_impl")
    sinkConnectionId: Optional[str] = Field(
        default=None, validation_alias="sink_connection_id"
    )
    # The Sorento company this company delivers INTO (plan 22 Appendix A6) -
    # sent as the top-level ``companyCode`` on every ingest/read/deletion call.
    # NULL for a logging-sink company and for every pre-plan-22 row.
    sorentoCompanyCode: Optional[str] = Field(
        default=None, validation_alias="sorento_company_code"
    )
    createdAt: Optional[datetime] = Field(default=None, validation_alias="created_at")


class CompanySinkUpdate(ApiModel):
    """Point a company at a push target (plan 14 hop 2 - operator wiring).

    ``sinkImpl='logging'`` clears the target (the no-op default);
    ``sinkImpl='sorento'`` requires a ``sinkConnectionId`` naming a Sorento
    ``consumer`` connection for this tenant AND (plan 22 Appendix A6) a
    ``sorentoCompanyCode`` - the anchor Sorento resolves on every call. Blank
    with ``sorento`` is a 422 ``{fieldErrors}``, never a stored configuration
    that is guaranteed to answer ``COMPANY_ANCHOR_REQUIRED``.
    """

    model_config = ConfigDict(populate_by_name=True)

    sinkImpl: str
    sinkConnectionId: Optional[str] = None
    sorentoCompanyCode: Optional[str] = None


class CompanyListResponse(ApiModel):
    data: List[CompanyItem]
    total: int
    page: int = 0


class CompanyDetailResponse(ApiModel):
    company: CompanyItem
    entities: List[EntityConfigItem]


# ── sync ──────────────────────────────────────────────────────────────────────


class SyncNowRequest(ApiModel):
    model_config = ConfigDict(populate_by_name=True)

    entityType: str = "goods_received_note"


class SyncJobItem(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    status: str
    progressTotal: int = Field(default=0, validation_alias="progress_total")
    progressDone: int = Field(default=0, validation_alias="progress_done")
    progressFailed: int = Field(default=0, validation_alias="progress_failed")
    result: Optional[Dict[str, Any]] = Field(default=None, validation_alias="result_json")
    error: Optional[str] = None
    createdAt: Optional[datetime] = Field(default=None, validation_alias="created_at")


class StagedRecordItem(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    entityType: str = Field(validation_alias="entity_type")
    sourceRef: str = Field(validation_alias="source_ref")
    docNo: Optional[str] = Field(default=None, validation_alias="doc_no")
    status: str
    # Changed fields ONLY - unchanged fields are never reported as changes
    # (AC-13-12).
    diff: Optional[Dict[str, Any]] = Field(default=None, validation_alias="diff_json")
    canonical: Optional[Dict[str, Any]] = Field(
        default=None, validation_alias="canonical_json"
    )
    errors: Optional[List[Dict[str, Any]]] = Field(
        default=None, validation_alias="errors_json"
    )
    error: Optional[str] = None
    sourceLastModified: Optional[datetime] = Field(
        default=None, validation_alias="source_last_modified"
    )
    # True when this record's diff has ANY changed field (AC-15-10). A first-sight
    # record (``{"__new__": True}``) HAS changes; a no-op re-fetch (``{}``, only
    # LastModified advanced) does not; a FAILED row (no diff) does not.
    hasChanges: bool = False

    @model_validator(mode="after")
    def _derive_has_changes(self) -> "StagedRecordItem":
        self.hasChanges = bool(self.diff)
        return self


class StagedListResponse(ApiModel):
    """The staged-record review page (AC-15-10/11).

    ``total`` is the WHOLE batch (every staged row), preserving its existing
    meaning for the current review page; ``filteredTotal`` is the count matching
    the ``changed`` filter (== ``total`` when unfiltered) for page math; and
    ``noChangeCount`` lets the FE render the collapsed "N records with no field
    changes" summary WITHOUT fetching those rows.
    """

    job: SyncJobItem
    data: List[StagedRecordItem]
    total: int
    page: int = 0
    filteredTotal: int = 0
    noChangeCount: int = 0


# ── jobs / review list (plan 15 §2, AC-15-02) ─────────────────────────────────


class SyncJobBatchItem(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    jobId: str = Field(validation_alias="job_id")
    companyId: str = Field(validation_alias="company_id")
    companyName: str = Field(validation_alias="company_name")
    databaseName: str = Field(validation_alias="database_name")
    entityType: str = Field(validation_alias="entity_type")
    status: str
    progressTotal: int = Field(default=0, validation_alias="progress_total")
    progressDone: int = Field(default=0, validation_alias="progress_done")
    progressFailed: int = Field(default=0, validation_alias="progress_failed")
    createdAt: Optional[datetime] = Field(default=None, validation_alias="created_at")
    startedAt: Optional[datetime] = Field(default=None, validation_alias="started_at")
    finishedAt: Optional[datetime] = Field(default=None, validation_alias="finished_at")
    updatedAt: Optional[datetime] = Field(default=None, validation_alias="updated_at")


class SyncJobListResponse(ApiModel):
    data: List[SyncJobBatchItem]
    total: int
    page: int = 0


# ── field-mapping editor (plan 15 §2, AC-15-40..43) ───────────────────────────


class MappingRowOut(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    sourcePath: str = Field(validation_alias="source_path")
    transform: str
    # The row's safe transform formula, if any (slice 16). None ⇒ the named
    # transform is authoritative.
    formula: Optional[str] = None
    # None when the stored canonical field is not delivered to Sorento (identity /
    # watermark provenance, or an extras key) - shown non-delivered (AC-15-40).
    sorentoField: Optional[str] = Field(validation_alias="sorento_field")
    canonicalField: str = Field(validation_alias="canonical_field")
    scope: str
    isRequired: bool = Field(validation_alias="is_required")
    isEnabled: bool = Field(validation_alias="is_enabled")


class SorentoFieldOut(ApiModel):
    """One accepted Sorento target for the picker (AC-15-42) - offered set only."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    field: str
    required: bool


class MappingViewResponse(ApiModel):
    entityType: str
    rows: List[MappingRowOut]
    # The accepted Sorento targets (the picker offers ONLY these) + known
    # AutoCount source paths (discovery; a free dotted path is still allowed).
    sorentoFields: List[SorentoFieldOut]
    acFields: List[str]


class MappingUpdateRow(ApiModel):
    model_config = ConfigDict(populate_by_name=True)

    sourcePath: str
    transform: str = "string"
    sorentoField: str
    # Optional safe transform formula (slice 16). NULL/blank ⇒ the named
    # transform runs. Validated (parsed) server-side at save (AC-16-03).
    formula: Optional[str] = None


class MappingUpdateRequest(ApiModel):
    model_config = ConfigDict(populate_by_name=True)

    rows: List[MappingUpdateRow]


# ── formula catalog + simulators (plan 16 §3, AC-16-13/21/30) ─────────────────


class FormulaTestRequest(ApiModel):
    """A single-formula parity check (AC-16-21): a mock ``value`` + a formula."""

    model_config = ConfigDict(populate_by_name=True)

    formula: str
    # The mock input value - the vendor sends strings, but a number/bool/null is
    # accepted too (the evaluator coerces).
    value: Any = None


class FormulaTestResponse(ApiModel):
    ok: bool
    output: Any = None
    error: Optional[str] = None


class SimulateRequest(ApiModel):
    """A whole-mapping simulation (AC-16-30): a mock AutoCount record, optionally
    with DRAFT (unsaved) rows to preview an in-progress edit."""

    model_config = ConfigDict(populate_by_name=True)

    record: Dict[str, Any]
    rows: Optional[List[MappingUpdateRow]] = None


class SimulateFieldResult(ApiModel):
    """One field's simulated outcome - value or a named error, side by side."""

    model_config = ConfigDict(populate_by_name=True)

    scope: str
    sourcePath: str
    canonicalField: str
    present: bool
    ok: bool
    value: Any = None
    error: Optional[str] = None


class SimulateResponse(ApiModel):
    ok: bool
    sourceRef: str = ""
    docNo: Optional[str] = None
    # The projected Sorento record (every mapped field), or None when the record
    # would be REJECTED (all-or-nothing per document).
    record: Optional[Dict[str, Any]] = None
    headerFields: List[SimulateFieldResult] = []
    lineFields: List[List[SimulateFieldResult]] = []
    errors: List[Dict[str, Any]] = []


class SyncRunItem(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    entityType: str = Field(validation_alias="entity_type")
    # NULL for a ``skipped`` overlap tick - it never enqueued a job (AC-22-14).
    jobId: Optional[str] = Field(default=None, validation_alias="job_id")
    windowFrom: Optional[datetime] = Field(default=None, validation_alias="window_from")
    windowTo: Optional[datetime] = Field(default=None, validation_alias="window_to")
    fetchedCount: int = Field(default=0, validation_alias="fetched_count")
    stagedCount: int = Field(default=0, validation_alias="staged_count")
    failedCount: int = Field(default=0, validation_alias="failed_count")
    pushedCount: int = Field(default=0, validation_alias="pushed_count")
    outcome: Optional[str] = None
    error: Optional[str] = None
    # True when the record cap was hit - a truncated sync must never read as a
    # complete one (AC-13-46).
    truncated: bool = False
    watermarkAdvancedTo: Optional[datetime] = Field(
        default=None, validation_alias="watermark_advanced_to"
    )
    startedAt: Optional[datetime] = Field(default=None, validation_alias="started_at")
    finishedAt: Optional[datetime] = Field(default=None, validation_alias="finished_at")
    # ── cost columns (plan 22 §2.7, AC-22-17) ────────────────────────────────
    # Volume x frequency is the thing an operator must be able to judge, so the
    # rows READ and the wall time are first-class, not buried in a job payload.
    # Every API-path run reports ``manual`` with zero adds/updates/deletes.
    mode: str = "manual"
    rowsScanned: int = Field(default=0, validation_alias="rows_scanned")
    addedCount: int = Field(default=0, validation_alias="added_count")
    updatedCount: int = Field(default=0, validation_alias="updated_count")
    deletedCount: int = Field(default=0, validation_alias="deleted_count")
    durationMs: Optional[int] = Field(default=None, validation_alias="duration_ms")
    # Why a ``skipped`` tick never ran (the overlap guard, AC-22-14).
    skipReason: Optional[str] = Field(default=None, validation_alias="skip_reason")


class SyncRunListResponse(ApiModel):
    data: List[SyncRunItem]
    total: int
    page: int = 0


class ApprovalResponse(ApiModel):
    jobId: str
    result: Dict[str, Any]


# ── direct-DB ETL (plan 22 S1, AC-22-04..07/11) ───────────────────────────────
# The wire shapes are pinned by the phase-1 frontend contract
# (``service_frontend/services/autocount-service.ts`` + ``types/autocount.ts``).


class SqlConnectionItem(ApiModel):
    """One tenant ``sql_database`` connection the task editor may pick."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str
    dialect: str
    database: str


class SqlColumnOut(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    name: str
    type: str


class SqlTableOut(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    name: str
    columns: List[SqlColumnOut]


class SqlSchemaNodeOut(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    name: str
    tables: List[SqlTableOut]


class SqlSchemaResponse(ApiModel):
    """``GET /autocount/sql/connections/{id}/schema`` - the cached tree."""

    connectionId: str
    dialect: str
    database: str
    schemas: List[SqlSchemaNodeOut]
    introspectedAt: datetime


class SqlPreviewRequest(ApiModel):
    model_config = ConfigDict(populate_by_name=True)

    connectionId: str
    query: str = ""


class SqlPreviewResponse(ApiModel):
    """``POST /autocount/sql/preview`` - at most 100 rows; ``truncated`` is a
    fact (a 101st row existed), so the UI never presents a capped preview as
    the whole set (AC-22-06)."""

    columns: List[SqlColumnOut]
    rows: List[Dict[str, Any]]
    rowCount: int
    truncated: bool
    durationMs: int


class EtlSourceConfigIn(ApiModel):
    """The task's ``source_config`` document as the editor sends it (plan 22
    §2.4). Every field is optional on the wire - a draft may be partial; the
    service validates + normalises (AC-22-11) and 422s with ``fieldErrors``."""

    model_config = ConfigDict(populate_by_name=True)

    connectionId: Optional[str] = None
    query: str = ""
    lineQuery: Optional[str] = None
    keyColumns: List[str] = []
    watermarkColumn: Optional[str] = None
    comparedColumns: List[str] = []
    fromDate: Optional[str] = None
    incrementalMinutes: int = 15
    reconcileMode: str = "dailyAt"
    reconcileHours: Optional[int] = None
    reconcileAt: Optional[str] = None


class EtlTaskUpdate(ApiModel):
    model_config = ConfigDict(populate_by_name=True)

    sourceConfig: EtlSourceConfigIn


class EtlTaskResponse(ApiModel):
    """``GET/PUT .../etl-task`` - one per-(company, entity) DB extraction task,
    anchored on ``ac_entity_config`` (decision Q13).

    Everything below ``sourceConfig`` is READ-ONLY on the wire: it is state the
    server stamps (a save, a dry run, a run), never something the editor sends.
    """

    companyId: str
    entityType: str
    etlStatus: str
    activatedAt: Optional[datetime] = None
    sourceConfig: Dict[str, Any]
    # The saved query's result columns, from the validation preview every PUT
    # runs - the Mapping tab's source picker (AC-22-09).
    resultColumns: List[str] = []
    # The activate-once gate (AC-22-18); CLEARED by every config save.
    lastPreviewAt: Optional[datetime] = None
    lastRunAt: Optional[datetime] = None
    # The LAST RUN's task-level failure (AC-22-19). A Sorento anchor 422 lands
    # here with its code, never as a per-record failure (Appendix A6).
    lastRunError: Optional[str] = None
    lastRunErrorCode: Optional[str] = None
    # ── schedule (plan 22 S3, AC-22-12/13) ───────────────────────────────────
    # When the sweep will next fire each cadence - armed at activate/resume,
    # recomputed on every PUT. NULL for a draft/paused task (the sweep never
    # dispatches it).
    nextIncrementalAt: Optional[datetime] = None
    nextReconcileAt: Optional[datetime] = None


class EtlPreviewResponse(ApiModel):
    """``POST .../etl-task/preview`` - the initial-load dry run. ``preview`` is
    the SAME shape the batch review renders; ``task`` is the task after it (its
    ``lastPreviewAt`` stamped when the dry run completed)."""

    task: EtlTaskResponse
    preview: Dict[str, Any]


class EtlRunStartResponse(ApiModel):
    """``POST .../etl-task/run`` - the manual run just enqueued. ``runId`` is
    empty until the handler creates the run row, which under a real worker
    happens after this returns (eager dev/test runs it inline)."""

    runId: str = ""
    jobId: str
    status: str
    task: EtlTaskResponse


class PreviewResponse(ApiModel):
    """The dry-run verdict shown at the approval gate (AC-14-20). ``preview``
    carries either the per-record predictions + summary, or a "nothing to
    preview" shape for a logging-sink company - the service owns the shape."""

    jobId: str
    preview: Dict[str, Any]
