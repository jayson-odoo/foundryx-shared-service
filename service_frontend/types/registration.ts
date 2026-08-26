/**
 * Cluster D (sprint-4/05) registration/ticketing types - Venues, Zones, Seats,
 * Offerings, CapacityUnits. camelCase wire (matches the Resource-shell + EMS
 * convention). Mirrors `documentation/plans/sprint-4/05-...-venue.md` data model.
 *
 * PHASE 1 (frontend-first): consumed by the mock `registration-service`. The
 * backend phase swaps the service bodies to `apiFetch` - these types are the
 * forever contract either way.
 */

export type AllocationMode = 'GA' | 'RESERVED';

/** Anonymous registration-portal payload (read-only, slice 1). */
export interface PublicOffering {
  id: string;
  productName: string;
  price: number | null;
  currency: string;
  allocationMode: AllocationMode;
  remaining: number;
}
export interface PublicEvent {
  projectId: string;
  title: string;
  tenantName: string;
  offerings: PublicOffering[];
}

// ── Checkout flow (slice 2, frontend-first on a mock service) ──

/** A seat shown on the public cinema map (free/held/sold + own-hold flag). */
export interface CheckoutSeat {
  id: string;
  label: string;
  row: string;
  number: string;
  zone: string | null;
  status: UnitStatus; // free|held|sold (held = someone else; mine flagged separately)
  mine: boolean; // held by THIS cart
}

export interface CartLine {
  offeringId: string;
  productName: string;
  allocationMode: AllocationMode;
  unitPrice: number;
  currency: string;
  qty: number;
  /** RESERVED only - the held seat ids + labels in this line. */
  seatIds: string[];
  seatLabels: string[];
}

export interface Cart {
  id: string;
  lines: CartLine[];
  subtotal: number;
  tax: number;
  total: number;
  currency: string;
  /** Hold expiry (ISO) - drives the countdown; null when the cart is empty. */
  expiresAt: string | null;
}

/** One attendee's captured detail (one per ticket). */
export interface AttendeeInput {
  offeringId: string;
  seatLabel: string | null;
  name: string;
  email: string;
  phone: string;
}

/** One ticket as returned by the live confirm response - carries the real
 * signed/opaque QR token (AC-05-TKT-02) the Done screen renders. */
export interface ConfirmedTicket {
  ticketId: string;
  qrToken: string | null;
  attendeeName: string | null;
  offeringName: string | null;
}

export interface OrderResult {
  orderRef: string;
  invoiceTotal: number;
  currency: string;
  ticketCount: number;
  /** Attendee emails that receive the confirmation mail (with tickets/QR). */
  confirmationEmails: string[];
  paid: boolean;
  /** Per-ticket QR from the live confirm result - real signed tokens. */
  tickets: ConfirmedTicket[];
}

export type TicketStatus = 'issued' | 'valid' | 'checked_in' | 'transferred' | 'void' | 'refunded';

// ── Admin add-one (AC-05-CART-09) ──

/** One attendee captured in the admin add-one dialog (wire shape for
 * `POST /ems/projects/{id}/register`). */
export interface AdminRegisterAttendee {
  name?: string;
  email: string;
  phone?: string;
}
export interface AdminRegisterItem {
  offeringId: string;
  attendee: AdminRegisterAttendee;
  /** RESERVED offering only - the chosen free seat's capacity unit. */
  capacityUnitId?: string;
}
export interface AdminRegisterRequest {
  items: AdminRegisterItem[];
  /** Complimentary - skips invoice creation. */
  comp: boolean;
}
/** `CheckoutService.confirm` result. `invoiceId`/`total`/`currency` are null for
 * a comp registration (no invoice minted). */
export interface AdminRegisterResult {
  orderRef: string;
  invoiceId: string | null;
  total: number | null;
  currency: string | null;
  ticketCount: number;
  confirmationEmails: string[];
}

/** Admin view - one registration row for an event (real `GET
 * /ems/projects/{id}/tickets`). `invoiceTotal`/`currency` are null for a comp
 * ticket (no invoice). `ticketStatus` is the status LABEL ("Issued"); the raw
 * key rides `ticketStatusKey`. */
