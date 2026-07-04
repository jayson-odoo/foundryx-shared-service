/**
 * Real WhatsApp template service — talks to FastAPI via the shared api-client.
 * Endpoints per plan 07 §4 (mounted under /omnichannel/channels/{id}/templates).
 */
import { apiFetch } from '@/lib/api-client';
import type { ListQuery, ListResult } from '@/types/resource';
import type { TemplateDetail, TemplateManageItem, WaTemplateDoc } from '@/types/whatsapp-template';
import type { UploadSampleResult, WhatsappTemplateService } from './whatsapp-template-service';

function listParams(query: ListQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page));
  p.set('page_size', String(query.pageSize));
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sort_by', query.sort.id);
    p.set('sort_dir', query.sort.desc ? 'desc' : 'asc');
  }
  // Template-specific facets ride the query's `extra` bag.
  const extra = (query as ListQuery & { extra?: Record<string, string> }).extra;
  if (extra) for (const [k, v] of Object.entries(extra)) if (v) p.set(k, v);
  return p;
}

const base = (channelId: string) => `/omnichannel/channels/${channelId}/templates`;

export const realWhatsappTemplateService: WhatsappTemplateService = {
  listManage(channelId, query) {
    return apiFetch<ListResult<TemplateManageItem>>(
      `${base(channelId)}/manage?${listParams(query).toString()}`,
    );
  },
  get(channelId, templateId) {
    return apiFetch<TemplateDetail>(`${base(channelId)}/manage/${templateId}`);
  },
  saveDraft(channelId, doc: WaTemplateDoc) {
    return apiFetch<TemplateDetail>(base(channelId), {
      method: 'POST',
      body: JSON.stringify(doc),
    });
  },
  edit(channelId, templateId, doc: WaTemplateDoc) {
    return apiFetch<TemplateDetail>(`${base(channelId)}/${templateId}`, {
      method: 'PATCH',
      body: JSON.stringify(doc),
    });
  },
  submit(channelId, templateId) {
    return apiFetch<TemplateDetail>(`${base(channelId)}/${templateId}/submit`, { method: 'POST' });
  },
  async remove(channelId, templateId) {
    await apiFetch<void>(`${base(channelId)}/${templateId}`, { method: 'DELETE' });
  },
  async sync(channelId) {
    const res = await apiFetch<ListResult<TemplateManageItem>>(`${base(channelId)}/sync`, {
      method: 'POST',
    });
    return res.data;
  },
  uploadSample(channelId, file: File) {
    const form = new FormData();
    form.append('file', file);
    return apiFetch<UploadSampleResult>(`${base(channelId)}/upload-sample`, {
      method: 'POST',
      body: form,
    });
  },
};
