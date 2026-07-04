"""CRM models (sprint-4/08) — ``app_crm`` schema. Client / Lead / Quotation
moved out of EMS. Money is Numeric (exact cents). ``lead.project_id`` is GONE
(1 lead → many events; the link of record is ``project.lead_id`` on the EMS side).
``quotation_lines.product_id`` is a plain column → core ``public.products`` (BL-030;
validated at the service, delete-guarded by the catalog reference-guard).
"""
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.utc_datetime import UTCDateTime
from modules.crm.db import CrmBase

MONEY = Numeric(14, 4)


def _uuid() -> str:
    return str(uuid.uuid4())


class Client(CrmBase):
    """B2B buyer account. Tenant-scoped; status engine (Active/Inactive/Archived).
    Leads + Quotations link to it M:1."""

    __tablename__ = "clients"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    name = Column(String, nullable=False)
    registration_no = Column(String, nullable=True)
    contact_person = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)
    contact_phone = Column(String, nullable=True)
    status_id = Column(String, nullable=True)  # core statuses FK = plain col (BL-030)
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(UTCDateTime, nullable=True)
    deleted_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())


class Lead(CrmBase):
    """Sales inquiry / opportunity. ``client_id`` NULLABLE (a raw inquiry can
    exist before a Client). Status engine (New→Contacted→Qualified→Won/Lost). Win
    is a PLAIN status move; creating an event from a Won lead is a SEPARATE,
    repeatable action (EMS ``project.create_from_template`` capability) — so a lead
    holds NO project_id (1 lead → many events; link lives on ``project.lead_id``)."""

    __tablename__ = "leads"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    client_id = Column(String, ForeignKey("clients.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    source = Column(String, nullable=True)
    contact_name = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)
    contact_phone = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    status_id = Column(String, nullable=True)  # core statuses FK = plain col (BL-030)
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(UTCDateTime, nullable=True)
    deleted_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())


class Quotation(CrmBase):
    """B2B service quote. ``client_id`` required; raised against a lead and/or an
    event (``project_id`` = optional CRM→EMS soft-ref). Revisions chain via
    ``parent_quotation_id`` + ``revision_number``. ONE currency per quotation; lines
    inherit. Status engine (Draft→Sent→Accepted/Rejected→Expired)."""

    __tablename__ = "quotations"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False, index=True)
    lead_id = Column(String, ForeignKey("leads.id"), nullable=True, index=True)
    project_id = Column(String, nullable=True, index=True)  # → EMS projects (soft-ref)
    revision_number = Column(Integer, nullable=False, default=1)
    parent_quotation_id = Column(String, ForeignKey("quotations.id"), nullable=True, index=True)
    currency = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    status_id = Column(String, nullable=True)  # core statuses FK = plain col (BL-030)
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(UTCDateTime, nullable=True)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())

    lines = relationship(
        "QuotationLine",
        order_by="QuotationLine.sort",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class QuotationLine(CrmBase):
    """A quote line — a core product reference OR free-form description. Values are
    SNAPSHOT-IMMUTABLE at add (qty/unit_price/amount frozen; editing the catalog
    price never touches an existing line). ``product_id`` → core ``public.products``
    (plain col, BL-030)."""

    __tablename__ = "quotation_lines"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    quotation_id = Column(String, ForeignKey("quotations.id"), nullable=False, index=True)
    product_id = Column(String, nullable=True, index=True)  # → core products (plain col, BL-030)
    description = Column(String, nullable=True)
    qty = Column(MONEY, nullable=False, default=1)
    unit_price = Column(MONEY, nullable=False, default=0)
    amount = Column(MONEY, nullable=False, default=0)
    sort = Column(Integer, nullable=True)


class SalesOrder(CrmBase):
    """A confirmed commercial order (sprint-4/07, Cluster F slice 2). Created from
    an Accepted quotation (``quotation_id`` soft link) or from scratch. ``client_id``
    required. ``doc_number`` is NULL in Draft, assigned at Confirm via the core
    Numbering engine (AC-07-19). Status engine (Draft→Confirmed→Fulfilled→Cancelled);
    Fulfilled is DERIVED when every line is fully invoiced (AC-07-23)."""

    __tablename__ = "sales_orders"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False, index=True)
    quotation_id = Column(String, ForeignKey("quotations.id"), nullable=True, index=True)
    project_id = Column(String, nullable=True, index=True)  # → EMS projects (soft-ref)
    currency = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    # NULL in Draft, assigned at Confirm via NumberingService (AC-07-19).
    doc_number = Column(String, nullable=True, index=True)
    confirmed_at = Column(UTCDateTime, nullable=True)
    status_id = Column(String, nullable=True)  # core statuses FK = plain col (BL-030)
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(UTCDateTime, nullable=True)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())

    lines = relationship(
        "SalesOrderLine",
        order_by="SalesOrderLine.sort",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class SalesOrderLine(CrmBase):
    """An SO line — product reference OR free-form description. Snapshot-immutable
    at add (qty/unit_price/amount frozen). ``invoiced_qty`` is denormalized: finance
    is the writer via the ``crm.so_line_invoiced@1`` capability (AC-07-22); CRM owns
    the number. Fulfilled derives when ``invoiced_qty >= qty`` on every line."""

    __tablename__ = "sales_order_lines"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col (BL-030)
    sales_order_id = Column(String, ForeignKey("sales_orders.id"), nullable=False, index=True)
    product_id = Column(String, nullable=True, index=True)  # → core products (plain col, BL-030)
    description = Column(String, nullable=True)
    qty = Column(MONEY, nullable=False, default=1)
    unit_price = Column(MONEY, nullable=False, default=0)
    tax_rate = Column(Numeric(6, 4), nullable=False, default=0)
    amount = Column(MONEY, nullable=False, default=0)
    invoiced_qty = Column(MONEY, nullable=False, default=0)  # finance-written (capability)
    sort = Column(Integer, nullable=True)


# Status entity keys.
CLIENT_ENTITY = "client"
LEAD_ENTITY = "lead"
QUOTATION_ENTITY = "quotation"
SALES_ORDER_ENTITY = "sales_order"
