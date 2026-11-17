/**
 * Staff Lead Capture Sources + Leads service boundary (plan 64 L-C,
 * AC-64-05/06/53). Real backend (`/lead-capture/*`, session JWT). The Resource
 * shell's filter tree is flattened to the endpoints' whitelisted params; a
 * field the server does not know is never sent.
 */
import { apiFetch } from '@/lib/api-client';
import type { FilterGroup, FilterRule, ListQuery, ListResult } from '@/types/resource';
import type { LeadDelivery, StaffLead, StaffLeadDetail, StaffSource } from '@/types/lead-capture-sources';

const BASE = '/lead-capture';

/** Sort ids the server sorts on (anything else falls back to its default). */
const SOURCE_SORTS = new Set(['name', 'platform', 'pageName', 'status', 'lastLeadAt', 'createdAt', 'leads7d']);
const LEAD_SORTS = new Set(['receivedAt', 'sourceName', 'platform', 'formName', 'email', 'phone', 'isTest']);

function conditions(group: FilterGroup | null | undefined): FilterRule[] {
  if (!group || group.combinator !== 'and') return [];
  return group.rules.flatMap((r) => (r.kind === 'group' ? conditions(r) : [r]));
}

function values(v: unknown): string[] {
  if (Array.isArray(v)) return v.map(String);
  return v === null || v === undefined || v === '' ? [] : [String(v)];
}

function baseParams(query: ListQuery, sorts: Set<string>): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page));
  p.set('pageSize', String(query.pageSize));
  if (query.search) p.set('search', query.search);
  if (query.sort && sorts.has(query.sort.id)) {
    p.set('sort', query.sort.id);
    p.set('order', query.sort.desc ? 'desc' : 'asc');
  }
  return p;
}

export function sourceListParams(query: ListQuery): URLSearchParams {
  const p = baseParams(query, SOURCE_SORTS);
  for (const rule of conditions(query.filter)) {
    if (rule.kind !== 'condition') continue;
    if (rule.field === 'status' || rule.field === 'platform') values(rule.value).forEach((v) => p.append(rule.field, v));
  }
  return p;
}

export function leadListParams(query: ListQuery, sourceId?: string | null): URLSearchParams {
  const p = baseParams(query, LEAD_SORTS);
  if (sourceId) p.append('source', sourceId);
  for (const rule of conditions(query.filter)) {
    if (rule.kind !== 'condition') continue;
    if (rule.field === 'source' || rule.field === 'platform') values(rule.value).forEach((v) => p.append(rule.field, v));
    if (rule.field === 'isTest') {
      if (rule.operator === 'is_true') p.set('isTest', 'true');
      if (rule.operator === 'is_false') p.set('isTest', 'false');
    }
    if (rule.field === 'receivedAt') {
      const [a, b] = values(rule.value);
      if (rule.operator === 'between') {
        if (a) p.set('receivedFrom', a);
        if (b) p.set('receivedTo', b);
      } else if (rule.operator === 'after' && a) p.set('receivedFrom', a);
      else if (rule.operator === 'before' && a) p.set('receivedTo', a);
      else if (rule.operator === 'eq' && a) {
        p.set('receivedFrom', a);
        p.set('receivedTo', a);
      }
    }
  }
  return p;
}

export interface LeadCaptureSourcesService {
  listSources(query: ListQuery): Promise<ListResult<StaffSource>>;
  listLeads(query: ListQuery, sourceId?: string | null): Promise<ListResult<StaffLead>>;
  leadDetail(id: string): Promise<StaffLeadDetail>;
  redeliver(deliveryId: string): Promise<LeadDelivery>;
  disconnect(sourceId: string): Promise<void>;
  /** A single-use hosted wizard URL for this user (Connect / Reconnect / Map fields). */
  wizardUrl(returnOrigin: string, sourceId?: string): Promise<string>;
}

export const leadCaptureSourcesService: LeadCaptureSourcesService = {
  async listSources(query) {
    const res = await apiFetch<{ data: StaffSource[]; total: number }>(
      `${BASE}/sources/list?${sourceListParams(query).toString()}`,
    );
    return { data: res.data, total: res.total, page: query.page };
  },
  async listLeads(query, sourceId) {
    const res = await apiFetch<{ data: StaffLead[]; total: number }>(
      `${BASE}/leads?${leadListParams(query, sourceId).toString()}`,
    );
    return { data: res.data, total: res.total, page: query.page };
  },
  async leadDetail(id) {
    const [detail, fields] = await Promise.all([
      apiFetch<Omit<StaffLeadDetail, 'fieldLabels'>>(`${BASE}/leads/${encodeURIComponent(id)}`),
      apiFetch<{ data: { key: string; label: string }[] }>(`${BASE}/fields`),
    ]);
    const fieldLabels = Object.fromEntries(fields.data.map((f) => [f.key, f.label || f.key]));
    return { ...detail, fieldLabels };
  },
  redeliver: (deliveryId) =>
    apiFetch<LeadDelivery>(`${BASE}/deliveries/${encodeURIComponent(deliveryId)}/redeliver`, { method: 'POST' }),
  disconnect: async (sourceId) => {
    await apiFetch(`${BASE}/sources/${encodeURIComponent(sourceId)}`, { method: 'DELETE' });
  },
  async wizardUrl(returnOrigin, sourceId) {
    const res = await apiFetch<{ url: string }>(`${BASE}/connect-sessions`, {
      method: 'POST',
      body: JSON.stringify({ returnOrigin, sourceId: sourceId ?? null }),
    });
    return res.url;
  },
};
