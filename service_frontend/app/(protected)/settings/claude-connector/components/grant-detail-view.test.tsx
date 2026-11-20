import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GrantDetailView } from './grant-detail-view';

const canKeys: string[] = ['connector.read', 'connector.manage'];
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (k: string) => canKeys.includes(k), ready: true, permissions: new Set(canKeys) }),
}));
const getGrant = vi.fn();
const getGrantActivity = vi.fn();
vi.mock('@/services/connector-service', () => ({
  getGrant: (...a: unknown[]) => getGrant(...a),
  getGrantActivity: (...a: unknown[]) => getGrantActivity(...a),
  revokeGrant: vi.fn(),
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/settings/claude-connector/g1',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ id: 'g1' }),
}));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDate: (s: string) => s, formatDateTime: (s: string) => s }),
}));
vi.mock('next-auth/react', () => ({ useSession: () => ({ data: null, status: 'unauthenticated' }), signOut: vi.fn() }));
vi.mock('@/services/terminology-service', () => ({ terminologyService: { getTerminology: vi.fn().mockResolvedValue({}), list: vi.fn().mockResolvedValue([]), get: vi.fn().mockResolvedValue({}) } }));
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

beforeEach(() => {
  vi.clearAllMocks();
  getGrant.mockResolvedValue({
    id: 'g1', status: 'active', product: 'acme', productUserId: '42', userName: 'Alice',
    clientName: 'Claude', grantedAt: '2026-10-01T00:00:00Z', lastUsedAt: null, calls30d: 2,
  });
  getGrantActivity.mockResolvedValue({
    calls: [
      { id: 'c1', tool: 'stock_list', statusCode: 200, rows: 12, chars: 3400, ms: 85, truncated: false, at: '2026-10-08T00:00:00Z' },
      { id: 'c2', tool: 'orders_list', statusCode: 200, rows: 500, chars: 90000, ms: 410, truncated: true, at: '2026-10-08T01:00:00Z' },
    ],
    events: [{ id: 'e1', type: 'consented', at: '2026-10-01T00:00:00Z' }],
  });
});

describe('GrantDetailView (AC-19-60)', () => {
  it('is read-only (no Edit toggle) with Details and Activity tabs', async () => {
    render(<GrantDetailView grantId="g1" />);
    await screen.findAllByText('Alice');
    expect(screen.getByRole('tab', { name: /details/i })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /activity/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^edit$/i })).toBeNull();
    expect(getGrant).toHaveBeenCalledWith('g1');
  });

  it('Activity tab lists tool, status code, rows, chars, ms and a truncated marker', async () => {
    render(<GrantDetailView grantId="g1" />);
    await screen.findAllByText('Alice');
    await userEvent.click(screen.getByRole('tab', { name: /activity/i }));
    await waitFor(() => expect(screen.getByText('stock_list')).toBeTruthy());
    expect(screen.getByText('orders_list')).toBeTruthy();
    expect(screen.getAllByText('ok').length).toBe(2);
    expect(screen.getByText('85')).toBeTruthy();
    expect(screen.getByText('410')).toBeTruthy();
    expect(screen.getAllByText(/truncated/i).length).toBe(1);
    expect(getGrantActivity).toHaveBeenCalledWith('g1');
  });
});
