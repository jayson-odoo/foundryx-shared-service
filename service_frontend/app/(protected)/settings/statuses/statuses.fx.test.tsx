/**
 * Settings > Statuses with the Foundryx UIUX switch on (slice W4-SETTINGS):
 * the status and transition drawers (the only places a tenant's statuses
 * are written) hand exactly the same values to the engine in both looks;
 * the statuses and rules lists render under the new look with their page
 * choices. Switch off is pinned by `__parity__/statuses.parity.test.tsx`.
 */
import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { StatusNodeData } from '@/types/status-engine';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { StatusDrawer } from '@/components/platform/status-engine/status-drawer';
import { TransitionDrawer } from '@/components/platform/status-engine/transition-drawer';
import TenantStatusesPage from './page';
import TenantRulesPage from '../rules/page';

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
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: ReactNode }) => children,
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
vi.mock('next-themes', () => ({ useTheme: () => ({ theme: 'light', setTheme: vi.fn() }) }));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/settings/statuses'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Nurul Huda', permissions: [], timezone: 'UTC' } },
    status: 'authenticated',
  }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

function look(on: boolean) {
  return function Look({ children }: { children: ReactNode }) {
    return (
      <SettingsProvider>
        <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
          {children}
        </FxProvider>
      </SettingsProvider>
    );
  };
}

afterEach(() => resetPageActionsForTests());

function status(overrides: Partial<StatusNodeData>): StatusNodeData {
  return {
    id: 'status-1',
    entityType: 'contact',
    key: 'pending',
    label: 'Pending',
    color: 'blue',
    sortOrder: 1,
    isInitial: false,
    isTerminal: false,
    isActive: true,
    blocksAccess: false,
    isArchived: false,
    isDefault: false,
    positionX: 0,
    positionY: 0,
    isSystem: false,
    recordCount: 0,
    ...overrides,
  };
}
const pending = status({ id: 's-pending', key: 'pending', label: 'Pending', isInitial: true });
const won = status({ id: 's-won', key: 'won', label: 'Won', isTerminal: true });

function statusDrawerProps() {
  return {
    open: true,
    onOpenChange: vi.fn(),
    statuses: [pending, won],
    onCreate: vi.fn().mockResolvedValue(true),
    onUpdate: vi.fn().mockResolvedValue(true),
    onDelete: vi.fn().mockResolvedValue(true),
    onSetActive: vi.fn().mockResolvedValue(true),
    onMigrate: vi.fn().mockResolvedValue(true),
  };
}

describe('statuses: the same writes in both looks', () => {
  it('creating a status', async () => {
    const calls: unknown[][] = [];
    for (const on of [false, true]) {
      const props = statusDrawerProps();
      const view = render(<StatusDrawer {...props} status={null} canManage />, {
        wrapper: look(on),
      });
      fireEvent.change(screen.getByLabelText(/Label/), { target: { value: 'On Hold' } });
      fireEvent.click(screen.getByRole('switch', { name: 'Blocks access' }));
      fireEvent.click(screen.getByRole('button', { name: 'Create status' }));
      await waitFor(() => expect(props.onCreate).toHaveBeenCalledTimes(1));
      calls.push(props.onCreate.mock.calls[0]);
      view.unmount();
    }
    expect(calls[1]).toEqual(calls[0]);
  });

  it('renaming a status', async () => {
    const calls: unknown[][] = [];
    for (const on of [false, true]) {
      const props = statusDrawerProps();
      const view = render(<StatusDrawer {...props} status={pending} canManage />, {
        wrapper: look(on),
      });
      fireEvent.change(screen.getByLabelText(/Label/), { target: { value: 'Waiting' } });
      fireEvent.click(screen.getByRole('button', { name: 'Save status' }));
      await waitFor(() => expect(props.onUpdate).toHaveBeenCalledTimes(1));
      calls.push(props.onUpdate.mock.calls[0]);
      view.unmount();
    }
    expect(calls[1]).toEqual(calls[0]);
  });

  it('creating a transition', async () => {
    const calls: unknown[][] = [];
    for (const on of [false, true]) {
      const onCreate = vi.fn().mockResolvedValue(true);
      const view = render(
        <TransitionDrawer
          open
          onOpenChange={vi.fn()}
          statuses={[pending, won]}
          roleOptions={[{ value: 'role-1', label: 'Admin' }]}
          userOptions={[{ value: 'user-1', label: 'Demo User' }]}
          templateOptions={[]}
          facts={[]}
          onCreate={onCreate}
          onUpdate={vi.fn().mockResolvedValue(true)}
          onDelete={vi.fn().mockResolvedValue(true)}
          transition={null}
          pending={{ fromStatusId: pending.id, toStatusId: won.id }}
          canManage
        />,
        { wrapper: look(on) },
      );
      fireEvent.change(screen.getByLabelText(/Action label/), { target: { value: 'Close won' } });
      fireEvent.click(screen.getByRole('button', { name: 'Create transition' }));
      await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1));
      calls.push(onCreate.mock.calls[0]);
      view.unmount();
    }
    expect(calls[1]).toEqual(calls[0]);
  });
});

describe('lists under the new look', () => {
  it('the statuses list says what it holds', async () => {
    render(<TenantStatusesPage />, { wrapper: look(true) });
    expect((await screen.findAllByText('Contact')).length).toBeGreaterThan(0);
  });

  it('the rules list renders its rows', async () => {
    render(<TenantRulesPage />, { wrapper: look(true) });
    expect((await screen.findAllByText('Email is set')).length).toBeGreaterThan(0);
  });
});
