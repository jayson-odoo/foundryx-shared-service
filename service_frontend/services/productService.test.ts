import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ListQuery } from '@/types/resource';

const { apiFetch, apiFetchText } = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  apiFetchText: vi.fn(),
}));

vi.mock('@/lib/api-client', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api-client')>('@/lib/api-client');
  return { ...actual, apiFetch, apiFetchText };
});

// Imported AFTER the mock is registered.
import { productService as svc } from './productService';

const query = (over: Partial<ListQuery> = {}): ListQuery => ({
  page: 0,
  pageSize: 25,
  ...over,
});

const aProduct = (over = {}) => ({
  id: 'p1',
  categoryId: null,
  name: 'Sorento CRM',
  sku: 'CRM-1',
  kind: 'software',
  kindLabel: 'Software',
  defaultPrice: 100,
  tax: 0,
  currency: 'MYR',
  uom: 'licence',
  isActive: true,
  createdAt: '2026-07-18T00:00:00Z',
  ...over,
});

beforeEach(() => {
  apiFetch.mockReset();
  apiFetchText.mockReset();
});

describe('productService', () => {
  it('listProducts maps the core envelope onto ListResult (items → data)', async () => {
    apiFetch.mockResolvedValue({ items: [aProduct()], total: 1, page: 0, pageSize: 25 });
    const res = await svc.listProducts(query({ search: 'crm' }));
    expect(apiFetch).toHaveBeenCalledWith('/products?page=0&page_size=25&search=crm');
    expect(res).toEqual({ data: [aProduct()], total: 1, page: 0 });
  });

  it('listProducts sends trashed=true for the trashed view + sort params', async () => {
    apiFetch.mockResolvedValue({ items: [], total: 0, page: 0, pageSize: 25 });
    await svc.listProducts(
      query({ statusView: 'trashed', sort: { id: 'name', desc: true } }),
    );
    expect(apiFetch).toHaveBeenCalledWith(
      '/products?page=0&page_size=25&trashed=true&sort_by=name&sort_dir=desc',
    );
  });

  it('listProducts returns empty data on an empty catalog', async () => {
    apiFetch.mockResolvedValue({ items: [], total: 0, page: 0, pageSize: 25 });
    const res = await svc.listProducts(query());
    expect(res).toEqual({ data: [], total: 0, page: 0 });
  });

  it('listKinds reads GET /products/kinds', async () => {
    apiFetch.mockResolvedValue([{ key: 'software', label: 'Software' }]);
    await expect(svc.listKinds()).resolves.toEqual([{ key: 'software', label: 'Software' }]);
    expect(apiFetch).toHaveBeenCalledWith('/products/kinds');
  });

  it('createProduct POSTs the payload', async () => {
    apiFetch.mockResolvedValue(aProduct());
    await svc.createProduct({ name: 'Sorento CRM', kind: 'software' });
    expect(apiFetch).toHaveBeenCalledWith('/products', {
      method: 'POST',
      body: JSON.stringify({ name: 'Sorento CRM', kind: 'software' }),
    });
  });

  it('updateProduct PATCHes the id', async () => {
    apiFetch.mockResolvedValue(aProduct({ name: 'Renamed' }));
    await svc.updateProduct('p1', { name: 'Renamed' });
    expect(apiFetch).toHaveBeenCalledWith('/products/p1', {
      method: 'PATCH',
      body: JSON.stringify({ name: 'Renamed' }),
    });
  });

  it('deleteProduct DELETEs and resolves void', async () => {
    apiFetch.mockResolvedValue(undefined);
    await expect(svc.deleteProduct('p1')).resolves.toBeUndefined();
    expect(apiFetch).toHaveBeenCalledWith('/products/p1', { method: 'DELETE' });
  });

  it('getDelivery reads the ideation delivery route', async () => {
    apiFetch.mockResolvedValue({ productId: 'p1', productDomainBase: 'https://x.my' });
    await svc.getDelivery('p1');
    expect(apiFetch).toHaveBeenCalledWith('/ideation/products/p1/delivery');
  });

  it('setDelivery PUTs productDomainBase (camelCase, matching the BE schema)', async () => {
    apiFetch.mockResolvedValue({ productId: 'p1', productDomainBase: 'https://x.my' });
    await svc.setDelivery('p1', { productDomainBase: 'https://x.my' });
    expect(apiFetch).toHaveBeenCalledWith('/ideation/products/p1/delivery', {
      method: 'PUT',
      body: JSON.stringify({ productDomainBase: 'https://x.my' }),
    });
  });

  it('exportCsv POSTs the export request as text', async () => {
    apiFetchText.mockResolvedValue('id,name\n');
    await svc.exportCsv(query({ search: 'crm', statusView: 'trashed' }), ['id', 'name'], ['p1']);
    expect(apiFetchText).toHaveBeenCalledWith('/products/export', {
      method: 'POST',
      body: JSON.stringify({ columns: ['id', 'name'], ids: ['p1'], search: 'crm', trashed: true }),
    });
  });

  it('propagates a backend error (e.g. 403 on delivery for a non-Maintainer)', async () => {
    apiFetch.mockImplementationOnce(() => Promise.reject(new Error('Forbidden')));
    await expect(svc.getDelivery('p1')).rejects.toThrow('Forbidden');
  });
});
