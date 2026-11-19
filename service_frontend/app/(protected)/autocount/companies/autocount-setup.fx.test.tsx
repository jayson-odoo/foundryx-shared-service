/**
 * The AutoCount setup pages with the Foundryx UIUX switch on (slice
 * W5-AC-SETUP).
 *
 * - Every write the pages make (connect a company, save a push target, sync
 *   now, re-fetch history, save a task with its SQL, run now, pause, resume,
 *   save a field mapping) is sent exactly as with the switch off: requests are
 *   captured at `apiFetch` under the real service (same path, method and
 *   body; the saved SQL is byte-identical).
 * - An active task's red action is Run now, a paused one's is Resume; a draft
 *   task has none at rest; Pause, Edit and Reset to preset are icon actions.
 * - Done toasts say what, for whom and by whom, with no Undo (none of these
 *   writes has an API that reverses it).
 * - A password or token that rides along on a connection payload is never
 *   shown, logged, stored or put in a toast, in either look.
 *
 * Nothing here reaches a real AutoCount server: the vendor, SQL and Sorento
 * calls are stubbed at `apiFetch`. Switch off is pinned by
 * `__parity__/companies.parity.test.tsx`.
 */
import type { ReactNode } from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import type {
  AutocountCompany,
  AutocountCompanyDetail,
  AutocountEntityConfig,
  AutocountEtlTask,
  AutocountMappingView,
} from '@/types/autocount';
import type { UseAutocountSourceConnectionsResult } from '@/hooks/use-autocount-connections';
import { mockAutocountService } from '@/services/autocount-service.mock';
import { ConnectCompanyView } from './components/connect-company-view';
import { AutocountCompanyDetailView } from './components/company-detail-view';
import { TaskEditorView } from './[id]/entities/[entityType]/components/task-editor-view';
import { MappingEditorView } from './[id]/entities/[entityType]/mapping/components/mapping-editor-view';
import { useAutocountCompaniesListConfig } from './components/use-companies-list-config';

const SECRET = 'S3cr3t-T0ken-9f2a';

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

const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push, prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/autocount/companies'),
  useParams: vi.fn(() => ({})),
}));
vi.mock('next-themes', () => ({ useTheme: () => ({ theme: 'light', setTheme: vi.fn() }) }));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Nurul Huda', permissions: [] } },
    status: 'authenticated',
    update: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
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

// The SQL editor is a recorded product difference; a plain textarea stands in
// so a test can type the exact SQL the task saves.
vi.mock('@/components/platform/autocount/sql-editor', () => ({
  SqlEditor: ({
    value,
    onChange,
    editing,
    ariaLabel,
  }: {
    value: string;
    onChange: (v: string) => void;
    editing: boolean;
    ariaLabel?: string;
  }) => (
    <textarea
      aria-label={ariaLabel}
      value={value}
      readOnly={!editing}
      onChange={(e) => onChange(e.target.value)}
    />
  ),
}));
vi.mock('@/components/platform/autocount/sql-schema-tree', () => ({
  SqlSchemaTree: () => <div data-stub="sql-schema-tree" />,
}));

// Capture the config each real shell is handed, to run its actions directly.
const seen = vi.hoisted(() => ({
  forms: [] as unknown[],
  lists: {} as Record<string, unknown>,
}));
vi.mock('@/components/platform/resource-form', async (orig) => {
  const real = (await orig()) as Record<string, unknown> & {
    ResourceForm: (p: { config: unknown }) => ReactNode;
  };
  return {
    ...real,
    ResourceForm: (p: { config: unknown }) => {
      seen.forms.push(p.config);
      return real.ResourceForm(p);
    },
  };
});
vi.mock('@/components/platform/resource-list', async (orig) => {
  const real = (await orig()) as Record<string, unknown> & {
    ResourceList: (p: { config: { viewKey: string } }) => ReactNode;
  };
  return {
    ...real,
    ResourceList: (p: { config: { viewKey: string } }) => {
      seen.lists[p.config.viewKey] = p.config;
      return real.ResourceList(p);
    },
  };
});

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
const ENTITY: AutocountEntityConfig = {
  id: 'customer',
  entityType: 'customer',
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
};
const DETAIL: AutocountCompanyDetail = { company: COMPANY, entities: [ENTITY] };

