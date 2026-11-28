/**
 * Real Hub Connector service - FastAPI staff routes under `/hub-connector`
 * (`service_backend/modules/hub_connector/routers`).
 */
import { apiFetch } from '@/lib/api-client';
import type {
  ApiKey,
  ApiKeyCreated,
  CustomerPreview,
  Hub,
  HubCreated,
  HubCustomer,
  HubDelivery,
  Option,
  Page,
  ScheduledTask,
  SyncState,
} from '@/types/hub-connector';
import type { HistoryEntry } from '@/types/record-history';
import type { FilterGroup, FilterRule, ListQuery } from '@/types/resource';
import type { HubConnectorService } from './hub-connector-service';

const BASE = '/hub-connector';

/** The list query as the backend reads it: page (0-based), pageSize, search, sort, order. */
export function hubListParams(query: ListQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page));
  p.set('pageSize', String(query.pageSize));
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sort', query.sort.id);
    p.set('order', query.sort.desc ? 'desc' : 'asc');
  }
  return p;
}

function conditions(group: FilterGroup | null | undefined): FilterRule[] {
  if (!group || group.combinator !== 'and') return [];
  return group.rules.flatMap((r) => (r.kind === 'group' ? conditions(r) : [r]));
}

function values(v: unknown): string[] {
  if (Array.isArray(v)) return v.map(String);
  return v === null || v === undefined || v === '' ? [] : [String(v)];
}

/** The list query plus its whitelisted multi-select filters: one repeated param per value. */
export function filteredParams(query: ListQuery, fields: readonly string[]): URLSearchParams {
  const p = hubListParams(query);
  for (const rule of conditions(query.filter)) {
    if (rule.kind !== 'condition' || !fields.includes(rule.field)) continue;
    values(rule.value).forEach((v) => p.append(rule.field, v));
  }
  return p;
}

const HUB_FILTERS = ['status', 'showPrice'] as const;
const CUSTOMER_FILTERS = ['status'] as const;
const DELIVERY_FILTERS = ['status'] as const;

const enc = encodeURIComponent;
const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });
const patch = (body: unknown): RequestInit => ({ method: 'PATCH', body: JSON.stringify(body) });

/** A list answer that is either a bare array or `{data: [...]}`. */
function rows<T>(res: T[] | { data: T[] }): T[] {
  return Array.isArray(res) ? res : res.data;
}

export const realHubConnectorService: HubConnectorService = {
  listHubs(query) {
    return apiFetch<Page<Hub>>(`${BASE}/hubs?${filteredParams(query, HUB_FILTERS).toString()}`);
  },
  createHub(input) {
    return apiFetch<HubCreated>(`${BASE}/hubs`, json(input));
  },
  getHub(id) {
    return apiFetch<Hub>(`${BASE}/hubs/${enc(id)}`);
  },
  updateHub(id, input) {
    return apiFetch<Hub>(`${BASE}/hubs/${enc(id)}`, patch(input));
  },
  async deleteHub(id) {
    await apiFetch(`${BASE}/hubs/${enc(id)}`, { method: 'DELETE' });
  },
  rotateSecret(id) {
    return apiFetch<{ signingSecret: string }>(`${BASE}/hubs/${enc(id)}/rotate-secret`, { method: 'POST' });
  },
  resync(id) {
    return apiFetch<{ queued: number }>(`${BASE}/hubs/${enc(id)}/resync`, { method: 'POST' });
  },

  listCustomers(hubId, query) {
    return apiFetch<Page<HubCustomer>>(
      `${BASE}/hubs/${enc(hubId)}/customers?${filteredParams(query, CUSTOMER_FILTERS).toString()}`,
    );
  },
  createCustomer(hubId, input) {
    return apiFetch<HubCustomer>(`${BASE}/hubs/${enc(hubId)}/customers`, json(input));
  },
  updateCustomer(hubId, customerId, input) {
    return apiFetch<HubCustomer>(`${BASE}/hubs/${enc(hubId)}/customers/${enc(customerId)}`, patch(input));
  },
  async deleteCustomer(hubId, customerId) {
    await apiFetch(`${BASE}/hubs/${enc(hubId)}/customers/${enc(customerId)}`, { method: 'DELETE' });
  },
  previewCustomer(hubId, customerId) {
    return apiFetch<CustomerPreview>(`${BASE}/hubs/${enc(hubId)}/customers/${enc(customerId)}/preview`);
  },

  listDeliveries(hubId, query, statuses = []) {
    const p = filteredParams(query, DELIVERY_FILTERS);
    statuses.forEach((s) => p.append('status', s));
    return apiFetch<Page<HubDelivery>>(`${BASE}/hubs/${enc(hubId)}/deliveries?${p.toString()}`);
  },
  async redeliver(deliveryId) {
    await apiFetch(`${BASE}/deliveries/${enc(deliveryId)}/redeliver`, { method: 'POST' });
  },

  async listOptions(kind, search) {
    const q = search ? `?search=${enc(search)}` : '';
    return rows(await apiFetch<Option[] | { data: Option[] }>(`${BASE}/options/${kind}${q}`));
  },

  async listKeys(hubId) {
    return rows(await apiFetch<ApiKey[] | { data: ApiKey[] }>(`${BASE}/hubs/${enc(hubId)}/keys`));
  },
  async createKey(hubId, name) {
    return apiFetch<ApiKeyCreated>(`${BASE}/hubs/${enc(hubId)}/keys`, json({ name }));
  },
  async revokeKey(hubId, id) {
    await apiFetch(`${BASE}/hubs/${enc(hubId)}/keys/${enc(id)}`, { method: 'DELETE' });
  },

  async hubHistory(hubId) {
    return rows(await apiFetch<HistoryEntry[] | { data: HistoryEntry[] }>(`${BASE}/hubs/${enc(hubId)}/history`));
  },

  async listScheduledTasks() {
    return rows(await apiFetch<ScheduledTask[] | { data: ScheduledTask[] }>(`${BASE}/scheduled-tasks`));
  },
  async runScheduledTask(key) {
    return rows(
      await apiFetch<ScheduledTask[] | { data: ScheduledTask[] }>(`${BASE}/scheduled-tasks/${enc(key)}/run`, {
        method: 'POST',
      }),
    );
  },

  getSync() {
    return apiFetch<SyncState>(`${BASE}/sync`);
  },
  syncNow() {
    return apiFetch<SyncState>(`${BASE}/sync`, { method: 'POST' });
  },
};
