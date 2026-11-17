/**
 * Lead Capture service - the boundary the Lead Capture screens talk to (lane
 * L-D, AC-64-57). The barrel binds the REAL api-client implementation. Every
 * call is the signed-in company's own data (the backend scopes by the JWT).
 */
import type {
  LeadEvent,
  LeadField,
  LeadFieldList,
  LeadFormQuestions,
  LeadKeyCreated,
  LeadKeyItem,
  LeadReceiverCreated,
  LeadReceiverItem,
  LeadSourceItem,
} from '@/types/lead-capture';
import { BASE_URL } from '@/lib/api-client';
import { realLeadCaptureService } from './lead-capture-service.real';

export interface LeadCaptureService {
  listKeys(): Promise<LeadKeyItem[]>;
  /** Returns the full key ONCE. */
  createKey(name: string): Promise<LeadKeyCreated>;

  listReceivers(): Promise<LeadReceiverItem[]>;
  /** Returns the signing secret ONCE. */
  createReceiver(url: string, events: LeadEvent[]): Promise<LeadReceiverCreated>;
  /** Queue one signed test delivery to the receiver. */
  sendTestPush(receiverId: string): Promise<void>;
  /** Remove every receiver at once (switch to pull only). */
  removeReceivers(ids: string[]): Promise<void>;

  getFields(): Promise<LeadFieldList>;
  /** Replace the product's field list; `[]` = back to the defaults. */
  saveFields(fields: LeadField[]): Promise<LeadFieldList>;

  listSources(): Promise<LeadSourceItem[]>;
  formQuestions(sourceId: string, formId: string): Promise<LeadFormQuestions>;
  /** Save one form's map (`formId` "*" = every form of the Page). */
  saveFieldMap(
    sourceId: string,
    formId: string,
    map: Record<string, string | null>,
  ): Promise<LeadSourceItem>;
}

export const leadCaptureService: LeadCaptureService = realLeadCaptureService;

/** The address a pull-only product reads its leads from (key-authed gateway). */
export function leadsPullUrl(): string {
  return `${BASE_URL.replace(/\/$/, '')}/api/v1/lead-capture/leads`;
}