function task(status: AutocountEtlTask['etlStatus'] = 'active'): AutocountEtlTask {
  return {
    companyId: 'c1',
    entityType: 'customer',
    etlStatus: status,
    activatedAt: '2026-11-05T03:00:00Z',
    sourceConfig: {
      connectionId: 'conn-1',
      query: 'SELECT AccNo FROM dbo.Debtor',
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
    resultColumns: ['AccNo'],
    lastPreviewAt: '2026-11-05T02:00:00Z',
    lastPreviewFailedCount: 0,
    lastRunAt: '2026-11-10T04:00:00Z',
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
  };
}

let taskStatus: AutocountEtlTask['etlStatus'] = 'active';
let mappingView: AutocountMappingView;

function route(path: string, init?: RequestInit): unknown {
  const method = init?.method ?? 'GET';
  if (method === 'GET') {
    if (path === '/autocount/companies/c1' || path === '/autocount/companies/company-db') return DETAIL;
    if (path.endsWith('/etl-task')) return task(taskStatus);
    if (path === '/autocount/sql/connections') {
      // A payload that carries a credential the pages must never surface.
      return [{ id: 'conn-1', name: 'SQL HQ', database: 'AED_VSOFT', dialect: 'mssql', password: SECRET, token: SECRET }];
    }
    if (path.endsWith('/mapping')) return mappingView;
    if (path.includes('/schema')) return { dialect: 'mssql', tables: [] };
    if (path.startsWith('/autocount/companies?')) return { data: [COMPANY], total: 1, page: 0 };
    return [];
  }
  if (path === '/autocount/companies' && method === 'POST') {
    return { ...COMPANY, id: 'c-new', name: JSON.parse(String(init?.body)).name };
  }
  if (path.endsWith('/sink-target')) return { ...COMPANY, ...JSON.parse(String(init?.body)) };
  if (path.endsWith('/sync')) return { id: 'j1', status: 'success', result: { fetched: 3, failed: 0 }, error: null };
  if (path.endsWith('/refetch')) return ENTITY;
  if (path.endsWith('/etl-task') && method === 'PUT') {
    const body = JSON.parse(String(init?.body));
    return { ...task('active'), sourceConfig: body.sourceConfig ?? task().sourceConfig };
  }
  if (path.endsWith('/pause')) return task('paused');
  if (path.endsWith('/resume')) return task('active');
  if (path.endsWith('/run')) return { runId: 'run-1', task: task('active') };
  if (path.endsWith('/mapping') && method === 'PUT') return mappingView;
  return {};
}

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
  return net.apiFetch.mock.calls
    .filter(([, init]) => init && (init as RequestInit).method && (init as RequestInit).method !== 'GET')
    .map(([path, init]) => ({
      path,
      method: (init as RequestInit).method,
      body: (init as RequestInit).body ?? null,
    }));
}

function lastForm<T>() {
  return seen.forms[seen.forms.length - 1] as ResourceFormConfig<T>;
}

const sources: UseAutocountSourceConnectionsResult = {
  api: {
    options: [{ label: 'AutoCount HQ', value: 'conn-api-1' }],
    hasAny: true,
    allBound: false,
    isLoading: false,
  },
  db: { options: [], hasAny: false, allBound: false, isLoading: false },
  isLoading: false,
  defaultKind: 'api',
  apiConnectionsById: {
    'conn-api-1': {
      id: 'conn-api-1',
      name: 'AutoCount HQ',
      baseUrl: 'https://api.example',
      auth: 'basic',
      // A credential riding along on the payload; never shown.
      password: SECRET,
    } as never,
  },
};
vi.mock('@/hooks/use-autocount-connections', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return { ...real, useAutocountSourceConnections: () => sources };
});

beforeEach(async () => {
  push.mockReset();
  net.apiFetch.mockReset();
  net.apiFetch.mockImplementation(async (path: string, init?: RequestInit) => route(path, init));
  Object.values(toasts).forEach((fn) => fn.mockReset());
  seen.forms = [];
  seen.lists = {};
  taskStatus = 'active';
  mappingView = await mockAutocountService.getMapping('company-db', 'product');
  window.localStorage.clear();
  window.sessionStorage.clear();
});
afterEach(() => resetPageActionsForTests());

const LOOKS = [false, true] as const;

