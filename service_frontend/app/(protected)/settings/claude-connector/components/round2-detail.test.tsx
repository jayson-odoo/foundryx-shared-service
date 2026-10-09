import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const canKeys: string[] = ['connector.read', 'connector.manage'];
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (k: string) => canKeys.includes(k), ready: true, permissions: new Set(canKeys) }),
}));
const getGrant = vi.fn();
const getGrantActivity = vi.fn();
const listGrants = vi.fn();
vi.mock('@/services/connector-service', () => ({
  getGrant: (...a: unknown[]) => getGrant(...a),
  getGrantActivity: (...a: unknown[]) => getGrantActivity(...a),
  listGrants: (...a: unknown[]) => listGrants(...a),
  revokeGrant: vi.fn(),
  bulkRevokeGrants: vi.fn(),
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/settings/claude-connector/g2',
  useSearchParams: () => new URLSearchParams('ctx=x&i=1'),
  useParams: () => ({ id: 'g2' }),
}));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDate: (s: string) => s, formatDateTime: (s: string) => `DT:${s}` }),
}));
vi.mock('next-auth/react', () => ({ useSession: () => ({ data: null, status: 'unauthenticated' }), signOut: vi.fn() }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}), list: vi.fn().mockResolvedValue([]) },
}));
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { GrantDetailView } from './grant-detail-view';

const grant = (over: Record<string, unknown> = {}) => ({
  id: 'g2', status: 'active', product: 'acme', productName: 'Acme', productUserId: '42',
  userName: 'Alice', clientName: 'Claude', grantedAt: '2026-10-01T00:00:00Z', lastUsedAt: null,
  calls30d: 2, ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  getGrant.mockResolvedValue(grant());
  listGrants.mockResolvedValue({
    data: [grant({ id: 'g1' }), grant(), grant({ id: 'g3' })], total: 3, page: 0,
  });
  getGrantActivity.mockResolvedValue({
    calls: [
      { id: 'c1', tool: 'stock_list', statusCode: 200, errorCode: null, rows: 12, chars: 3400, ms: 85,
        truncated: false, args: '{"search":"widgets"}', at: '2026-10-08T11:00:00Z' },
      { id: 'c2', tool: 'chat_search', statusCode: 403, errorCode: 'chat_history_not_permitted',
        rows: null, chars: null, ms: 95, truncated: true, args: '{"text":"hi"}', at: '2026-10-08T12:00:00Z' },
    ],
    events: [
      { id: 'e1', type: 'consented', at: '2026-10-08T09:00:00Z' },
      { id: 'e2', type: 'refreshed', at: '2026-10-08T10:00:00Z' },
      { id: 'e3', type: 'revoked', at: '2026-10-08T13:00:00Z' },
    ],
  });
});

async function openActivity() {
  render(<GrantDetailView grantId="g2" />);
  await screen.findAllByText('Alice');
  await userEvent.click(screen.getByRole('tab', { name: /activity/i }));
  return screen.findByRole('tabpanel');
}

describe('round 2 item 1: Activity tab is ONE merged table', () => {
  it('columns Time, Event, Tool, Status, Rows, Chars, ms, Args', async () => {
    const panel = await openActivity();
    await within(panel).findByText('stock_list');
    for (const h of ['Time', 'Event', 'Tool', 'Status', 'Rows', 'Chars', 'ms', 'Args']) {
      expect(within(panel).getByRole('columnheader', { name: new RegExp(`^${h}`, 'i') })).toBeTruthy();
    }
    expect(within(panel).getAllByRole('table').length).toBe(1);
  });

  it('merges calls and events newest-first with event labels', async () => {
    const panel = await openActivity();
    await within(panel).findByText('stock_list');
    const body = within(panel).getAllByRole('row').slice(1).map((r) => r.textContent ?? '');
    const order = ['13:00', '12:00', '11:00', '10:00', '09:00'];
    const idx = order.map((t) => body.findIndex((r) => r.includes(`T${t}`)));
    expect(idx.every((i) => i >= 0)).toBe(true);
    expect([...idx].sort((a, b) => a - b)).toEqual(idx);
    expect(body[idx[0]]).toMatch(/Revoked/);
    expect(body[idx[1]]).toMatch(/Tool call/);
    expect(body[idx[3]]).toMatch(/Token refreshed/);
    expect(body[idx[4]]).toMatch(/Consented/);
  });

  it('Status shows errorCode when present else ok; null rows/chars render "-"; Args capped with Truncated marker', async () => {
    const panel = await openActivity();
    await within(panel).findByText('stock_list');
    const rows = within(panel).getAllByRole('row');
    const errRow = rows.find((r) => r.textContent?.includes('chat_search'))!;
    expect(errRow.textContent).toContain('chat_history_not_permitted');
    expect(errRow.textContent).not.toMatch(/null/);
    expect(within(errRow).getAllByText('-').length).toBeGreaterThanOrEqual(2);
    expect(errRow.textContent).toMatch(/truncated/i);
    const okRow = rows.find((r) => r.textContent?.includes('stock_list'))!;
    expect(within(okRow).getByText('ok')).toBeTruthy();
    expect(okRow.textContent).toContain('{"search":"widgets"}');
    expect(okRow.textContent).not.toMatch(/truncated/i);
  });

  it('does not repeat the page title/breadcrumb nor show an Active/Trashed toggle inside the tab', async () => {
    const panel = await openActivity();
    await within(panel).findByText('stock_list');
    expect(within(panel).queryByText(/claude connector/i)).toBeNull();
    expect(within(panel).queryByRole('heading')).toBeNull();
    expect(within(panel).queryByRole('button', { name: /^(active|trashed)$/i })).toBeNull();
    expect(within(panel).queryByText(/trashed/i)).toBeNull();
  });
});

describe('round 2 item 4/6: detail header', () => {
  it('shows the product display name, not the key', async () => {
    render(<GrantDetailView grantId="g2" />);
    await screen.findAllByText('Alice');
    expect(screen.getAllByText('Acme').length).toBeGreaterThan(0);
    expect(screen.queryByText('acme')).toBeNull();
  });

  it('record nav "N / M" across the list', async () => {
    render(<GrantDetailView grantId="g2" />);
    await screen.findAllByText('Alice');
    await waitFor(() => expect(screen.getByText(/2\s*\/\s*3/)).toBeTruthy());
  });

  it('Actions menu has Revoke for active grants only', async () => {
    const { unmount } = render(<GrantDetailView grantId="g2" />);
    await screen.findAllByText('Alice');
    await userEvent.click(screen.getByRole('button', { name: /actions/i }));
    expect(await screen.findByRole('menuitem', { name: /revoke/i })).toBeTruthy();
    unmount();
    getGrant.mockResolvedValue(grant({ status: 'revoked' }));
    render(<GrantDetailView grantId="g2" />);
    await screen.findAllByText('Alice');
    const btn = screen.queryByRole('button', { name: /actions/i });
    if (btn) {
      await userEvent.click(btn);
      expect(screen.queryByRole('menuitem', { name: /revoke/i })).toBeNull();
    }
  });
});
