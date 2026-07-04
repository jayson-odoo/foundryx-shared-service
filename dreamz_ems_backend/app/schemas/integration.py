"""Integration schemas (plan 09 §6) — camelCase on the wire.

Credentials are WRITE-ONLY: accepted on create/update, never serialized back.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import Field

from app.schemas.base import ApiModel


class ProviderOut(ApiModel):
    """Catalog entry — `fields` is the config schema driving the wizard."""

    provider: str
    type: str
    title: str
    description: str
    icon: Optional[str] = None
    fields: List[Dict[str, Any]]
    testLabel: str
    testTarget: Optional[Dict[str, str]] = None


class ConnectionOut(ApiModel):
    id: str
    tenantId: str
    provider: str
    type: str
    name: str
    # Non-secret config only — camelCase keys for the frontend.
    config: Dict[str, str]
    status: str
    lastTestedAt: Optional[datetime] = None
    lastError: Optional[str] = None
    rateLimitPerMinute: int
    createdAt: datetime
    updatedAt: datetime


class ConnectionCreateRequest(ApiModel):
    provider: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=120)
    config: Dict[str, str] = Field(default_factory=dict)
    # Write-only secrets; on update an omitted key keeps the stored value.
    credentials: Dict[str, str] = Field(default_factory=dict)
    rateLimitPerMinute: int = Field(default=30, ge=1, le=600)


class ConnectionUpdateRequest(ApiModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    config: Optional[Dict[str, str]] = None
    credentials: Optional[Dict[str, str]] = None
    rateLimitPerMinute: Optional[int] = Field(default=None, ge=1, le=600)


class ConnectionListResponse(ApiModel):
    """Resource-shell page (plan 06 D6) — like every list entity."""

    data: List[ConnectionOut]
    total: int
    page: int


class ConnectionNeighborResponse(ApiModel):
    """Record-nav: the connection at `index` under the carried query."""

    connection: Optional[ConnectionOut] = None
    total: int


class TestRequest(ApiModel):
    # Optional targeted test (SMTP: recipient). Absent = connection check.
    target: Optional[str] = Field(default=None, max_length=254)


class TestResultOut(ApiModel):
    ok: bool
    message: str
    checkedAt: datetime
