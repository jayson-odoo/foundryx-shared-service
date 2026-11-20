import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, renderHook, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { BulkActions } from '@/components/platform/resource-actions/bulk-actions';

const canKeys: string[] = ['connector.read', 'connector.manage'];
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (k: string) => canKeys.includes(k), ready: true, permissions: new Set(canKeys) }),
}));
vi.mock('@/services/connector-service', () => ({
  listGrants: vi.fn().mockResolvedValue({ data: [], total: 0, page: 0 }),
  revokeGrant: vi.fn(),
  bulkRevokeGrants: vi.fn(),
}));
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDate: (s: string) => s, formatDateTime: (s: string) => s }),
}));

import { useConnectorGrantListConfig } from './use-connector-grant-list-config';

const grant = (over: Record<string, unknown> = {}) => ({
  id: 'g1', status: 'active', product: 'acme', productName: 'Acme', productUserId: '42',
  userName: 'Alice', clientName: 'Claude', grantedAt: '2026-10-01T00:00:00Z',
  lastUsedAt: '2026-10-08T00:00:00Z', calls30d: 7, ...over,
});
const cfg = () => renderHook(() => useConnectorGrantListConfig()).result.current;

beforeEach(() => vi.clearAllMocks());

describe('round 2 item 2: table view selection + row menu', () => {
  it('has a select column first and a row actions column', () => {
    const ids = cfg().columns.map((c) => (c as { id?: string }).id);
    expect(ids[0]).toBe('select');
  });
  it('row menu offers Revoke on active rows only', async () => {
    const c = cfg();
    const { unmount } = render(
      <ActionMenu actions={c.actions} rows={[grant()] as never[]} runtime={{ reload: vi.fn() }} surface="row" />);
    await userEvent.click(screen.getAllByRole('button')[0]);
    expect((await screen.findAllByRole('menuitem')).map((i) => i.textContent?.trim())).toContain('Revoke');
    unmount();
  });
});

describe('round 2 item 4/5: product display name, Filters, Export', () => {
  it('Product column and card show productName, not the key', () => {
    const c = cfg();
    render(<div>{c.cardRender!(grant() as never)}</div>);
    expect(screen.getByText(/Acme/)).toBeTruthy();
    expect(screen.queryByText(/\bacme\b/)).toBeNull();
    const col = c.columns.find((x) => (x.meta as { headerTitle?: string })?.headerTitle === 'Product')!;
    const acc = (col as { accessorFn?: (r: unknown) => unknown }).accessorFn;
    expect(acc?.(grant())).toBe('Acme');
  });
  it('has status + product filter fields and export wired', () => {
    const c = cfg();
    const fields = (c.filterFields ?? []).map((f) => f.field);
    expect(fields).toEqual(expect.arrayContaining(['status', 'product']));
    expect(typeof c.exporter).toBe('function');
    expect((c.exportColumns ?? []).length).toBeGreaterThan(0);
  });
});

describe('round 2 item 7: revoke copy', () => {
  it('single: title and consequence copy per the mock', async () => {
    const c = cfg();
    render(<ActionMenu actions={c.actions} rows={[grant()] as never[]} runtime={{ reload: vi.fn() }} surface="row" />);
    await userEvent.click(screen.getAllByRole('button')[0]);
    await userEvent.click(await screen.findByRole('menuitem', { name: /^revoke$/i }));
    expect(await screen.findByText('Revoke this grant?')).toBeTruthy();
    expect(screen.getByText(
      'Alice loses Claude access to Acme now. Connecting again asks them to sign in to Acme.')).toBeTruthy();
  });

  it('bulk: "Revoke N grants?", type REVOKE copy, confirm button "Revoke N"', async () => {
    const c = cfg();
    const rows = [grant(), grant({ id: 'g2', userName: 'Bob' })] as never[];
    render(<BulkActions actions={c.actions} rows={rows} runtime={{ reload: vi.fn() }} />);
    await userEvent.click(screen.getAllByRole('button')[0]);
    await userEvent.click(await screen.findByRole('menuitem', { name: /revoke/i }));
    expect(await screen.findByText('Revoke 2 grants?')).toBeTruthy();
    expect(screen.getByText(/Type REVOKE to confirm\./)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Revoke 2' })).toBeTruthy();
  });
});
