/**
 * Switch-off parity for Settings > Statuses and Settings > Rules (Foundryx
 * UIUX slice W4-SETTINGS): both lists rendered with the switch OFF. Recorded
 * on the code as it was before the slice; a change that needs one of these
 * snapshots updated is wrong by definition (fix the code, never the snapshot).
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import TenantStatusesPage from '../page';
import TenantRulesPage from '../../rules/page';

vi.mock('@/services/status-engine-service', () => ({
  statusEngineService: {
    entities: vi.fn(async () => [
      {
        entityType: 'contact',
        label: 'Contact',
        module: 'omnichannel',
        platformOwned: false,
        requiredFlags: [],
        statusCount: 4,
        transitionCount: 6,
        customized: true,
        hasTimeAutoEdges: false,
      },
      {
        entityType: 'broadcast',
        label: 'Broadcast',
        module: 'omnichannel',
        platformOwned: false,
        requiredFlags: [],
        statusCount: 5,
        transitionCount: 7,
        customized: false,
        hasTimeAutoEdges: false,
      },
    ]),
  },
}));
vi.mock('@/services/rule-engine-service', () => ({
  ruleEngineService: {
    listRules: vi.fn(async () => ({
      data: [
        {
          site: 'status_transition',
          siteLabel: 'Status transition',
          context: 'Contact: New to Qualified',
          summary: 'Email is set',
          target: 'contact',
          updatedAt: '2026-11-01T02:00:00Z',
        },
      ],
      total: 1,
      page: 0,
    })),
  },
}));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/settings/statuses'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { name: 'Demo Admin', permissions: [], timezone: 'UTC' } }, status: 'authenticated' }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/hooks/use-view-preferences', () => ({
  useViewPreferences: () => ({
    isLoaded: true,
    columnOrder: [],
    columnVisibility: {},
    columnSizing: {},
    setColumnOrder: () => {},
    setColumnVisibility: () => {},
    setColumnSizing: () => {},
  }),
}));

function stable(root: Element): string {
  const seen = new Map<string, string>();
  return parityHtml(root).replace(/_r_[0-9a-z]+_/g, (id) => {
    let name = seen.get(id);
    if (!name) {
      name = `_rid${seen.size}_`;
      seen.set(id, name);
    }
    return name;
  });
}

describe('parity (switch off): Settings > Statuses and Rules', () => {
  it('the statuses list', async () => {
    const { container } = render(
      <SettingsProvider>
        <TenantStatusesPage />
      </SettingsProvider>,
    );
    await screen.findByText('Broadcast');
    expect(stable(container)).toMatchSnapshot();
  });

  it('the rules list', async () => {
    const { container } = render(
      <SettingsProvider>
        <TenantRulesPage />
      </SettingsProvider>,
    );
    await screen.findByText('Email is set');
    expect(stable(container)).toMatchSnapshot();
  });
});
