"""EMS wire schemas (sprint-3/11). camelCase via ApiModel."""
from datetime import date, datetime
from typing import List, Optional

from pydantic import ConfigDict, Field, field_validator

from app.schemas.base import ApiModel


class _Base(ApiModel):
    model_config = ConfigDict(from_attributes=True)


class ProfileOut(_Base):
    id: str
    email: str
    phone: Optional[str] = None
    fullName: Optional[str] = Field(default=None, validation_alias="full_name")
    country: Optional[str] = None
    organization: Optional[str] = None
    title: Optional[str] = None
    statusId: Optional[str] = Field(default=None, validation_alias="status_id")
    createdAt: datetime = Field(validation_alias="created_at")


class ProfileIn(ApiModel):
    email: str
    phone: Optional[str] = None
    fullName: Optional[str] = None
    country: Optional[str] = None
    organization: Optional[str] = None
    title: Optional[str] = None


class ProfilePatch(ApiModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    fullName: Optional[str] = None
    country: Optional[str] = None
    organization: Optional[str] = None
    title: Optional[str] = None


class ProjectTypeOut(_Base):
    id: str
    name: str
    description: Optional[str] = None


class ProjectTypeIn(ApiModel):
    name: str
    description: Optional[str] = None


class ProjectTypePatch(ApiModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ProjectTemplateOut(_Base):
    id: str
    typeId: str = Field(validation_alias="type_id")
    name: str
    description: Optional[str] = None


class ProjectTemplateIn(ApiModel):
    typeId: str
    name: str
    description: Optional[str] = None


class ProjectTemplatePatch(ApiModel):
    name: Optional[str] = None
    description: Optional[str] = None


class TemplateChildOut(_Base):
    """A template role or segment — id + name (sort reserved)."""
    id: str
    name: str


class TemplateChildIn(ApiModel):
    name: str


class ProjectOut(_Base):
    id: str
    templateId: str = Field(validation_alias="template_id")
    typeId: Optional[str] = Field(default=None, validation_alias="type_id")
    title: str
    brief: Optional[str] = None
    notes: Optional[str] = None
    domainName: Optional[str] = Field(default=None, validation_alias="domain_name")
    # Calendar dates (date-only, no tz) — Slice 5.
    startDate: Optional[date] = Field(default=None, validation_alias="start_date")
    endDate: Optional[date] = Field(default=None, validation_alias="end_date")
    eventValidityEnd: Optional[date] = Field(
        default=None, validation_alias="event_validity_end"
    )
    statusId: Optional[str] = Field(default=None, validation_alias="status_id")
    # Commercial mode + agency fee config (Cluster F slice 4, AC-07-45).
    commercialMode: str = Field(default="SELF_RUN", validation_alias="commercial_mode")
    feeType: Optional[str] = Field(default=None, validation_alias="fee_type")
    feeValue: Optional[float] = Field(default=None, validation_alias="fee_value")
    paymentConnectionId: Optional[str] = Field(
        default=None, validation_alias="payment_connection_id"
    )
    createdAt: datetime = Field(validation_alias="created_at")


class ProjectIn(ApiModel):
    templateId: str
    title: str
    brief: Optional[str] = None


class ProjectUpdate(ApiModel):
    """PATCH body — all-optional; immutable fields (template/type/client/status)
    are intentionally absent. ``model_fields_set`` distinguishes absent (keep)
    from explicit null (clear). Dates are calendar dates (date-only)."""

    title: Optional[str] = None
    brief: Optional[str] = None
    notes: Optional[str] = None
    domainName: Optional[str] = None
    startDate: Optional[date] = None
    endDate: Optional[date] = None
    eventValidityEnd: Optional[date] = None
    # Commercial mode + agency fee config (Cluster F slice 4, AC-07-45).
    commercialMode: Optional[str] = None  # SELF_RUN | AGENCY
    feeType: Optional[str] = None  # PERCENT | FLAT | PER_TICKET
    feeValue: Optional[float] = None
    paymentConnectionId: Optional[str] = None


class ParticipantOut(_Base):
    id: str
    profileId: str = Field(validation_alias="profile_id")
    projectId: str = Field(validation_alias="project_id")
    roleId: Optional[str] = Field(default=None, validation_alias="role_id")
    segmentId: Optional[str] = Field(default=None, validation_alias="segment_id")
    statusId: Optional[str] = Field(default=None, validation_alias="status_id")


class ParticipantIn(ApiModel):
    profileId: str
    roleId: Optional[str] = None
    segmentId: Optional[str] = None


class ParticipantPatch(ApiModel):
    roleId: Optional[str] = None
    segmentId: Optional[str] = None


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
    projectId: Optional[str] = Field(default=None, validation_alias="project_id")
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


class LeadConvertIn(ApiModel):
    """Won → spawn a Project from a chosen template, link lead↔client↔project."""
    templateId: str
    title: Optional[str] = None  # defaults to the lead title


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


class ProductOut(_Base):
    id: str
    categoryId: Optional[str] = Field(default=None, validation_alias="category_id")
    name: str
    sku: Optional[str] = None
    kind: str
    defaultPrice: Optional[float] = Field(default=None, validation_alias="default_price")
    tax: Optional[float] = None
    uom: Optional[str] = None
    isActive: bool = Field(validation_alias="is_active")
    createdAt: datetime = Field(validation_alias="created_at")


class ProductIn(ApiModel):
    name: str
    kind: str = "SERVICE"
    categoryId: Optional[str] = None
    sku: Optional[str] = None
    defaultPrice: Optional[float] = None
    tax: Optional[float] = None
    uom: Optional[str] = None
    isActive: bool = True


class ProductPatch(ApiModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    categoryId: Optional[str] = None
    sku: Optional[str] = None
    defaultPrice: Optional[float] = None
    tax: Optional[float] = None
    uom: Optional[str] = None
    isActive: Optional[bool] = None


class QuotationLineOut(_Base):
    id: str
    productId: Optional[str] = Field(default=None, validation_alias="product_id")
    description: Optional[str] = None
    qty: float
    unitPrice: float = Field(validation_alias="unit_price")
    amount: float
    sort: Optional[int] = None


class QuotationLineIn(ApiModel):
    productId: Optional[str] = None
    description: Optional[str] = None
    qty: float = 1
    unitPrice: float = 0
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


# ── Cluster D (sprint-4/05) — Venues / Zones / Seats / Offerings / Capacity ──

class VenueOut(_Base):
    id: str
    name: str
    address: Optional[str] = None
    capacity: Optional[int] = None
    zoneCount: int = 0
    seatCount: int = 0
    isTrashed: bool = Field(default=False, validation_alias="is_deleted")
    createdAt: datetime = Field(validation_alias="created_at")


class VenueIn(ApiModel):
    name: str
    address: Optional[str] = None
    capacity: Optional[int] = None


class VenuePatch(ApiModel):
    name: Optional[str] = None
    address: Optional[str] = None
    capacity: Optional[int] = None


class VenueZoneOut(_Base):
    id: str
    venueId: str = Field(validation_alias="venue_id")
    name: str
    kind: str
    sort: int
    seatCount: int = 0


class VenueZoneIn(ApiModel):
    name: str
    kind: str = "section"


class VenueZonePatch(ApiModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    sort: Optional[int] = None


class VenueSeatOut(_Base):
    id: str
    venueId: str = Field(validation_alias="venue_id")
    zoneId: str = Field(validation_alias="zone_id")
    section: Optional[str] = None
    row: Optional[str] = None
    number: Optional[str] = None
    label: str
    x: float
    y: float


class SeatGenerateIn(ApiModel):
    zoneId: str
    rows: int
    perRow: int
    rowLabels: str = "alpha"  # alpha|numeric
    startNumber: int = 1
    section: Optional[str] = None


class OfferingOut(_Base):
    id: str
    projectId: str = Field(validation_alias="project_id")
    productId: str = Field(validation_alias="product_id")
    productName: str = ""
    price: Optional[float] = None
    currency: str
    taxRate: float = Field(validation_alias="tax_rate")
    capacity: int
    allocationMode: str = Field(validation_alias="allocation_mode")
    validFrom: Optional[date] = Field(default=None, validation_alias="valid_from")
    validUntil: Optional[date] = Field(default=None, validation_alias="valid_until")
    grantsSegmentId: Optional[str] = Field(default=None, validation_alias="grants_segment_id")
    grantsRoleId: Optional[str] = Field(default=None, validation_alias="grants_role_id")
    maxTicketsPerAttendee: Optional[int] = Field(
        default=None, validation_alias="max_tickets_per_attendee"
    )
    venueId: Optional[str] = Field(default=None, validation_alias="venue_id")
    zoneIds: List[str] = []
    soldCount: int = 0
    heldCount: int = 0
    unitCount: int = 0


class OfferingIn(ApiModel):
    productId: str
    price: Optional[float] = None
    currency: Optional[str] = None  # null → tenant default_currency (resolved server-side)
    taxRate: float = 0
    capacity: int = 0
    allocationMode: str = "GA"
    validFrom: Optional[date] = None
    validUntil: Optional[date] = None
    grantsSegmentId: Optional[str] = None
    grantsRoleId: Optional[str] = None
    maxTicketsPerAttendee: Optional[int] = None
    venueId: Optional[str] = None
    zoneIds: List[str] = []


class OfferingPatch(ApiModel):
    productId: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    taxRate: Optional[float] = None
    capacity: Optional[int] = None
    allocationMode: Optional[str] = None
    validFrom: Optional[date] = None
    validUntil: Optional[date] = None
    grantsSegmentId: Optional[str] = None
    grantsRoleId: Optional[str] = None
    maxTicketsPerAttendee: Optional[int] = None
    venueId: Optional[str] = None
    zoneIds: Optional[List[str]] = None


class CheckoutSeatIn(ApiModel):
    offeringId: str
    seatId: str


class CheckoutGaIn(ApiModel):
    offeringId: str
    qty: int


class CheckoutConfirmIn(ApiModel):
    attendees: List[RegisterAttendee]


class PublicOfferingOut(ApiModel):
    id: str
    productName: str
    price: Optional[float] = None
    currency: str
    allocationMode: str
    remaining: int


class PublicEventOut(ApiModel):
    """Anonymous registration-portal payload (read-only, slice 1)."""
    projectId: str
    title: str
    tenantName: str
    offerings: List[PublicOfferingOut] = []


class RegisterAttendee(ApiModel):
    name: Optional[str] = None
    email: str
    phone: Optional[str] = None


class RegisterItem(ApiModel):
    offeringId: str
    attendee: RegisterAttendee
    capacityUnitId: Optional[str] = None


class RegisterIn(ApiModel):
    items: List[RegisterItem]
    comp: bool = False


class CapacityUnitOut(_Base):
    id: str
    offeringId: str = Field(validation_alias="project_product_id")
    venueSeatId: Optional[str] = Field(default=None, validation_alias="venue_seat_id")
    label: str
    section: Optional[str] = None
    row: Optional[str] = None
    number: Optional[str] = None
    zone: Optional[str] = None
    x: float
    y: float
    status: str
    participantId: Optional[str] = Field(default=None, validation_alias="participant_id")
    occupantName: Optional[str] = None


# ── Cluster D slice 3 (sprint-4/05) — tickets · nomination · checkpoints ─────


class TicketOut(_Base):
    id: str
    projectId: str = Field(validation_alias="project_id")
    offeringId: str = Field(validation_alias="project_product_id")
    capacityUnitId: Optional[str] = Field(default=None, validation_alias="capacity_unit_id")
    attendeeProfileId: Optional[str] = Field(default=None, validation_alias="attendee_profile_id")
    participantId: Optional[str] = Field(default=None, validation_alias="participant_id")
    invoiceId: Optional[str] = Field(default=None, validation_alias="invoice_id")
    status: str
    statusId: Optional[str] = Field(default=None, validation_alias="status_id")
    createdAt: datetime = Field(validation_alias="created_at")


class TicketRowOut(ApiModel):
    """Event-wide tickets list row (BL-120) — the admin Tickets tab. Attendee +
    offering + invoice details resolved set-based in the service (no N+1)."""

    id: str
    attendeeName: str
    attendeeEmail: str
    offeringName: str
    seatLabel: Optional[str] = None
    ticketStatus: str  # status label (e.g. "Issued")
    ticketStatusKey: str  # status key (e.g. "issued")
    paid: bool
    invoiceId: Optional[str] = None
    invoiceTotal: Optional[float] = None
    currency: Optional[str] = None
    qrToken: Optional[str] = None  # signed/opaque QR (AC-05-TKT-02) — admin renders it
    registeredAt: datetime


class NominateIn(ApiModel):
    profileId: str


class NominateOut(ApiModel):
    ticketId: str
    attendeeProfileId: Optional[str] = None
    participantId: Optional[str] = None
    status: str
    qrRotated: bool


class VoidRefundOut(ApiModel):
    """Void/refund result (AC-05-TKT-04) — status moved, QR rotated, seat freed."""

    ticketId: str
    status: str
    qrRotated: bool
    seatReleased: bool


class CheckpointIn(ApiModel):
    name: str
    segmentId: Optional[str] = None
    # Slice 3 = check-in PREVIEW (full event-day = Cluster H). Only single-entry
    # is supported: a ticket may be admitted at a given checkpoint at most once.
    # Multi-entry re-entry tracking is deferred to Cluster H — accepting it here
    # would let the API be configured into a guaranteed-wrong state (a 2nd
    # legitimate admit collides on the dedup), so it is rejected (foolproof-UI).
    entryType: str = "single"

    @field_validator("entryType")
    @classmethod
    def _single_only(cls, v: str) -> str:
        if v != "single":
            raise ValueError("Only single-entry checkpoints are supported in this release.")
        return v


class CheckpointOut(_Base):
    id: str
    projectId: str = Field(validation_alias="project_id")
    name: str
    segmentId: Optional[str] = Field(default=None, validation_alias="segment_id")
    entryType: str = Field(validation_alias="entry_type")
    createdAt: datetime = Field(validation_alias="created_at")


class CheckpointLogOut(ApiModel):
    """One scan record for the check-in log (newest-first). ``attendeeName`` is
    resolved cross-record (ticket → attendee profile / participant profile),
    batch-resolved by the service to avoid N+1."""

    id: str
    checkpointId: str
    ticketId: str
    attendeeName: Optional[str] = None
    result: str  # admitted|denied|already_in
    reason: Optional[str] = None
    scannedAt: datetime


class CheckpointLogListResponse(ApiModel):
    items: List[CheckpointLogOut]
    total: int
    page: int
    pageSize: int


class ScanIn(ApiModel):
    qrToken: str


class ScanOut(ApiModel):
    result: str  # admitted|denied|already_in
    reason: Optional[str] = None
    ticketId: Optional[str] = None
    participantId: Optional[str] = None
    scannedAt: Optional[datetime] = None
