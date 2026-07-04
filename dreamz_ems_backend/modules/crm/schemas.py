"""CRM wire schemas (sprint-4/08). camelCase via ApiModel. Money Decimal→float."""
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import ApiModel


class _Base(ApiModel):
    model_config = ConfigDict(from_attributes=True)


def _money(v) -> float:
    return 0.0 if v is None else float(v)


class ClientOut(_Base):
    id: str
    name: str
    registrationNo: Optional[str] = Field(default=None, validation_alias="registration_no")
    contactPerson: Optional[str] = Field(default=None, validation_alias="contact_person")
    contactEmail: Optional[str] = Field(default=None, validation_alias="contact_email")
    contactPhone: Optional[str] = Field(default=None, validation_alias="contact_phone")
    statusId: Optional[str] = Field(default=None, validation_alias="status_id")
    createdAt: datetime = Field(validation_alias="created_at")


class ClientIn(ApiModel):
    name: str
    registrationNo: Optional[str] = None
    contactPerson: Optional[str] = None
    contactEmail: Optional[str] = None
    contactPhone: Optional[str] = None


class ClientPatch(ApiModel):
    name: Optional[str] = None
    registrationNo: Optional[str] = None
    contactPerson: Optional[str] = None
    contactEmail: Optional[str] = None
    contactPhone: Optional[str] = None


class LeadOut(_Base):
    id: str
    clientId: Optional[str] = Field(default=None, validation_alias="client_id")
    title: str
    source: Optional[str] = None
    contactName: Optional[str] = Field(default=None, validation_alias="contact_name")
    contactEmail: Optional[str] = Field(default=None, validation_alias="contact_email")
    contactPhone: Optional[str] = Field(default=None, validation_alias="contact_phone")
    notes: Optional[str] = None
    statusId: Optional[str] = Field(default=None, validation_alias="status_id")
    createdAt: datetime = Field(validation_alias="created_at")


class LeadIn(ApiModel):
    title: str
    clientId: Optional[str] = None
    source: Optional[str] = None
    contactName: Optional[str] = None
    contactEmail: Optional[str] = None
    contactPhone: Optional[str] = None
    notes: Optional[str] = None


class LeadPatch(ApiModel):
    title: Optional[str] = None
    clientId: Optional[str] = None
    source: Optional[str] = None
    contactName: Optional[str] = None
    contactEmail: Optional[str] = None
    contactPhone: Optional[str] = None
    notes: Optional[str] = None


class LeadCreateEventIn(ApiModel):
    """Won lead → spawn an event (EMS project) from a template. Repeatable (1 lead
    → many events). Delegated to the EMS ``project.create_from_template`` capability."""
    templateId: str
    title: Optional[str] = None  # defaults to the lead title


class LeadEventOut(ApiModel):
    """A spawned event, as resolved cross-module from EMS (projects.by_lead)."""
    id: str
    title: Optional[str] = None
    statusId: Optional[str] = None


class QuotationLineOut(_Base):
    id: str
    productId: Optional[str] = Field(default=None, validation_alias="product_id")
    description: Optional[str] = None
    qty: float
    unitPrice: float = Field(validation_alias="unit_price")
    amount: float
    sort: Optional[int] = None

    @classmethod
    def from_row(cls, ln) -> "QuotationLineOut":
        return cls(
            id=ln.id, product_id=ln.product_id, description=ln.description,
            qty=_money(ln.qty), unit_price=_money(ln.unit_price), amount=_money(ln.amount),
            sort=ln.sort,
        )


class QuotationLineIn(ApiModel):
    productId: Optional[str] = None
    description: Optional[str] = None
    qty: Decimal = Decimal(1)
    unitPrice: Decimal = Decimal(0)
    sort: Optional[int] = None


