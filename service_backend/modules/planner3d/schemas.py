"""Planner 3D wire shapes (camelCase, ISO-Z). Contract of record: the Phase 1
contract block of documentation/plans/planner3d-s3-gpu-worker.md."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.base import ApiModel


class JobFileOut(BaseModel):
    direction: str
    role: str
    name: str
    mime: str
    size: int
    sha256: str


class JobErrorOut(BaseModel):
    code: str
    message: str


class JobOut(ApiModel):
    id: str
    kind: str
    status: str
    engine: Optional[str] = None
    progress: int = 0
    params: Optional[Dict[str, Any]] = None
    error: Optional[JobErrorOut] = None
    gpuSeconds: Optional[float] = None
    peakRssMb: Optional[int] = None
    attempts: int = 0
    approvedCandidate: Optional[str] = None
    sourceJobId: Optional[str] = None
    files: List[JobFileOut] = []
    createdAt: datetime
    startedAt: Optional[datetime] = None
    finishedAt: Optional[datetime] = None


class JobList(BaseModel):
    items: List[JobOut]
    total: int


class ApproveRequest(BaseModel):
    candidate: str = Field(min_length=1, max_length=64)


# ── worker wire ─────────────────────────────────────────────────────────────

class ClaimRequest(BaseModel):
    kinds: List[Literal["model", "render", "convert"]] = Field(min_length=1)


class ClaimInput(BaseModel):
    role: str
    name: str
    mime: str
    size: int
    sha256: str


class ClaimResponse(BaseModel):
    jobId: str
    kind: str
    params: Optional[Dict[str, Any]] = None
    inputs: List[ClaimInput]


class HeartbeatRequest(BaseModel):
    progress: Optional[int] = Field(default=None, ge=0, le=100)


class OutputAck(BaseModel):
    name: str
    size: int
    sha256: str


class FinishError(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(default="", max_length=2000)


class FinishRequest(BaseModel):
    status: Literal["succeeded", "failed"]
    error: Optional[FinishError] = None
    gpuSeconds: Optional[float] = Field(default=None, ge=0)
    peakRssMb: Optional[float] = Field(default=None, ge=0)


# ── S1 gateway (contract 3.1-3.3; lane PLANNER-3D-S1) ───────────────────────
# Times are already ISO-Z strings (``gateway_service._z``), so plain models.


class UploadOut(BaseModel):
    id: str
    mime: str
    size: int
    sha256: str
    expiresAt: str


class DimensionsMm(BaseModel):
    length: float = Field(gt=0, le=100000)
    width: float = Field(gt=0, le=100000)
    height: float = Field(gt=0, le=100000)


class CreateModelRequest(BaseModel):
    productCode: str = Field(min_length=1, max_length=100)
    uploadIds: List[str] = Field(min_length=1, max_length=3)
    dimensionsMm: DimensionsMm
    company: Optional[str] = Field(default=None, max_length=100)
    engine: Optional[Literal["default"]] = None


class GatewayFileOut(BaseModel):
    role: str
    name: str
    mime: str
    size: int
    sha256: str
    url: str
    expiresAt: str


class GatewayResult(BaseModel):
    files: List[GatewayFileOut] = []


class GatewayInput(BaseModel):
    productCode: Optional[str] = None
    company: Optional[str] = None
    uploadIds: List[str] = []
    dimensionsMm: Optional[Dict[str, float]] = None


class GatewayUsage(BaseModel):
    gpuSeconds: Optional[int] = None
    paidCost: Optional[Dict[str, str]] = None


class GatewayJobOut(BaseModel):
    id: str
    kind: str
    status: str
    engine: Optional[str] = None
    createdAt: Optional[str] = None
    startedAt: Optional[str] = None
    finishedAt: Optional[str] = None
    progress: int = 0
    input: GatewayInput
    result: GatewayResult
    error: Optional[JobErrorOut] = None
    sourceJobId: Optional[str] = None
    approvedCandidate: Optional[str] = None
    usage: GatewayUsage


# ── S1 staff: keys + receivers ──────────────────────────────────────────────


class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class KeyItem(ApiModel):
    id: str
    name: str
    keyMasked: str
    createdAt: datetime
    lastUsedAt: Optional[datetime] = None
    revokedAt: Optional[datetime] = None


class KeyCreated(KeyItem):
    key: str


class KeyList(BaseModel):
    data: List[KeyItem]


class ReceiverCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    events: List[str] = Field(min_length=1, max_length=10)


class ReceiverItem(ApiModel):
    id: str
    url: str
    events: List[str]
    createdAt: datetime
    lastSuccessAt: Optional[datetime] = None


class ReceiverCreated(ReceiverItem):
    secret: str


class ReceiverList(BaseModel):
    data: List[ReceiverItem]