describe('Connect company: the same request in both looks', () => {
  async function create(on: boolean) {
    const user = userEvent.setup();
    render(<ConnectCompanyView />, { wrapper: look(on) });
    await user.click(screen.getByRole('combobox', { name: 'AutoCount connection' }));
    await user.click(await screen.findByRole('option', { name: /AutoCount HQ/ }));
    await user.type(screen.getByRole('textbox', { name: 'Label' }), '  V Soft  ');
    await user.click(screen.getByRole('button', { name: /^Create/ }));
    await waitFor(() => expect(writes()).toHaveLength(1));
  }

  it('create sends the same body, then says what, for whom and by whom', async () => {
    await create(false);
    const off = writes();
    expect(off[0]).toEqual({
      path: '/autocount/companies',
      method: 'POST',
      body: JSON.stringify({ connectionId: 'conn-api-1', name: 'V Soft' }),
    });
    expect(toasts.success).toHaveBeenCalledWith('Connected AED_VSOFT.');
    expect(toasts.fxDone).not.toHaveBeenCalled();
    document.body.innerHTML = '';
    net.apiFetch.mockClear();
    await create(true);
    expect(writes()).toEqual(off);
    await waitFor(() =>
      expect(toasts.fxDone).toHaveBeenCalledWith({
        what: 'V Soft connected',
        forWhom: 'AED_VSOFT',
        byWhom: 'Nurul Huda',
      }),
    );
    expect(toasts.fxDone.mock.calls[0][0].undo).toBeUndefined();
  });

  it('on: the form names its red action and its discard name', async () => {
    render(<ConnectCompanyView />, { wrapper: look(true) });
    expect(lastForm<AutocountCompany>().fx).toEqual({
      mainActionId: 'save',
      discardName: 'the new company connection',
    });
  });
});

describe('Company record: the same writes in both looks', () => {
  async function sinkSave(on: boolean) {
    const user = userEvent.setup();
    render(<AutocountCompanyDetailView companyId="c1" />, { wrapper: look(on) });
    await user.click(await screen.findByRole('button', { name: /^Edit/ }));
    await user.click(await screen.findByRole('button', { name: /^Save/ }));
    await waitFor(() => expect(writes()).toHaveLength(1));
  }

  it('push target save', async () => {
    await sinkSave(false);
    const off = writes();
    expect(off[0]).toEqual({
      path: '/autocount/companies/c1/sink-target',
      method: 'PATCH',
      body: JSON.stringify({ sinkImpl: 'logging', sinkConnectionId: null, sorentoCompanyCode: null }),
    });
    expect(toasts.success).toHaveBeenCalledWith('Push target updated.');
    document.body.innerHTML = '';
    net.apiFetch.mockClear();
    await sinkSave(true);
    expect(writes()).toEqual(off);
    expect(toasts.fxDone).toHaveBeenCalledWith({
      what: 'Push target updated',
      forWhom: 'V Soft',
      byWhom: 'Nurul Huda',
    });
  });

  async function entityActions(on: boolean) {
    const user = userEvent.setup();
    render(<AutocountCompanyDetailView companyId="c1" />, { wrapper: look(on) });
    await user.click(await screen.findByRole('tab', { name: /Entities/ }));
    await waitFor(() => expect(seen.lists['autocount.entities.list']).toBeTruthy());
    const list = seen.lists['autocount.entities.list'] as ResourceListConfig<AutocountEntityConfig>;
    const runtime = { reload: vi.fn() };
    for (const id of ['sync-now', 'refetch-history']) {
      const action = list.actions.find((a) => a.id === id)!;
      await act(async () => {
        await (action as { run: (rows: AutocountEntityConfig[], rt: typeof runtime) => unknown }).run([ENTITY], runtime);
      });
    }
  }

  it('sync now and re-fetch history', async () => {
    await entityActions(false);
    const off = writes();
    expect(off.map((w) => `${w.method} ${w.path}`)).toEqual([
      'POST /autocount/companies/c1/sync',
      'POST /autocount/companies/c1/entities/customer/refetch',
    ]);
    expect(off[0].body).toBe(JSON.stringify({ entityType: 'customer' }));
    document.body.innerHTML = '';
    net.apiFetch.mockClear();
    await entityActions(true);
    expect(writes()).toEqual(off);
    expect(toasts.fxDone).toHaveBeenCalledWith({
      what: 'Customer history re-fetch scheduled',
      forWhom: 'V Soft',
      byWhom: 'Nurul Huda',
    });
  });
});

