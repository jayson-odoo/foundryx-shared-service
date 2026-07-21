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

from pydantic import ConfigDict, Field

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
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    entityType: str = Field(validation_alias="entity_type")
    syncMode: str = Field(validation_alias="sync_mode")
    sourceImpl: str = Field(validation_alias="source_impl")
    recordCap: int = Field(validation_alias="record_cap")
    initialLookbackDays: int = Field(validation_alias="initial_lookback_days")
    enabled: bool


class CompanyItem(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    connectionId: str = Field(validation_alias="connection_id")
    databaseName: str = Field(validation_alias="database_name")
    companyName: str = Field(validation_alias="company_name")
    name: str
    isActive: bool = Field(validation_alias="is_active")
    createdAt: Optional[datetime] = Field(default=None, validation_alias="created_at")


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


class StagedListResponse(ApiModel):
    job: SyncJobItem
    data: List[StagedRecordItem]
    total: int


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
