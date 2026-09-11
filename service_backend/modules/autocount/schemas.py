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
from typing import Any, Dict, List, Literal, Optional

from pydantic import ConfigDict, Field, model_validator

from app.schemas.base import ApiModel

from .sql_source.source import MAX_DOCUMENT_LINES_PER_HEADER


# ── companies ─────────────────────────────────────────────────────────────────


class CompanyCreate(ApiModel):
    """The operator supplies ONLY a connection (and an optional label).

    There is deliberately no company field: the identity is DISCOVERED - from
    the vendor login for an ``autocount`` connection (the API resolves the
    company from the ``AppId`` header, so any value typed here would be
    silently overridden, AC-13-01) or from the connection's own ``database``,
    verified by a live probe, for a ``sql_database`` connection (plan
    sprint-5/01 AC-01-02). Foolproof-UI: never ask for something we determine.
    """

    model_config = ConfigDict(populate_by_name=True)

    connectionId: str
    name: str = ""
    # sprint-5/08 (AC-08-06/07) - required, operator-typed, ONLY for an open
    # (no-auth) API connection; ``None`` for every other connection kind
    # (a value here on a vendor/SQL connection is a 422 "not applicable").
    refPrefix: Optional[str] = None


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
    # The DB-task lifecycle (plan 22 §2.4, AC-22-23) - surfaced on the LIST so
    # the task editor's Review & Activate tab can warn a `product` task's
    # activation of a missing category/UOM prerequisite without a second fetch.
    etlStatus: str = Field(default="draft", validation_alias="etl_status")


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


