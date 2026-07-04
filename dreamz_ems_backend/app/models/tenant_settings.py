"""Per-tenant general settings (sprint-4/08) — ``public`` schema.

A general per-tenant config row (modeled on ``workflow_settings``/``import_settings``
but cross-feature). First field = ``default_currency`` (catalog + quotation
default). Room to grow (locale, number format, …). A row exists only once a
tenant overrides a default; absence = app defaults.
"""
from sqlalchemy import Column, Integer, String
from sqlalchemy.sql import func

from app.database import Base
from app.models.utc_datetime import UTCDateTime

# App-wide fallbacks when a tenant has no row / NULL value.
DEFAULT_CURRENCY = "USD"
DEFAULT_PRICE_DECIMALS = 2


class TenantSettings(Base):
    __tablename__ = "tenant_settings"

    tenant_id = Column(String, primary_key=True)
    default_currency = Column(String, nullable=True)  # ISO-4217; NULL = app default
    price_decimals = Column(Integer, nullable=True)  # money display DP; NULL = app default
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())
