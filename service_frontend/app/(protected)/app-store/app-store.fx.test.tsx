/**
 * The App Store with the Foundryx UIUX switch on (slice W3-PLATFORM).
 *
 * - Uninstall is confirmed by typing the module's name (one module) or how
 *   many modules there are (several); case and spaces are ignored, the old
 *   word UNINSTALL no longer confirms, and nothing is sent before it matches.
 * - Install, update, deactivate, reactivate and uninstall send exactly what
 *   they send with the switch off, on the storefront and on a tenant record's
 *   Modules tab (requests captured at `apiFetch` under the real services).
 * - The pages stay closed to anyone without the permission, in both looks.
 *
 * Switch off is pinned by `__parity__/app-store.parity.test.tsx`.
 */
import type { ReactNode } from 'react';
import {
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { StoreModule } from '@/types/app-store';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import {
  buildModuleActions,
  fxUninstallExpected,
  useModuleListConfig,
} from '@/components/platform/app-store';
import { ConfirmActionDialog } from '@/components/platform/resource-actions/confirm-action-dialog';
import { runResourceAction } from '@/components/platform/resource-actions/run-action';
import type { ResourceAction } from '@/components/platform/resource-list';
import ModuleDetailPage from './[name]/page';
import AppStorePage from './page';

const net = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock('@/lib/api-client', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return { ...real, apiFetch: net.apiFetch };
});
vi.mock('@/hooks/use-app-store', () => ({
  invalidateInstalledModules: vi.fn(async () => undefined),
}));

const toasts = vi.hoisted(() => ({
  fxDone: vi.fn(),
  error: vi.fn(),
  success: vi.fn(),
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
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    prefetch: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
  })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/app-store'),
  useParams: vi.fn(() => ({ name: 'omnichannel' })),
}));
const session = vi.hoisted(() => ({ update: vi.fn(async () => undefined) }));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Nurul Huda', permissions: [] } },
    status: 'authenticated',
    update: session.update,
  }),
}));
vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));

