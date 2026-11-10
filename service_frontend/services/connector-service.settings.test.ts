import { describe, expect, it, vi, beforeEach } from 'vitest';

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock('@/lib/api-client', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api-client')>('@/lib/api-client');
  return { ...actual, apiFetch };
});

import {
  createProduct,
  deleteProduct,
  getProductSettings,
  getTenantSettings,
  listSettingsAudit,
  updateProductSettings,
  updateTenantSettings,
} from './connector-service';

beforeEach(() => apiFetch.mockReset());

const body = (i: number) => JSON.parse((apiFetch.mock.calls[i][1] as { body: string }).body);

describe('connector-service settings wire (SETTINGS-IN-DB-SS)', () => {
  it('tenant settings GET/PUT and audit', async () => {
    apiFetch.mockResolvedValue({ data: [] });
    await getTenantSettings();
    expect(apiFetch.mock.calls[0][0]).toBe('/connector/settings');
    await updateTenantSettings({ callTimeoutSeconds: 20, publicBaseUrl: null });
    expect(apiFetch.mock.calls[1][0]).toBe('/connector/settings');
    expect(apiFetch.mock.calls[1][1]).toMatchObject({ method: 'PUT' });
    expect(body(1)).toEqual({ callTimeoutSeconds: 20, publicBaseUrl: null });
    expect(await listSettingsAudit()).toEqual([]);
    expect(apiFetch.mock.calls[2][0]).toBe('/connector/settings/audit');
  });

  it('product settings paths encode the key; delete carries the typed key', async () => {
    apiFetch.mockResolvedValue({});
    await getProductSettings('a/b');
    expect(apiFetch.mock.calls[0][0]).toBe('/connector/products/a%2Fb/settings');
    await createProduct({ key: 'delta' });
    expect(apiFetch.mock.calls[1]).toEqual(['/connector/products', expect.objectContaining({ method: 'POST' })]);
    await updateProductSettings('delta', { displayName: 'D' });
    expect(apiFetch.mock.calls[2][0]).toBe('/connector/products/delta/settings');
    expect(apiFetch.mock.calls[2][1]).toMatchObject({ method: 'PUT' });
    await deleteProduct('delta', 'delta');
    expect(apiFetch.mock.calls[3][0]).toBe('/connector/products/delta');
    expect(apiFetch.mock.calls[3][1]).toMatchObject({ method: 'DELETE' });
    expect(body(3)).toEqual({ confirmKey: 'delta' });
  });
});
