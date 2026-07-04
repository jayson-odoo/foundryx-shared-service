"""Finance wire schemas (sprint-4/05). camelCase via ApiModel. Money is stored
as Numeric(14,4) since sprint-4/07 (Cluster F, AC-07-01/02); the wire coerces
Decimal → float for JSON (the FE renders it via lib/money.ts formatMoney)."""
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import ConfigDict, Field, field_validator

from app.schemas.base import ApiModel


class _Base(ApiModel):
    model_config = ConfigDict(from_attributes=True)


def _to_float(v) -> float:
    """Decimal/None → JSON-safe float (4dp money). Pydantic validator helper.

    SAFE for ``Numeric(14,4)``: every such value is < 2^53, so it is exactly
    representable in float64 — no precision loss on the wire."""
    return 0.0 if v is None else float(v)


class InvoiceLineOut(_Base):
    id: str
    projectProductId: Optional[str] = Field(default=None, validation_alias="project_product_id")
    description: Optional[str] = None
    qty: int
    unitPrice: float = Field(validation_alias="unit_price")
    taxRate: float = Field(default=0.0, validation_alias="tax_rate")
    taxAmount: float = Field(default=0.0, validation_alias="tax_amount")
    tax: float
    amount: float

    @field_validator("unitPrice", "taxRate", "taxAmount", "tax", "amount", mode="before")
    @classmethod
    def _money(cls, v):
        return _to_float(v) if isinstance(v, Decimal) or v is None else v


class PaymentOut(_Base):
    id: str
    invoiceId: str = Field(validation_alias="invoice_id")
    amount: float
    method: str
    statusId: Optional[str] = Field(default=None, validation_alias="status_id")
    paidAt: Optional[datetime] = Field(default=None, validation_alias="paid_at")
    note: Optional[str] = None
    gatewayFee: Optional[float] = Field(default=None, validation_alias="gateway_fee")
    externalPaymentId: Optional[str] = Field(default=None, validation_alias="external_payment_id")
    createdAt: datetime = Field(validation_alias="created_at")

    @field_validator("amount", "gatewayFee", mode="before")
    @classmethod
    def _money(cls, v):
        return _to_float(v) if isinstance(v, Decimal) else v


class TaxSummaryRow(ApiModel):
    rate: float
    label: str
    base: float
    tax: float


class InvoiceOut(_Base):
    id: str
    projectId: Optional[str] = Field(default=None, validation_alias="project_id")
    billToType: str = Field(validation_alias="bill_to_type")
    billToId: str = Field(validation_alias="bill_to_id")
    currency: str
    statusId: Optional[str] = Field(default=None, validation_alias="status_id")
    invoiceNumber: Optional[str] = Field(default=None, validation_alias="invoice_number")
    issuedAt: Optional[datetime] = Field(default=None, validation_alias="issued_at")
    dueDate: Optional[datetime] = Field(default=None, validation_alias="due_date")
    notes: Optional[str] = None
    buyerTin: Optional[str] = Field(default=None, validation_alias="buyer_tin")
    sstRegNo: Optional[str] = Field(default=None, validation_alias="sst_reg_no")
    taxCode: Optional[str] = Field(default=None, validation_alias="tax_code")
    einvoiceType: Optional[str] = Field(default=None, validation_alias="einvoice_type")
    subtotal: float
    tax: float
    total: float
    createdAt: datetime = Field(validation_alias="created_at")

    @field_validator("subtotal", "tax", "total", mode="before")
    @classmethod
    def _money(cls, v):
        return _to_float(v) if isinstance(v, Decimal) or v is None else v
    # display-only enrichments (set transiently by the service)
    billToName: str = ""
    statusLabel: Optional[str] = None
    statusKey: Optional[str] = None
    paidTotal: float = 0.0
    lines: List[InvoiceLineOut] = []
    payments: List[PaymentOut] = []
    taxSummary: List[TaxSummaryRow] = []


class TransitionIn(ApiModel):
    toStatusId: str


class InvoiceUpdateIn(ApiModel):
    notes: Optional[str] = None
    dueDate: Optional[datetime] = None
    currency: Optional[str] = None
    buyerTin: Optional[str] = None
    sstRegNo: Optional[str] = None
    taxCode: Optional[str] = None
    einvoiceType: Optional[str] = None
    lines: Optional[List[dict]] = None


class RecordPaymentIn(ApiModel):
    amount: float
    method: str  # CASH | CARD | BANK
    note: Optional[str] = None


class ListResponse(ApiModel):
    items: list
    total: int
    page: int
    pageSize: int


class CheckoutOut(ApiModel):
    """Gateway checkout session (AC-07-27) — the buyer redirect + the Pending
    payment row id (= the gateway external_ref)."""
    redirectUrl: str
    paymentId: str


# ── refunds (Cluster F slice 4, AC-07-37..43) ───────────────────────────────
class RefundIn(ApiModel):
    """Refund SELECTED tickets on an invoice. The amount is derived per ticket;
    the method mirrors the invoice's primary payment method (AC-07-38)."""
    ticketIds: List[str]
    reason: Optional[str] = None


class RefundableTicketOut(ApiModel):
    id: str
    projectId: Optional[str] = None
    status: str
    refundable: bool


class RefundOut(ApiModel):
    id: str
    invoiceId: str
    amount: float
    method: str
    statusId: Optional[str] = None
    statusKey: Optional[str] = None
    creditNoteNumber: Optional[str] = None
    gatewayRef: Optional[str] = None
    reason: Optional[str] = None
    ticketIds: List[str] = []
    createdAt: datetime


# ── settlements (Cluster F slice 4, AC-07-45..48) ───────────────────────────
class SettlementLineOut(ApiModel):
    id: str
    invoiceId: str
    amount: float


class SettlementOut(ApiModel):
    id: str
    projectId: str
    clientId: Optional[str] = None
    kind: str
    grossCollected: float
    gatewayFees: float
    feeType: Optional[str] = None
    feeAmount: float
    netPayable: float
    statusId: Optional[str] = None
    statusKey: Optional[str] = None
    statusLabel: Optional[str] = None
    remittanceRef: Optional[str] = None
    generatedAt: datetime
    lines: List[SettlementLineOut] = []


class GenerateSettlementIn(ApiModel):
    projectId: str


class SettlementTransitionIn(ApiModel):
    toStatusId: str
    remittanceRef: Optional[str] = None


class SettlementListResponse(ApiModel):
    items: List[SettlementOut]
    total: int
    page: int
    pageSize: int