export interface EventRegistration {
  id: string;
  attendeeName: string;
  attendeeEmail: string;
  offeringName: string;
  seatLabel: string | null;
  ticketStatus: string;
  ticketStatusKey: string;
  paid: boolean;
  invoiceId: string | null;
  invoiceTotal: number | null;
  currency: string | null;
  /** Signed/opaque QR token (AC-05-TKT-02) - rendered in the detail view. */
  qrToken: string | null;
  registeredAt: string;
}

/** Admin view - one invoice for an event. */
export interface EventInvoice {
  id: string;
  billToName: string;
  billToType: 'Client' | 'Profile';
  total: number;
  currency: string;
  status: 'Draft' | 'Issued' | 'Paid' | 'Cancelled';
  lineCount: number;
  createdAt: string;
}

/** Real invoice wire (finance module). */
export interface InvoiceLine {
  id: string;
  projectProductId: string | null;
  description: string | null;
  qty: number;
  unitPrice: number;
  taxRate: number;
  taxAmount: number;
  tax: number;
  amount: number;
}
export type PaymentMethod = 'CASH' | 'CARD' | 'BANK' | 'GATEWAY' | 'FPX';
export interface Payment {
  id: string;
  invoiceId: string;
  amount: number;
  method: PaymentMethod;
  statusId: string | null;
  paidAt: string | null;
  note: string | null;
  createdAt: string;
}
export interface TaxSummaryRow {
  rate: number;
  label: string;
  base: number;
  tax: number;
}

/** A ticket that can be refunded on an invoice (Cluster F slice 4, AC-07-37). */
export interface RefundableTicket {
  id: string;
  projectId: string | null;
  status: string;
  refundable: boolean;
}

/** A confirmed/pending refund record (Cluster F slice 4). */
export interface Refund {
  id: string;
  invoiceId: string;
  amount: number;
  method: PaymentMethod;
  statusId: string | null;
  statusKey: string | null;
  creditNoteNumber: string | null;
  gatewayRef: string | null;
  reason: string | null;
  ticketIds: string[];
  createdAt: string;
}

/** An agency give-back settlement (Cluster F slice 4, AC-07-45..48). */
export type SettlementKind = 'PRIMARY' | 'ADJUSTMENT';
export interface SettlementLine {
  id: string;
  invoiceId: string;
  amount: number;
}
export interface Settlement {
  id: string;
  projectId: string;
  clientId: string | null;
  kind: SettlementKind;
  grossCollected: number;
  gatewayFees: number;
  feeType: string | null;
  feeAmount: number;
  netPayable: number;
  statusId: string | null;
  statusKey: string | null;
  statusLabel: string | null;
  remittanceRef: string | null;
  generatedAt: string;
  lines: SettlementLine[];
}
export interface Invoice {
  id: string;
  projectId: string | null;
  billToType: 'Client' | 'Profile';
  billToId: string;
  currency: string;
  statusId: string | null;
  statusLabel: string | null;
  statusKey: string | null;
  invoiceNumber: string | null;
  issuedAt: string | null;
  dueDate: string | null;
  notes: string | null;
  buyerTin: string | null;
  sstRegNo: string | null;
  taxCode: string | null;
  einvoiceType: string | null;
  paidTotal: number;
  billToName: string;
  subtotal: number;
  tax: number;
  total: number;
  createdAt: string;
  lines: InvoiceLine[];
  payments: Payment[];
  taxSummary: TaxSummaryRow[];
}

export interface EventInvoiceLine {
  id: string;
  description: string;
  qty: number;
  unitPrice: number;
  tax: number;
  amount: number;
}
/** Admin invoice detail (form view). */
export interface EventInvoiceDetail {
  id: string;
  billToName: string;
  billToType: 'Client' | 'Profile';
  status: 'Draft' | 'Issued' | 'Paid' | 'Cancelled';
  currency: string;
  subtotal: number;
  tax: number;
  total: number;
  createdAt: string;
  lines: EventInvoiceLine[];
}

