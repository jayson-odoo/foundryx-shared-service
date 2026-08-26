"""Per-tenant developer-logs settings (sprint-4/12 Slice 3, AC-DLC-21) - core
``public`` table, one row per tenant. Mirrors ``workflow_settings`` shape.

``retention_days`` NULL = fall back to the global default
(``settings.integration_activity_retention_days``). A row exists only once a
tenant overrides the default; the beat pruner reads the override else the global.
"""
from sqlalchemy import Column, Integer, String

from app.database import Base


class IntegrationLogSettings(Base):
    __tablename__ = "integration_log_settings"

    tenant_id = Column(String, primary_key=True)
    retention_days = Column(Integer, nullable=True)
