/**
 * Lead Capture staff-API wire types (lane L-D, AC-64-57). Mirrors
 * `service_backend/modules/lead_capture/schemas.py` - camelCase, ISO-Z.
 * Everything is the signed-in company's own data (one product = one company).
 */

/** A gateway key as listed (never the plaintext). */
export interface LeadKeyItem {
  id: string;
  name: string;
  keyMasked: string;
  createdAt: string;
  lastUsedAt: string | null;
  revokedAt: string | null;
}

/** Create answer - the full key, shown ONCE. */
export interface LeadKeyCreated extends LeadKeyItem {
  key: string;
}

export type LeadEvent = 'lead.created' | 'lead.updated' | 'source.updated';

/** A product receiver (push endpoint). */
export interface LeadReceiverItem {
  id: string;
  url: string;
  events: LeadEvent[];
  createdAt: string;
  lastSuccessAt: string | null;
}

/** Create answer - the signing secret, shown ONCE. */
export interface LeadReceiverCreated extends LeadReceiverItem {
  secret: string;
}

export type LeadFieldType = 'name' | 'phone' | 'email' | 'notes' | 'text';

/** One of the product's own lead fields (a map target). */
export interface LeadField {
  key: string;
  label: string;
  type: LeadFieldType;
}

export interface LeadFieldList {
  data: LeadField[];
  /** True when the company saved no list and the four defaults apply. */
  isDefault: boolean;
}

export interface LeadFormNotice {
  formId: string;
  formName: string | null;
  unmappedCount: number;
}

/** A connected lead source (a Facebook Page today). */
export interface LeadSourceItem {
  id: string;
  platform: string;
  name: string;
  status: string;
  pageId: string | null;
  pageName: string | null;
  formsMode: string | null;
  needsMapping: LeadFormNotice[];
  /** `{formId | "*": {questionKey: fieldKey}}`. */
  fieldMap: Record<string, Record<string, string>>;
  lastLeadAt: string | null;
  createdAt: string;
}

export interface LeadFormQuestion {
  key: string;
  label: string;
  type: string;
}

export interface LeadFormQuestions {
  formId: string;
  formName: string | null;
  data: LeadFormQuestion[];
}

/** The "*" form id: one map for every form of a Page. */
export const ALL_FORMS = '*';
