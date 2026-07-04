"""Finance models (sprint-4/05, Cluster D / R3-1) — ``app_finance`` schema.

Invoice = the unified order header (polymorphic bill-to: Client | Profile),
born in Cluster D for the registration stream (ticket → invoice). Cluster F adds
payments / sales_orders / settlement + the derived Paid/Overdue states.
"""
import uuid

from sqlalchemy import Column, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.sql import func

from app.models.utc_datetime import UTCDateTime
from modules.finance.db import FinanceBase

# Money = exact decimal (14,4) — NEVER Float (binary float can't represent cents;
# 0.1+0.2 drift compounds over a ledger). sprint-4/07 Cluster F (AC-07-01).
MONEY = Numeric(14, 4)
# A tax rate is a small decimal fraction (e.g. 0.0600), not money.
TAX_RATE = Numeric(6, 4)


def _uuid() -> str:
    return str(uuid.uuid4())


INVOICE_ENTITY = "invoice"
PAYMENT_ENTITY = "payment"
REFUND_ENTITY = "refund"
SETTLEMENT_ENTITY = "settlement"

# Manual record-payment methods (AC-07-10). GATEWAY/FPX are webhook-created only
# (Slice 3) — never manually recorded.
MANUAL_PAYMENT_METHODS = ("CASH", "CARD", "BANK")
GATEWAY_PAYMENT_METHODS = ("GATEWAY", "FPX")
PAYMENT_METHODS = ("CASH", "CARD", "BANK", "GATEWAY", "FPX")

# Refund method mirrors the payment method (AC-07-38): GATEWAY/FPX route through
# the gateway refund API; CASH/CARD/BANK are MANUAL records (no API call).
GATEWAY_REFUND_METHODS = ("GATEWAY", "FPX")

# Settlement kinds (AC-07-46/48): one PRIMARY per project; a post-remit refund
# spawns a supplementary ADJUSTMENT (may be negative).
SETTLEMENT_PRIMARY = "PRIMARY"
SETTLEMENT_ADJUSTMENT = "ADJUSTMENT"

# Project commercial mode (AC-07-45). AGENCY = the tenant runs the event for a
# client and owes a give-back; SELF_RUN produces NO settlement.
COMMERCIAL_SELF_RUN = "SELF_RUN"
COMMERCIAL_AGENCY = "AGENCY"
FEE_TYPES = ("PERCENT", "FLAT", "PER_TICKET")


class Invoice(FinanceBase):
    """Order header. ``bill_to`` is polymorphic (Client in app_crm OR Profile in
    app_ems) — resolved via capability for display (BL-030). ``project_id`` =
    app_ems soft-ref. Money is stored as ``Numeric(14,4)`` (exact decimal)."""

    __tablename__ = "invoices"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col
    project_id = Column(String, nullable=True, index=True)  # app_ems soft-ref
    bill_to_type = Column(String, nullable=False)  # Client | Profile
    bill_to_id = Column(String, nullable=False, index=True)
    sales_order_id = Column(String, nullable=True)  # Cluster F
    currency = Column(String, nullable=False, default="USD")
    status_id = Column(String, nullable=True)  # core statuses FK = plain col
    subtotal = Column(MONEY, nullable=False, default=0)
    tax = Column(MONEY, nullable=False, default=0)
    total = Column(MONEY, nullable=False, default=0)
    # Numbering (AC-07-06): NULL in Draft, assigned at Issue via NumberingService
    # in the SAME commit as the status change; frozen thereafter.
    invoice_number = Column(String, nullable=True, index=True)
    issued_at = Column(UTCDateTime, nullable=True)
    due_date = Column(UTCDateTime, nullable=True)  # AC-07-13 Overdue derivation
    notes = Column(Text, nullable=True)  # editable post-Issue (AC-07-09)
    # Reserved e-invoice fields (AC-07-16) — settable, inert (no submission logic).
    buyer_tin = Column(String, nullable=True)
    sst_reg_no = Column(String, nullable=True)
    tax_code = Column(String, nullable=True)
    einvoice_type = Column(String, nullable=True)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())


class InvoiceLine(FinanceBase):
    """One billed line — either a product reference (offering) or a free-form
    description."""

    __tablename__ = "invoice_lines"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    invoice_id = Column(String, ForeignKey("invoices.id"), nullable=False, index=True)
    project_product_id = Column(String, nullable=True)  # app_ems offering soft-ref
    description = Column(Text, nullable=True)
    qty = Column(Integer, nullable=False, default=1)
    unit_price = Column(MONEY, nullable=False, default=0)
    # Per-line tax (AC-07-15): exclusive, ``tax_amount = round(amount * rate)`` in
    # Decimal. ``tax`` is the legacy column kept = ``tax_amount`` (back-compat).
    tax_rate = Column(TAX_RATE, nullable=False, default=0)
    tax_amount = Column(MONEY, nullable=False, default=0)
    tax = Column(MONEY, nullable=False, default=0)
    amount = Column(MONEY, nullable=False, default=0)


