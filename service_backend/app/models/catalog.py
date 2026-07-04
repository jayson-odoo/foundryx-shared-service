"""Core catalog models (sprint-4/08) — ``public`` schema, horizontal.

Moved out of ``modules/ems`` (wrong boundary): products + categories are
consumed by CRM quotations, EMS ticketing, and future commerce, so they are
core. ``Product.kind`` is a registry key (validated against the active
product-kind registry, NEVER an enum branch). Money columns are ``Numeric`` (exact
cents), not Float. ``Product.currency`` is a per-product override; effective
currency = product.currency or the tenant default (``tenant_settings``).
"""
import uuid

from sqlalchemy import Boolean, Column, ForeignKey, Integer, Numeric, String
from sqlalchemy.sql import func

from app.database import Base
from app.models.utc_datetime import UTCDateTime

MONEY = Numeric(14, 4)


def _uuid() -> str:
    return str(uuid.uuid4())


class ProductCategory(Base):
    """Self-referencing taxonomy tree — classification/reporting only. Code never
    branches on category; behavior (if any) comes from product ``kind``."""

    __tablename__ = "product_categories"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    parent_id = Column(String, ForeignKey("product_categories.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    sort = Column(Integer, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())


class Product(Base):
    """Tenant product catalog. ``kind`` = registry key (metadata facet, not a
    behavior branch). ``is_active`` is a plain flag (NOT the status engine).
    Soft-delete ONLY (no hard delete), and a delete is BLOCKED while any module
    reports the product in use (reference-guard registry). Quotation lines + future
    ticketing reference these; line values are snapshot-immutable at add."""

    __tablename__ = "products"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    category_id = Column(String, ForeignKey("product_categories.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    sku = Column(String, nullable=True)
    kind = Column(String, nullable=False, default="service")  # product-kind registry key
    default_price = Column(MONEY, nullable=True)
    tax = Column(MONEY, nullable=True)
    currency = Column(String, nullable=True)  # per-product override; else tenant default
    uom = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())
