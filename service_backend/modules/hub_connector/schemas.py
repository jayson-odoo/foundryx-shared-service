"""Hub Connector wire shapes (camelCase; datetime-bearing models inherit ApiModel)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.base import ApiModel


class Option(BaseModel):
    code: str
    name: str


class OptionList(BaseModel):
    data: List[Option]


class HubItem(ApiModel):
    id: str
    name: str
    code: str
    callbackUrl: Optional[str] = None
    exposePrice: bool
    active: bool
    customerCount: int = 0
    lastSuccessAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class HubPage(BaseModel):
    data: List[HubItem]
    total: int


class HubCreate(BaseModel):
    name: str = Field(max_length=200)
    code: str = Field(max_length=64)
    callbackUrl: Optional[str] = Field(default=None, max_length=2000)
    exposePrice: bool = False


class HubCreated(BaseModel):
    hub: HubItem
    signingSecret: str


class HubUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    callbackUrl: Optional[str] = Field(default=None, max_length=2000)
    exposePrice: Optional[bool] = None
    active: Optional[bool] = None


class SecretOut(BaseModel):
    signingSecret: str


class QueuedOut(BaseModel):
    queued: int


class HubCustomerItem(ApiModel):
    id: str
    hubId: str
    customerCode: str
    customerName: str
    locationCodes: List[str]
    brandCodes: List[str]
    locations: List[Option]
    brands: List[Option]
    active: bool
    updatedAt: Optional[datetime] = None


class HubCustomerPage(BaseModel):
    data: List[HubCustomerItem]
    total: int


class HubCustomerCreate(BaseModel):
    customerCode: str = Field(max_length=64)
    customerName: str = Field(max_length=300)
    locationCodes: List[str] = Field(default_factory=list, max_length=500)
    brandCodes: List[str] = Field(default_factory=list, max_length=500)


class HubCustomerUpdate(BaseModel):
    customerName: Optional[str] = Field(default=None, max_length=300)
    locationCodes: Optional[List[str]] = Field(default=None, max_length=500)
    brandCodes: Optional[List[str]] = Field(default=None, max_length=500)
    active: Optional[bool] = None


class PreviewOut(BaseModel):
    items: List[Dict[str, Any]]


class DeliveryItem(ApiModel):
    id: str
    event: str
    customerCode: Optional[str] = None
    customerName: Optional[str] = None
    itemCount: int = 0
    status: str
    attempt: int
    lastCode: Optional[int] = None
    lastError: Optional[str] = None
    createdAt: Optional[datetime] = None
    lastAttemptAt: Optional[datetime] = None


class DeliveryPage(BaseModel):
    data: List[DeliveryItem]
    total: int


class KeyItem(ApiModel):
    id: str
    name: str
    masked: str
    createdAt: Optional[datetime] = None
    lastUsedAt: Optional[datetime] = None
    revokedAt: Optional[datetime] = None


class KeyCreated(KeyItem):
    key: str


class KeyList(BaseModel):
    data: List[KeyItem]


class KeyCreate(BaseModel):
    name: str = Field(default="", max_length=200)


# ── hub read API ────────────────────────────────────────────────────────────

class HubProductPage(BaseModel):
    data: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


class SyncStateOut(ApiModel):
    configured: bool
    lastRunAt: Optional[datetime] = None
    lastSuccessAt: Optional[datetime] = None
    lastError: Optional[str] = None
    products: int = 0
    queued: int = 0
