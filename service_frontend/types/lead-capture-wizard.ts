/**
 * Hosted Lead Capture connect wizard wire types (plan 64 L-C). Mirror of
 * `service_backend/modules/lead_capture/schemas.py` (Wizard*, FacebookPage*,
 * SourceItem, FormList, FormQuestionList, ConsumerFieldList).
 */

export type LeadSourceStatus = 'DRAFT' | 'WAITING_FOR_TEST' | 'LIVE' | 'NEEDS_RECONNECT' | 'DISCONNECTED';

export interface WizardFormNotice {
  formId: string;
  formName: string | null;
  unmappedCount: number;
}

export interface WizardSource {
  id: string;
  platform: string;
  name: string;
  status: LeadSourceStatus;
  pageId: string | null;
  pageName: string | null;
  formsMode: string | null;
  formIds: string[];
  needsMapping: WizardFormNotice[];
  fieldMap: Record<string, Record<string, string>>;
  lastLeadAt: string | null;
  createdAt: string;
}

export interface WizardSessionGrant {
  accessToken: string;
  expiresAt: string;
  returnOrigin: string | null;
  sourceId: string | null;
}

export interface WizardChannel {
  key: string;
  label: string;
  setup: 'automatic' | 'guided';
}

export interface WizardLoginConfig {
  available: boolean;
  simulated: boolean;
  appId: string | null;
  configId: string | null;
  graphVersion: string;
  scopes: string[];
}

export interface WizardContext {
  branding: { name: string; logoUrl: string | null };
  channels: WizardChannel[];
  login: WizardLoginConfig;
  returnOrigin: string | null;
  source: WizardSource | null;
}

export interface WizardPage {
  id: string;
  name: string;
}

export interface WizardForm {
  id: string;
  name: string | null;
  status: string | null;
  createdAt: string | null;
}

export interface WizardFormList {
  formsMode: string;
  formIds: string[];
  tosAccepted: boolean | null;
  data: WizardForm[];
}

export interface WizardQuestion {
  key: string;
  label: string;
  type: string;
}

export interface WizardQuestionList {
  formId: string;
  formName: string | null;
  data: WizardQuestion[];
}

export interface WizardConsumerField {
  key: string;
  label: string;
  type: string;
}

export interface WizardDone {
  source: WizardSource;
  connectedBy: string | null;
  connectedAt: string | null;
  testLeadAt: string | null;
  testLeadFormName: string | null;
  waitingForRealLead: boolean;
}

/** postMessage contract to the opener (AC-64-08). */
export type LeadCaptureMessage =
  | { type: 'lead-capture:done'; sourceId: string }
  | { type: 'lead-capture:closed'; sourceId?: string };
