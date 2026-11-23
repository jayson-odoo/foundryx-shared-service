/**
 * Switch-off parity for the App Store (Foundryx UIUX slice W3-PLATFORM, build
 * plan 1.3 and 4): the storefront card list, a module record (installed and
 * not installed) and the uninstall confirm (one module and several), rendered
 * with the switch OFF. Recorded on the code as it was before the slice; a
 * change that needs one of these snapshots updated is wrong by definition
 * (fix the code, never the snapshot). Generated ids are renamed in order of
 * appearance.
 */
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import { ConfirmActionDialog } from '@/components/platform/resource-actions/confirm-action-dialog';
import { buildModuleActions } from '@/components/platform/app-store';
import type { StoreModule } from '@/types/app-store';
import AppStorePage from '../page';
import { ModuleDetail } from '../[name]/module-detail';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/app-store'),
  useParams: vi.fn(() => ({})),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Demo Admin', permissions: [] } },
    status: 'authenticated',
    update: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn().mockResolvedValue(null), save: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));
vi.mock('@/services/pending-actions-service', () => ({
  pendingActionsService: { park: vi.fn(), cancel: vi.fn(), current: vi.fn().mockResolvedValue({ pending: null }) },
}));

const MODULES: StoreModule[] = [
  {
    name: 'omnichannel',
    title: 'Omnichannel',
    description: 'WhatsApp messaging for events.',
    icon: 'message-square',
    version: '0.2.0',
    status: 'ACTIVE',
    installedVersion: '0.1.0',
    updateAvailable: true,
    installedAt: '2026-05-01T00:00:00Z',
    requires: [{ name: 'core' }],
    provides: [{ capability: 'messaging', version: 1 }],
  },
  {
    name: 'helpdesk',
    title: 'Helpdesk',
    description: 'Tickets.',
    icon: 'life-buoy',
    version: '1.0.0',
    status: null,
    installedVersion: null,
    updateAvailable: false,
    installedAt: null,
  },
  {
    name: 'autocount',
    title: 'AutoCount',
    description: 'ERP bridge.',
    icon: null,
    version: '2.0.0',
    status: 'INACTIVE',
    installedVersion: '2.0.0',
    updateAvailable: false,
    installedAt: '2026-05-01T00:00:00Z',
  },
];
vi.mock('@/services/app-store-service', () => ({
  appStoreService: {
    catalog: vi.fn(async () => MODULES),
    catalogForTenant: vi.fn(async () => MODULES),
    installed: vi.fn(async () => []),
    act: vi.fn(),
    actForTenant: vi.fn(),
    uninstall: vi.fn(),
    uninstallForTenant: vi.fn(),
  },
}));

/** Also masks React 19's `_r_N_` ids, in order of first appearance. */
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

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe('parity (switch off): App Store', () => {
  it('storefront cards', async () => {
    const { container } = render(<AppStorePage />, { wrapper: SettingsProvider });
    await screen.findByText('Helpdesk');
    expect(stable(container)).toMatchSnapshot();
  });

  it('an installed module record', async () => {
    const { container } = render(<ModuleDetail name="omnichannel" />, { wrapper: SettingsProvider });
    await screen.findByText('messaging@1');
    expect(stable(container)).toMatchSnapshot();
  });

  it('a module not installed', async () => {
    const { container } = render(<ModuleDetail name="helpdesk" />, { wrapper: SettingsProvider });
    await screen.findAllByText('v1.0.0');
    expect(stable(container)).toMatchSnapshot();
  });

  it('uninstall confirm for one module and for several', () => {
    const uninstall = buildModuleActions(undefined, vi.fn()).find((a) => a.id === 'uninstall')!;
    const one = render(
      <ConfirmActionDialog pending={uninstall} rows={[MODULES[0]]} onClose={vi.fn()} onConfirm={vi.fn()} />,
    );
    expect(stable(document.body)).toMatchSnapshot();
    one.unmount();
    render(
      <ConfirmActionDialog
        pending={uninstall}
        rows={[MODULES[0], MODULES[2]]}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(stable(document.body)).toMatchSnapshot();
  });
});
