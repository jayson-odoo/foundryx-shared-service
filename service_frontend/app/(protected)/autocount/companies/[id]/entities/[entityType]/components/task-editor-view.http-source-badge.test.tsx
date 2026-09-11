import { render as rtlRender, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountCompanyDetail, AutocountEtlTask } from '@/types/autocount';
import { TaskEditorView } from './task-editor-view';

/**
 * Sprint-5/08 AC-08-18 - "Add entity" on an `http` (open, no-auth) company
 * must create the task with `sourceImpl: 'autocount_http'` AT BIRTH, so the
 * task editor's header badge reads "Open API" before any save. The S1
 * evidence screenshot (`08-evidence/s1-mock/04-mocha-product-test-1280.png`)
 * shows "Database" for exactly this state - this test pins that defect.
 *
 * `task-editor-view.tsx` currently derives the badge from
 * `(task.sourceImpl ?? 'sql_db') === 'autocount_http' ? 'Open API' :
 * 'Database'` (read 2026-09-12) - a never-configured task's `sourceImpl` is
 * absent, so the fallback `'sql_db'` always reads "Database" regardless of
 * the COMPANY's own kind. RED until the coder either seeds
 * `sourceImpl: 'autocount_http'` on the birth-time task for an `http`
 * company, or derives the badge from the working Source-tab state
 * (`sourceKind`/`derivedImpl`) instead of the saved task alone.
 */

function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true }),
}));

/** The backend's `default_source_config('product')` on a never-configured
 * entity - no `sourceImpl` key at all (mirrors `unbornTask()` in the
 * sibling `task-editor-view.locked-connection.test.tsx`). */
function unbornTask(): AutocountEtlTask {
  return {
    companyId: 'c1',
    entityType: 'product',
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
  };
}

function companyDetail(): AutocountCompanyDetail {
  return {
    company: {
      id: 'c1',
      connectionId: 'conn-open-1',
      databaseName: 'MOCHA',
      companyName: 'Mocha',
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
    save: vi.fn(),
    apply: vi.fn(),
    reload: vi.fn(),
  }),
  useAutocountSqlConnections: () => ({ connections: [], isLoading: false, error: null }),
  useAutocountApiConnections: () => ({
    connections: [
      { id: 'conn-open-1', name: 'Mocha REST', baseUrl: 'https://hapi.sorento.cc.cd/api/db2', auth: 'none' as const },
    ],
    isLoading: false,
    error: null,
  }),
  useAutocountSqlSchema: () => ({ schema: null, isLoading: false, error: null, refresh: vi.fn() }),
  useEtlTaskLifecycle: () => ({
    busy: null, error: null, activate: vi.fn(), pause: vi.fn(), resume: vi.fn(),
    runNow: vi.fn(), clearError: vi.fn(),
  }),
  useEtlTaskPreview: () => ({ state: { status: 'idle' }, run: vi.fn(), reset: vi.fn() }),
  useSqlPreview: () => ({ state: { status: 'idle' }, run: vi.fn(), reset: vi.fn() }),
  useHttpPreview: () => ({ state: { status: 'idle' }, run: vi.fn(), fieldErrors: {}, reset: vi.fn() }),
}));

vi.mock('@/hooks/use-autocount-mapping', () => ({
  useAutocountMappingPresets: () => ({ presets: [], isLoading: false }),
  useAutocountMapping: () => ({
    view: null, isLoading: false, notFound: false, saveError: null, isSaving: false,
    save: vi.fn(), testFormula: vi.fn(), simulate: vi.fn(),
  }),
}));

vi.mock('../../../../components/use-runs-list-config', () => ({
  useAutocountRunsListConfig: () => ({}),
}));

beforeEach(() => {
  taskBox.current = unbornTask();
  detailBox.current = companyDetail();
});

describe('TaskEditorView - open (http) company birth-time source badge (AC-08-18)', () => {
  it('reads "Open API", never "Database", for a never-configured task on an http company', () => {
    render(<TaskEditorView companyId="c1" entityType="product" />);
    expect(screen.getByText('Open API')).toBeInTheDocument();
    expect(screen.queryByText('Database')).not.toBeInTheDocument();
  });
});