const mod = (over: Partial<StoreModule>): StoreModule => ({
  name: 'omnichannel',
  title: 'Omnichannel',
  description: 'WhatsApp messaging.',
  icon: 'message-square',
  version: '0.2.0',
  status: 'ACTIVE',
  installedVersion: '0.1.0',
  updateAvailable: true,
  installedAt: '2026-05-01T00:00:00Z',
  ...over,
});
const OMNI = mod({});
const AC = mod({
  name: 'autocount',
  title: 'AutoCount',
  status: 'INACTIVE',
  updateAvailable: false,
  installedVersion: '0.2.0',
});
const HELP = mod({
  name: 'helpdesk',
  title: 'Helpdesk',
  status: null,
  installedVersion: null,
  updateAvailable: false,
  installedAt: null,
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

function writes() {
  return net.apiFetch.mock.calls
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
  session.update.mockClear();
  Object.values(toasts).forEach((fn) => fn.mockReset());
  window.localStorage.clear();
  window.sessionStorage.clear();
  net.apiFetch.mockImplementation(async (path: string) => {
    if (path === '/app-store/modules' || path.endsWith('/modules'))
      return [OMNI, AC, HELP];
    return {};
  });
});

const actionsFor = (on: boolean, tenantId?: string) =>
  buildModuleActions(tenantId, session.update, { on, byWhom: 'Nurul Huda' });

function openConfirm(
  on: boolean,
  action: ResourceAction<StoreModule>,
  rows: StoreModule[],
) {
  return render(
    <ConfirmActionDialog
      pending={action}
      rows={rows}
      onClose={vi.fn()}
      onConfirm={(a) => void runResourceAction(a, rows, { reload: vi.fn() })}
    />,
    { wrapper: look(on) },
  );
}

describe('uninstall: typed confirm and the same request in both looks', () => {
  for (const tenantId of [undefined, 'ten-9']) {
    const where = tenantId ? "a tenant's Modules tab" : 'the storefront';

    it(`one module on ${where}: its name, any case and spacing; nothing sent before`, async () => {
      const off = openConfirm(
        false,
        actionsFor(false, tenantId).find((a) => a.id === 'uninstall')!,
        [OMNI],
      );
      fireEvent.change(screen.getByLabelText('Confirmation text'), {
        target: { value: 'omnichannel' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Uninstall' }));
      await waitFor(() => expect(writes()).toHaveLength(1));
      const offWrites = writes();
      off.unmount();
      net.apiFetch.mockClear();

      openConfirm(
        true,
        actionsFor(true, tenantId).find((a) => a.id === 'uninstall')!,
        [OMNI],
      );
      expect(screen.getByRole('alertdialog')).toHaveTextContent(
        'Uninstall Omnichannel?',
      );
      const box = screen.getByLabelText('Type "omnichannel"');
      const doIt = screen.getByRole('button', { name: 'Uninstall module' });
      fireEvent.click(doIt);
      for (const wrong of ['UNINSTALL', 'omni', 'omnichannels', '1']) {
        fireEvent.change(box, { target: { value: wrong } });
        fireEvent.click(doIt);
      }
      await new Promise((r) => setTimeout(r, 20));
      expect(writes()).toEqual([]);

      fireEvent.change(box, { target: { value: ' OmniChannel ' } });
      fireEvent.click(doIt);
      await waitFor(() => expect(writes()).toHaveLength(1));
      expect(writes()).toEqual(offWrites);
      expect(offWrites[0]).toMatchObject({
        path: tenantId
          ? '/platform/tenants/ten-9/modules/omnichannel/uninstall'
          : '/app-store/modules/omnichannel/uninstall',
        method: 'POST',
      });
      await waitFor(() =>
        expect(toasts.fxDone).toHaveBeenCalledWith({
          what: 'Omnichannel uninstalled',
          byWhom: 'Nurul Huda',
        }),
      );
    });
  }

  it('several modules: the number of modules; UNINSTALL no longer confirms', async () => {
    const off = openConfirm(
      false,
      actionsFor(false).find((a) => a.id === 'uninstall')!,
      [OMNI, AC],
    );
    fireEvent.change(screen.getByLabelText('Confirmation text'), {
      target: { value: 'UNINSTALL' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Uninstall' }));
    await waitFor(() => expect(writes()).toHaveLength(2));
    const offWrites = writes();
    off.unmount();
    net.apiFetch.mockClear();

    openConfirm(true, actionsFor(true).find((a) => a.id === 'uninstall')!, [
      OMNI,
      AC,
    ]);
    const box = screen.getByLabelText('Type "2"');
    const doIt = screen.getByRole('button', { name: 'Uninstall 2 modules' });
    for (const wrong of ['UNINSTALL', 'uninstall', 'omnichannel', '3']) {
      fireEvent.change(box, { target: { value: wrong } });
      fireEvent.click(doIt);
    }
    await new Promise((r) => setTimeout(r, 20));
    expect(writes()).toEqual([]);
    fireEvent.change(box, { target: { value: '2' } });
    fireEvent.click(doIt);
    await waitFor(() => expect(writes()).toHaveLength(2));
    expect(writes()).toEqual(offWrites);
    expect(fxUninstallExpected([OMNI])).toBe('omnichannel');
    expect(fxUninstallExpected([OMNI, AC])).toBe('2');
  });
});

describe('install, update, deactivate and reactivate: the same requests in both looks', () => {
  const cases: [string, StoreModule[]][] = [
    ['install', [HELP]],
    ['update', [OMNI]],
    ['reactivate', [AC]],
  ];
  for (const tenantId of [undefined, 'ten-9']) {
    for (const [id, rows] of cases) {
      it(`${id} on ${tenantId ? "a tenant's Modules tab" : 'the storefront'}`, async () => {
        await runResourceAction(
          actionsFor(false, tenantId).find((a) => a.id === id)!,
          rows,
          { reload: vi.fn() },
        );
        const off = writes();
        expect(toasts.fxDone).not.toHaveBeenCalled();
        net.apiFetch.mockClear();
        await runResourceAction(
          actionsFor(true, tenantId).find((a) => a.id === id)!,
          rows,
          { reload: vi.fn() },
        );
        expect(writes()).toEqual(off);
        expect(off).toHaveLength(1);
        expect(toasts.fxDone).toHaveBeenCalledTimes(1);
      });
    }
  }

  it("deactivate on a tenant's Modules tab (plain confirm) sends the same request", async () => {
    await runResourceAction(
      actionsFor(false, 'ten-9').find((a) => a.id === 'deactivate')!,
      [OMNI],
      { reload: vi.fn() },
    );
    const off = writes();
    net.apiFetch.mockClear();
    await runResourceAction(
      actionsFor(true, 'ten-9').find((a) => a.id === 'deactivate')!,
      [OMNI],
      { reload: vi.fn() },
    );
    expect(writes()).toEqual(off);
    expect(off).toEqual([
      {
        path: '/platform/tenants/ten-9/modules/omnichannel/deactivate',
        method: 'POST',
        body: null,
      },
    ]);
  });

  it('deactivate on the storefront parks the same deferred action', () => {
    const strip = (a: ResourceAction<StoreModule>) => ({
      actionKey: a.deferred?.actionKey,
      entityType: a.deferred?.entityType,
      payload: a.deferred?.payload?.([OMNI]),
    });
    const off = actionsFor(false).find((a) => a.id === 'deactivate')!;
    const on = actionsFor(true).find((a) => a.id === 'deactivate')!;
    expect(strip(on)).toEqual(strip(off));
    expect(on.deferred?.fxName?.([OMNI])).toBe('Omnichannel');
  });

  it('a failed install still reports the error and shows no done toast', async () => {
    net.apiFetch.mockRejectedValueOnce(new Error('Needs core first.'));
    await runResourceAction(
      actionsFor(true).find((a) => a.id === 'install')!,
      [HELP],
      { reload: vi.fn() },
    );
    expect(toasts.error).toHaveBeenCalledWith('Needs core first.');
    expect(toasts.fxDone).not.toHaveBeenCalled();
  });
});

describe('module record: the red action sends what the record menu sends today', () => {
  it('Update on an installed module with an update waiting', async () => {
    render(<ModuleDetailPage />, { wrapper: look(true) });
    const update = await screen.findByRole('button', { name: /^Update/ });
    fireEvent.click(update);
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()).toEqual([
      {
        path: '/app-store/modules/omnichannel/update',
        method: 'POST',
        body: null,
      },
    ]);
    await runResourceAction(
      actionsFor(false).find((a) => a.id === 'update')!,
      [OMNI],
      { reload: vi.fn() },
    );
    expect(writes()[1]).toEqual(writes()[0]);
  });
});

describe('the list config under the switch', () => {
  it('storefront and tenant tab', () => {
    const shop = renderHook(() => useModuleListConfig(), {
      wrapper: look(true),
    }).result.current;
    expect(shop.fx).toMatchObject({
      noun: 'modules',
      moreActionIds: ['uninstall'],
      compactStates: false,
    });
    const tab = renderHook(() => useModuleListConfig('ten-9'), {
      wrapper: look(true),
    }).result.current;
    expect(tab.fx?.compactStates).toBe(true);
  });
});

describe('the App Store stays closed without the permission, in both looks', () => {
  for (const on of [false, true]) {
    it(`${on ? 'on' : 'off'}: storefront and module record`, async () => {
      perms.allow = false;
      for (const Page of [AppStorePage, ModuleDetailPage]) {
        const view = render(<Page />, { wrapper: look(on) });
        expect(
          screen.getByText('You don’t have access to this page'),
        ).toBeInTheDocument();
        view.unmount();
      }
      await new Promise((r) => setTimeout(r, 20));
      expect(net.apiFetch).not.toHaveBeenCalled();
    });
  }
});
