"""Connector admin wire schemas (camelCase, Z-suffixed datetimes)."""
from datetime import datetime
from typing import List, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import ApiModel


class GrantItem(ApiModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    product: str
    product_user_id: str = Field(serialization_alias="productUserId")
    name: Optional[str] = None
    email: Optional[str] = None
    client_id: str = Field(serialization_alias="clientId")
    consented_at: datetime = Field(serialization_alias="consentedAt")
    status: str
    revoked_reason: Optional[str] = Field(default=None, serialization_alias="revokedReason")
    last_used_at: Optional[datetime] = Field(default=None, serialization_alias="lastUsedAt")
    created_at: datetime = Field(serialization_alias="createdAt")


class GrantPage(ApiModel):
    data: List[GrantItem]
    total: int
    page: int
    page_size: int = Field(serialization_alias="pageSize")
