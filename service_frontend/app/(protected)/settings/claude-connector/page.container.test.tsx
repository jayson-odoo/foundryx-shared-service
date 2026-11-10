import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';

const widths: unknown[] = [];
vi.mock('@/components/common/container', () => ({
  Container: ({ children, width }: { children: React.ReactNode; width?: string }) => {
    widths.push(width);
    return <div data-testid="container">{children}</div>;
  },
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set(['connector.read']) }),
}));
vi.mock('./components/use-connector-grant-list-config', () => ({
  useConnectorGrantListConfig: () => ({ columns: [], actions: [], fetcher: vi.fn(), viewKey: 'x', getRowId: () => '' }),
}));
vi.mock('@/components/platform/resource-list', () => ({ ResourceList: () => <div data-testid="grants-list" /> }));
vi.mock('./components/products-tab', () => ({ ProductsTab: () => <div /> }));
vi.mock('next-auth/react', () => ({ useSession: () => ({ data: null, status: 'unauthenticated' }), signOut: vi.fn() }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}), list: vi.fn().mockResolvedValue([]) },
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/settings/claude-connector',
  useSearchParams: () => new URLSearchParams(),
}));

import ClaudeConnectorPage from './page';

describe('review fix 7: page uses the shared fluid Container', () => {
  it('wraps content in Container width="fluid"', () => {
    const { getByTestId } = render(<ClaudeConnectorPage />);
    expect(widths).toContain('fluid');
    expect(getByTestId('container').contains(getByTestId('grants-list'))).toBe(true);
  });
});
