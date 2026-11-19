/**
 * The platform pages with the Foundryx UIUX switch on (slice W3-PLATFORM).
 *
 * - A tenant purge is confirmed by typing the tenant's slug (one tenant) or
 *   how many tenants there are (several); case and spaces are ignored, the
 *   old word DELETE no longer confirms, and nothing is sent before the typed
 *   text matches.
 * - Purge, the lifecycle moves, create and save send exactly what they send
 *   with the switch off (requests captured at `apiFetch`, under the real
 *   services: same path, method and body).
 * - The status engine record saves through the same layout handle in both
 *   looks; the rules list is read-only (it sends nothing).
 * - The pages stay closed to anyone without the permission, in both looks.
 *
 * Switch off is pinned by `__parity__/platform.parity.test.tsx`.
 */
import type { ReactNode } from 'react';
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { StatusGraph } from '@/types/status-engine';
import type { TenantDetail, TenantListItem } from '@/types/tenant-admin';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { ConfirmActionDialog } from '@/components/platform/resource-actions/confirm-action-dialog';
import { runResourceAction } from '@/components/platform/resource-actions/run-action';
import type { ResourceAction } from '@/components/platform/resource-list';
import PlatformRulesPage from './rules/page';
import PlatformStatusEntityPage from './status-engine/[entity]/page';
import PlatformStatusEnginePage from './status-engine/page';
import {
  fxPurgeExpected,
  useTenantActions,
} from './tenants/components/use-tenant-actions';
import { useTenantForm } from './tenants/components/use-tenant-form';
import { useTenantsListConfig } from './tenants/components/use-tenants-list-config';
import NewTenantPage from './tenants/new/page';
import TenantsPage from './tenants/page';

const net = vi.hoisted(() => ({ apiFetch: vi.fn(), apiFetchText: vi.fn() }));
vi.mock('@/lib/api-client', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return { ...real, apiFetch: net.apiFetch, apiFetchText: net.apiFetchText };
});

const toasts = vi.hoisted(() => ({
  fxDone: vi.fn(),
  error: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
}));
vi.mock('@/lib/toast', async (orig) => {
  const real = (await orig()) as { toast: Record<string, unknown> };
  return { toast: { ...real.toast, ...toasts } };
});

const perms = vi.hoisted(() => ({ allow: true }));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({
    can: () => perms.allow,
    ready: true,
    permissions: new Set<string>(),
  }),
}));

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({
    push,
    prefetch: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
  })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/platform/tenants'),
  useParams: vi.fn(() => ({ entity: 'ticket' })),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Nurul Huda', permissions: [] } },
    status: 'authenticated',
    update: vi.fn(),
  }),
}));
vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));

const layout = vi.hoisted(() => ({ save: vi.fn(), discard: vi.fn() }));
vi.mock('@/components/platform/status-engine/entity-flow', () => ({
  EntityFlow: ({
    layoutController,
  }: {
    layoutController: {
      current: { save: () => void; discard: () => void } | null;
    };
  }) => {
    layoutController.current = layout;
    return <div data-stub="entity-flow" />;
  },
}));

const node = (
  id: string,
  key: string,
  label: string,
  flags: Partial<{ isArchived: boolean; blocksAccess: boolean }> = {},
) => ({
  id,
  entityType: 'tenant',
  key,
  label,
  color: 'blue',
  sortOrder: 1,
  isInitial: key === 'active',
  isTerminal: false,
  isActive: true,
  blocksAccess: flags.blocksAccess ?? false,
  isArchived: flags.isArchived ?? false,
  isDefault: false,
  positionX: 0,
  positionY: 0,
  isSystem: key !== 'dormant',
  recordCount: 0,
});
const GRAPH: StatusGraph = {
  entityType: 'tenant',
  source: 'platform',
  statuses: [
    node('s-active', 'active', 'Active'),
    node('s-suspended', 'suspended', 'Suspended', { blocksAccess: true }),
    node('s-archived', 'archived', 'Archived', {
      isArchived: true,
      blocksAccess: true,
    }),
    // An operator-added status: its edge falls back to a plain confirm.
    node('s-dormant', 'dormant', 'Dormant', { blocksAccess: true }),
  ],
  transitions: [
    {
      id: 't-suspend',
      entityType: 'tenant',
      fromStatusId: 's-active',
      toStatusId: 's-suspended',
      label: 'Suspend',
      sortOrder: 1,
      roles: [],
      notifications: [],
    },
    {
      id: 't-archive',
      entityType: 'tenant',
      fromStatusId: 's-active',
      toStatusId: 's-archived',
      label: 'Archive',
      sortOrder: 2,
      roles: [],
      notifications: [],
    },
    {
      id: 't-restore',
      entityType: 'tenant',
      fromStatusId: 's-archived',
      toStatusId: 's-active',
      label: 'Restore',
      sortOrder: 3,
      roles: [],
      notifications: [],
    },
    {
      id: 't-sleep',
      entityType: 'tenant',
      fromStatusId: 's-active',
      toStatusId: 's-dormant',
      label: 'Hibernate',
      sortOrder: 4,
      roles: [],
      notifications: [],
    },
  ],
};

