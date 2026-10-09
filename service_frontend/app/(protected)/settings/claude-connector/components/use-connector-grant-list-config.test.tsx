import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, renderHook, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { BulkActions } from '@/components/platform/resource-actions/bulk-actions';
import type { ListQuery } from '@/types/resource';
import type { ConnectorGrant } from '@/types/connector';
import { useConnectorGrantListConfig } from './use-connector-grant-list-config';

const canKeys: string[] = ['connector.read', 'connector.manage'];
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (k: string) => canKeys.includes(k), ready: true, permissions: new Set(canKeys) }),
}));
const listGrants = vi.fn();
const revokeGrant = vi.fn();
const bulkRevokeGrants = vi.fn();
vi.mock('@/services/connector-service', () => ({
  listGrants: (...a: unknown[]) => listGrants(...a),
  revokeGrant: (...a: unknown[]) => revokeGrant(...a),
  bulkRevokeGrants: (...a: unknown[]) => bulkRevokeGrants(...a),
}));
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDate: (s: string) => s, formatDateTime: (s: string) => s }),
}));

const grant = (over: Partial<ConnectorGrant> = {}): ConnectorGrant => ({
  id: 'g1',
  status: 'active',
  product: 'acme',
  productUserId: '42',
  userName: 'Alice',
  clientName: 'Claude',
  grantedAt: '2026-10-01T00:00:00Z',
  lastUsedAt: '2026-10-08T00:00:00Z',
  calls30d: 7,
  ...over,
});

const query: ListQuery = { page: 1, pageSize: 25, search: 'ali', sort: undefined, filter: null, segment: 'active' };

beforeEach(() => {
  vi.clearAllMocks();
  canKeys.splice(0, canKeys.length, 'connector.read', 'connector.manage');
});

function cfg() {
  return renderHook(() => useConnectorGrantListConfig()).result.current;
}

describe('useConnectorGrantListConfig (AC-19-60)', () => {
  it('exposes the spec columns in order', () => {
    const c = cfg();
    const titles = c.columns.map((col) => (col.meta as { headerTitle?: string } | undefined)?.headerTitle);
    expect(titles).toEqual([
      'User', 'Product user id', 'Product', 'Client', 'Granted', 'Last used', 'Calls (30 d)', 'Status',
    ]);
  });

  it('has Active|Revoked|Expired segments and a mobile card renderer', () => {
    const c = cfg();
    expect(c.segments?.map((s) => s.label)).toEqual(['Active', 'Revoked', 'Expired']);
    expect(c.segments?.map((s) => s.id)).toEqual(['active', 'revoked', 'expired']);
    expect(typeof c.cardRender).toBe('function');
  });

  it('fetcher maps segment/search/page to the service (0-based page, pageSize)', async () => {
    listGrants.mockResolvedValue({ data: [grant()], total: 1, page: 1 });
    const res = await cfg().fetcher(query);
    expect(listGrants).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'active', search: 'ali', page: 1, pageSize: 25 }),
    );
    expect(res.total).toBe(1);
  });

  it('Revoke is gated by connector.manage, row + bulk surfaces', () => {
    const c = cfg();
    const row = c.actions.find((a) => a.surfaces?.row && /revoke/i.test(a.label));
    const bulk = c.actions.find((a) => a.surfaces?.bulk && /revoke/i.test(a.label));
    expect(row?.permission).toBe('connector.manage');
    expect(bulk?.permission).toBe('connector.manage');
  });

  it('bulk revoke requires typing REVOKE; single row confirm has no typed input', () => {
    const c = cfg();
    const row = c.actions.find((a) => a.surfaces?.row && /revoke/i.test(a.label))!;
    const bulk = c.actions.find((a) => a.surfaces?.bulk && /revoke/i.test(a.label))!;
    expect(row.confirm).toBeDefined();
    expect(row.confirm?.input).toBeUndefined();
    expect(bulk.confirm?.input?.expected([grant(), grant({ id: 'g2' })])).toBe('REVOKE');
  });

  it('Revoke is hidden for revoked and expired rows, shown for active', async () => {
    const c = cfg();
    const names = async (rows: ConnectorGrant[]) => {
      const { unmount } = render(
        <ActionMenu actions={c.actions} rows={rows} runtime={{ reload: vi.fn() }} surface="row" />,
      );
      const btns = screen.queryAllByRole('button');
      if (btns.length === 0) {
        unmount();
        return [] as string[];
      }
      await userEvent.click(btns[0]);
      const items = screen.queryAllByRole('menuitem').map((i) => i.textContent?.trim() ?? '');
      unmount();
      return items;
    };
    expect(await names([grant()])).toContain('Revoke');
    expect(await names([grant({ status: 'revoked' })])).not.toContain('Revoke');
    expect(await names([grant({ status: 'expired' })])).not.toContain('Revoke');
  });

  it('card body shows user, product and status', () => {
    const c = cfg();
    render(<div>{c.cardRender!(grant())}</div>);
    expect(screen.getByText('Alice')).toBeTruthy();
    expect(screen.getByText(/acme/)).toBeTruthy();
    expect(screen.getByText(/active/i)).toBeTruthy();
  });

  it('no instructional copy in the search placeholder', () => {
    expect(cfg().searchPlaceholder ?? '').not.toMatch(/click|drag|you can|to (revoke|view)/i);
  });
});
void BulkActions;