class Payment(FinanceBase):
    """A payment against an invoice (AC-07-10..12). Manual record = Succeeded
    immediately (CASH/CARD/BANK); GATEWAY/FPX rows are webhook-created (Slice 3,
    gateway columns reserved here). Money = ``Numeric(14,4)``; the invoice
    re-derives Partially Paid/Paid from Σ Succeeded payments."""

    __tablename__ = "payments"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col
    invoice_id = Column(String, ForeignKey("invoices.id"), nullable=False, index=True)
    amount = Column(MONEY, nullable=False, default=0)
    method = Column(String, nullable=False)  # CASH|CARD|BANK|GATEWAY|FPX
    status_id = Column(String, nullable=True)  # core statuses FK = plain col
    paid_at = Column(UTCDateTime, nullable=True)
    note = Column(Text, nullable=True)
    # Gateway columns (Slice 3) — reserved, nullable, inert in Slice 1.
    gateway_connection_id = Column(String, nullable=True)
    external_ref = Column(String, nullable=True)
    external_payment_id = Column(String, nullable=True)
    gateway_fee = Column(MONEY, nullable=True)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())


class Refund(FinanceBase):
    """A refund against an invoice/payment (Cluster F slice 4, AC-07-37..43).

    Method MIRRORS the originating payment (AC-07-38): GATEWAY/FPX route through
    the gateway refund API → confirmed via webhook; CASH/BANK are MANUAL records
    confirmed immediately. The ``credit_note_number`` is assigned at confirm via
    the numbering engine (AC-07-40). Money = ``Numeric(14,4)`` exact Decimal.
    Refunds are scoped per ticket via ``refund_lines``."""

    __tablename__ = "refunds"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col
    invoice_id = Column(String, ForeignKey("invoices.id"), nullable=False, index=True)
    payment_id = Column(String, nullable=True)  # the reversed payment (intra-app_finance soft)
    amount = Column(MONEY, nullable=False, default=0)
    method = Column(String, nullable=False)  # GATEWAY|FPX|CASH|BANK (mirrors payment)
    status_id = Column(String, nullable=True)  # core statuses FK = plain col
    # Numbering (AC-07-40): NULL until confirmed; assigned in the same commit as
    # the refund reaching Confirmed.
    credit_note_number = Column(String, nullable=True, index=True)
    gateway_ref = Column(String, nullable=True)  # external refund id (or manual: marker)
    reason = Column(Text, nullable=True)
    confirmed_at = Column(UTCDateTime, nullable=True)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())


class RefundLine(FinanceBase):
    """Per-ticket refund line (AC-07-37). ``ticket_id`` = app_ems soft-ref."""

    __tablename__ = "refund_lines"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    refund_id = Column(String, ForeignKey("refunds.id"), nullable=False, index=True)
    ticket_id = Column(String, nullable=False, index=True)  # app_ems Ticket soft-ref
    amount = Column(MONEY, nullable=False, default=0)


class Settlement(FinanceBase):
    """Agency give-back settlement (Cluster F slice 4, AC-07-45..48). ONE PRIMARY
    per project; a post-remit refund spawns a supplementary ADJUSTMENT (may be
    negative). ``net_payable = gross_collected − gateway_fees − fee_amount`` (all
    three lines visible). Lifecycle rides the status engine
    (Draft→Approved→Remitted). ``project_id``/``client_id`` = app_ems/app_crm
    soft-refs."""

    __tablename__ = "settlements"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)  # core FK = plain col
    project_id = Column(String, nullable=False, index=True)  # app_ems soft-ref
    client_id = Column(String, nullable=True, index=True)  # app_crm soft-ref
    kind = Column(String, nullable=False, default=SETTLEMENT_PRIMARY)  # PRIMARY|ADJUSTMENT
    gross_collected = Column(MONEY, nullable=False, default=0)
    gateway_fees = Column(MONEY, nullable=False, default=0)
    fee_type = Column(String, nullable=True)  # PERCENT|FLAT|PER_TICKET (snapshot)
    fee_amount = Column(MONEY, nullable=False, default=0)
    net_payable = Column(MONEY, nullable=False, default=0)
    status_id = Column(String, nullable=True)  # core statuses FK = plain col
    remittance_ref = Column(String, nullable=True)  # AC-07-47
    generated_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    remitted_at = Column(UTCDateTime, nullable=True)
    created_at = Column(UTCDateTime, server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime, server_default=func.now(), onupdate=func.now())


class SettlementLine(FinanceBase):
    """A settlement's source invoice contribution (AC-07-46)."""

    __tablename__ = "settlement_lines"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    settlement_id = Column(String, ForeignKey("settlements.id"), nullable=False, index=True)
    invoice_id = Column(String, nullable=False, index=True)  # intra-app_finance soft-ref
    amount = Column(MONEY, nullable=False, default=0)
