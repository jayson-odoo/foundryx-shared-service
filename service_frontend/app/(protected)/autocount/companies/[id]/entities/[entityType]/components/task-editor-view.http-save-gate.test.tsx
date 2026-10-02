import { act, fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountCompanyDetail, AutocountEtlTask } from '@/types/autocount';
import { TaskEditorView } from './task-editor-view';
import { stubAuthFetch } from './task-editor-view.test-helpers';

stubAuthFetch();

/**
 * sprint-5/08 S5 (AC-08-20) - the Source tab's API branch withholds Save
 * until a Test succeeded for the CURRENT connectionId/path pair, the SAME
 * "Test a query first" rule the SQL branch's server enforces (422 today),
 * mirrored here client-side so the operator never hits it. The tracking
 * lives in `TaskEditorView` (it owns `saveDisabled` on the `ResourceForm`
 * config) - `SourceTab` only reports a successful Test upward via
 * `onHttpPreviewSuccess`.
 */
function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true }),
}));

/** A task ALREADY configured (path/connection/keys saved) but NEVER
 * previewed this session or ever (`resultColumns: []`) - the state an
 * operator lands in right after "Add entity" seeds the preset and they
 * start editing. */
function unpreviewedHttpTask(): AutocountEtlTask {
  return {
    companyId: 'company-http',
    entityType: 'product',
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
      path: '/itembypage',
      keyFields: ['ItemCode'],
      watermarkField: 'LastModified',
      comparedFields: [],
      distinctOf: null,
    },
    resultColumns: [],
    lastPreviewAt: null,
    lastPreviewFailedCount: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
  };
}

/** A DB (SQL) task, saved and query-configured - the save gate must never
 * touch this branch (AC-08-20's "unaffected on the Database branch"). */
function sqlTask(): AutocountEtlTask {
  return {
    companyId: 'company-sql',
    entityType: 'customer',
    etlStatus: 'draft',
    activatedAt: null,
    sourceConfig: {
      connectionId: 'conn-sql-1',
      query: 'SELECT * FROM dbo.Debtor',
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
    lastPreviewAt: null,
    lastPreviewFailedCount: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
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

function dbCompanyDetail(): AutocountCompanyDetail {
  return {
    company: {
      id: 'company-sql',
      connectionId: 'conn-sql-1',
      databaseName: 'AED_2024',
      companyName: 'AED',
      name: 'AED',
      isActive: true,
      sinkImpl: 'logging',
      sinkConnectionId: null,
      sorentoCompanyCode: null,
      createdAt: null,
      sourceKind: 'db',
      documentPrerequisites: [],
    },
    entities: [],
  };
}

const detailBox = vi.hoisted(() => ({ current: null as unknown }));
const taskBox = vi.hoisted(() => ({ current: null as unknown }));
const httpRunSpy = vi.hoisted(() => vi.fn());

vi.mock('@/hooks/use-autocount-company', () => ({
  useAutocountCompany: () => ({
    detail: detailBox.current,
    isLoading: false,
    notFound: false,
    reload: vi.fn(),
  }),
}));

vi.mock('@/hooks/use-autocount-etl', () => ({
  useLineFetcher: () => ({ fetchLines: vi.fn().mockResolvedValue([]) }),
  useAutocountEtlTask: () => ({
    task: taskBox.current,
    isLoading: false,
    notFound: false,
    saveError: null,
    fieldErrors: {},
    isSaving: false,
    save: vi.fn().mockResolvedValue(true),
    apply: vi.fn(),
    reload: vi.fn(),
  }),
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
  useHttpPreview: () => ({ state: { status: 'idle' }, run: httpRunSpy, fieldErrors: {}, reset: vi.fn() }),
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

function editButton() {
  return screen.getByRole('button', { name: /^Edit$/ });
}
function saveButton() {
  return screen.getByRole('button', { name: /^Save/i });
}

beforeEach(() => {
  httpRunSpy.mockReset();
  detailBox.current = httpCompanyDetail();
  taskBox.current = unpreviewedHttpTask();
});

describe('TaskEditorView - Source tab API branch save gate (sprint-5/08, AC-08-20)', () => {
  it('Save is disabled before any Test has proved the current path/connection', () => {
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    fireEvent.click(editButton());
    expect(saveButton()).toBeDisabled();
  });

  it('Save enables once Test succeeds for the current path/connection', async () => {
    httpRunSpy.mockResolvedValue(true);
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    fireEvent.click(editButton());
    expect(saveButton()).toBeDisabled();

    await act(async () => {
      fireEvent.click(screen.getByTestId('http-test-path'));
      await Promise.resolve();
    });

    expect(saveButton()).toBeEnabled();
  });

  it('Save disables again after editing the path, even though it just passed Test', async () => {
    httpRunSpy.mockResolvedValue(true);
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    fireEvent.click(editButton());

    await act(async () => {
      fireEvent.click(screen.getByTestId('http-test-path'));
      await Promise.resolve();
    });
    expect(saveButton()).toBeEnabled();

    fireEvent.change(screen.getByLabelText('Endpoint path'), {
      target: { value: '/itembypage2' },
    });
    expect(saveButton()).toBeDisabled();
  });

  it('a FAILED Test never enables Save', async () => {
    httpRunSpy.mockResolvedValue(false);
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    fireEvent.click(editButton());

    await act(async () => {
      fireEvent.click(screen.getByTestId('http-test-path'));
      await Promise.resolve();
    });

    expect(saveButton()).toBeDisabled();
  });
});

describe('TaskEditorView - Save gate is unaffected on the Database branch (AC-08-20)', () => {
  it('a SQL task with no HTTP preview at all keeps Save enabled once dirtied', () => {
    detailBox.current = dbCompanyDetail();
    taskBox.current = sqlTask();
    render(<TaskEditorView companyId="company-sql" entityType="customer" />);
    fireEvent.click(editButton());
    // The SQL branch's own Save button is never gated by `httpPreviewValid`
    // (`derivedImpl` reads `sql_db` here, so `saveDisabled` is always false).
    expect(saveButton()).toBeEnabled();
    expect(httpRunSpy).not.toHaveBeenCalled();
  });
});
