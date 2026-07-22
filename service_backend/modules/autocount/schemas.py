"""AutoCount wire schemas — camelCase out, ``ApiModel`` for Z-suffixed UTC.

House shape (matches every other schema in the codebase): the field NAME is
camelCase and ``validation_alias`` names the snake_case ORM attribute, with
``from_attributes`` doing the mapping. Every schema carrying a datetime inherits
``ApiModel`` — aware-UTC columns already emit ``Z``, and the base is the
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
    overridden (AC-13-01, foolproof-UI — never ask for something we determine).
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
    # Default 30 — anything older is invisible until the supervised full initial
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
    # The high-water mark itself — "we have everything modified up to here".
    watermarkAt: Optional[datetime] = Field(default=None, validation_alias="watermark_at")
    consecutiveFailures: int = Field(default=0, validation_alias="consecutive_failures")
    lastError: Optional[str] = Field(default=None, validation_alias="last_error")


class EntityConfigUpdate(ApiModel):
    """Editable slice of an entity's sync configuration.

    Deliberately narrow. Changing the lookback does NOT re-fetch history — it
    only governs the window used when no watermark exists yet.
    """

    model_config = ConfigDict(populate_by_name=True)

    initialLookbackDays: Optional[int] = None


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
    createdAt: Optional[datetime] = Field(default=None, validation_alias="created_at")


class CompanySinkUpdate(ApiModel):
    """Point a company at a push target (plan 14 hop 2 — operator wiring).

    ``sinkImpl='logging'`` clears the target (the no-op default);
    ``sinkImpl='sorento'`` requires a ``sinkConnectionId`` naming a Sorento
    ``consumer`` connection for this tenant.
    """

    model_config = ConfigDict(populate_by_name=True)

    sinkImpl: str
    sinkConnectionId: Optional[str] = None


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
    # Changed fields ONLY — unchanged fields are never reported as changes
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
    # None when the stored canonical field is not delivered to Sorento (identity /
    # watermark provenance, or an extras key) — shown non-delivered (AC-15-40).
    sorentoField: Optional[str] = Field(validation_alias="sorento_field")
    canonicalField: str = Field(validation_alias="canonical_field")
    scope: str
    isRequired: bool = Field(validation_alias="is_required")
    isEnabled: bool = Field(validation_alias="is_enabled")


class SorentoFieldOut(ApiModel):
    """One accepted Sorento target for the picker (AC-15-42) — offered set only."""

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


class MappingUpdateRequest(ApiModel):
    model_config = ConfigDict(populate_by_name=True)

    rows: List[MappingUpdateRow]


class SyncRunItem(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    entityType: str = Field(validation_alias="entity_type")
    jobId: str = Field(validation_alias="job_id")
    windowFrom: Optional[datetime] = Field(default=None, validation_alias="window_from")
    windowTo: Optional[datetime] = Field(default=None, validation_alias="window_to")
    fetchedCount: int = Field(default=0, validation_alias="fetched_count")
    stagedCount: int = Field(default=0, validation_alias="staged_count")
    failedCount: int = Field(default=0, validation_alias="failed_count")
    pushedCount: int = Field(default=0, validation_alias="pushed_count")
    outcome: Optional[str] = None
    error: Optional[str] = None
    # True when the record cap was hit — a truncated sync must never read as a
    # complete one (AC-13-46).
    truncated: bool = False
    watermarkAdvancedTo: Optional[datetime] = Field(
        default=None, validation_alias="watermark_advanced_to"
    )
    startedAt: Optional[datetime] = Field(default=None, validation_alias="started_at")
    finishedAt: Optional[datetime] = Field(default=None, validation_alias="finished_at")


class SyncRunListResponse(ApiModel):
    data: List[SyncRunItem]
    total: int
    page: int = 0


class ApprovalResponse(ApiModel):
    jobId: str
    result: Dict[str, Any]


class PreviewResponse(ApiModel):
    """The dry-run verdict shown at the approval gate (AC-14-20). ``preview``
    carries either the per-record predictions + summary, or a "nothing to
    preview" shape for a logging-sink company — the service owns the shape."""

    jobId: str
    preview: Dict[str, Any]
