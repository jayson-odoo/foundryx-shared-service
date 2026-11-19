/**
 * Switch-off parity for the AutoCount setup pages (Foundryx UIUX slice
 * W5-AC-SETUP, build plan 1.3 and 4): the companies list, Connect company, a
 * company record (Overview and Entities tabs), the entity task editor (active,
 * paused and draft records, at rest and while editing) and the standalone
 * field-mapping editor, rendered with the switch OFF. Recorded on the code as
 * it was before the slice; a change that needs one of these snapshots updated
 * is wrong by definition (fix the code, never the snapshot). Generated ids are
 * renamed in order of appearance. The SQL editor and the schema tree are
 * stubbed: they are recorded product differences the slice never touches.
 */
import type { ReactNode } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import { mockAutocountService } from '@/services/autocount-service.mock';
import type {
  AutocountCompany,
  AutocountCompanyDetail,
  AutocountEntityConfig,
  AutocountEtlTask,
  AutocountMappingView,
} from '@/types/autocount';
import type { UseAutocountSourceConnectionsResult } from '@/hooks/use-autocount-connections';
import AutocountCompaniesPage from '../page';
import { ConnectCompanyView } from '../components/connect-company-view';
import { AutocountCompanyDetailView } from '../components/company-detail-view';
import { TaskEditorView } from '../[id]/entities/[entityType]/components/task-editor-view';
import { MappingEditorView } from '../[id]/entities/[entityType]/mapping/components/mapping-editor-view';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/autocount/companies'),
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
  RequirePermission: ({ children }: { children: ReactNode }) => children,
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
// Recorded product differences: untouched by the slice, pinned elsewhere.
vi.mock('@/components/platform/autocount/sql-editor', () => ({
  SqlEditor: () => <div data-stub="sql-editor" />,
}));
vi.mock('@/components/platform/autocount/sql-schema-tree', () => ({
  SqlSchemaTree: () => <div data-stub="sql-schema-tree" />,
}));

const COMPANY: AutocountCompany = {
  id: 'c1',
  connectionId: 'conn-1',
  databaseName: 'AED_VSOFT',
  companyName: 'V Soft Trading',
  name: 'V Soft',
  isActive: true,
  sinkImpl: 'logging',
  sinkConnectionId: null,
  sorentoCompanyCode: null,
  createdAt: '2026-11-02T03:00:00Z',
  sourceKind: 'db',
  documentPrerequisites: [],
};
const COMPANY_2: AutocountCompany = {
  ...COMPANY,
  id: 'c2',
  databaseName: 'AED_OLD',
  companyName: '',
  name: 'Old Branch',
  isActive: false,
  createdAt: null,
};

function entity(entityType: string, over: Partial<AutocountEntityConfig> = {}): AutocountEntityConfig {
  return {
    id: entityType,
    entityType,
    syncMode: 'AUTO',
    sourceImpl: 'sql_db',
    recordCap: 200,
    initialLookbackDays: 30,
    enabled: true,
    lastSuccessAt: '2026-11-10T04:00:00Z',
    lastAttemptAt: '2026-11-10T04:00:00Z',
    watermarkAt: '2026-11-10T04:00:00Z',
    consecutiveFailures: 0,
    lastError: null,
    etlStatus: 'active',
    ...over,
  };
}
const ENTITIES = [entity('customer'), entity('product', { watermarkAt: null, lastSuccessAt: null })];
const DETAIL: AutocountCompanyDetail = { company: COMPANY, entities: ENTITIES };

vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    listCompanies: vi.fn(async () => ({ data: [COMPANY, COMPANY_2], total: 2, page: 0 })),
    getCompany: vi.fn(async () => DETAIL),
    listRuns: vi.fn(async () => ({ data: [], total: 0, page: 0 })),
    listDocFeeds: vi.fn(async () => []),
  },
}));
vi.mock('@/hooks/use-autocount-company', () => ({
  useAutocountCompany: () => ({ detail: DETAIL, isLoading: false, notFound: false, reload: vi.fn() }),
}));

