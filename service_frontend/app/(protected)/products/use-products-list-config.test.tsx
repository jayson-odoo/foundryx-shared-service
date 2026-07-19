import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';

const { listProducts } = vi.hoisted(() => ({ listProducts: vi.fn() }));

vi.mock('@/services/productService', () => ({
  productService: { listProducts },
}));

import { useProductsListConfig } from './use-products-list-config';
import type { Product } from '@/services/productService';

const aProduct = (over: Partial<Product> = {}): Product => ({
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

const handlers = () => ({
  onCreate: vi.fn(),
  onEdit: vi.fn(),
  onDelete: vi.fn().mockResolvedValue(undefined),
});

beforeEach(() => listProducts.mockReset());

describe('useProductsListConfig', () => {
  it('exposes the required columns (name, sku, kind, price, active)', () => {
    const { result } = renderHook(() => useProductsListConfig(handlers()));
    const ids = result.current.columns.map((c) => c.id);
    expect(ids).toEqual(
      expect.arrayContaining(['select', 'name', 'sku', 'kind', 'price', 'active', 'actions']),
    );
  });

  it('registers Edit + confirm-gated Delete actions', () => {
    const { result } = renderHook(() => useProductsListConfig(handlers()));
    const del = result.current.actions.find((a) => a.id === 'delete');
    const edit = result.current.actions.find((a) => a.id === 'edit');
    expect(edit?.permission).toBe('products.update');
    expect(del?.tone).toBe('destructive');
    expect(del?.permission).toBe('products.delete');
    expect(del?.confirm?.title).toBe('Confirm delete');
    expect(del?.confirm?.description).toMatch(/cannot be undone/i);
  });

  it('Edit action calls the onEdit handler with the row', () => {
    const h = handlers();
    const { result } = renderHook(() => useProductsListConfig(h));
    const edit = result.current.actions.find((a) => a.id === 'edit')!;
    const row = aProduct();
    void edit.run([row], { reload: () => {} });
    expect(h.onEdit).toHaveBeenCalledWith(row);
  });

  it('Delete action calls the onDelete handler for each row', async () => {
    const h = handlers();
    const { result } = renderHook(() => useProductsListConfig(h));
    const del = result.current.actions.find((a) => a.id === 'delete')!;
    await del.run([aProduct({ id: 'a' }), aProduct({ id: 'b' })], { reload: () => {} });
    expect(h.onDelete).toHaveBeenCalledTimes(2);
  });

  it('fetcher delegates to productService.listProducts — data state', async () => {
    listProducts.mockResolvedValue({ data: [aProduct()], total: 1, page: 0 });
    const { result } = renderHook(() => useProductsListConfig(handlers()));
    const res = await result.current.fetcher({ page: 0, pageSize: 25 });
    expect(listProducts).toHaveBeenCalledWith({ page: 0, pageSize: 25 });
    expect(res.data).toHaveLength(1);
    expect(res.total).toBe(1);
  });

  it('fetcher surfaces an empty catalog', async () => {
    listProducts.mockResolvedValue({ data: [], total: 0, page: 0 });
    const { result } = renderHook(() => useProductsListConfig(handlers()));
    const res = await result.current.fetcher({ page: 0, pageSize: 25 });
    expect(res.data).toEqual([]);
    expect(res.total).toBe(0);
  });

  it('fetcher propagates a load error', async () => {
    listProducts.mockImplementationOnce(() => Promise.reject(new Error('Boom')));
    const { result } = renderHook(() => useProductsListConfig(handlers()));
    await expect(result.current.fetcher({ page: 0, pageSize: 25 })).rejects.toThrow('Boom');
  });

  it('wires the create button + gates it on products.create; trashed view disabled', () => {
    const h = handlers();
    const { result } = renderHook(() => useProductsListConfig(h));
    expect(result.current.createLabel).toBe('Add product');
    expect(result.current.createPermission).toBe('products.create');
    expect(result.current.enableStatusViews).toBe(false);
    result.current.onCreate?.();
    expect(h.onCreate).toHaveBeenCalled();
  });
});
