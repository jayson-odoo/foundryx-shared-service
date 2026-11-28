import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.fn();
vi.mock('@/lib/api-client', () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
  BASE_URL: 'http://api.test',
  ApiError: class ApiError extends Error {},
}));

import { filteredParams, hubListParams, realHubConnectorService } from './hub-connector-service.real';
import { createMockHubConnectorService } from './hub-connector-service.mock';

beforeEach(() => apiFetch.mockReset());

describe('hub connector list params', () => {
  it('sends page, pageSize, search, sort and order', () => {
    const p = hubListParams({ page: 2, pageSize: 25, search: 'north', sort: { id: 'customerCount', desc: true } });
    expect(p.get('page')).toBe('2');
    expect(p.get('pageSize')).toBe('25');
    expect(p.get('search')).toBe('north');
    expect(p.get('sort')).toBe('customerCount');
    expect(p.get('order')).toBe('desc');
    expect(p.has('dir')).toBe(false);
  });
});

describe('real hub connector service', () => {
  it('lists hubs on the staff route', async () => {
    apiFetch.mockResolvedValue({ data: [], total: 0 });
    await realHubConnectorService.listHubs({ page: 0, pageSize: 10 });
    expect(apiFetch).toHaveBeenCalledWith('/hub-connector/hubs?page=0&pageSize=10');
  });

  it('repeats the status filter on deliveries', async () => {
    apiFetch.mockResolvedValue({ data: [], total: 0 });
    await realHubConnectorService.listDeliveries('h1', { page: 0, pageSize: 10 }, ['FAILED', 'PENDING']);
    expect(String(apiFetch.mock.calls[0][0])).toContain('status=FAILED&status=PENDING');
  });

  it('reads options and keys from {data}', async () => {
    apiFetch.mockResolvedValueOnce({ data: [{ code: 'A', name: 'Alpha' }] });
    expect(await realHubConnectorService.listOptions('brands', 'al')).toEqual([{ code: 'A', name: 'Alpha' }]);
    expect(apiFetch).toHaveBeenCalledWith('/hub-connector/options/brands?search=al');
    apiFetch.mockResolvedValueOnce({ data: [{ id: 'k1' }] });
    expect(await realHubConnectorService.listKeys('h1')).toEqual([{ id: 'k1' }]);
    expect(apiFetch).toHaveBeenLastCalledWith('/hub-connector/hubs/h1/keys');
  });

  it('returns the created key with its secret value', async () => {
    apiFetch.mockResolvedValue({ id: 'k1', name: 'CRM', masked: 'x', key: 'fxh_live_abc' });
    const created = await realHubConnectorService.createKey('h1', 'CRM');
    expect(created.key).toBe('fxh_live_abc');
    expect(apiFetch).toHaveBeenCalledWith('/hub-connector/hubs/h1/keys', { method: 'POST', body: JSON.stringify({ name: 'CRM' }) });
  });

  it('posts a customer policy', async () => {
    apiFetch.mockResolvedValue({ id: 'c1' });
    await realHubConnectorService.createCustomer('h1', {
      customerCode: 'CU-1',
      customerName: 'Sample Co',
      locationCodes: ['L'],
      brandCodes: ['B'],
    });
    expect(apiFetch).toHaveBeenCalledWith('/hub-connector/hubs/h1/customers', {
      method: 'POST',
      body: JSON.stringify({ customerCode: 'CU-1', customerName: 'Sample Co', locationCodes: ['L'], brandCodes: ['B'] }),
    });
  });
});

const inFilter = (field: string, value: string[]) =>
  ({ kind: 'condition', id: field, field, operator: 'in', value }) as const;
const andOf = (...rules: ReturnType<typeof inFilter>[]) => ({ kind: 'group', id: 'root', combinator: 'and', rules }) as const;

