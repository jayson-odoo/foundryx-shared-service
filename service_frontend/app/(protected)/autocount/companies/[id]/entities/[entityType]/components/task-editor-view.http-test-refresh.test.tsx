import { act, fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountCompanyDetail, AutocountEtlTask } from '@/types/autocount';
import { TaskEditorView } from './task-editor-view';
import { stubAuthFetch } from './task-editor-view.test-helpers';

stubAuthFetch();

/**
 * Defect 3 (tester, review round 6, live at 3110490f) - a successful
 * Source-tab Test on the API branch only set the LOCAL `httpPreviewedFor`
 * guard; nothing re-read the task, so `task.lastPreviewAt` (the ONLY thing
 * that unlocks Activate, AC-22-18) stayed stale in state after
 * Test -> Save -> Test again, until the operator left and re-entered the
 * editor. The fix: `onHttpPreviewSuccess` must call the hook's own
 * `reload()` (already used elsewhere in this file) so the freshly-stamped
 * `lastPreviewAt`/`resultColumns` land in `task` without a remount.
 */
function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true }),
}));

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

const detailBox = vi.hoisted(() => ({ current: null as unknown }));
const taskBox = vi.hoisted(() => ({ current: null as unknown }));
const httpRunSpy = vi.hoisted(() => vi.fn());
const reloadSpy = vi.hoisted(() => vi.fn());

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
    reload: reloadSpy,
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

beforeEach(() => {
  httpRunSpy.mockReset();
  reloadSpy.mockReset();
  detailBox.current = httpCompanyDetail();
  taskBox.current = unpreviewedHttpTask();
});

describe('TaskEditorView - Source tab Test refresh (Defect 3, review round 6)', () => {
  it('reloads the task after a successful HTTP Test so lastPreviewAt/resultColumns never go stale', async () => {
    httpRunSpy.mockResolvedValue(true);
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    fireEvent.click(editButton());

    await act(async () => {
      fireEvent.click(screen.getByTestId('http-test-path'));
      await Promise.resolve();
    });

    expect(reloadSpy).toHaveBeenCalledTimes(1);
  });

  it('a second successful Test (post-Save) reloads again - Activate never needs a remount to see it', async () => {
    httpRunSpy.mockResolvedValue(true);
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    fireEvent.click(editButton());

    await act(async () => {
      fireEvent.click(screen.getByTestId('http-test-path'));
      await Promise.resolve();
    });
    // Simulate the Save that follows a Test clearing `lastPreviewAt` server-side
    // (the PUT contract) - the task the hook reports now reflects that PUT.
    taskBox.current = { ...unpreviewedHttpTask(), lastPreviewAt: null, resultColumns: [] };

    await act(async () => {
      fireEvent.click(screen.getByTestId('http-test-path'));
      await Promise.resolve();
    });

    expect(reloadSpy).toHaveBeenCalledTimes(2);
  });

  it('a FAILED Test never reloads the task', async () => {
    httpRunSpy.mockResolvedValue(false);
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    fireEvent.click(editButton());

    await act(async () => {
      fireEvent.click(screen.getByTestId('http-test-path'));
      await Promise.resolve();
    });

    expect(reloadSpy).not.toHaveBeenCalled();
  });
});
