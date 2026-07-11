"""Integration-activity wire schemas (sprint-4/12) — camelCase, Z-datetimes.

The list item is the console-row projection; the detail adds the redacted
request/response summaries. Both inherit ``ApiModel`` (the datetime→Z net).
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import ApiModel


class IntegrationActivityItem(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    tenantId: str = Field(validation_alias="tenant_id")
    traceId: Optional[str] = Field(default=None, validation_alias="trace_id")
    source: str
    workspaceId: Optional[str] = Field(default=None, validation_alias="workspace_id")
    apiKeyId: Optional[str] = Field(default=None, validation_alias="api_key_id")
    operation: str
    method: Optional[str] = None
    status: str
    statusCode: Optional[int] = Field(default=None, validation_alias="status_code")
    errorCode: Optional[str] = Field(default=None, validation_alias="error_code")
    latencyMs: Optional[int] = Field(default=None, validation_alias="latency_ms")
    externalRef: Optional[str] = Field(default=None, validation_alias="external_ref")
    createdAt: datetime = Field(validation_alias="created_at")


class IntegrationActivityDetail(IntegrationActivityItem):
    errorMessage: Optional[str] = Field(default=None, validation_alias="error_message")
    requestSummary: Optional[Dict[str, Any]] = Field(
        default=None, validation_alias="request_summary_json"
    )
    responseSummary: Optional[Dict[str, Any]] = Field(
        default=None, validation_alias="response_summary_json"
    )


class IntegrationActivityListResponse(ApiModel):
    data: List[IntegrationActivityItem]
    total: int
    page: int


class IntegrationActivityTraceResponse(ApiModel):
    """The ordered legs (oldest→newest) of ONE consumption — inbound API →
    outbound Meta → webhook delivery — for the trace timeline (AC-DLC-17/18)."""

    traceId: str
    legs: List[IntegrationActivityItem]


class IntegrationLogSettingsOut(ApiModel):
    """Per-tenant developer-logs retention (AC-DLC-21). ``isDefault`` = using the
    deployment default (no per-tenant override)."""

    retention_days: int = Field(serialization_alias="retentionDays")
    is_default: bool = Field(serialization_alias="isDefault")


class IntegrationLogSettingsUpdate(BaseModel):
    retentionDays: int = Field(ge=1, le=3650)