describe('hub connector filters', () => {
  it('sends one repeated param per value, and one per filter', async () => {
    apiFetch.mockResolvedValue({ data: [], total: 0 });
    await realHubConnectorService.listHubs({
      page: 0,
      pageSize: 10,
      filter: andOf(inFilter('status', ['active', 'inactive']), inFilter('showPrice', ['yes'])),
    } as never);
    const url = String(apiFetch.mock.calls[0][0]);
    expect(url).toContain('status=active&status=inactive');
    expect(url).toContain('showPrice=yes');
  });

  it('maps customer and delivery status, ignoring unknown fields', async () => {
    apiFetch.mockResolvedValue({ data: [], total: 0 });
    const filter = andOf(inFilter('status', ['FAILED']), inFilter('showPrice', ['yes']));
    await realHubConnectorService.listCustomers('h1', { page: 0, pageSize: 10, filter } as never);
    expect(String(apiFetch.mock.calls[0][0])).toContain('status=FAILED');
    expect(String(apiFetch.mock.calls[0][0])).not.toContain('showPrice');
    await realHubConnectorService.listDeliveries('h1', { page: 0, pageSize: 10, filter } as never);
    expect(String(apiFetch.mock.calls[1][0])).toContain('status=FAILED');
    expect(filteredParams({ page: 0, pageSize: 5 }, ['status']).has('status')).toBe(false);
  });
});

describe('hub history and scheduled tasks', () => {
  it('reads the hub history from {data}', async () => {
    const entry = { id: 'e1', at: null, who: 'A', onBehalfOf: null, action: 'Hub created', from: null, to: 'Hub' };
    apiFetch.mockResolvedValue({ data: [entry] });
    expect(await realHubConnectorService.hubHistory('h1')).toEqual([entry]);
    expect(apiFetch).toHaveBeenCalledWith('/hub-connector/hubs/h1/history');
  });

  it('lists and runs scheduled tasks', async () => {
    apiFetch.mockResolvedValue({ data: [{ key: 'stock_sync' }] });
    expect(await realHubConnectorService.listScheduledTasks()).toEqual([{ key: 'stock_sync' }]);
    expect(apiFetch).toHaveBeenLastCalledWith('/hub-connector/scheduled-tasks');
    await realHubConnectorService.runScheduledTask('stock_sync');
    expect(apiFetch).toHaveBeenLastCalledWith('/hub-connector/scheduled-tasks/stock_sync/run', { method: 'POST' });
  });
});

describe('hub connector sync and keys', () => {
  it('reads and runs the sync on /sync', async () => {
    apiFetch.mockResolvedValue({ configured: true, products: 3 });
    await realHubConnectorService.getSync();
    expect(apiFetch).toHaveBeenLastCalledWith('/hub-connector/sync');
    await realHubConnectorService.syncNow();
    expect(apiFetch).toHaveBeenLastCalledWith('/hub-connector/sync', { method: 'POST' });
  });

  it('revokes a key under its hub', async () => {
    apiFetch.mockResolvedValue(undefined);
    await realHubConnectorService.revokeKey('h1', 'k1');
    expect(apiFetch).toHaveBeenCalledWith('/hub-connector/hubs/h1/keys/k1', { method: 'DELETE' });
  });
});

describe('mock hub connector service', () => {
  it('creates a hub with a one-time secret and keeps price off in the preview', async () => {
    const svc = createMockHubConnectorService();
    const created = await svc.createHub({ name: 'Hub Two', code: 'hub-two', callbackUrl: 'https://x.example.com' });
    expect(created.signingSecret).toBeTruthy();
    const page = await svc.listHubs({ page: 0, pageSize: 10, search: 'two' });
    expect(page.total).toBe(1);
    const preview = await svc.previewCustomer('hub-1', 'hc-1');
    expect(preview.items.every((i) => i.list_price === undefined)).toBe(true);
    await svc.updateHub('hub-1', { exposePrice: true });
    const withPrice = await svc.previewCustomer('hub-1', 'hc-1');
    expect(withPrice.items.every((i) => typeof i.list_price === 'number')).toBe(true);
  });
});
