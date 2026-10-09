import { describe, expect, it, vi, beforeEach } from 'vitest';

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock('@/lib/api-client', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api-client')>('@/lib/api-client');
  return { ...actual, apiFetch };
});

import {
  listGrants,
  getGrant,
  getGrantActivity,
  revokeGrant,
  bulkRevokeGrants,
  listProducts,
  refreshManifest,
} from './connector-service';

beforeEach(() => apiFetch.mockReset());

describe('connector-service (AC-19-60/61, S5 wire)', () => {
  it('listGrants sends status/product/search/page/page_size and returns {data,total,page}', async () => {
    apiFetch.mockResolvedValue({ data: [], total: 0, page: 0 });
    const res = await listGrants({ status: 'active', product: 'acme', search: 'ali ce', page: 2, pageSize: 25 });
    const url = new URL(String(apiFetch.mock.calls[0][0]), 'http://x');
    expect(url.pathname).toBe('/connector/grants');
    expect(url.searchParams.get('status')).toBe('active');
    expect(url.searchParams.get('product')).toBe('acme');
    expect(url.searchParams.get('search')).toBe('ali ce');
    expect(url.searchParams.get('page')).toBe('2');
    expect(url.searchParams.get('page_size')).toBe('25');
    expect(res).toEqual({ data: [], total: 0, page: 0 });
  });

  it('listGrants omits empty params', async () => {
    apiFetch.mockResolvedValue({ data: [], total: 0, page: 0 });
    await listGrants({});
    const url = new URL(String(apiFetch.mock.calls[0][0]), 'http://x');
    expect([...url.searchParams.keys()]).toEqual([]);
  });

  it('getGrant and getGrantActivity hit the id paths', async () => {
    apiFetch.mockResolvedValue({});
    await getGrant('g/1');
    expect(apiFetch.mock.calls[0][0]).toBe('/connector/grants/g%2F1');
    apiFetch.mockResolvedValue({ calls: [], events: [] });
    const act = await getGrantActivity('g1');
    expect(apiFetch.mock.calls[1][0]).toBe('/connector/grants/g1/activity');
    expect(act).toEqual({ calls: [], events: [] });
  });

  it('revoke and bulk revoke POST', async () => {
    apiFetch.mockResolvedValue({});
    await revokeGrant('g1');
    expect(apiFetch.mock.calls[0][0]).toBe('/connector/grants/g1/revoke');
    expect(apiFetch.mock.calls[0][1]).toMatchObject({ method: 'POST' });
    await bulkRevokeGrants(['a', 'b']);
    expect(apiFetch.mock.calls[1][0]).toBe('/connector/grants/bulk-revoke');
    expect(apiFetch.mock.calls[1][1]).toMatchObject({ method: 'POST' });
    expect(JSON.parse((apiFetch.mock.calls[1][1] as { body: string }).body)).toEqual({ ids: ['a', 'b'] });
  });

  it('listProducts unwraps data and refreshManifest POSTs the key path', async () => {
    apiFetch.mockResolvedValue({ data: [{ key: 'acme' }] });
    expect(await listProducts()).toEqual([{ key: 'acme' }]);
    expect(apiFetch.mock.calls[0][0]).toBe('/connector/products');
    apiFetch.mockResolvedValue({});
    await refreshManifest('acme');
    expect(apiFetch.mock.calls[1][0]).toBe('/connector/products/acme/refresh-manifest');
    expect(apiFetch.mock.calls[1][1]).toMatchObject({ method: 'POST' });
  });
});