const sources: UseAutocountSourceConnectionsResult = {
  api: { options: [{ label: 'AutoCount HQ', value: 'conn-api-1' }], hasAny: true, allBound: false, isLoading: false },
  db: { options: [{ label: 'SQL HQ · AED_HQ', value: 'conn-sql-1' }], hasAny: true, allBound: false, isLoading: false },
  isLoading: false,
  defaultKind: 'api',
  apiConnectionsById: {
    'conn-api-1': { id: 'conn-api-1', name: 'AutoCount HQ', baseUrl: 'https://api.example', auth: 'basic' },
  },
};
vi.mock('@/hooks/use-autocount-connections', () => ({
  useAutocountSourceConnections: () => sources,
}));

const taskBox = vi.hoisted(() => ({ current: null as unknown }));
vi.mock('@/hooks/use-autocount-etl', () => ({
  useLineFetcher: () => ({ fetchLines: vi.fn().mockResolvedValue([]) }),
  useAutocountEtlTask: () => ({
    task: taskBox.current,
    isLoading: false,
    notFound: false,
    saveError: null,
    fieldErrors: {},
    isSaving: false,
    save: vi.fn(),
    apply: vi.fn(),
    reload: vi.fn(),
  }),
  useAutocountSqlConnections: () => ({
    connections: [{ id: 'conn-1', name: 'SQL HQ', database: 'AED_VSOFT' }],
    isLoading: false,
    error: null,
  }),
  useAutocountApiConnections: () => ({ connections: [], isLoading: false, error: null }),
  useAutocountSqlSchema: () => ({ schema: null, isLoading: false, error: null, refresh: vi.fn() }),
  useEtlTaskLifecycle: () => ({
    busy: null,
    error: null,
    activate: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    runNow: vi.fn(),
    clearError: vi.fn(),
  }),
  useEtlTaskPreview: () => ({ state: { status: 'idle' }, run: vi.fn(), reset: vi.fn() }),
  useSqlPreview: () => ({ state: { status: 'idle' }, run: vi.fn(), reset: vi.fn() }),
  useHttpPreview: () => ({ state: { status: 'idle' }, run: vi.fn(), fieldErrors: {}, reset: vi.fn() }),
}));
vi.mock('@/hooks/use-autocount-pull', () => ({
  usePreviewColumnsMap: () => ({ probe: vi.fn(), state: { status: 'idle' }, reset: vi.fn() }),
  useSetDeliveryMode: () => ({ save: vi.fn(), error: null, fieldErrors: {} }),
}));

const mappingBox = vi.hoisted(() => ({ view: null as AutocountMappingView | null }));
vi.mock('@/hooks/use-autocount-mapping', () => ({
  useAutocountMappingPresets: () => ({ presets: [], isLoading: false }),
  useAutocountMapping: () => ({
    view: mappingBox.view,
    isLoading: false,
    notFound: false,
    saveError: null,
    isSaving: false,
    save: vi.fn(),
    testFormula: vi.fn(),
    simulate: vi.fn(),
    applyView: vi.fn(),
    reload: vi.fn(),
  }),
}));

function task(over: Partial<AutocountEtlTask> = {}): AutocountEtlTask {
  return {
    companyId: 'c1',
    entityType: 'customer',
    etlStatus: 'active',
    activatedAt: '2026-11-05T03:00:00Z',
    sourceConfig: {
      connectionId: 'conn-1',
      query: 'SELECT AccNo, CompanyName FROM dbo.Debtor',
      lineQuery: null,
      keyColumns: ['AccNo'],
      watermarkColumn: null,
      comparedColumns: [],
      fromDate: null,
      docDateColumn: null,
      filterFormula: null,
      incrementalMinutes: 5,
      reconcileMode: 'dailyAt',
      reconcileHours: null,
      reconcileAt: '02:00',
    },
    resultColumns: ['AccNo', 'CompanyName'],
    lastPreviewAt: '2026-11-05T02:00:00Z',
    lastPreviewFailedCount: 0,
    lastRunAt: '2026-11-10T04:00:00Z',
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: '2026-11-10T04:05:00Z',
    nextReconcileAt: '2026-11-11T02:00:00Z',
    ...over,
  };
}

/**
 * Also masks React 19's `_r_N_` ids, in order of first appearance, and the
 * tab panel's presence timing style (`animation-duration: 0s` or empty,
 * whichever frame the snapshot lands on).
 */
function stable(root: Element): string {
  const seen = new Map<string, string>();
  return parityHtml(root)
    .replace(/ style="(animation-duration: 0s;)?"/g, '')
    .replace(/_r_[0-9a-z]+_/g, (id) => {
    let name = seen.get(id);
    if (!name) {
      name = `_rid${seen.size}_`;
      seen.set(id, name);
    }
    return name;
  });
}

