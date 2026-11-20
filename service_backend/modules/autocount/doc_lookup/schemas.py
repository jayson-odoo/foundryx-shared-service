"""Doc finder wire shapes (sprint-5/17) - camelCase, datetimes via ApiModel."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.base import ApiModel

from ..models import DOC_LOOKUP_MAX_WINDOW_DAYS


class DocTypeOut(BaseModel):
    key: str
    label: str
    prefixes: List[str]
    hasLastModified: bool
    hasByDocNo: bool
    connected: Optional[bool] = None


class DocTypeListOut(BaseModel):
    data: List[DocTypeOut]


class SnapshotSightingOut(ApiModel):
    snapshotId: str
    createdAt: Optional[datetime] = None
    extractedAt: Optional[datetime] = None
    fromDay: Optional[str] = None
    toDay: Optional[str] = None
    byNumber: bool = False
    docKey: Optional[int] = None
    docDate: Optional[str] = None
    lastModified: Optional[str] = None
    cancelled: bool = False


class LedgerSightingOut(ApiModel):
    docKey: Optional[int] = None
    docDate: Optional[str] = None
    sourceModifiedAt: Optional[datetime] = None
    lastOutcome: Optional[str] = None
    pushedAt: Optional[datetime] = None
    vanishedAt: Optional[datetime] = None


class StoredLookupOut(ApiModel):
    docType: str
    docNo: str
    snapshots: List[SnapshotSightingOut]
    ledger: Optional[LedgerSightingOut] = None


class DocLookupStartIn(BaseModel):
    companyId: str
    docNo: str
    docType: Optional[str] = None
    aroundDay: Optional[str] = None


class DocLookupJobOut(ApiModel):
    jobId: str
    status: str
    companyId: Optional[str] = None
    docNo: Optional[str] = None
    docType: Optional[str] = None
    progressDone: int = 0
    progressTotal: int = 0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    createdAt: Optional[datetime] = None
    finishedAt: Optional[datetime] = None


class DocLookupSettingsIn(BaseModel):
    companyId: str
    lastModifiedBackDays: int = Field(ge=0, le=DOC_LOOKUP_MAX_WINDOW_DAYS)
    docDateForwardDays: int = Field(ge=0, le=DOC_LOOKUP_MAX_WINDOW_DAYS)


class DocLookupSettingsOut(BaseModel):
    companyId: str
    lastModifiedBackDays: int
    docDateForwardDays: int
