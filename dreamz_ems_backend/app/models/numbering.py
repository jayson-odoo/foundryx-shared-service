"""Numbering core tables (sprint-4/07, Cluster F) — gapless document numbering.

THREE pieces (the terminology_overrides pattern + a counter):
- The code-side ``NumberSequenceDef`` registry holds DEFAULTS (app/numbering).
- ``number_formats`` — a per-tenant OVERRIDE row (exists only when a tenant
  customises prefix / format / reset for a doc type). Tenant-editable.
- ``number_counters`` — the gapless running counter, ONE row per
  (tenant, doc_type, period_key). The ``SELECT … FOR UPDATE`` counter row
  (AC-07-04): ``next_val`` is the NEXT number to hand out, incremented inside
  the CALLER's transaction (flush, not commit) so a caller rollback un-advances
  it (no Postgres SEQUENCE — those skip on rollback = illegal gaps).
"""
import uuid

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base
from app.models.utc_datetime import UTCDateTime


class NumberFormat(Base):
    """Per-tenant override of a registered doc type's prefix / format / reset.
    Absence = use the code-side ``NumberSequenceDef`` default."""

    __tablename__ = "number_formats"
    __table_args__ = (
        UniqueConstraint("tenant_id", "doc_type", name="uq_number_format_tenant_doctype"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The registered NumberSequenceDef key (e.g. "invoice"). 422 if unknown.
    doc_type = Column(String, nullable=False)
    prefix = Column(String, nullable=False, default="")
    format_pattern = Column(String, nullable=False)
    reset_period = Column(String, nullable=False, default="yearly")
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())
    updated_by = Column(String, ForeignKey("users.id"), nullable=True)


class NumberCounter(Base):
    """The gapless running counter. ``next_val`` = the NEXT number to hand out
    for (tenant, doc_type, period_key). Locked ``FOR UPDATE`` on Postgres so two
    concurrent ``next_number`` calls serialise; the increment rides the caller's
    transaction (rollback un-advances)."""

    __tablename__ = "number_counters"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "doc_type", "period_key", name="uq_number_counter_tenant_doctype_period"
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doc_type = Column(String, nullable=False)
    # Period bucket: "" (never) / "2026" (yearly) / "2026-06" (monthly).
    period_key = Column(String, nullable=False, default="")
    next_val = Column(Integer, nullable=False, default=1)