describe('Task editor: the same writes in both looks', () => {
  async function lifecycle(on: boolean, status: AutocountEtlTask['etlStatus'], ids: string[]) {
    taskStatus = status;
    render(<TaskEditorView companyId="c1" entityType="customer" />, { wrapper: look(on) });
    await screen.findByRole('tab', { name: /Review & Activate/ });
    await waitFor(() => expect(lastForm<AutocountEtlTask>()?.actionRows).toHaveLength(1));
    const config = lastForm<AutocountEtlTask>();
    for (const id of ids) {
      const action = config.actions.find((a) => a.id === id)!;
      await act(async () => {
        await (action as { run: (rows: AutocountEtlTask[], rt: { reload: () => void }) => unknown }).run(
          config.actionRows,
          { reload: vi.fn() },
        );
      });
    }
  }

  it('run now and pause (active task)', async () => {
    await lifecycle(false, 'active', ['run-now', 'pause']);
    const off = writes();
    expect(off.map((w) => `${w.method} ${w.path.replace('/autocount/companies/c1/entities/customer', '')}`)).toEqual([
      'POST /etl-task/run',
      'POST /etl-task/pause',
    ]);
    expect(toasts.success).toHaveBeenCalledWith('Run finished.');
    expect(toasts.success).toHaveBeenCalledWith('Task paused.');
    document.body.innerHTML = '';
    net.apiFetch.mockClear();
    await lifecycle(true, 'active', ['run-now', 'pause']);
    expect(writes()).toEqual(off);
    expect(toasts.fxDone).toHaveBeenCalledWith({
      what: 'Customer run finished',
      forWhom: 'V Soft',
      byWhom: 'Nurul Huda',
    });
    expect(toasts.fxDone).toHaveBeenCalledWith({
      what: 'Customer task paused',
      forWhom: 'V Soft',
      byWhom: 'Nurul Huda',
    });
    for (const [input] of toasts.fxDone.mock.calls) expect(input.undo).toBeUndefined();
  });

  it('resume (paused task)', async () => {
    await lifecycle(false, 'paused', ['resume']);
    const off = writes();
    expect(off).toHaveLength(1);
    expect(off[0].method).toBe('POST');
    expect(off[0].path).toBe('/autocount/companies/c1/entities/customer/etl-task/resume');
    document.body.innerHTML = '';
    net.apiFetch.mockClear();
    await lifecycle(true, 'paused', ['resume']);
    expect(writes()).toEqual(off);
    expect(toasts.fxDone).toHaveBeenCalledWith({
      what: 'Customer task resumed',
      forWhom: 'V Soft',
      byWhom: 'Nurul Huda',
    });
  });

  async function saveSql(on: boolean, sql: string) {
    const user = userEvent.setup();
    render(<TaskEditorView companyId="c1" entityType="customer" />, { wrapper: look(on) });
    await user.click(await screen.findByRole('button', { name: /^Edit/ }));
    const box = await screen.findByRole('textbox', { name: 'Query' });
    await user.clear(box);
    // `type` would mangle braces and brackets; paste the exact text.
    await user.click(box);
    await user.paste(sql);
    await user.click(await screen.findByRole('button', { name: /^Save/ }));
    await waitFor(() => expect(writes().length).toBeGreaterThan(0));
  }

  it('save sends the SQL byte for byte as the same trimmed text', async () => {
    const sql = "  SELECT AccNo,\n\t[Company Name]  AS Name\n  FROM dbo.Debtor\n WHERE Note = 'a  b' -- keep\n  ";
    await saveSql(false, sql);
    const off = writes();
    expect(off).toHaveLength(1);
    expect(off[0].method).toBe('PUT');
    expect(JSON.parse(String(off[0].body)).sourceConfig.query).toBe(sql.trim());
    expect(toasts.success).toHaveBeenCalledWith('Task saved.');
    document.body.innerHTML = '';
    net.apiFetch.mockClear();
    await saveSql(true, sql);
    expect(writes()).toEqual(off);
    expect(toasts.fxDone).toHaveBeenCalledWith({
      what: 'Customer task saved',
      forWhom: 'V Soft',
      byWhom: 'Nurul Huda',
    });
  });

  it.each([
    ['active', 'run-now'],
    ['paused', 'resume'],
    ['draft', undefined],
  ] as const)('on, %s task: red action is %s', async (status, main) => {
    taskStatus = status;
    render(<TaskEditorView companyId="c1" entityType="customer" />, { wrapper: look(true) });
    await screen.findByRole('tab', { name: /Review & Activate/ });
    await waitFor(() => expect(lastForm<AutocountEtlTask>()?.actionRows).toHaveLength(1));
    const fx = lastForm<AutocountEtlTask>().fx!;
    expect(fx.mainActionId).toBe(main);
    expect(fx.moreActionIds).toEqual(['reset-to-preset']);
    expect(fx.discardName).toBe('Customer task');
    if (main === 'run-now') expect(fx.fullLabel!([])).toBe('Run Customer sync now for V Soft');
    if (main === 'resume') expect(fx.fullLabel!([])).toBe('Resume Customer sync for V Soft');
  });

  it('on: Run now is the one red button and Pause an icon action beside it', async () => {
    render(<TaskEditorView companyId="c1" entityType="customer" />, { wrapper: look(true) });
    await screen.findByRole('tab', { name: /Review & Activate/ });
    expect(await screen.findByRole('button', { name: 'Run Customer sync now for V Soft' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Pause' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Edit' })).toBeTruthy();
  });

  it('off: the config carries no fx page choices that show', async () => {
    render(<TaskEditorView companyId="c1" entityType="customer" />, { wrapper: look(false) });
    await screen.findByRole('tab', { name: /Review & Activate/ });
    expect(screen.queryByRole('button', { name: 'Run Customer sync now for V Soft' })).toBeNull();
  });
});