const tenant = (over: Partial<TenantDetail>): TenantDetail => ({
  id: 'ten-1',
  name: 'Acme Events',
  slug: 'acme-events',
  status: 'ARCHIVED',
  statusId: 's-archived',
  statusLabel: 'Archived',
  statusColor: 'gray',
  availableTransitionIds: null,
  isPlatform: false,
  contactName: 'Kay Meister',
  contactEmail: 'kay@acme.test',
  customDomain: null,
  userCount: 12,
  createdAt: '2026-11-01T02:00:00Z',
  updatedAt: '2026-11-02T02:00:00Z',
  notes: null,
  ...over,
});
const ACME = tenant({});
const GONE = tenant({ id: 'ten-2', name: 'Gone Co', slug: 'gone-co' });
const LIVE = tenant({
  id: 'ten-3',
  name: 'Live Co',
  slug: 'live-co',
  status: 'ACTIVE',
  statusId: 's-active',
  statusLabel: 'Active',
});

function look(on: boolean) {
  return function Look({ children }: { children: ReactNode }) {
    return (
      <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
        <SettingsProvider>{children}</SettingsProvider>
      </FxProvider>
    );
  };
}

/** Every write sent: path, method and body. */
function writes() {
  return [...net.apiFetch.mock.calls, ...net.apiFetchText.mock.calls]
    .filter(
      ([, init]) =>
        init &&
        (init as RequestInit).method &&
        (init as RequestInit).method !== 'GET',
    )
    .map(([path, init]) => ({
      path,
      method: (init as RequestInit).method,
      body: (init as RequestInit).body ?? null,
    }));
}

beforeEach(() => {
  perms.allow = true;
  net.apiFetch.mockReset();
  net.apiFetchText.mockReset();
  push.mockReset();
  layout.save.mockReset();
  layout.discard.mockReset();
  Object.values(toasts).forEach((fn) => fn.mockReset());
  window.localStorage.clear();
  window.sessionStorage.clear();
  net.apiFetch.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === '/platform/tenants/status-graph') return GRAPH;
    if (path.startsWith('/platform/tenants?'))
      return { data: [ACME, GONE, LIVE], total: 3, page: 0 };
    if (path === '/platform/tenants' && init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      return tenant({
        id: 'ten-new',
        name: body.name,
        slug: body.slug,
        status: 'ACTIVE',
      });
    }
    if (path === '/platform/tenants/ten-3' && init?.method === 'PATCH') {
      return { ...LIVE, ...JSON.parse(String(init.body)) };
    }
    if (path === '/platform/tenants/ten-3') return LIVE;
    if (path.startsWith('/rules')) return { data: [], total: 0, page: 0 };
    return {};
  });
});
afterEach(() => resetPageActionsForTests());

async function tenantActions(on: boolean) {
  const { result } = renderHook(() => useTenantActions(), {
    wrapper: look(on),
  });
  await waitFor(() =>
    expect(result.current.some((a) => a.id === 'transition-t-sleep')).toBe(
      true,
    ),
  );
  return result.current;
}

/** Opens the confirm the menus open (the same component in both looks) and
 *  runs the action the way the menus do once it is confirmed. */
