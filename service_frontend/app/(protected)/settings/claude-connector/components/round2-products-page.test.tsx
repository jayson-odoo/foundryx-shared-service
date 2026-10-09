import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

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
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }));
vi.mock('@/lib/toast', () => ({ toast }));
vi.mock('sonner', () => ({ toast }));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDate: (s: string) => s, formatDateTime: (s: string) => `DT:${s}` }),
}));
vi.mock('@/providers/settings-provider', () => ({ useSettings: () => ({ settings: { container: 'fixed' } }) }));
vi.mock('./use-connector-grant-list-config', () => ({
  useConnectorGrantListConfig: () => ({ columns: [], actions: [], fetcher: vi.fn(), viewKey: 'x', getRowId: () => '' }),
}));
vi.mock('@/components/platform/resource-list', () => ({ ResourceList: () => <div data-testid="grants-list" /> }));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/settings/claude-connector',
  useSearchParams: () => new URLSearchParams(),
}));

import { ProductsTab } from './products-tab';
import ClaudeConnectorPage from '../page';

const prod = (over: Record<string, unknown> = {}) => ({
  key: 'acme', displayName: 'Acme', mcpUrl: 'https://ss.test/mcp/acme',
  consentUrl: 'https://acme.test/connect/claude', apiBase: 'https://acme.test', manifestVersion: 'v1',
  toolCount: 3, fetchedAt: '2026-10-08T00:00:00Z', stale: false, lastError: null,
  secrets: { productToSs: 'set', ssToProduct: 'set' }, ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  canKeys.splice(0, canKeys.length, 'connector.read', 'connector.manage');
});

describe('round 2 item 8: stale banner + refresh toast', () => {
  it('banner text matches the mock', async () => {
    listProducts.mockResolvedValue([prod({ stale: true, lastError: 'upstream_error' })]);
    render(<ProductsTab />);
    expect(await screen.findByText(
      'Acme manifest is stale: last refresh failed (upstream_error). Serving the copy fetched DT:2026-10-08T00:00:00Z.',
    )).toBeTruthy();
  });

  it('refresh error toast auto-dismisses (finite duration)', async () => {
    listProducts.mockResolvedValue([prod()]);
    refreshManifest.mockResolvedValue(prod({ stale: true, lastError: 'upstream_error' }));
    render(<ProductsTab />);
    await screen.findByText('https://ss.test/mcp/acme');
    await userEvent.click(screen.getByRole('button', { name: /refresh manifest/i }));
    await vi.waitFor(() => expect(toast.error).toHaveBeenCalled());
    const opts = toast.error.mock.calls[0][1] as { duration?: number } | undefined;
    expect(typeof opts?.duration).toBe('number');
    expect(Number.isFinite(opts!.duration)).toBe(true);
  });
});

describe('round 2 item 3: page heading + breadcrumb before the tabs', () => {
  it('renders the title and a Settings breadcrumb before the tablist', () => {
    render(<ClaudeConnectorPage />);
    const heading = screen.getByRole('heading', { name: 'Claude connector' });
    const crumbs = screen.getByRole('navigation', { name: /breadcrumb/i });
    expect(crumbs.textContent).toContain('Settings');
    const tabs = screen.getByRole('tablist');
    expect(heading.compareDocumentPosition(tabs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(crumbs.compareDocumentPosition(tabs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