describe('Field mapping: the same write in both looks', () => {
  async function save(on: boolean) {
    const user = userEvent.setup();
    render(<MappingEditorView companyId="company-db" entityType="product" />, { wrapper: look(on) });
    await user.click(await screen.findByRole('button', { name: /^Edit/ }));
    await user.click(await screen.findByRole('button', { name: /^Save/ }));
    await waitFor(() => expect(writes()).toHaveLength(1));
  }

  it('save', async () => {
    await save(false);
    const off = writes();
    expect(off[0].method).toBe('PUT');
    expect(off[0].path).toBe('/autocount/companies/company-db/entities/product/mapping');
    expect(toasts.success).toHaveBeenCalledWith('Field mapping saved.');
    document.body.innerHTML = '';
    net.apiFetch.mockClear();
    await save(true);
    expect(writes()).toEqual(off);
    expect(toasts.fxDone).toHaveBeenCalledWith(expect.objectContaining({ what: 'Product field mapping saved', byWhom: 'Nurul Huda' }));
  });
});

describe('a credential on a connection payload is never shown, logged, stored or toasted', () => {
  it.each(LOOKS)('look on=%s', async (on) => {
    const logs = [
      vi.spyOn(console, 'log').mockImplementation(() => {}),
      vi.spyOn(console, 'info').mockImplementation(() => {}),
      vi.spyOn(console, 'warn').mockImplementation(() => {}),
      vi.spyOn(console, 'error').mockImplementation(() => {}),
    ];
    const user = userEvent.setup();
    render(<ConnectCompanyView />, { wrapper: look(on) });
    await user.click(screen.getByRole('combobox', { name: 'AutoCount connection' }));
    await user.click(await screen.findByRole('option', { name: /AutoCount HQ/ }));
    await user.click(screen.getByRole('button', { name: /^Create/ }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    document.body.innerHTML = '';
    render(<TaskEditorView companyId="c1" entityType="customer" />, { wrapper: look(on) });
    await user.click(await screen.findByRole('button', { name: /^Edit/ }));
    await screen.findByRole('textbox', { name: 'Query' });

    expect(document.body.innerHTML).not.toContain(SECRET);
    expect(JSON.stringify(Array.from(Object.entries(window.localStorage)))).not.toContain(SECRET);
    expect(JSON.stringify(Array.from(Object.entries(window.sessionStorage)))).not.toContain(SECRET);
    expect(JSON.stringify(writes())).not.toContain(SECRET);
    expect(JSON.stringify([toasts.fxDone.mock.calls, toasts.success.mock.calls, toasts.error.mock.calls])).not.toContain(SECRET);
    for (const spy of logs) expect(JSON.stringify(spy.mock.calls)).not.toContain(SECRET);
    logs.forEach((s) => s.mockRestore());
  });
});

describe('the companies list under the switch', () => {
  it('keeps Connect company as the red action with the status column and card lines', async () => {
    const { renderHook } = await import('@testing-library/react');
    const { result } = renderHook(() => useAutocountCompaniesListConfig(), { wrapper: look(true) });
    expect(result.current.createLabel).toBe('Connect company');
    expect(result.current.fx).toMatchObject({
      noun: 'companies',
      columnKind: { status: 'status' },
      copyable: ['databaseName'],
    });
    expect(result.current.fx?.mainActionId).toBeUndefined();
  });
});