class QuotationOut(_Base):
    id: str
    clientId: str = Field(validation_alias="client_id")
    leadId: Optional[str] = Field(default=None, validation_alias="lead_id")
    projectId: Optional[str] = Field(default=None, validation_alias="project_id")
    revisionNumber: int = Field(validation_alias="revision_number")
    parentQuotationId: Optional[str] = Field(default=None, validation_alias="parent_quotation_id")
    currency: Optional[str] = None
    notes: Optional[str] = None
    statusId: Optional[str] = Field(default=None, validation_alias="status_id")
    total: float = 0
    lines: List[QuotationLineOut] = []
    createdAt: datetime = Field(validation_alias="created_at")

    @classmethod
    def from_row(cls, q) -> "QuotationOut":
        total = round(sum(float(ln.amount or 0) for ln in q.lines), 2)
        return cls(
            id=q.id, client_id=q.client_id, lead_id=q.lead_id, project_id=q.project_id,
            revision_number=q.revision_number, parent_quotation_id=q.parent_quotation_id,
            currency=q.currency, notes=q.notes, status_id=q.status_id, total=total,
            lines=[QuotationLineOut.from_row(ln) for ln in q.lines], created_at=q.created_at,
        )


class QuotationIn(ApiModel):
    clientId: str
    leadId: Optional[str] = None
    projectId: Optional[str] = None
    currency: Optional[str] = None
    notes: Optional[str] = None
    lines: List[QuotationLineIn] = []


class QuotationPatch(ApiModel):
    clientId: Optional[str] = None
    leadId: Optional[str] = None
    projectId: Optional[str] = None
    currency: Optional[str] = None
    notes: Optional[str] = None
    lines: Optional[List[QuotationLineIn]] = None


class SalesOrderLineOut(_Base):
    id: str
    productId: Optional[str] = Field(default=None, validation_alias="product_id")
    description: Optional[str] = None
    qty: float
    unitPrice: float = Field(validation_alias="unit_price")
    taxRate: float = Field(validation_alias="tax_rate")
    amount: float
    invoicedQty: float = Field(validation_alias="invoiced_qty")
    sort: Optional[int] = None

    @classmethod
    def from_row(cls, ln) -> "SalesOrderLineOut":
        return cls(
            id=ln.id, product_id=ln.product_id, description=ln.description,
            qty=_money(ln.qty), unit_price=_money(ln.unit_price), tax_rate=_money(ln.tax_rate),
            amount=_money(ln.amount), invoiced_qty=_money(ln.invoiced_qty), sort=ln.sort,
        )


class SalesOrderLineIn(ApiModel):
    productId: Optional[str] = None
    description: Optional[str] = None
    qty: Decimal = Decimal(1)
    unitPrice: Decimal = Decimal(0)
    taxRate: Decimal = Decimal(0)
    sort: Optional[int] = None


class SalesOrderOut(_Base):
    id: str
    docNumber: Optional[str] = Field(default=None, validation_alias="doc_number")
    clientId: str = Field(validation_alias="client_id")
    quotationId: Optional[str] = Field(default=None, validation_alias="quotation_id")
    projectId: Optional[str] = Field(default=None, validation_alias="project_id")
    currency: Optional[str] = None
    notes: Optional[str] = None
    statusId: Optional[str] = Field(default=None, validation_alias="status_id")
    total: float = 0
    lines: List[SalesOrderLineOut] = []
    createdAt: datetime = Field(validation_alias="created_at")

    @classmethod
    def from_row(cls, so) -> "SalesOrderOut":
        total = round(sum(float(ln.amount or 0) for ln in so.lines), 2)
        return cls(
            id=so.id, doc_number=so.doc_number, client_id=so.client_id,
            quotation_id=so.quotation_id, project_id=so.project_id, currency=so.currency,
            notes=so.notes, status_id=so.status_id, total=total,
            lines=[SalesOrderLineOut.from_row(ln) for ln in so.lines], created_at=so.created_at,
        )


class SalesOrderIn(ApiModel):
    clientId: str
    quotationId: Optional[str] = None
    projectId: Optional[str] = None
    currency: Optional[str] = None
    notes: Optional[str] = None
    lines: List[SalesOrderLineIn] = []


class SalesOrderPatch(ApiModel):
    clientId: Optional[str] = None
    projectId: Optional[str] = None
    currency: Optional[str] = None
    notes: Optional[str] = None
    lines: Optional[List[SalesOrderLineIn]] = None


class SalesOrderFromQuotationIn(ApiModel):
    quotationId: str


class InvoiceLineSelection(ApiModel):
    lineId: str
    qty: Decimal


class CreateInvoiceFromSoIn(ApiModel):
    selections: List[InvoiceLineSelection]


class CreatedInvoiceOut(ApiModel):
    id: str
    total: Optional[float] = None
    currency: Optional[str] = None


class TransitionIn(ApiModel):
    toStatusId: str


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
