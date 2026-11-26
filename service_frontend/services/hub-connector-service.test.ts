import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.fn();
vi.mock('@/lib/api-client', () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
  BASE_URL: 'http://api.test',
  ApiError: class ApiError extends Error {},
}));

import { hubListParams, realHubConnectorService } from './hub-connector-service.real';
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
    expect(await realHubConnectorService.listKeys()).toEqual([{ id: 'k1' }]);
  });

  it('returns the created key with its secret value', async () => {
    apiFetch.mockResolvedValue({ id: 'k1', name: 'CRM', masked: 'x', key: 'fxh_live_abc' });
    const created = await realHubConnectorService.createKey('CRM');
    expect(created.key).toBe('fxh_live_abc');
    expect(apiFetch).toHaveBeenCalledWith('/hub-connector/keys', { method: 'POST', body: JSON.stringify({ name: 'CRM' }) });
  });

  it('posts a customer policy', async () => {
    apiFetch.mockResolvedValue({ id: 'c1' });
    await realHubConnectorService.createCustomer('h1', { customerCode: 'CU-1', locationCodes: ['L'], brandCodes: ['B'] });
    expect(apiFetch).toHaveBeenCalledWith('/hub-connector/hubs/h1/customers', {
      method: 'POST',
      body: JSON.stringify({ customerCode: 'CU-1', locationCodes: ['L'], brandCodes: ['B'] }),
    });
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
    expect(preview.items.every((i) => i.price === undefined)).toBe(true);
    await svc.updateHub('hub-1', { exposePrice: true });
    const withPrice = await svc.previewCustomer('hub-1', 'hc-1');
    expect(withPrice.items.every((i) => typeof i.price === 'number')).toBe(true);
  });
});
