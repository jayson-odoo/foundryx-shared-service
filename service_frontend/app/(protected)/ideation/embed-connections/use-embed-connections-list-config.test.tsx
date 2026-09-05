import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import type { Product } from '@/types/ideation';
import type { EmbedConnectionItem } from '@/types/embed-connection';
import type { ListQuery } from '@/types/resource';
import { useEmbedConnectionsListConfig } from './use-embed-connections-list-config';

const list = vi.fn();
const setActive = vi.fn();
const remove = vi.fn();

vi.mock('@/services/embed-connection-service', () => ({
  embedConnectionService: {
    list: (...a: unknown[]) => list(...a),
    setActive: (...a: unknown[]) => setActive(...a),
    remove: (...a: unknown[]) => remove(...a),
    create: vi.fn(),
    rotate: vi.fn(),
  },
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDate: (s: string) => s, formatDateTime: (s: string) => s }),
}));

const PRODUCTS: Product[] = [
  { id: 'prod-1', name: 'Sorento CRM', kind: 'software', productDomainBase: null },
];

const conn = (over: Partial<EmbedConnectionItem> = {}): EmbedConnectionItem => ({
  connectionId: 'sorento-ideation',
  tenantId: 'default',
  allowedOrigins: ['https://fe-sorento.foundryx.my'],
  productId: 'prod-1',
  isActive: true,
  hasSecret: true,
  createdAt: '2026-07-10T00:00:00Z',
  updatedAt: '2026-07-12T00:00:00Z',
  ...over,
});

const query: ListQuery = { page: 0, pageSize: 25, search: '', sort: undefined, filter: null };

function config(rows: EmbedConnectionItem[]) {
  list.mockResolvedValue(rows);
  const handlers = { onCreate: vi.fn(), onRotate: vi.fn() };
  const { result } = renderHook(() => useEmbedConnectionsListConfig(PRODUCTS, handlers));
  return { config: result.current.config, handlers };
}

beforeEach(() => vi.clearAllMocks());

describe('useEmbedConnectionsListConfig (PLAN-ideation-embed-sso §7)', () => {
  it('exposes the create action gated by ideation.triage.manage', () => {
    const { config: c } = config([]);
    expect(c.createLabel).toBe('Add connection');
    expect(c.createPermission).toBe('ideation.triage.manage');
    expect(c.actions.map((a) => a.id)).toEqual(['rotate', 'toggle-active', 'delete']);
    expect(c.actions.every((a) => a.permission === 'ideation.triage.manage')).toBe(true);
  });

  it('fetcher returns the connection list, newest-first, and honours search', async () => {
    const rows = [conn({ connectionId: 'aaa' }), conn({ connectionId: 'zzz-match' })];
    const { config: c } = config(rows);
    const all = await c.fetcher(query);
    expect(all.total).toBe(2);
    const searched = await c.fetcher({ ...query, search: 'zzz' });
    expect(searched.total).toBe(1);
    expect(searched.data[0]?.connectionId).toBe('zzz-match');
  });

  it('resolves the product-scope accessor to a name (never a raw id), "All ideas" when null', () => {
    const { config: c } = config([]);
    const productCol = c.columns.find((col) => col.id === 'product')!;
    const acc = (productCol as unknown as { accessorFn: (r: EmbedConnectionItem) => string })
      .accessorFn;
    expect(acc(conn({ productId: 'prod-1' }))).toBe('Sorento CRM');
    expect(acc(conn({ productId: null }))).toBe('All ideas');
  });

  it('toggle-active is a deferred (grace-window) action - no confirm, no run; label reflects state and the payload carries the flipped flag (fix round 1, T5, item 15)', () => {
    const { config: c } = config([]);
    const toggle = c.actions.find((a) => a.id === 'toggle-active')!;
    expect((toggle.label as (rows: EmbedConnectionItem[]) => string)([conn({ isActive: true })])).toBe(
      'Deactivate',
    );
    expect(toggle.confirm).toBeUndefined();
    expect(toggle.run).toBeUndefined();
    expect(toggle.deferred).toEqual({
      actionKey: 'ideation_embed_connections.set_active',
      entityType: 'ideation_embed_connection',
      payload: expect.any(Function),
    });
    expect(toggle.deferred?.payload?.([conn({ isActive: true })])).toEqual({ isActive: false });
  });

  it('delete is a deferred (grace-window) action - destructive, no confirm, no run (fix round 1, T5, item 15)', () => {
    const { config: c } = config([]);
    const del = c.actions.find((a) => a.id === 'delete')!;
    expect(del.tone).toBe('destructive');
    expect(del.confirm).toBeUndefined();
    expect(del.run).toBeUndefined();
    expect(del.deferred).toEqual({
      actionKey: 'ideation_embed_connections.delete',
      entityType: 'ideation_embed_connection',
    });
  });

  it('rotate action delegates to the onRotate handler (opens the rotate dialog)', () => {
    const { config: c, handlers } = config([]);
    const rotate = c.actions.find((a) => a.id === 'rotate')!;
    const item = conn({ connectionId: 'x' });
    rotate.run([item], { reload: vi.fn() });
    expect(handlers.onRotate).toHaveBeenCalledWith(item);
  });
});