class DocumentPrerequisiteOut(ApiModel):
    """One configured document entity's prerequisite-master status (plan
    sprint-5/01, AC-01-11). ``missing`` = no config row; ``inactive`` = a row
    that is not ``active`` or is disabled. Detail only - the list carries
    ``[]`` (pinned by the phase-1 frontend contract)."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    entityType: str = Field(validation_alias="entity_type")
    missing: List[str] = []
    inactive: List[str] = []


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
    # ── plan sprint-5/01 (AC-01-07/11) - DERIVED, set by the router from the
    # service, never read off the row (``ac_company`` stores no kind): how the
    # company is connected (``'api'`` = vendor HTTP API, ``'db'`` = a direct
    # ``sql_database`` connection) and, on the DETAIL only, the prerequisite-
    # master status of each configured document entity.
    sourceKind: Literal["api", "db", "http"] = "api"
    documentPrerequisites: List[DocumentPrerequisiteOut] = []


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
    # sprint-5/02 (AC-02-02) - a document entity's LINE catalog. Empty for a
    # non-document entity (master/GRN have no line scope).
    lineSorentoFields: List[SorentoFieldOut] = []
    lineAcFields: List[str] = []


class MappingUpdateRow(ApiModel):
    model_config = ConfigDict(populate_by_name=True)

    sourcePath: str
    transform: str = "string"
    sorentoField: str
    # Optional safe transform formula (slice 16). NULL/blank ⇒ the named
    # transform runs. Validated (parsed) server-side at save (AC-16-03).
    formula: Optional[str] = None
    # sprint-5/02 (AC-02-01) - which scope this row targets. Defaulting to
    # ``header`` reproduces every pre-existing (master/GRN) save request.
    # A `Literal` (S8, review nit) - "header"/"line" are the only two scopes
    # this engine has ever had (SCOPE_HEADER/SCOPE_LINE in mapping.py); a
    # typo'd third value should 422 at the wire boundary, not silently
    # coerce through `getattr(row, "scope", SCOPE_HEADER) != SCOPE_LINE`
    # everywhere it is read.
    scope: Literal["header", "line"] = "header"
    # R1 (code-review round) - write-side twin of the read-side
    # `MappingRowOut.isEnabled`. A backfill/preset can seed a fixed-field
    # line row disabled (its source_path doesn't match a real preview
    # column); the operator toggles it once they've fixed the source
    # column, or leaves it disabled to save the rest of the draft.
    isEnabled: bool = True


class MappingUpdateRequest(ApiModel):
    """``PUT .../mapping`` body.

    ``lineRows`` is the WIRE SIGNAL a header-only save needs and could never
    express before (security re-review should-fix, sprint-5/02 review round):
    a document entity's line rows are a SEPARATE scope from ``rows`` (header)
    now - ``None``/absent = line scope untouched this save, ``[]`` = the
    operator explicitly cleared every line row (wipe), a non-empty list =
    replace the line set with exactly what was submitted. Threading this
    tri-state through required a dedicated field - ``rows`` alone can never
    distinguish "no lineRows key at all" from "lineRows: []" once both arrive
    as an empty slice.

    Backward compat (one release): a caller that still sends its line rows
    INSIDE ``rows`` (``scope: "line"`` items mixed in, the pre-existing
    shape) is honoured exactly as before - those rows count as a submitted
    line scope too, same as a non-empty ``lineRows``. The router folds both
    sources together before handing them to ``CompanyService.replace_
    mapping``.
    """

    model_config = ConfigDict(populate_by_name=True)

    rows: List[MappingUpdateRow]
    lineRows: Optional[List[MappingUpdateRow]] = None


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
    # A sane defensive cap (review-round nit) - a mapping draft is operator-
    # authored (a handful to a few dozen rows per entity in practice); this
    # is not a real business constant, just a ceiling against a pathological
    # payload reaching the simulator unbounded.
    rows: Optional[List[MappingUpdateRow]] = Field(default=None, max_length=500)
    # sprint-5/02 (AC-02-22) - a document entity's fetched line records for
    # the picked header, so Simulate can preview the header AND its lines
    # together (aggregates, status formula) without saving anything. Capped
    # at the SAME ceiling the live SQL source enforces per header
    # (``MAX_DOCUMENT_LINES_PER_HEADER``, review-round nit) - Simulate must
    # never accept a payload the real pipeline would already have rejected.
    lines: Optional[List[Dict[str, Any]]] = Field(
        default=None, max_length=MAX_DOCUMENT_LINES_PER_HEADER
    )


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
    # sprint-5/02 (AC-02-22) - the mapped document's `status`, mirrored to the
    # top level for a document simulate (None for a non-document entity, or
    # when the record was rejected).
    status: Optional[str] = None


class MappingPresetOut(ApiModel):
    """One documented AutoCount SQL-pack preset for a document entity
    (sprint-5/02 S3, AC-02-16 "Use preset" action) - database-substituted,
    read-only. Empty list from the endpoint = no preset registered for this
    entity (a non-document entity, or a family not yet documented)."""

    model_config = ConfigDict(populate_by_name=True)

    entityType: str
    label: str
    headerQuery: str
    lineQuery: Optional[str] = None
    keyColumns: List[str] = []
    watermarkColumn: Optional[str] = None
    docDateColumn: Optional[str] = None
    fromDate: Optional[str] = None
    filterFormula: Optional[str] = None


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
    # ── push request accounting (fix/push-marks-per-chunk, prod 2026-09-07) ──
    # How many chunk POSTs this run's push made, how many of them failed, and
    # the first one's account (``{status, message}``) - an operator reading
    # `pushed_count 0` / `error` alone could not tell a lone chunk-level
    # fault from total silence.
    requests: Optional[int] = Field(default=None, validation_alias="requests")
    requestsFailed: Optional[int] = Field(default=None, validation_alias="requests_failed")
    firstFailure: Optional[Dict[str, Any]] = Field(
        default=None, validation_alias="first_failure"
    )


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
    # Plan 22 S5 - previewing a document's ``lineQuery`` (which carries a
    # ``:doc_key`` bound param). ``bindDocKey=false`` (every non-document
    # preview) runs the query exactly as before; ``true`` binds ``docKey``
    # (blank/None = a harmless NULL bind, just enough to let the query
    # execute for column discovery) - a SEPARATE flag from the value itself
    # because an ordinary header-query preview also sends no ``docKey`` and
    # must NOT be treated as parameterized.
    bindDocKey: bool = False
    docKey: Optional[str] = None


class SqlPreviewResponse(ApiModel):
    """``POST /autocount/sql/preview`` - at most 100 rows; ``truncated`` is a
    fact (a 101st row existed), so the UI never presents a capped preview as
    the whole set (AC-22-06)."""

    columns: List[SqlColumnOut]
    rows: List[Dict[str, Any]]
    rowCount: int
    truncated: bool
    durationMs: int


# ── open REST API source (sprint-5/08, AC-08-14/15) ───────────────────────────


class HttpConnectionItem(ApiModel):
    """One tenant ``autocount`` connection the Source tab's API picker may
    pick, badged by its auth mode (AC-08-15)."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str
    baseUrl: str = Field(default="", validation_alias="base_url")
    auth: Literal["basic", "none"] = "basic"


class HttpPreviewRequest(ApiModel):
    model_config = ConfigDict(populate_by_name=True)

    connectionId: str
    path: str = ""
    distinctOf: Optional[List[str]] = None
    # When both are given, the preview also records `resultColumns`/
    # `lastPreviewAt` on the task (AC-08-14) - exactly as the SQL preview
    # does, so the Source tab's column pickers see it without a second call.
    companyId: Optional[str] = None
    entityType: Optional[str] = None


