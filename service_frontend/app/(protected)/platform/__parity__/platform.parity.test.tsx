/**
 * Switch-off parity for the platform pages (Foundryx UIUX slice W3-PLATFORM,
 * build plan 1.3 and 4): the tenants list, a tenant record (view, edit, new),
 * its Modules tab, the purge confirm (one tenant and several), the status
 * engine list and one entity's record chrome, and the rules list, rendered
 * with the switch OFF. Recorded on the code as it was before the slice; a
 * change that needs one of these snapshots updated is wrong by definition
 * (fix the code, never the snapshot). Generated ids are renamed in order of
 * appearance. The status machine canvas is stubbed: it is an SS difference
 * the slice never touches, and only the record chrome around it is pinned.
 */
import { renderHook, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import { ConfirmActionDialog } from '@/components/platform/resource-actions/confirm-action-dialog';
import type { StoreModule } from '@/types/app-store';
import type { StatusEntity, StatusGraph } from '@/types/status-engine';
import type { RuleSiteRow } from '@/types/rules';
import type { TenantDetail } from '@/types/tenant-admin';
import TenantsPage from '../tenants/page';
import { TenantFormView } from '../tenants/components/tenant-form-view';
import { ModulesTab } from '../tenants/components/tenant-form-fields';
import { useTenantActions } from '../tenants/components/use-tenant-actions';
import PlatformStatusEnginePage from '../status-engine/page';
import PlatformRulesPage from '../rules/page';
import { StatusEntityDetail } from '@/components/platform/status-engine';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/platform/tenants'),
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
vi.mock('@/components/platform/branding', () => ({
  BrandingEditor: () => <div data-stub="branding-editor" />,
}));
vi.mock('@/components/platform/status-engine/entity-flow', () => ({
  EntityFlow: ({ editing }: { editing: boolean }) => (
    <div data-stub="entity-flow" data-editing={String(editing)} />
  ),
}));

const tenant = (over: Partial<TenantDetail>): TenantDetail => ({
  id: 'ten-1',
  name: 'Acme Events',
  slug: 'acme-events',
  status: 'ACTIVE',
  statusId: 's-active',
  statusLabel: 'Active',
  statusColor: 'green',
  availableTransitionIds: null,
  isPlatform: false,
  contactName: 'Kay Meister',
  contactEmail: 'kay@acme.test',
  customDomain: null,
  userCount: 12,
  createdAt: '2026-11-01T02:00:00Z',
  updatedAt: '2026-11-02T02:00:00Z',
  notes: 'Pilot customer',
  ...over,
});
const TENANTS: TenantDetail[] = [
  tenant({}),
  tenant({ id: 'ten-2', name: 'Platform', slug: 'platform', isPlatform: true, contactEmail: null, contactName: null }),
  tenant({ id: 'ten-3', name: 'Old Co', slug: 'old-co', status: 'ARCHIVED', statusId: 's-archived', statusLabel: 'Archived', statusColor: 'gray' }),
];

const node = (id: string, key: string, label: string, flags: Partial<{ isArchived: boolean; blocksAccess: boolean }> = {}) => ({
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
  isSystem: true,
  recordCount: 0,
});
const GRAPH: StatusGraph = {
  entityType: 'tenant',
  source: 'platform',
  statuses: [
    node('s-active', 'active', 'Active'),
    node('s-suspended', 'suspended', 'Suspended', { blocksAccess: true }),
    node('s-archived', 'archived', 'Archived', { isArchived: true, blocksAccess: true }),
  ],
  transitions: [
    { id: 't-suspend', entityType: 'tenant', fromStatusId: 's-active', toStatusId: 's-suspended', label: 'Suspend', sortOrder: 1, roles: [], notifications: [] },
    { id: 't-archive', entityType: 'tenant', fromStatusId: 's-active', toStatusId: 's-archived', label: 'Archive', sortOrder: 2, roles: [], notifications: [] },
    { id: 't-restore', entityType: 'tenant', fromStatusId: 's-archived', toStatusId: 's-active', label: 'Restore', sortOrder: 3, roles: [], notifications: [] },
  ],
};

vi.mock('@/services/tenant-admin-service', () => ({
  tenantAdminService: {
    list: vi.fn(async () => ({ data: TENANTS, total: TENANTS.length, page: 0 })),
    get: vi.fn(async (id: string) => TENANTS.find((t) => t.id === id)),
    getAt: vi.fn(async () => ({ tenant: TENANTS[0], total: 3 })),
    statusGraph: vi.fn(async () => GRAPH),
    exportCsv: vi.fn(async () => ''),
    provision: vi.fn(),
    update: vi.fn(),
    transition: vi.fn(),
    purge: vi.fn(),
  },
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

const ENTITIES: StatusEntity[] = [
  { entityType: 'tenant', label: 'Tenant', module: 'core', platformOwned: true, requiredFlags: [], statusCount: 3, transitionCount: 3, customized: false, hasTimeAutoEdges: false },
  { entityType: 'ticket', label: 'Ticket', module: 'helpdesk', platformOwned: false, requiredFlags: [], statusCount: 5, transitionCount: 7, customized: true, hasTimeAutoEdges: true },
];
vi.mock('@/services/status-engine-service', () => ({
  statusEngineService: {
    entities: vi.fn(async () => ENTITIES),
    graph: vi.fn(async () => GRAPH),
  },
}));

const RULES: RuleSiteRow[] = [
  { site: 'status_transition', siteLabel: 'Status transition', context: 'Tenant · Active → Suspended', summary: 'When users is more than 10', target: 'tenant', updatedAt: '2026-11-03T04:00:00Z' },
];
vi.mock('@/services/rule-engine-service', () => ({
  ruleEngineService: { listRules: vi.fn(async () => ({ data: RULES, total: 1, page: 0 })) },
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

describe('parity (switch off): tenants', () => {
  it('list with rows, toolbar and Add tenant', async () => {
    const { container } = render(
      <SettingsProvider>
        <TenantsPage />
      </SettingsProvider>,
    );
    await screen.findByText('Old Co');
    expect(stable(container)).toMatchSnapshot();
  });

  it('tenant record at rest', async () => {
    const { container } = render(<TenantFormView tenantId="ten-1" initialEditing={false} />, { wrapper: SettingsProvider });
    await screen.findByText('Pilot customer');
    expect(stable(container)).toMatchSnapshot();
  });

  it('tenant record while editing', async () => {
    const { container } = render(<TenantFormView tenantId="ten-1" initialEditing />, { wrapper: SettingsProvider });
    await screen.findByDisplayValue('Pilot customer');
    expect(stable(container)).toMatchSnapshot();
  });

  it('new tenant', async () => {
    const { container } = render(<TenantFormView initialEditing />, { wrapper: SettingsProvider });
    await screen.findByText('First admin user');
    expect(stable(container)).toMatchSnapshot();
  });

  it('a tenant Modules tab', async () => {
    const { container } = render(<ModulesTab tenant={TENANTS[0]} />);
    await screen.findByText('Helpdesk');
    expect(stable(container)).toMatchSnapshot();
  });

  it('purge confirm for one tenant and for several', async () => {
    const { result } = renderHook(() => useTenantActions());
    await vi.waitFor(() => expect(result.current.some((a) => a.id.startsWith('transition-'))).toBe(true));
    const purge = result.current.find((a) => a.id === 'purge')!;
    const one = render(
      <ConfirmActionDialog pending={purge} rows={[TENANTS[2]]} onClose={vi.fn()} onConfirm={vi.fn()} />,
    );
    expect(stable(document.body)).toMatchSnapshot();
    one.unmount();
    render(
      <ConfirmActionDialog
        pending={purge}
        rows={[TENANTS[2], { ...TENANTS[2], id: 'ten-4', slug: 'gone-co' }]}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(stable(document.body)).toMatchSnapshot();
  });
});

describe('parity (switch off): status engine and rules', () => {
  it('status engine list', async () => {
    const { container } = render(
      <SettingsProvider>
        <PlatformStatusEnginePage />
      </SettingsProvider>,
    );
    await screen.findByText('Ticket');
    expect(stable(container)).toMatchSnapshot();
  });

  it('one entity record chrome (canvas stubbed)', async () => {
    const { container } = render(
      <StatusEntityDetail entityType="ticket" basePath="/platform/status-engine" listLabel="Status Engine" />,
      { wrapper: SettingsProvider },
    );
    await screen.findByText('Flow');
    expect(stable(container)).toMatchSnapshot();
  });

  it('rules list', async () => {
    const { container } = render(
      <SettingsProvider>
        <PlatformRulesPage />
      </SettingsProvider>,
    );
    await screen.findByText('When users is more than 10');
    expect(stable(container)).toMatchSnapshot();
  });
});
