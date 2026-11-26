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
