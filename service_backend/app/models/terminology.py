"""Terminology overrides (sprint-3/08, F10) — per-tenant entity relabeling.

The DB table + code names stay fixed (an immutable contract); only the
**display label** is configurable. A row exists only when a tenant has
overridden a registered entity key; absence = use the code-side ``TermDef``
default. Reset = delete the row.

Two-form storage (D3): English irregulars (Person/People) make naive
pluralization wrong, so an override supplies BOTH ``singular`` and ``plural``.
Per-tenant only (D4) — no platform-tier fork; the "default" is the code value.
"""
import uuid

from sqlalchemy import Column, ForeignKey, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base
from app.models.utc_datetime import UTCDateTime


class TerminologyOverride(Base):
    __tablename__ = "terminology_overrides"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "entity_key", name="uq_terminology_tenant_entity"
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(
        String, ForeignKey("tenants.id"), nullable=False, index=True
    )
    # The registered TermDef key (e.g. "form"). Validated against the registry
    # at write time — an unknown key is a 422 (must be registered).
    entity_key = Column(String, nullable=False)
    singular = Column(String, nullable=False)
    plural = Column(String, nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())
    updated_by = Column(String, ForeignKey("users.id"), nullable=True)