class HttpPreviewColumnOut(ApiModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    sample: Optional[str] = None


class HttpPreviewResponse(ApiModel):
    """``POST /autocount/http/preview`` - one page-1 sample (AC-08-14)."""

    envelope: Literal["paged", "list"]
    totalCount: Optional[int] = None
    columns: List[HttpPreviewColumnOut] = []
    rows: List[Dict[str, Any]] = []
    durationMs: int = 0


class EtlSourceConfigIn(ApiModel):
    """The task's ``source_config`` document as the editor sends it (plan 22
    §2.4). Every field is optional on the wire - a draft may be partial; the
    service validates + normalises (AC-22-11) and 422s with ``fieldErrors``."""

    model_config = ConfigDict(populate_by_name=True)

    connectionId: Optional[str] = None
    # sprint-5/08 (AC-08-13) - which fetch implementation this task saves as.
    # ``None``/``'sql_db'`` keep the SQL shape below; ``'autocount_http'``
    # routes to the HTTP shape at the bottom of this schema - ONE envelope,
    # never a second endpoint. A stray key from the OTHER shape is simply not
    # copied into the clean config the service persists (dropped, never 422).
    sourceImpl: Optional[str] = None
    query: str = ""
    lineQuery: Optional[str] = None
    keyColumns: List[str] = []
    watermarkColumn: Optional[str] = None
    comparedColumns: List[str] = []
    fromDate: Optional[str] = None
    # ── documents only (plan 22 S5) ───────────────────────────────────────
    # The header column the from-date filters (a document's OWN date, e.g.
    # `DocDate` - deliberately separate from `watermarkColumn`/`LastModified`,
    # which drives change detection, not the sync's date floor).
    docDateColumn: Optional[str] = None
    # sprint-5/02 (AC-02-11) - a document task's optional header filter,
    # authored ONLY via the AutocountFormulaBuilder (never free text). The
    # line-column pickers this slot replaces (`lineKeyColumn`/
    # `lineProductColumn`/`lineWarehouseColumn`) are gone - a document's line
    # fields are persisted `ac_field_mapping` rows now (AC-02-01), saved
    # through the mapping editor's PUT, not this task-config PUT.
    filterFormula: Optional[str] = None
    incrementalMinutes: int = 15
    reconcileMode: str = "dailyAt"
    reconcileHours: Optional[int] = None
    reconcileAt: Optional[str] = None
    # ── HTTP (open REST API) shape only (sprint-5/08, AC-08-13) ──────────────
    path: Optional[str] = None
    keyFields: List[str] = []
    watermarkField: Optional[str] = None
    comparedFields: List[str] = []
    distinctOf: Optional[List[str]] = None


class InitialLoadProgress(ApiModel):
    """A paged pass in progress (plan sprint-5/03 S1/S4, AC-03-03/21) - the
    wire shape of ``AcWatermark.cursor_json["pass"]``, typed (NIT, review
    round 2 - was a bare ``Dict[str, Any]``, which let the shape drift
    silently)."""

    complete: bool
    pagesDone: int
    lastMark: Optional[Any] = None
    kind: Optional[str] = None


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
    # sprint-5/08 (AC-08-30) - which fetch implementation this task saves as.
    sourceImpl: str = "sql_db"
    sourceConfig: Dict[str, Any]
    # The saved query's result columns, from the validation preview every PUT
    # runs - the Mapping tab's source picker (AC-22-09).
    resultColumns: List[str] = []
    # The saved LINE query's result columns (sprint-5/02, AC-02-06) - the
    # Mapping tab's Line-fields source picker.
    lineResultColumns: List[str] = []
    # The activate-once gate (AC-22-18); CLEARED by every config save.
    lastPreviewAt: Optional[datetime] = None
    # The last preview's genuinely-``failed`` count (S5 review SHOULD-FIX 4b) -
    # NOT ``retryable``. ``activate_task`` refuses while this is truthy.
    lastPreviewFailedCount: Optional[int] = None
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
    # ── continuation (plan sprint-5/03 S1/S4, AC-03-03/21) ───────────────────
    # A paged pass in progress (initial, incremental or reconcile) - derived
    # from ``AcWatermark.cursor_json["pass"]``. ``None`` once no pass is open
    # (never configured, or the last one completed) - the FE offers no
    # "continues" affordance in that case.
    initialLoad: Optional[InitialLoadProgress] = None


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


class EtlRepushResponse(ApiModel):
    """``POST .../etl-task/repush`` (plan sprint-5/07, AC-07-13..19) - clears
    this task's change-tracking rows so the next reconcile re-pushes every
    document. ``nextReconcileAt`` mirrors what the server armed: ``now(utc)``
    for an `active` task (the next sweep claims a reconcile), ``None`` for a
    `paused` one (nothing scheduled until resumed). ``status`` is the task's
    `etlStatus`, unchanged by this call."""

    clearedCount: int
    nextReconcileAt: Optional[datetime] = None
    status: str


class PreviewResponse(ApiModel):
    """The dry-run verdict shown at the approval gate (AC-14-20). ``preview``
    carries either the per-record predictions + summary, or a "nothing to
    preview" shape for a logging-sink company - the service owns the shape."""

    jobId: str
    preview: Dict[str, Any]
