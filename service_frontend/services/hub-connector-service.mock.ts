// PHASE 1 MOCK - in-memory Hub Connector service for tests and the dev toggle.
// The shipped barrel (`hub-connector-service.ts`) binds the REAL implementation.
// All names below are made up.
import type {
  ApiKey,
  Hub,
  HubCustomer,
  HubDelivery,
  Option,
  OptionKind,
  Page,
  PreviewItem,
  SyncState,
} from '@/types/hub-connector';
import type { ListQuery } from '@/types/resource';
import type { HubConnectorService } from './hub-connector-service';

const LOCATIONS: Option[] = [
  { code: 'LOC-N', name: 'North warehouse' },
  { code: 'LOC-S', name: 'South warehouse' },
  { code: 'LOC-E', name: 'East showroom' },
];
const BRANDS: Option[] = [
  { code: 'BR-A', name: 'Alpha Tools' },
  { code: 'BR-B', name: 'Beta Fittings' },
  { code: 'BR-C', name: 'Gamma Paints' },
];
const CUSTOMERS: Option[] = [
  { code: 'CU-001', name: 'Sample Trading Co' },
  { code: 'CU-002', name: 'Example Supplies Ltd' },
];

const NOW = '2026-11-20T08:00:00Z';

function pick(options: Option[], codes: string[]): Option[] {
  return options.filter((o) => codes.includes(o.code));
}

function paginate<T>(items: T[], query: ListQuery, text: (row: T) => string, value: (row: T, field: string) => unknown): Page<T> {
  const term = (query.search ?? '').trim().toLowerCase();
  let out = term ? items.filter((r) => text(r).toLowerCase().includes(term)) : items.slice();
  if (query.sort) {
    const { id, desc } = query.sort;
    out = out.sort((a, b) => {
      const x = value(a, id);
      const y = value(b, id);
      const cmp = String(x ?? '').localeCompare(String(y ?? ''), undefined, { numeric: true });
      return desc ? -cmp : cmp;
    });
  }
  const start = query.page * query.pageSize;
  return { data: out.slice(start, start + query.pageSize), total: out.length, page: query.page, pageSize: query.pageSize };
}

export interface MockState {
  hubs: Hub[];
  customers: HubCustomer[];
  deliveries: Record<string, HubDelivery[]>;
  keys: ApiKey[];
  sync: SyncState;
}

function seed(): MockState {
  const hub: Hub = {
    id: 'hub-1',
    name: 'Partner Hub One',
    code: 'partner-one',
    callbackUrl: 'https://hub.example.com/hooks/availability',
    exposePrice: false,
    active: true,
    customerCount: 2,
    lastSuccessAt: NOW,
    createdAt: NOW,
    updatedAt: NOW,
  };
  const mk = (id: string, cu: Option, loc: string[], br: string[]): HubCustomer => ({
    id,
    hubId: hub.id,
    customerCode: cu.code,
    customerName: cu.name,
    locationCodes: loc,
    brandCodes: br,
    locations: pick(LOCATIONS, loc),
    brands: pick(BRANDS, br),
    active: true,
    updatedAt: NOW,
  });
  return {
    hubs: [hub],
    customers: [mk('hc-1', CUSTOMERS[0], ['LOC-N', 'LOC-S'], ['BR-A']), mk('hc-2', CUSTOMERS[1], ['LOC-E'], ['BR-A', 'BR-B'])],
    deliveries: {
      [hub.id]: [
        { id: 'd-1', event: 'availability.updated', customerCode: 'CU-001', customerName: 'Sample Trading Co', status: 'SUCCESS', attempt: 1, lastCode: 200, lastError: null, createdAt: NOW, lastAttemptAt: NOW },
        { id: 'd-2', event: 'availability.updated', customerCode: 'CU-002', customerName: 'Example Supplies Ltd', status: 'FAILED', attempt: 4, lastCode: 503, lastError: 'Receiver unavailable', createdAt: NOW, lastAttemptAt: NOW },
      ],
    },
    sync: { configured: true, lastRunAt: NOW, lastSuccessAt: NOW, lastError: null, products: 3, queued: 0 },
    keys: [{ id: 'k-1', name: 'Hub key', masked: 'fxh_live_****abcd', createdAt: NOW, lastUsedAt: null, revokedAt: null }],
  };
}

