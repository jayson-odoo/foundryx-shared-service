/**
 * Hosted Lead Capture wizard service boundary (plan 64 L-C). The hosted page
 * has NO NextAuth session: `redeem` swaps the URL secret for a scoped wizard
 * token, every other call carries it as a Bearer. Real backend only - the
 * simulated Facebook flow (no Meta app on the server) is the backend's own
 * dev path, not a frontend mock.
 */
import { publicFetch } from '@/lib/api-client';
import type {
  WizardConsumerField,
  WizardContext,
  WizardDone,
  WizardFormList,
  WizardPage,
  WizardQuestionList,
  WizardSessionGrant,
  WizardSource,
} from '@/types/lead-capture-wizard';

const BASE = '/public/lead-capture';

function auth(token: string, init: RequestInit = {}): RequestInit {
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${token}`);
  return { ...init, headers };
}

function json(method: string, body: unknown): RequestInit {
  return { method, body: JSON.stringify(body) };
}

export interface LeadCaptureWizardService {
  redeem(secret: string): Promise<WizardSessionGrant>;
  context(token: string): Promise<WizardContext>;
  login(token: string, code: string, redirectUri?: string): Promise<WizardPage[]>;
  pages(token: string): Promise<WizardPage[]>;
  connect(token: string, pageId: string): Promise<WizardSource>;
  source(token: string, sourceId: string): Promise<WizardSource>;
  forms(token: string, sourceId: string): Promise<WizardFormList>;
  saveForms(token: string, sourceId: string, formsMode: 'all' | 'pick', formIds: string[]): Promise<WizardSource>;
  fields(token: string): Promise<WizardConsumerField[]>;
  questions(token: string, sourceId: string, formId: string): Promise<WizardQuestionList>;
  saveFieldMap(token: string, sourceId: string, formId: string, map: Record<string, string | null>): Promise<WizardSource>;
  sendTestLead(token: string, sourceId: string, formId: string): Promise<void>;
  finish(token: string): Promise<WizardDone>;
}

export const leadCaptureWizardService: LeadCaptureWizardService = {
  redeem: (secret) => publicFetch<WizardSessionGrant>(`${BASE}/connect/redeem`, json('POST', { token: secret })),
  context: (token) => publicFetch<WizardContext>(`${BASE}/wizard/context`, auth(token)),
  login: async (token, code, redirectUri) =>
    (
      await publicFetch<{ data: WizardPage[] }>(
        `${BASE}/wizard/facebook/login`,
        auth(token, json('POST', { code, redirectUri: redirectUri ?? null })),
      )
    ).data,
  pages: async (token) =>
    (await publicFetch<{ data: WizardPage[] }>(`${BASE}/wizard/facebook/pages`, auth(token))).data,
  connect: (token, pageId) =>
    publicFetch<WizardSource>(`${BASE}/wizard/facebook/connect`, auth(token, json('POST', { pageId }))),
  source: (token, sourceId) =>
    publicFetch<WizardSource>(`${BASE}/wizard/sources/${encodeURIComponent(sourceId)}`, auth(token)),
  forms: (token, sourceId) =>
    publicFetch<WizardFormList>(`${BASE}/wizard/sources/${encodeURIComponent(sourceId)}/forms`, auth(token)),
  saveForms: (token, sourceId, formsMode, formIds) =>
    publicFetch<WizardSource>(
      `${BASE}/wizard/sources/${encodeURIComponent(sourceId)}/forms`,
      auth(token, json('PUT', { formsMode, formIds })),
    ),
  fields: async (token) =>
    (await publicFetch<{ data: WizardConsumerField[] }>(`${BASE}/wizard/fields`, auth(token))).data,
  questions: (token, sourceId, formId) =>
    publicFetch<WizardQuestionList>(
      `${BASE}/wizard/sources/${encodeURIComponent(sourceId)}/forms/${encodeURIComponent(formId)}/questions`,
      auth(token),
    ),
  saveFieldMap: (token, sourceId, formId, map) =>
    publicFetch<WizardSource>(
      `${BASE}/wizard/sources/${encodeURIComponent(sourceId)}/field-map`,
      auth(token, json('PUT', { formId, map })),
    ),
  sendTestLead: async (token, sourceId, formId) => {
    await publicFetch(
      `${BASE}/wizard/sources/${encodeURIComponent(sourceId)}/test-lead`,
      auth(token, json('POST', { formId })),
    );
  },
  finish: (token) => publicFetch<WizardDone>(`${BASE}/wizard/finish`, auth(token, json('POST', {}))),
};
