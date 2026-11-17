/**
 * Staff Lead Capture Sources + Leads lists (plan 64 L-C, AC-64-05/53).
 * Mirror of `StaffSourceItem` / `StaffLeadItem` / `StaffLeadDetail` in
 * `service_backend/modules/lead_capture/schemas.py`.
 */
import type { WizardSource } from './lead-capture-wizard';

export interface StaffSource extends WizardSource {
  leads7d: number;
  backfillLastRunAt: string | null;
  backfillLastError: string | null;
}

export type DeliveryStatus = 'PENDING' | 'SUCCESS' | 'FAILED';

export interface StaffLead {
  id: string;
  sourceId: string;
  sourceName: string;
  platform: string;
  formId: string | null;
  formName: string | null;
  name: string | null;
  email: string | null;
  phone: string | null;
  isTest: boolean;
  duplicateOf: string | null;
  receivedAt: string;
  deliveryStatus: DeliveryStatus | null;
}

export interface LeadAnswer {
  key?: string;
  label?: string;
  value?: string | string[] | null;
}

/** The documented lead body (consumer guide), as the detail shows it. */
export interface LeadBody {
  id: string;
  sourceId: string;
  sourceName: string;
  platform: string;
  platformLeadId: string;
  pageId: string | null;
  formId: string | null;
  formName: string | null;
  receivedAt: string;
  createdAt: string | null;
  isTest: boolean;
  duplicateOf: string | null;
  fields: Record<string, string | null>;
  answers: LeadAnswer[];
  attribution: Record<string, string | null>;
}

export interface LeadDelivery {
  id: string;
  leadId: string | null;
  event: string;
  status: DeliveryStatus;
  attempt: number;
  nextAttemptAt: string | null;
  lastStatusCode: number | null;
  lastError: string | null;
  endpointUrl: string | null;
  lastAttemptAt: string | null;
  createdAt: string | null;
}

export interface StaffLeadDetail {
  lead: LeadBody;
  deliveries: LeadDelivery[];
}
