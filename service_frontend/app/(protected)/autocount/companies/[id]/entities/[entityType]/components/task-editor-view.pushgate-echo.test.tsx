import { fireEvent, render as rtlRender, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountCompanyDetail, AutocountEtlTask } from '@/types/autocount';
import { TaskEditorView } from './task-editor-view';
import { stubAuthFetch } from './task-editor-view.test-helpers';

stubAuthFetch();

/**
 * sprint-5/13 owner repro (2026-09-26, real backend) - a saved-pull stock
 * task whose GET carried a shut `pushGate` (`{reason: 'no_snapshot'}`)
 * offered the Push toggle again, selectable, right after the Source tab's
 * Test button completed. Root cause (fixed server-side,
 * `modules/autocount/preview_job.py::_task_echo_model`): the Test
 * completion's OWN task echo omitted `pushGate` entirely, which the FE
 * (correctly) reads as "gate open". `mergeTaskEcho` (`lib/autocount-etl.ts`)
 * is the frontend's own belt-and-braces guard against exactly this shape of
 * echo, wired into `TaskEditorView.onHttpPreviewSuccess`
 * (`task-editor-view.tsx`) - this suite drives the REAL hooks (only the
 * service layer is mocked, mirroring `task-editor-view.http-test-refresh.
 * test.tsx`'s own rig) so the regression is caught at the ACTUAL seam, not
 * just at `mergeTaskEcho`'s own unit level (`lib/autocount-etl.test.ts`).
 */
function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true }),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ status: 'authenticated', data: { user: { id: 'u1', timezone: 'UTC' } } }),
  SessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

const getEtlTask = vi.fn();
const updateEtlTask = vi.fn();
const startPreviewJob = vi.fn();
const getPreviewJob = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    getEtlTask: (...args: unknown[]) => getEtlTask(...args),
    updateEtlTask: (...args: unknown[]) => updateEtlTask(...args),
    startPreviewJob: (...args: unknown[]) => startPreviewJob(...args),
    getPreviewJob: (...args: unknown[]) => getPreviewJob(...args),
  },
}));

function mockHttpPreviewDone(task: AutocountEtlTask) {
  startPreviewJob.mockResolvedValue({ jobId: 'preview-job-1', status: 'queued' });
  getPreviewJob.mockResolvedValue({
    id: 'preview-job-1',
    scope: 'sample',
    status: 'done',
    progress: null,
    result: {
      scope: 'sample',
      preview: {
        envelope: 'paged', totalCount: 1,
        columns: [{ name: 'ItemCode', sample: 'A1' }],
        rows: [{ ItemCode: 'A1' }], durationMs: 20,
        task,
      },
    },
    error: null,
    taskError: null,
    createdAt: null,
  });
}

vi.mock('@/hooks/use-autocount-etl', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/use-autocount-etl')>();
  return {
    // `useAutocountEtlTask`/`useHttpPreview` stay REAL - the exact seam this
    // bug lives in (`task-editor-view.tsx`'s `onHttpPreviewSuccess`).
    ...actual,
    useLineFetcher: () => ({ fetchLines: vi.fn().mockResolvedValue([]) }),
    useAutocountSqlConnections: () => ({
      connections: [{ id: 'conn-sql-1', name: 'AutoCount DB', dialect: 'mssql', database: 'AED_2024' }],
      isLoading: false,
      error: null,
    }),
    useAutocountApiConnections: () => ({
      connections: [
        { id: 'conn-api-mocha', name: 'Mocha REST', baseUrl: 'https://hapi.sorento.cc.cd/api/db2', auth: 'none' as const },
      ],
      isLoading: false,
      error: null,
    }),
    useAutocountSqlSchema: () => ({ schema: null, isLoading: false, error: null, refresh: vi.fn() }),
    useEtlTaskLifecycle: () => ({
      busy: null, error: null, activate: vi.fn(), pause: vi.fn(), resume: vi.fn(), runNow: vi.fn(),
      clearError: vi.fn(),
    }),
    useEtlTaskPreview: () => ({ state: { status: 'idle' }, run: vi.fn(), reset: vi.fn() }),
    useSqlPreview: () => ({ state: { status: 'idle' }, run: vi.fn(), reset: vi.fn() }),
  };
});

vi.mock('@/hooks/use-autocount-pull', () => ({
  usePreviewColumnsMap: () => ({ columnsByKey: {}, loadingKeys: {}, errorsByKey: {}, run: vi.fn() }),
  useSetDeliveryMode: () => ({
    saving: false, error: null, fieldErrors: {}, save: vi.fn(), clearError: vi.fn(),
  }),
}));

vi.mock('@/hooks/use-autocount-mapping', () => ({
  useAutocountMappingPresets: () => ({ presets: [], isLoading: false }),
  useAutocountMapping: () => ({
    view: null,
    isLoading: false,
    notFound: false,
    saveError: null,
    isSaving: false,
    save: vi.fn(),
    reload: vi.fn(),
    testFormula: vi.fn(),
    simulate: vi.fn(),
  }),
}));

vi.mock('../../../../components/use-runs-list-config', () => ({
  useAutocountRunsListConfig: () => ({}),
}));

const detailBox = vi.hoisted(() => ({ current: null as unknown }));

vi.mock('@/hooks/use-autocount-company', () => ({
  useAutocountCompany: () => ({
    detail: detailBox.current,
    isLoading: false,
    notFound: false,
    reload: vi.fn(),
  }),
}));

