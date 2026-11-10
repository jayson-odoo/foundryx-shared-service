import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import ClaudeConnectorPage from './page';

const canKeys: string[] = [];
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (k: string) => canKeys.includes(k), ready: true, permissions: new Set(canKeys) }),
}));
vi.mock('./components/use-connector-grant-list-config', () => ({
  useConnectorGrantListConfig: () => ({ columns: [], actions: [], fetcher: vi.fn(), viewKey: 'x', getRowId: () => '' }),
}));
vi.mock('@/components/platform/resource-list', () => ({
  ResourceList: () => <div data-testid="grants-list" />,
}));
vi.mock('./components/products-tab', () => ({ ProductsTab: () => <div data-testid="products-tab" /> }));
vi.mock('@/providers/settings-provider', () => ({ useSettings: () => ({ settings: { container: 'fixed' } }) }));
vi.mock('next-auth/react', () => ({ useSession: () => ({ data: null, status: 'unauthenticated' }), signOut: vi.fn() }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}), list: vi.fn().mockResolvedValue([]) },
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/settings/claude-connector',
  useSearchParams: () => new URLSearchParams(),
}));

beforeEach(() => canKeys.splice(0, canKeys.length));

describe('Claude connector page (AC-19-60)', () => {
  it('shows NoPermission without connector.read', () => {
    render(<ClaudeConnectorPage />);
    expect(screen.queryByTestId('grants-list')).toBeNull();
  });

  it('renders Grants and Products tabs with connector.read', () => {
    canKeys.push('connector.read');
    render(<ClaudeConnectorPage />);
    expect(screen.getByRole('tab', { name: /grants/i })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /products/i })).toBeTruthy();
    expect(screen.getByTestId('grants-list')).toBeTruthy();
  });
});
