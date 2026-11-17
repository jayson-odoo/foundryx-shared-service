/**
 * Real Lead Capture service - FastAPI staff routes under `/lead-capture`
 * (`service_backend/modules/lead_capture/routers/staff.py`).
 */
import { ApiError, apiFetch } from '@/lib/api-client';
import type {
  LeadFieldList,
  LeadFormList,
  LeadFormQuestions,
  LeadKeyCreated,
  LeadKeyItem,
  LeadReceiverCreated,
  LeadReceiverItem,
  LeadSourceItem,
} from '@/types/lead-capture';
import type { LeadCaptureService } from './lead-capture-service';

const BASE = '/lead-capture';

export const realLeadCaptureService: LeadCaptureService = {
  async listKeys() {
    const res = await apiFetch<{ data: LeadKeyItem[] }>(`${BASE}/keys`);
    return res.data;
  },
  createKey(name) {
    return apiFetch<LeadKeyCreated>(`${BASE}/keys`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  },

  async listReceivers() {
    const res = await apiFetch<{ data: LeadReceiverItem[] }>(`${BASE}/webhooks`);
    return res.data;
  },
  createReceiver(url, events) {
    return apiFetch<LeadReceiverCreated>(`${BASE}/webhooks`, {
      method: 'POST',
      body: JSON.stringify({ url, events }),
    });
  },
  async sendTestPush(receiverId) {
    await apiFetch(`${BASE}/webhooks/${encodeURIComponent(receiverId)}/test`, { method: 'POST' });
  },
  async removeReceivers(ids) {
    for (const id of ids) {
      try {
        await apiFetch(`${BASE}/webhooks/${encodeURIComponent(id)}`, { method: 'DELETE' });
      } catch (err) {
        // Already removed (e.g. a Remove that lapsed meanwhile) - the goal holds.
        if (!(err instanceof ApiError && err.status === 404)) throw err;
      }
    }
  },

  getFields() {
    return apiFetch<LeadFieldList>(`${BASE}/fields`);
  },
  saveFields(fields) {
    return apiFetch<LeadFieldList>(`${BASE}/fields`, {
      method: 'PUT',
      body: JSON.stringify(fields),
    });
  },

  async listSources() {
    const res = await apiFetch<{ data: LeadSourceItem[] }>(`${BASE}/sources`);
    return res.data;
  },
  listForms(sourceId) {
    return apiFetch<LeadFormList>(`${BASE}/sources/${encodeURIComponent(sourceId)}/forms`);
  },
  formQuestions(sourceId, formId) {
    return apiFetch<LeadFormQuestions>(
      `${BASE}/sources/${encodeURIComponent(sourceId)}/forms/${encodeURIComponent(formId)}/questions`,
    );
  },
  saveFieldMap(sourceId, formId, map) {
    return apiFetch<LeadSourceItem>(
      `${BASE}/sources/${encodeURIComponent(sourceId)}/field-map`,
      { method: 'PUT', body: JSON.stringify({ formId, map }) },
    );
  },
};
