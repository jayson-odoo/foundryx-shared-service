import { act, fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountCompanyDetail, AutocountEtlTask } from '@/types/autocount';
import { TaskEditorView } from './task-editor-view';
import { stubAuthFetch } from './task-editor-view.test-helpers';

stubAuthFetch();

/**
 * sprint-5/08 S1 fix (found via the agent-browser evidence run, not a
 * vitest-first catch) - a never-configured HTTP task's Source tab opens
 * ALREADY pre-filled from its preset (AC-08-16, foolproof-UI). The FIRST
 * cut baked that pre-fill into `baseline` itself, so `config` matched
 * `baseline` from the first render and `isDirty` read false - clicking Save
 * showed a "Task saved." toast while `onSave`'s `if (configDirty ||
 * sourceKindDirty)` gate silently skipped the actual `save()` call. The fix
 * seeds the preset onto the WORKING `config` only, leaving `baseline` as the
 * genuinely-saved (blank) state - so a fresh mount reads dirty=true and a
 * real save fires.
 */
function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true }),
}));

function blankHttpTask(): AutocountEtlTask {
  return {
    companyId: 'company-http',
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
const etlSaveSpy = vi.hoisted(() => vi.fn().mockResolvedValue(true));

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
    save: etlSaveSpy,
    apply: vi.fn(),
    reload: vi.fn(),
  }),
  useAutocountSqlConnections: () => ({ connections: [], isLoading: false, error: null }),
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
  // sprint-5/08 S5 (AC-08-20) - `run` resolves `true` so a Test click proves
  // the save gate; the tests below click Test before Save exactly as the
  // gate now requires.
  useHttpPreview: () => ({
    state: { status: 'idle' },
    run: vi.fn().mockResolvedValue(true),
    fieldErrors: {},
    reset: vi.fn(),
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

function editButton() {
  return screen.getByRole('button', { name: /^Edit$/ });
}
function saveButton() {
  return screen.getByRole('button', { name: /^Save/i });
}

beforeEach(() => {
  etlSaveSpy.mockClear();
  taskBox.current = blankHttpTask();
  detailBox.current = httpCompanyDetail();
});

describe('TaskEditorView - a never-configured HTTP task is dirty from the first render (sprint-5/08 fix)', () => {
  it('Edit -> Cancel on the untouched-by-the-operator preset DOES ask "Discard changes?" (there is a real unsaved preset to lose)', () => {
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    fireEvent.click(editButton());
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByText('Discard changes?')).toBeInTheDocument();
  });

  it('clicking Save actually calls the save() hook (not a fake "Task saved." with nothing persisted)', async () => {
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    fireEvent.click(editButton());
    // AC-08-20 - Save is withheld until Test proves the preset-filled path/
    // connection; this session's Test click satisfies it.
    await act(async () => {
      fireEvent.click(screen.getByTestId('http-test-path'));
      await Promise.resolve();
    });
    fireEvent.click(saveButton());
    expect(etlSaveSpy).toHaveBeenCalled();
    // The derived impl (API + no-auth connection) travels as the second arg.
    expect(etlSaveSpy.mock.calls[0][1]).toBe('autocount_http');
  });

  it('the saved config carries the preset path/keyFields, not a blank draft', async () => {
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    fireEvent.click(editButton());
    await act(async () => {
      fireEvent.click(screen.getByTestId('http-test-path'));
      await Promise.resolve();
    });
    fireEvent.click(saveButton());
    const [sentConfig] = etlSaveSpy.mock.calls[0];
    expect(sentConfig.path).toBe('/itembypage');
    expect(sentConfig.keyFields).toEqual(['ItemCode']);
    expect(sentConfig.connectionId).toBe('conn-api-mocha');
    // Found via the agent-browser evidence run: ScheduleTab reads
    // `watermarkColumn` (the SQL field name) unconditionally - an HTTP
    // task's `watermarkField` pick must mirror onto it too, or Schedule
    // wrongly shows the "no watermark" 15-minute floor warning.
    expect(sentConfig.watermarkField).toBe('LastModified');
    expect(sentConfig.watermarkColumn).toBe('LastModified');
  });
});
