"""Core catalog wire schemas (sprint-4/08). camelCase via ApiModel. Money is
Decimal on the model; exposed as float on the wire."""
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import ApiModel


class _Base(ApiModel):
    model_config = ConfigDict(from_attributes=True)


def _money(v) -> Optional[float]:
    return None if v is None else float(v)


class CategoryOut(_Base):
    id: str
    parentId: Optional[str] = Field(default=None, validation_alias="parent_id")
    name: str
    sort: Optional[int] = None


class CategoryIn(ApiModel):
    name: str
    parentId: Optional[str] = None
    sort: Optional[int] = None


class CategoryPatch(ApiModel):
    name: Optional[str] = None
    parentId: Optional[str] = None
    sort: Optional[int] = None


class ProductKindOut(ApiModel):
    key: str
    label: str


class ProductOut(_Base):
    id: str
    categoryId: Optional[str] = Field(default=None, validation_alias="category_id")
    name: str
    sku: Optional[str] = None
    kind: str
    kindLabel: Optional[str] = None  # humanized (handles hidden/orphaned kinds)
    defaultPrice: Optional[float] = Field(default=None, validation_alias="default_price")
    tax: Optional[float] = None
    currency: Optional[str] = None
    uom: Optional[str] = None
    isActive: bool = Field(validation_alias="is_active")
    createdAt: datetime = Field(validation_alias="created_at")

    @classmethod
    def from_row(cls, row, kind_label: str) -> "ProductOut":
        return cls(
            id=row.id,
            category_id=row.category_id,
            name=row.name,
            sku=row.sku,
            kind=row.kind,
            kindLabel=kind_label,
            default_price=_money(row.default_price),
            tax=_money(row.tax),
            currency=row.currency,
            uom=row.uom,
            is_active=row.is_active,
            created_at=row.created_at,
        )


class ProductIn(ApiModel):
    name: str
    kind: str = "service"
    categoryId: Optional[str] = None
    sku: Optional[str] = None
    defaultPrice: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    currency: Optional[str] = None
    uom: Optional[str] = None
    isActive: bool = True


class ProductPatch(ApiModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    categoryId: Optional[str] = None
    sku: Optional[str] = None
    defaultPrice: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    currency: Optional[str] = None
    uom: Optional[str] = None
    isActive: Optional[bool] = None


class TenantSettingsOut(ApiModel):
    defaultCurrency: str
    priceDecimals: int


class TenantSettingsPatch(ApiModel):
    defaultCurrency: Optional[str] = None
    priceDecimals: Optional[int] = None


class ListResponse(ApiModel):
    items: list
    total: int
    page: int
    pageSize: int


class ExportRequest(ApiModel):
    columns: List[str]
    ids: Optional[List[str]] = None
    search: Optional[str] = None
    trashed: bool = False