/** Portal view - a participant's order (tickets + invoice). */
export interface PortalTicket {
  id: string;
  offeringName: string;
  seatLabel: string | null;
  attendeeName: string;
  status: TicketStatus;
}
export interface PortalOrder {
  orderRef: string;
  eventTitle: string;
  tickets: PortalTicket[];
  invoiceTotal: number;
  currency: string;
  paid: boolean;
}
/** A minted capacity unit's live state (cinema-style hold). */
export type UnitStatus = 'free' | 'held' | 'sold';
export type ZoneKind = 'section' | 'hall' | 'room';

// ── Venue master (tenant-level, reusable across events) ──

export interface Venue {
  id: string;
  name: string;
  address: string | null;
  /** Optional declared headline capacity (informational; seats are the truth). */
  capacity: number | null;
  zoneCount: number;
  seatCount: number;
  isTrashed: boolean;
  createdAt: string;
}

export interface VenueCreate {
  name: string;
  address?: string | null;
  capacity?: number | null;
}
export type VenueUpdate = Partial<VenueCreate>;

export interface VenueZone {
  id: string;
  venueId: string;
  name: string;
  kind: ZoneKind;
  sort: number;
  seatCount: number;
}
export interface VenueZoneCreate {
  name: string;
  kind: ZoneKind;
}
export type VenueZoneUpdate = Partial<{ name: string; kind: ZoneKind; sort: number }>;

export interface VenueSeat {
  id: string;
  venueId: string;
  zoneId: string;
  section: string | null;
  row: string | null;
  number: string | null;
  label: string;
  /** Auto-grid coordinates (R3-4 - visual designer repositions these later). */
  x: number;
  y: number;
}

/** Functional seat generator request (R3-4: "generate N rows × M seats"). */
export interface SeatGenerateRequest {
  zoneId: string;
  rows: number;
  perRow: number;
  /** Row labels: A,B,C… (alpha) or 1,2,3… (numeric). */
  rowLabels: 'alpha' | 'numeric';
  startNumber: number;
  section?: string | null;
}

// ── Offering (per-project; picks a core catalog product) ──

export interface Offering {
  id: string;
  projectId: string;
  productId: string;
  productName: string;
  /** Price override; null = use the product default. */
  price: number | null;
  currency: string;
  /** Per-line tax rate, percent (v1 pricing). */
  taxRate: number;
  capacity: number;
  allocationMode: AllocationMode;
  validFrom: string | null;
  validUntil: string | null;
  grantsSegmentId: string | null;
  grantsRoleId: string | null;
  /** Per-attendee ticket cap (R3-7; null = unlimited). */
  maxTicketsPerAttendee: number | null;
  /** RESERVED seat source - venue + the zones this offering draws seats from. */
  venueId: string | null;
  zoneIds: string[];
  /** Live counters (GA: counter-only; RESERVED: derived from units). */
  soldCount: number;
  heldCount: number;
  /** Minted capacity_units (RESERVED only; 0 for GA). */
  unitCount: number;
}

export interface OfferingCreate {
  productId: string;
  price?: number | null;
  currency: string;
  taxRate: number;
  capacity: number;
  allocationMode: AllocationMode;
  validFrom?: string | null;
  validUntil?: string | null;
  grantsSegmentId?: string | null;
  grantsRoleId?: string | null;
  maxTicketsPerAttendee?: number | null;
  venueId?: string | null;
  zoneIds?: string[];
}
export type OfferingUpdate = Partial<OfferingCreate>;

/** A minted, addressable unit ("seat") for a RESERVED offering. */
export interface CapacityUnit {
  id: string;
  offeringId: string;
  venueSeatId: string | null;
  label: string;
  section: string | null;
  row: string | null;
  number: string | null;
  zone: string | null;
  x: number;
  y: number;
  status: UnitStatus;
  /** Occupant when sold/held (null when free). Phase B = ticket→participant. */
  participantId: string | null;
  occupantName: string | null;
}