/** A saved stock_balance HTTP task whose GATE IS SHUT (no ready snapshot) -
 * the owner's own repro state: saved `pull`, `pushGate: {reason:
 * 'no_snapshot'}`. */
function shutGateStockTask(overrides: Partial<AutocountEtlTask> = {}): AutocountEtlTask {
  return {
    companyId: 'company-http',
    entityType: 'stock_balance',
    etlStatus: 'draft',
    activatedAt: null,
    sourceImpl: 'autocount_http',
    sourceConfig: {
      connectionId: 'conn-api-mocha',
      query: '',
      lineQuery: null,
      keyColumns: [],
      watermarkColumn: null,
      comparedColumns: [],
      fromDate: null,
      docDateColumn: null,
      filterFormula: null,
      incrementalMinutes: 5,
      reconcileMode: 'dailyAt',
      reconcileHours: null,
      reconcileAt: '02:00',
      path: '/itembatchbalqtybypage',
      keyFields: [],
      watermarkField: null,
      comparedFields: [],
      distinctOf: null,
    },
    resultColumns: ['ItemCode', 'BalQty'],
    lastPreviewAt: '2026-09-25T00:00:00Z',
    lastPreviewFailedCount: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
    deliveryMode: 'pull',
    pushGate: { reason: 'no_snapshot' },
    ...overrides,
  };
}

function httpCompanyDetail(): AutocountCompanyDetail {
  return {
    company: {
      id: 'company-http',
      connectionId: 'conn-api-mocha',
      databaseName: 'MOCHA',
      companyName: 'Mocha Sdn Bhd',
      name: 'Mocha',
      isActive: true,
      sinkImpl: 'logging',
      sinkConnectionId: null,
      sorentoCompanyCode: null,
      createdAt: null,
      sourceKind: 'http',
      documentPrerequisites: [],
    },
    entities: [],
  };
}

function editButton() {
  return screen.getByRole('button', { name: /^Edit$/ });
}
function testButton() {
  return screen.getByTestId('http-test-path');
}
function scheduleTab() {
  return screen.getByRole('tab', { name: /Schedule/i });
}
function sourceTab() {
  return screen.getByRole('tab', { name: /Source/i });
}

beforeEach(() => {
  getEtlTask.mockReset();
  updateEtlTask.mockReset();
  startPreviewJob.mockReset();
  getPreviewJob.mockReset();
  detailBox.current = httpCompanyDetail();
  getEtlTask.mockResolvedValue(shutGateStockTask());
});

describe('TaskEditorView Schedule tab - a Test-completion echo never reopens an already-shut push gate (sprint-5/13 owner repro)', () => {
  it('Test completes with an echo carrying NO pushGate at all: Push stays hidden', async () => {
    const user = userEvent.setup();
    render(<TaskEditorView companyId="company-http" entityType="stock_balance" />);
    await screen.findByRole('tab', { name: /Source/i });
    fireEvent.click(editButton());

    // Before any Test: the initial GET's own shut gate hides Push.
    await user.click(scheduleTab());
    expect(screen.queryByTestId('etl-delivery-push')).not.toBeInTheDocument();
    expect(screen.getByTestId('etl-push-gate-warning')).toHaveTextContent(
      'Push needs a stock snapshot from the last 24 hours.',
    );

    // The exact shape of the live repro: the completed job's own task echo
    // carries every OTHER field but no `pushGate` key at all.
    const echoedTask = shutGateStockTask({ resultColumns: ['ItemCode', 'BalQty', 'Location'] });
    delete (echoedTask as { pushGate?: unknown }).pushGate;
    mockHttpPreviewDone(echoedTask);

    await user.click(sourceTab());
    fireEvent.click(testButton());
    await waitFor(() => expect(startPreviewJob).toHaveBeenCalled());

    // Same instance, only a tab switch - never a remount.
    await user.click(scheduleTab());
    expect(screen.queryByTestId('etl-delivery-push')).not.toBeInTheDocument();
    expect(screen.queryByTestId('etl-delivery-pull')).not.toBeInTheDocument();
    expect(screen.getByTestId('etl-push-gate-warning')).toHaveTextContent(
      'Push needs a stock snapshot from the last 24 hours.',
    );
  });

  it('an already-OPEN task (no previously-known shut gate) is unaffected by the merge - the toggle still renders normally', async () => {
    // The gate was NEVER shut this session (`pushGate: null` from the
    // initial GET, saved mode still `pull`) - `mergeTaskEcho` must stay a
    // no-op here; only a PREVIOUSLY-shut gate is ever preserved, never
    // invented from nothing for a task that was always open.
    getEtlTask.mockResolvedValue(shutGateStockTask({ pushGate: null }));
    const user = userEvent.setup();
    render(<TaskEditorView companyId="company-http" entityType="stock_balance" />);
    await screen.findByRole('tab', { name: /Source/i });
    fireEvent.click(editButton());

    await user.click(scheduleTab());
    expect(screen.getByTestId('etl-delivery-push')).toBeInTheDocument();

    const echoedTask = shutGateStockTask({ pushGate: null });
    delete (echoedTask as { pushGate?: unknown }).pushGate;
    mockHttpPreviewDone(echoedTask);

    await user.click(sourceTab());
    fireEvent.click(testButton());
    await waitFor(() => expect(startPreviewJob).toHaveBeenCalled());

    await user.click(scheduleTab());
    expect(screen.getByTestId('etl-delivery-push')).toBeInTheDocument();
    expect(screen.getByTestId('etl-delivery-pull')).toBeInTheDocument();
    expect(screen.queryByTestId('etl-push-gate-warning')).not.toBeInTheDocument();
  });
});