function openConfirm(
  on: boolean,
  action: ResourceAction<TenantListItem>,
  rows: TenantListItem[],
) {
  const reload = vi.fn();
  const view = render(
    <ConfirmActionDialog
      pending={action}
      rows={rows}
      onClose={vi.fn()}
      onConfirm={(a) => void runResourceAction(a, rows, { reload })}
    />,
    { wrapper: look(on) },
  );
  return { ...view, reload };
}

describe('tenant purge: typed confirm and the same request in both looks', () => {
  it('one tenant: the slug, any case and spacing; nothing sent before it matches', async () => {
    const offPurge = (await tenantActions(false)).find(
      (a) => a.id === 'purge',
    )!;
    const off = openConfirm(false, offPurge, [ACME]);
    fireEvent.change(screen.getByLabelText('Confirmation text'), {
      target: { value: 'acme-events' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Delete forever' }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    const offWrites = writes();
    off.unmount();
    net.apiFetch.mockClear();

    const onPurge = (await tenantActions(true)).find((a) => a.id === 'purge')!;
    const on = openConfirm(true, onPurge, [ACME]);
    expect(screen.getByRole('alertdialog')).toHaveTextContent(
      'Delete Acme Events permanently?',
    );
    const doIt = screen.getByRole('button', { name: 'Delete tenant' });
    const box = screen.getByLabelText('Type "acme-events"');

    fireEvent.click(doIt);
    for (const wrong of ['DELETE', 'acme', 'acme-event', 'Acme Events', '1']) {
      fireEvent.change(box, { target: { value: wrong } });
      fireEvent.click(doIt);
    }
    await new Promise((r) => setTimeout(r, 20));
    expect(writes()).toEqual([]);
    expect(screen.getByText('Type the name to confirm.')).toBeInTheDocument();

    fireEvent.change(box, { target: { value: '  ACME-Events ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Delete tenant' }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()).toEqual(offWrites);
    expect(offWrites[0]).toEqual({
      path: '/platform/tenants/ten-1/purge',
      method: 'POST',
      body: JSON.stringify({ confirmSlug: 'acme-events' }),
    });
    await waitFor(() =>
      expect(toasts.fxDone).toHaveBeenCalledWith({
        what: 'Tenant acme-events deleted permanently',
        byWhom: 'Nurul Huda',
      }),
    );
    expect(on.reload).toHaveBeenCalled();
  });

  it('several tenants: the number of tenants; DELETE no longer confirms', async () => {
    const offPurge = (await tenantActions(false)).find(
      (a) => a.id === 'purge',
    )!;
    const off = openConfirm(false, offPurge, [ACME, GONE]);
    fireEvent.change(screen.getByLabelText('Confirmation text'), {
      target: { value: 'DELETE' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Delete forever' }));
    await waitFor(() => expect(writes()).toHaveLength(2));
    const offWrites = writes();
    off.unmount();
    net.apiFetch.mockClear();

    const onPurge = (await tenantActions(true)).find((a) => a.id === 'purge')!;
    openConfirm(true, onPurge, [ACME, GONE]);
    expect(screen.getByRole('alertdialog')).toHaveTextContent(
      'Delete 2 tenants permanently?',
    );
    const box = screen.getByLabelText('Type "2"');
    for (const wrong of ['DELETE', 'delete', 'acme-events', '3', '22']) {
      fireEvent.change(box, { target: { value: wrong } });
      fireEvent.click(screen.getByRole('button', { name: 'Delete 2 tenants' }));
    }
    await new Promise((r) => setTimeout(r, 20));
    expect(writes()).toEqual([]);

    fireEvent.change(box, { target: { value: ' 2 ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Delete 2 tenants' }));
    await waitFor(() => expect(writes()).toHaveLength(2));
    expect(writes()).toEqual(offWrites);
    expect(fxPurgeExpected([ACME, GONE])).toBe('2');
    expect(fxPurgeExpected([ACME])).toBe('acme-events');
  });
});

describe('tenant lifecycle: the same moves in both looks', () => {
  it('suspend, archive and restore park the same deferred action', async () => {
    const strip = (a: ResourceAction<TenantListItem>) => {
      return {
        id: a.id,
        label: a.label,
        permission: a.permission,
        actionKey: a.deferred?.actionKey,
        entityType: a.deferred?.entityType,
        payload: a.deferred?.payload?.([LIVE]),
      };
    };
    const off = (await tenantActions(false))
      .filter((a) => a.deferred)
      .map(strip);
    const on = await tenantActions(true);
    expect(on.filter((a) => a.deferred).map(strip)).toEqual(off);
    expect(off.map((a) => a.actionKey).sort()).toEqual([
      'tenants.archive',
      'tenants.reactivate',
      'tenants.suspend',
    ]);
    const suspend = on.find((a) => a.id === 'transition-t-suspend')!;
    expect(suspend.deferred?.fxName?.([LIVE])).toBe('Live Co');
  });

  it("an operator-added status's move sends the same transition", async () => {
    const offSleep = (await tenantActions(false)).find(
      (a) => a.id === 'transition-t-sleep',
    )!;
    await runResourceAction(offSleep, [LIVE], { reload: vi.fn() });
    const offWrites = writes();
    expect(toasts.success).toHaveBeenCalled();
    net.apiFetch.mockClear();

    const onSleep = (await tenantActions(true)).find(
      (a) => a.id === 'transition-t-sleep',
    )!;
    await runResourceAction(onSleep, [LIVE], { reload: vi.fn() });
    expect(writes()).toEqual(offWrites);
    expect(offWrites).toEqual([
      {
        path: '/platform/tenants/ten-3/transition',
        method: 'POST',
        body: JSON.stringify({ transitionId: 't-sleep' }),
      },
    ]);
    expect(toasts.fxDone).toHaveBeenCalledWith({
      what: 'Hibernate: Live Co',
      howMany: undefined,
      byWhom: 'Nurul Huda',
    });
  });
});

describe('tenant create and save: the same request in both looks', () => {
  async function createIn(on: boolean) {
    const { result } = renderHook(() => useTenantForm(undefined, true), {
      wrapper: look(on),
    });
    await waitFor(() => expect(result.current.config).not.toBeNull());
    act(() => {
      const f = result.current.form;
      f.setValue('name', ' Kopi Kita ', { shouldDirty: true });
      f.setValue('slug', 'kopi-kita', { shouldDirty: true });
      f.setValue('contactName', '', { shouldDirty: true });
      f.setValue('contactEmail', 'ops@kopi.test', { shouldDirty: true });
      f.setValue('notes', 'Trial', { shouldDirty: true });
      f.setValue('adminName', 'Siti', { shouldDirty: true });
      f.setValue('adminEmail', 'siti@kopi.test', { shouldDirty: true });
      f.setValue('adminPassword', 'Str0ng!Passw0rd', { shouldDirty: true });
    });
    let ok = false;
    await act(async () => {
      ok = await result.current.config!.onSave();
    });
    return ok;
  }

  it('create', async () => {
    expect(await createIn(false)).toBe(true);
    const off = writes();
    expect(toasts.success).toHaveBeenCalledWith('Tenant provisioned.');
    net.apiFetch.mockClear();
    expect(await createIn(true)).toBe(true);
    expect(writes()).toEqual(off);
    expect(off).toHaveLength(1);
    expect(off[0].path).toBe('/platform/tenants');
    expect(toasts.fxDone).toHaveBeenCalledWith({
      what: 'Tenant Kopi Kita created',
      byWhom: 'Nurul Huda',
    });
    expect(push).toHaveBeenNthCalledWith(2, push.mock.calls[0][0]);
  });

  async function saveIn(on: boolean) {
    const { result } = renderHook(() => useTenantForm('ten-3', true), {
      wrapper: look(on),
    });
    await waitFor(() => expect(result.current.config).not.toBeNull());
    act(() => {
      const f = result.current.form;
      f.setValue('name', 'Live Co Sdn Bhd', { shouldDirty: true });
      f.setValue('customDomain', ' events.live.test ', { shouldDirty: true });
      f.setValue('contactName', '   ', { shouldDirty: true });
    });
    let ok = false;
    await act(async () => {
      ok = await result.current.config!.onSave();
    });
    return { ok, config: result.current.config! };
  }

  it('save, with the form red action and discard name set only for the new look', async () => {
    const off = await saveIn(false);
    expect(off.ok).toBe(true);
    const offWrites = writes();
    net.apiFetch.mockClear();
    const on = await saveIn(true);
    expect(on.ok).toBe(true);
    expect(writes()).toEqual(offWrites);
    expect(offWrites).toEqual([
      {
        path: '/platform/tenants/ten-3',
        method: 'PATCH',
        body: JSON.stringify({
          name: 'Live Co Sdn Bhd',
          contactName: null,
          contactEmail: 'kay@acme.test',
          customDomain: 'events.live.test',
          notes: null,
        }),
      },
    ]);
    expect(toasts.fxDone).toHaveBeenCalledWith({
      what: 'Tenant Live Co Sdn Bhd saved',
      byWhom: 'Nurul Huda',
    });
    expect(on.config.fx).toMatchObject({
      mainActionId: 'save',
      discardName: 'Live Co Sdn Bhd',
    });
  });
});

describe('the tenants list config under the switch', () => {
  it('keeps Add tenant as the red action and Delete permanently in More', async () => {
    const { result } = renderHook(() => useTenantsListConfig(), {
      wrapper: look(true),
    });
    await waitFor(() =>
      expect(result.current.actions.length).toBeGreaterThan(3),
    );
    expect(result.current.fx?.mainActionId).toBeUndefined();
    expect(result.current.createLabel).toBe('Add tenant');
    expect(result.current.fx?.moreActionIds).toEqual(['purge']);
    expect(result.current.fx?.noun).toBe('tenants');
  });
});

describe('status engine record: Save sends through the same layout handle in both looks', () => {
  beforeEach(() => {
    net.apiFetch.mockImplementation(async (path: string) => {
      if (path.startsWith('/statuses?'))
        return { ...GRAPH, entityType: 'ticket' };
      return {
        data: [
          {
            entityType: 'ticket',
            label: 'Ticket',
            module: 'helpdesk',
            platformOwned: false,
            requiredFlags: [],
            statusCount: 4,
            transitionCount: 4,
            customized: false,
            hasTimeAutoEdges: false,
          },
        ],
      };
    });
  });

  it('off: Edit, then the record Save button', async () => {
    render(<PlatformStatusEntityPage />, { wrapper: look(false) });
    fireEvent.click(await screen.findByRole('button', { name: /^Edit/ }));
    fireEvent.click(await screen.findByRole('button', { name: /^Save/ }));
    await waitFor(() => expect(layout.save).toHaveBeenCalledTimes(1));
    expect(writes()).toEqual([]);
  });

  it('on: the same handle, from the red action', async () => {
    render(<PlatformStatusEntityPage />, { wrapper: look(true) });
    await screen.findByText('Flow');
    // The red action registers with the page header; take it from there.
    const edit = await screen.findByRole('button', { name: /^Edit/ });
    fireEvent.click(edit);
    const save = await screen.findByRole('button', { name: /^Save/ });
    fireEvent.click(save);
    await waitFor(() => expect(layout.save).toHaveBeenCalledTimes(1));
    expect(writes()).toEqual([]);
  });
});

describe('the platform pages stay closed without the permission, in both looks', () => {
  for (const on of [false, true]) {
    it(`${on ? 'on' : 'off'}: tenants, new tenant, status engine, rules`, async () => {
      perms.allow = false;
      for (const Page of [
        TenantsPage,
        NewTenantPage,
        PlatformStatusEnginePage,
        PlatformRulesPage,
        PlatformStatusEntityPage,
      ]) {
        const view = render(<Page />, { wrapper: look(on) });
        expect(
          screen.getByText('You don’t have access to this page'),
        ).toBeInTheDocument();
        expect(screen.queryByRole('table')).toBeNull();
        view.unmount();
      }
      await new Promise((r) => setTimeout(r, 20));
      // No record is loaded and nothing is written. (The tenants page reads
      // the lifecycle graph above its gate today, in both looks.)
      const paths = net.apiFetch.mock.calls.map(([path]) => String(path));
      expect(
        paths.filter((path) => path !== '/platform/tenants/status-graph'),
      ).toEqual([]);
      expect(writes()).toEqual([]);
    });
  }
});