beforeAll(async () => {
  mappingBox.view = await mockAutocountService.getMapping('company-db', 'product');
});

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  taskBox.current = task();
});

describe('parity (switch off): companies list and Connect company', () => {
  it('companies list with rows and Connect company', async () => {
    const { container } = render(
      <SettingsProvider>
        <AutocountCompaniesPage />
      </SettingsProvider>,
    );
    await screen.findByText('Old Branch');
    expect(stable(container)).toMatchSnapshot();
  });

  it('Connect company, API source', () => {
    const { container } = render(<ConnectCompanyView />, { wrapper: SettingsProvider });
    expect(stable(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): company record', () => {
  it('Overview at rest', async () => {
    const { container } = render(<AutocountCompanyDetailView companyId="c1" />, { wrapper: SettingsProvider });
    await screen.findByText('V Soft Trading');
    expect(stable(container)).toMatchSnapshot();
  });

  it('Overview while editing', async () => {
    const user = userEvent.setup();
    const { container } = render(<AutocountCompanyDetailView companyId="c1" />, { wrapper: SettingsProvider });
    await user.click(await screen.findByRole('button', { name: /^Edit/ }));
    await screen.findByRole('button', { name: /^Cancel/ });
    expect(stable(container)).toMatchSnapshot();
  });

  it('Entities tab', async () => {
    const user = userEvent.setup();
    const { container } = render(<AutocountCompanyDetailView companyId="c1" />, { wrapper: SettingsProvider });
    await user.click(await screen.findByRole('tab', { name: /Entities/ }));
    await screen.findByText('Nothing synced yet');
    expect(stable(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): task editor', () => {
  it.each(['active', 'paused', 'draft'] as const)('%s task at rest, Source tab', async (status) => {
    taskBox.current = task({ etlStatus: status });
    const { container } = render(<TaskEditorView companyId="c1" entityType="customer" />, {
      wrapper: SettingsProvider,
    });
    await screen.findByRole('tab', { name: /Review & Activate/ });
    expect(stable(container)).toMatchSnapshot();
  });

  it('active task while editing', async () => {
    const user = userEvent.setup();
    const { container } = render(<TaskEditorView companyId="c1" entityType="customer" />, {
      wrapper: SettingsProvider,
    });
    await user.click(await screen.findByRole('button', { name: /^Edit/ }));
    await screen.findByRole('button', { name: /^Cancel/ });
    expect(stable(container)).toMatchSnapshot();
  });

  it.each(['active', 'paused'] as const)('%s task, Review & Activate tab', async (status) => {
    const user = userEvent.setup();
    taskBox.current = task({ etlStatus: status });
    const { container } = render(<TaskEditorView companyId="c1" entityType="customer" />, {
      wrapper: SettingsProvider,
    });
    await user.click(await screen.findByRole('tab', { name: /Review & Activate/ }));
    await waitFor(() => expect(screen.getByTestId(status === 'active' ? 'etl-run-now' : 'etl-resume')).toBeTruthy());
    expect(stable(container)).toMatchSnapshot();
  });

  it('task with an open incident', async () => {
    taskBox.current = task({
      openIncident: {
        id: 'inc-1',
        openedAt: '2026-11-09T01:00:00Z',
        firstFailureAt: '2026-11-09T01:00:00Z',
        failedRuns: 3,
        lastError: 'Connection refused',
      },
    } as Partial<AutocountEtlTask>);
    const { container } = render(<TaskEditorView companyId="c1" entityType="customer" />, {
      wrapper: SettingsProvider,
    });
    await screen.findByTestId('task-incident-banner');
    expect(stable(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): field mapping editor', () => {
  it('at rest and while editing', async () => {
    const user = userEvent.setup();
    const { container } = render(<MappingEditorView companyId="company-db" entityType="product" />, {
      wrapper: SettingsProvider,
    });
    await screen.findByRole('tab', { name: /Mapping/ });
    expect(stable(container)).toMatchSnapshot();
    await user.click(await screen.findByRole('button', { name: /^Edit/ }));
    await screen.findByRole('button', { name: /^Cancel/ });
    expect(stable(container)).toMatchSnapshot();
  });
});
