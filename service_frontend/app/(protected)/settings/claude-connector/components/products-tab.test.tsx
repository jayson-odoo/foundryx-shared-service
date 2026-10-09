import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ProductsTab } from './products-tab';

const canKeys: string[] = ['connector.read', 'connector.manage'];
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (k: string) => canKeys.includes(k), ready: true, permissions: new Set(canKeys) }),
}));
const listProducts = vi.fn();
const refreshManifest = vi.fn();
vi.mock('@/services/connector-service', () => ({
  listProducts: (...a: unknown[]) => listProducts(...a),
  refreshManifest: (...a: unknown[]) => refreshManifest(...a),
}));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDate: (s: string) => s, formatDateTime: (s: string) => `DT:${s}` }),
}));
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const prod = (over: Record<string, unknown> = {}) => ({
  key: 'acme', mcpUrl: 'https://ss.test/mcp/acme', consentUrl: 'https://acme.test/connect/claude',
  apiBase: 'https://acme.test', manifestVersion: 'v1', toolCount: 3, fetchedAt: '2026-10-08T00:00:00Z',
  stale: false, lastError: null,
  secrets: { productToSs: 'set', ssToProduct: 'missing' },
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  canKeys.splice(0, canKeys.length, 'connector.read', 'connector.manage');
  listProducts.mockResolvedValue([prod()]);
  refreshManifest.mockResolvedValue({});
});

describe('ProductsTab (AC-19-61)', () => {
  it('shows read-only facts', async () => {
    render(<ProductsTab />);
    await screen.findByText('https://ss.test/mcp/acme');
    expect(screen.getByText('https://acme.test/connect/claude')).toBeTruthy();
    expect(screen.getByText('https://acme.test')).toBeTruthy();
    expect(screen.getByText('v1')).toBeTruthy();
    expect(screen.getByText('3')).toBeTruthy();
    expect(screen.queryAllByRole('textbox').length).toBe(0);
  });

  it('renders secrets only as Set / Missing', async () => {
    render(<ProductsTab />);
    await screen.findByText('https://ss.test/mcp/acme');
    expect(screen.getByText('Set')).toBeTruthy();
    expect(screen.getByText('Missing')).toBeTruthy();
  });

  it('copy MCP URL button is present', async () => {
    render(<ProductsTab />);
    await screen.findByText('https://ss.test/mcp/acme');
    expect(screen.getByRole('button', { name: /copy mcp url/i })).toBeTruthy();
  });

  it('no stale banner when fresh; stale banner shows lastError and last good fetchedAt', async () => {
    const { unmount } = render(<ProductsTab />);
    await screen.findByText('https://ss.test/mcp/acme');
    expect(screen.queryByText(/stale/i)).toBeNull();
    unmount();
    listProducts.mockResolvedValue([prod({ stale: true, lastError: 'upstream_error 503' })]);
    render(<ProductsTab />);
    await screen.findByText(/upstream_error 503/);
    expect(screen.getByText(/stale/i)).toBeTruthy();
    expect(screen.getAllByText(/DT:2026-10-08T00:00:00Z/).length).toBeGreaterThan(0);
  });

  it('Refresh manifest calls the service then reloads; hidden without connector.manage', async () => {
    const { unmount } = render(<ProductsTab />);
    await screen.findByText('https://ss.test/mcp/acme');
    await userEvent.click(screen.getByRole('button', { name: /refresh manifest/i }));
    expect(refreshManifest).toHaveBeenCalledWith('acme');
    await screen.findByText('https://ss.test/mcp/acme');
    expect(listProducts.mock.calls.length).toBeGreaterThanOrEqual(2);
    unmount();
    canKeys.splice(0, canKeys.length, 'connector.read');
    render(<ProductsTab />);
    await screen.findByText('https://ss.test/mcp/acme');
    expect(screen.queryByRole('button', { name: /refresh manifest/i })).toBeNull();
  });
});
