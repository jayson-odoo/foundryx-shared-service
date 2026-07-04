/** EMS domain types (sprint-3/11, F4) — mirror of the module wire schemas. */

export interface Profile {
  id: string;
  email: string;
  phone: string | null;
  fullName: string | null;
  country: string | null;
  organization: string | null;
  title: string | null;
  statusId: string | null;
  createdAt: string;
}

export interface ProjectType {
  id: string;
  name: string;
  description: string | null;
}

export interface ProjectTemplate {
  id: string;
  typeId: string;
  name: string;
  description: string | null;
}

/** A template-owned role or segment (shared by participants, not copied). */
export interface TemplateChild {
  id: string;
  name: string;
}

export interface Project {
  id: string;
  templateId: string;
  typeId: string | null;
  title: string;
  brief: string | null;
  notes: string | null;
  domainName: string | null;
  /** Calendar dates (date-only, "YYYY-MM-DD") — not instants. */
  startDate: string | null;
  endDate: string | null;
  eventValidityEnd: string | null;
  statusId: string | null;
  /** Commercial mode + agency fee config (Cluster F slice 4, AC-07-45). */
  commercialMode: CommercialMode;
  feeType: FeeType | null;
  feeValue: number | null;
  paymentConnectionId: string | null;
  createdAt: string;
}

export type CommercialMode = 'SELF_RUN' | 'AGENCY';
export type FeeType = 'PERCENT' | 'FLAT' | 'PER_TICKET';

/** PATCH body for the event Details edit — all-optional; immutable fields
 * (template/type/client/status) are intentionally absent. */
export interface ProjectUpdate {
  title?: string;
  brief?: string | null;
  notes?: string | null;
  domainName?: string | null;
  startDate?: string | null;
  endDate?: string | null;
  eventValidityEnd?: string | null;
  commercialMode?: CommercialMode;
  feeType?: FeeType | null;
  feeValue?: number | null;
  paymentConnectionId?: string | null;
}

export interface Participant {
  id: string;
  profileId: string;
  projectId: string;
  roleId: string | null;
  segmentId: string | null;
  statusId: string | null;
}

/** A ticket (Cluster D slice 3) — status-engine backed, signed QR. */
export interface Ticket {
  id: string;
  projectId: string;
  offeringId: string;
  capacityUnitId: string | null;
  attendeeProfileId: string | null;
  participantId: string | null;
  invoiceId: string | null;
  status: string;
  statusId: string | null;
  createdAt: string;
}

/** Result of a ticket nomination / transfer. */
export interface NominateResult {
  ticketId: string;
  attendeeProfileId: string | null;
  participantId: string | null;
  status: string;
  qrRotated: boolean;
}

/** Result of a void / refund (AC-05-TKT-04). */
export interface VoidRefundResult {
  ticketId: string;
  status: string;
  qrRotated: boolean;
  seatReleased: boolean;
}

/** Cluster D slice 3 (sprint-4/05) — event-day check-in. */
export interface Checkpoint {
  id: string;
  projectId: string;
  name: string;
  segmentId: string | null;
  entryType: string; // single (only mode in v1)
  createdAt: string;
}

export interface CheckpointCreate {
  name: string;
  segmentId?: string | null;
  entryType?: string;
}

/** A QR scan result returned by POST /checkpoints/{id}/scan. */
export interface ScanResult {
  result: 'admitted' | 'denied' | 'already_in';
  reason: string | null;
  ticketId: string | null;
  participantId: string | null;
  scannedAt: string | null;
}

/** One recent-scan log row (newest-first) with the attendee name resolved. */
export interface CheckpointLog {
  id: string;
  checkpointId: string;
  ticketId: string;
  attendeeName: string | null;
  result: 'admitted' | 'denied' | 'already_in';
  reason: string | null;
  scannedAt: string;
}

/** Cluster B (sprint-3/12) — commercial CRM. */
export interface Client {
  id: string;
  name: string;
  registrationNo: string | null;
  contactPerson: string | null;
  contactEmail: string | null;
  contactPhone: string | null;
  statusId: string | null;
  createdAt: string;
}

export interface Lead {
  id: string;
  clientId: string | null;
  title: string;
  source: string | null;
  contactName: string | null;
  contactEmail: string | null;
  contactPhone: string | null;
  notes: string | null;
  statusId: string | null;
  createdAt: string;
}

/** An event spawned from a Won lead (cross-module, resolved from EMS). */
export interface LeadEvent {
  id: string;
  title: string | null;
  statusId: string | null;
}

/** Product kind = extensible registry option (key + display label). */
export interface ProductKind {
  key: string;
  label: string;
}

export interface TenantSettings {
  defaultCurrency: string;
  priceDecimals: number;
}

export interface ProductCategory {
  id: string;
  parentId: string | null;
  name: string;
  sort: number | null;
}

export interface Product {
  id: string;
  categoryId: string | null;
  name: string;
  sku: string | null;
  kind: string;
  kindLabel?: string | null;
  defaultPrice: number | null;
  tax: number | null;
  currency: string | null;
  uom: string | null;
  isActive: boolean;
  createdAt: string;
}

export interface QuotationLine {
  id?: string;
  productId: string | null;
  description: string | null;
  qty: number;
  unitPrice: number;
  amount?: number;
  sort?: number | null;
}

export interface Quotation {
  id: string;
  clientId: string;
  leadId: string | null;
  projectId: string | null;
  revisionNumber: number;
  parentQuotationId: string | null;
  currency: string | null;
  notes: string | null;
  statusId: string | null;
  total: number;
  lines: QuotationLine[];
  createdAt: string;
}

export interface SalesOrderLine {
  id?: string;
  productId: string | null;
  description: string | null;
  qty: number;
  unitPrice: number;
  taxRate?: number;
  amount?: number;
  invoicedQty?: number;
  sort?: number | null;
}

export interface SalesOrder {
  id: string;
  docNumber: string | null;
  clientId: string;
  quotationId: string | null;
  projectId: string | null;
  currency: string | null;
  notes: string | null;
  statusId: string | null;
  total: number;
  lines: SalesOrderLine[];
  createdAt: string;
}

/** One chosen line + qty for "create invoice from SO". */
export interface InvoiceLineSelection {
  lineId: string;
  qty: number;
}

/** The minimal invoice header returned by create-invoice-from-SO. */
export interface CreatedInvoice {
  id: string;
  total: number | null;
  currency: string | null;
}

/** Drive file linked to a domain entity (core /documents/file-links). */
export interface FileLink {
  id: string;
  entityType: string;
  entityId: string;
  fileId: string;
  createdAt: string;
}

export interface EmsList<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}
