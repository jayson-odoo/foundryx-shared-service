import { render as rtlRender, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountCompanyDetail, AutocountEtlTask } from '@/types/autocount';
import { TaskEditorView } from './task-editor-view';
import { stubAuthFetch } from './task-editor-view.test-helpers';

stubAuthFetch();

/**
 * fix/autocount-add-http-only-entity-on-db-company - `stock_balance` has no
 * `sql_db` variant (AC-10-39/D4), but the backend already accepts an
 * `autocount_http` task on ANY company kind (`_update_http_task` runs
 * before the "DB company reads only its own connection" rule, AC-08-13). A
 * `db` company's Add-entity picker now offers it (`autocount-meta.test.ts`);
 * this pins the task editor's OWN foolproof-UI half - the Source tab must
 * open pre-selected to API (never Database, which would be a guaranteed
 * dead end for this entity) and must never offer Database as a choice at
 * all, even though this company otherwise defaults every other entity to
 * Database (AC-08-18).
 */
function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true }),
}));

function unbornStockTask(): AutocountEtlTask {
  return {
    companyId: 'company-db',
    entityType: 'stock_balance',
    etlStatus: 'draft',
    activatedAt: null,
    sourceConfig: {
      connectionId: null,
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
    },
    resultColumns: [],
    lastPreviewAt: null,
    lastPreviewFailedCount: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
    deliveryMode: 'pull',
  };
}

function dbCompanyDetail(): AutocountCompanyDetail {
  return {
    company: {
      id: 'company-db',
      connectionId: 'conn-sql-1',
      databaseName: 'MOCHA',
      companyName: 'Mocha Sdn Bhd',
      name: 'Mocha',
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
    connections: [{ id: 'conn-sql-1', name: 'AutoCount DB', dialect: 'mssql', database: 'MOCHA' }],
    isLoading: false,
    error: null,
  }),
  useAutocountApiConnections: () => ({
    // A DB company's HTTP-only task keeps the FREE cross-tenant picker
    // (AC-08-13) - no locked connection, so at least one open connection
    // must exist for the Source tab to have anything to offer.
    connections: [
      { id: 'conn-open-1', name: 'Mocha REST', baseUrl: 'https://hapi.sorento.cc.cd/api/db2', auth: 'none' as const },
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
  useHttpPreview: () => ({ state: { status: 'idle' }, run: vi.fn(), fieldErrors: {}, reset: vi.fn() }),
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

beforeEach(() => {
  taskBox.current = unbornStockTask();
  detailBox.current = dbCompanyDetail();
});

describe('TaskEditorView - stock_balance on a DB company (fix/autocount-add-http-only-entity-on-db-company)', () => {
  it('opens with Source pre-selected to API, badged "Open API", never "Database"', async () => {
    render(<TaskEditorView companyId="company-db" entityType="stock_balance" />);
    await screen.findByRole('tab', { name: /Source/i });
    expect(screen.getByText('Open API')).toBeInTheDocument();
    expect(screen.queryByText('Database')).not.toBeInTheDocument();
    // Pre-filled from the stock_balance HTTP preset the same way an open
    // company's never-configured task is (AC-10-40).
    expect(screen.getByLabelText('Endpoint path')).toHaveValue('/itembatchbalqtybypage');
  });

  it('never offers Database as a Source choice, even though this IS a DB company', async () => {
    render(<TaskEditorView companyId="company-db" entityType="stock_balance" />);
    await screen.findByRole('tab', { name: /Source/i });
    expect(screen.queryByRole('radio', { name: 'Database' })).not.toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'API' })).toHaveAttribute('data-state', 'on');
  });
});
