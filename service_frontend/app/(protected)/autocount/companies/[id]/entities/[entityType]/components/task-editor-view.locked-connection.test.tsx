import { fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountCompanyDetail, AutocountEtlTask } from '@/types/autocount';
import { TaskEditorView } from './task-editor-view';

/**
 * Plan sprint-5/01 review SHOULD-FIX - a DB company's locked connection is
 * seeded into the config BASELINE, never patched after mount (AC-01-19 /
 * AC-01-23). The backend's default draft for a never-configured entity carries
 * `connectionId: null`; the old post-mount patch left `configDirty` true in
 * read mode, so Edit -> Cancel asked "Discard changes?" on an untouched editor
 * (and Discard re-dirtied it forever). These cases render the REAL
 * `ResourceForm` shell so the Edit/Cancel/dirty-guard path is the production
 * one, with the data hooks mocked at the hook boundary.
 */

/** Container/Toolbar read layout settings - provide the real provider. */
function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true }),
}));

/** The backend's `default_source_config('customer')` - `connectionId: null`. */
function unbornTask(): AutocountEtlTask {
  return {
    companyId: 'c1',
    entityType: 'customer',
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
      lineKeyColumn: null,
      lineProductColumn: null,
      lineWarehouseColumn: null,
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

function companyDetail(sourceKind: 'db' | 'api'): AutocountCompanyDetail {
  return {
    company: {
      id: 'c1',
      connectionId: 'conn-sql-1',
      databaseName: 'AED_2024',
      companyName: 'AED Trading',
      name: 'AED Trading',
      isActive: true,
      sinkImpl: 'logging',
      sinkConnectionId: null,
      sorentoCompanyCode: null,
      createdAt: null,
      sourceKind,
      documentPrerequisites: [],
    },
    entities: [],
  };
}

// `vi.hoisted` mutable boxes - a test picks the company kind before rendering;
// `schemaSpy` observes the connection id the editor's working config carries
// (`useAutocountSqlSchema(config?.connectionId)` is the one consumer of it).
const detailBox = vi.hoisted(() => ({ current: null as unknown }));
const taskBox = vi.hoisted(() => ({ current: null as unknown }));
const schemaSpy = vi.hoisted(() => vi.fn());

vi.mock('@/hooks/use-autocount-company', () => ({
  useAutocountCompany: () => ({
    detail: detailBox.current,
    isLoading: false,
    notFound: false,
    reload: vi.fn(),
  }),
}));

vi.mock('@/hooks/use-autocount-etl', () => ({
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
    connections: [
      { id: 'conn-sql-1', name: 'AutoCount DB', dialect: 'postgresql', database: 'AED_2024' },
    ],
    isLoading: false,
    error: null,
  }),
  useAutocountSqlSchema: (connectionId: string | null) => {
    schemaSpy(connectionId);
    return { schema: null, isLoading: false, error: null, refresh: vi.fn() };
  },
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
  // A success preview so the Query tab's column pickers are ENABLED - the
  // control case below makes a real edit through one of them.
  useSqlPreview: () => ({
    state: {
      status: 'success',
      preview: {
        columns: [
          { name: 'acc_no', type: 'string' },
          { name: 'company_name', type: 'string' },
        ],
        rows: [],
        rowCount: 0,
        truncated: false,
        durationMs: 3,
      },
    },
    run: vi.fn(),
    reset: vi.fn(),
  }),
}));

vi.mock('@/hooks/use-autocount-mapping', () => ({
  useAutocountMapping: () => ({
    view: null,
    isLoading: false,
    notFound: false,
    saveError: null,
    isSaving: false,
    save: vi.fn(),
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
  schemaSpy.mockReset();
  taskBox.current = unbornTask();
  detailBox.current = companyDetail('db');
});

describe('TaskEditorView - DB company locked connection seeds the BASELINE (review fix, AC-01-19)', () => {
  it('mounts clean: locked row shown, config.connectionId pre-set, no picker', () => {
    render(<TaskEditorView companyId="c1" entityType="customer" />);
    expect(screen.getByTestId('locked-connection')).toHaveTextContent('AutoCount DB · AED_2024');
    expect(screen.queryByRole('combobox', { name: 'Connection' })).not.toBeInTheDocument();
    // The working config carries the company connection from the first render.
    expect(schemaSpy).toHaveBeenLastCalledWith('conn-sql-1');
  });

  it('Edit -> Cancel on an untouched editor never asks "Discard changes?"', () => {
    render(<TaskEditorView companyId="c1" entityType="customer" />);
    fireEvent.click(editButton());
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByText('Discard changes?')).not.toBeInTheDocument();
    // Straight back to read mode - the seed survives the reset too.
    expect(editButton()).toBeInTheDocument();
    expect(schemaSpy).toHaveBeenLastCalledWith('conn-sql-1');
  });

  it('control: a real edit then Cancel DOES ask "Discard changes?" (the guard is live)', () => {
    render(<TaskEditorView companyId="c1" entityType="customer" />);
    fireEvent.click(editButton());
    fireEvent.click(screen.getByLabelText('Watermark column'));
    fireEvent.click(screen.getByRole('option', { name: 'acc_no' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByText('Discard changes?')).toBeInTheDocument();
  });

  it('an API company keeps the null draft as-is (picker present, nothing seeded)', () => {
    detailBox.current = companyDetail('api');
    render(<TaskEditorView companyId="c1" entityType="customer" />);
    expect(screen.getByRole('combobox', { name: 'Connection' })).toBeInTheDocument();
    expect(screen.queryByTestId('locked-connection')).not.toBeInTheDocument();
    expect(schemaSpy).toHaveBeenLastCalledWith(null);
  });
});
