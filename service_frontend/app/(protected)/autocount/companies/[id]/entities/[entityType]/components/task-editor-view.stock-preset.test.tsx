import { fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountCompanyDetail, AutocountEtlTask } from '@/types/autocount';
import { TaskEditorView } from './task-editor-view';
import { stubAuthFetch } from './task-editor-view.test-helpers';

stubAuthFetch();

/**
 * sprint-5/10 S5b-FE (AC-10-40/41) - a never-configured `stock_balance` task
 * on an open (http) company opens with its Source tab ALREADY pre-filled
 * from `HTTP_PRESETS.stock_balance` (`lib/autocount-etl.ts`, mirroring the
 * backend's `STOCK_BALANCE_HTTP_PRESET`): two ordered lookups and a
 * Combine rows step with the `negative` drop rule's "list dropped rows"
 * switch already on - the operator configures nothing (foolproof-UI).
 * Mirrors `task-editor-view.http-preset-dirty.test.tsx`'s mocking pattern
 * (`useAutocountEtlTask` fully stubbed) rather than the SERVICE-mocking
 * pattern, since this suite never exercises Test/Save.
 */
function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true }),
}));

function blankStockTask(): AutocountEtlTask {
  return {
    companyId: 'company-http',
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
  taskBox.current = blankStockTask();
  detailBox.current = httpCompanyDetail();
});

describe('TaskEditorView - a new stock_balance task pre-fills lookups + combine (sprint-5/10, AC-10-40/41)', () => {
  it('the Source tab shows the pre-filled negative drop rule with "list dropped rows" already on', async () => {
    render(<TaskEditorView companyId="company-http" entityType="stock_balance" />);
    await screen.findByRole('tab', { name: /Source/i });

    expect(screen.getByLabelText('Endpoint path')).toHaveValue('/itembatchbalqtybypage');
    expect(screen.getByLabelText('Drop rule 1 name')).toHaveValue('zero');
    expect(screen.getByLabelText('Drop rule 2 name')).toHaveValue('negative');
    expect(screen.getByTestId('drop-list-rows-1')).toHaveAttribute('data-state', 'checked');
    expect(screen.getByTestId('drop-list-rows-0')).toHaveAttribute('data-state', 'unchecked');
  });

  // Opus confirm review addendum (S-1) - `keysMissing`'s `!combineKeyed &&`
  // guard (`task-editor-view.tsx` ~562-567) had zero test coverage: a kill
  // (deleting the guard) survived the full suite. A combine-keyed task must
  // NOT show the warning even though `keyFields` itself is empty (AC-10-80 -
  // keys are DERIVED from `combine.groupBy`); a task with neither combine
  // nor keys still must.
  it('a preset-seeded, never-saved stock task (combine-keyed) shows NO "no key columns" warning', async () => {
    render(<TaskEditorView companyId="company-http" entityType="stock_balance" />);
    await screen.findByRole('tab', { name: /Source/i });
    expect(screen.queryByTestId('task-keys-missing')).not.toBeInTheDocument();
  });

  it('a task with a configured path but no combine and no key fields DOES show the warning', async () => {
    // Path already set (so the preset-seeding effect never fires) - no
    // `combine`, no `keyFields`: exactly the case the warning exists for.
    taskBox.current = {
      ...blankStockTask(),
      sourceConfig: { ...blankStockTask().sourceConfig, path: '/itembatchbalqtybypage', keyFields: [] },
    };
    render(<TaskEditorView companyId="company-http" entityType="stock_balance" />);
    await screen.findByRole('tab', { name: /Source/i });
    expect(screen.getByTestId('task-keys-missing')).toBeInTheDocument();
  });

  it('the pre-filled group-by locks the Key fields picker to read-only chips (AC-10-80)', async () => {
    render(<TaskEditorView companyId="company-http" entityType="stock_balance" />);
    await screen.findByRole('tab', { name: /Source/i });
    // S4c (review round 1) - `ColumnPickers` renders read-only
    // chips whenever `!editing` REGARDLESS of `keyReadOnly` (the shell's
    // default view mode), so without clicking Edit this assertion passes
    // even with `keyReadOnly` wired to nothing - a vacuous pass. Editing
    // mode is the only state where `keyReadOnly` actually does anything.
    fireEvent.click(screen.getByRole('button', { name: /^Edit$/ }));

    const keyColumnsLabel = screen.getByText(
      (_, el) => el?.tagName === 'LABEL' && (el.textContent ?? '').startsWith('Key columns'),
    );
    const box = keyColumnsLabel.parentElement as HTMLElement;
    expect(box.querySelector('[role="combobox"]')).not.toBeInTheDocument();
    expect(box).toHaveTextContent('item_code');
    expect(box).toHaveTextContent('location_code');
  });
});