export function createMockHubConnectorService(): HubConnectorService & { state: MockState } {
  const state = seed();
  let n = 100;
  const nextId = (p: string) => `${p}-${++n}`;
  const hubOf = (id: string): Hub => {
    const h = state.hubs.find((x) => x.id === id);
    if (!h) throw new Error('Hub not found');
    return h;
  };
  const customerOf = (hubId: string, cid: string): HubCustomer => {
    const c = state.customers.find((x) => x.hubId === hubId && x.id === cid);
    if (!c) throw new Error('Customer not found');
    return c;
  };
  const recount = (hubId: string) => {
    hubOf(hubId).customerCount = state.customers.filter((c) => c.hubId === hubId).length;
  };

  return {
    state,
    async listHubs(query) {
      return paginate(state.hubs, query, (h) => `${h.name} ${h.code} ${h.callbackUrl}`, (h, f) => (h as unknown as Record<string, unknown>)[f]);
    },
    async createHub(input) {
      const hub: Hub = { id: nextId('hub'), ...input, exposePrice: false, active: true, customerCount: 0, lastSuccessAt: null, createdAt: NOW, updatedAt: NOW };
      state.hubs.push(hub);
      return { hub, signingSecret: 'whsec_mock_0123456789abcdef' };
    },
    async getHub(id) {
      return hubOf(id);
    },
    async updateHub(id, input) {
      const hub = hubOf(id);
      Object.assign(hub, input);
      return hub;
    },
    async deleteHub(id) {
      state.hubs = state.hubs.filter((h) => h.id !== id);
      state.customers = state.customers.filter((c) => c.hubId !== id);
    },
    async rotateSecret() {
      return { signingSecret: 'whsec_mock_rotated_fedcba9876543210' };
    },
    async resync(id) {
      return { queued: state.customers.filter((c) => c.hubId === id).length };
    },

    async listCustomers(hubId, query) {
      const mine = state.customers.filter((c) => c.hubId === hubId);
      return paginate(mine, query, (c) => `${c.customerName} ${c.customerCode}`, (c, f) =>
        (c as unknown as Record<string, unknown>)[f]);
    },
    async createCustomer(hubId, input) {
      const row: HubCustomer = {
        id: nextId('hc'),
        hubId,
        customerCode: input.customerCode,
        customerName: input.customerName,
        locationCodes: input.locationCodes,
        brandCodes: input.brandCodes,
        locations: pick(LOCATIONS, input.locationCodes),
        brands: pick(BRANDS, input.brandCodes),
        active: true,
        updatedAt: NOW,
      };
      state.customers.push(row);
      recount(hubId);
      return row;
    },
    async updateCustomer(hubId, cid, input) {
      const row = customerOf(hubId, cid);
      if (input.customerName !== undefined) row.customerName = input.customerName;
      if (input.locationCodes) {
        row.locationCodes = input.locationCodes;
        row.locations = pick(LOCATIONS, input.locationCodes);
      }
      if (input.brandCodes) {
        row.brandCodes = input.brandCodes;
        row.brands = pick(BRANDS, input.brandCodes);
      }
      if (input.active !== undefined) row.active = input.active;
      return row;
    },
    async deleteCustomer(hubId, cid) {
      state.customers = state.customers.filter((c) => !(c.hubId === hubId && c.id === cid));
      recount(hubId);
    },
    async previewCustomer(hubId, cid) {
      const hub = hubOf(hubId);
      const row = customerOf(hubId, cid);
      const items: PreviewItem[] = row.brands.map((b, i) => ({
        code: `ITM-${b.code}-${i + 1}`,
        name: `${b.name} sample item`,
        brand_name: b.name,
        in_stock: i % 2 === 0,
        incoming: true,
        ...(hub.exposePrice ? { list_price: 10 + i, currency: 'MYR' } : {}),
      }));
      return { items };
    },

    async listDeliveries(hubId, query, statuses = []) {
      const mine = (state.deliveries[hubId] ?? []).filter((d) => !statuses.length || statuses.includes(d.status));
      return paginate(mine, query, (d) => `${d.customerName} ${d.event}`, (d, f) =>
        (d as unknown as Record<string, unknown>)[f]);
    },
    async redeliver(deliveryId) {
      for (const list of Object.values(state.deliveries)) {
        const d = list.find((x) => x.id === deliveryId);
        if (d) {
          d.status = 'PENDING';
          d.lastError = null;
        }
      }
    },

    async listOptions(kind: OptionKind, search) {
      const all = kind === 'locations' ? LOCATIONS : BRANDS;
      const term = (search ?? '').trim().toLowerCase();
      return term ? all.filter((o) => `${o.name} ${o.code}`.toLowerCase().includes(term)) : all;
    },

    async listKeys() {
      return state.keys;
    },
    async createKey(_hubId, name) {
      const key = { id: nextId('k'), name, masked: 'fxh_live_****wxyz', createdAt: NOW, lastUsedAt: null, revokedAt: null };
      state.keys.push(key);
      return { ...key, key: 'fxh_live_mock_0123456789wxyz' };
    },
    async revokeKey(_hubId, id) {
      const k = state.keys.find((x) => x.id === id);
      if (k) k.revokedAt = NOW;
    },

    async getSync() {
      return state.sync;
    },
    async syncNow() {
      if (!state.sync.configured) throw new Error('No feed configured');
      state.sync = { ...state.sync, lastRunAt: NOW, lastSuccessAt: NOW };
      return state.sync;
    },
  };
}

export const mockHubConnectorService = createMockHubConnectorService();
