import { fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountCompanyDetail, AutocountEtlTask, AutocountEtlTaskUpdate } from '@/types/autocount';
import { TaskEditorView } from './task-editor-view';
import { stubAuthFetch } from './task-editor-view.test-helpers';

stubAuthFetch();

/**
 * S5 (review round 1) - the backend contract change landing alongside this
 * round: explicit `combine: null` on `PUT .../etl-task` now CLEARS the
 * stored combine server-side (an ABSENT `combine` key leaves it untouched).
 * `AutocountEtlSourceConfig.combine` is a non-optional key (`| null`, never
 * `?:`), so `{...config, combine: null}` already serialises as a genuine
 * `"combine":null` on the wire (`JSON.stringify` only drops `undefined`) -
 * this pins that turning the Combine rows switch off and saving actually
 * sends the explicit clear, never an omitted key.
 */

function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true }),
}));

function stockTaskWithCombine(): AutocountEtlTask {
  return {
    companyId: 'company-http',
    entityType: 'stock_balance',
    etlStatus: 'active',
    activatedAt: '2026-09-01T00:00:00Z',
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
      incrementalMinutes: 15,
      reconcileMode: 'dailyAt',
      reconcileHours: null,
      reconcileAt: '02:00',
      path: '/itembatchbalqtybypage',
      keyFields: [],
      watermarkField: null,
      comparedFields: [],
      distinctOf: null,
      combine: {
        computed: [],
        require: [],
        measure: 'qty',
        groupBy: ['item_code'],
        measures: [{ source: 'BalQty', op: 'sum', alias: 'qty' }],
        carry: [],
        round: [],
        drop: [],
      },
    },
    resultColumns: ['ItemCode', 'BalQty'],
    lastPreviewAt: '2026-09-19T00:00:00Z',
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

function editButton() {
  return screen.getByRole('button', { name: /^Edit$/ });
}
function saveButton() {
  return screen.getByRole('button', { name: /^Save/i });
}

beforeEach(() => {
  etlSaveSpy.mockClear();
  taskBox.current = stockTaskWithCombine();
  detailBox.current = httpCompanyDetail();
});

describe('TaskEditorView - turning off Combine rows sends an explicit `combine: null` on save (S5, review round 1)', () => {
  it('the save() payload carries combine: null, not an absent key', async () => {
    render(<TaskEditorView companyId="company-http" entityType="stock_balance" />);
    await screen.findByRole('tab', { name: /Source/i });
    fireEvent.click(editButton());

    fireEvent.click(screen.getByTestId('combine-enable'));
    fireEvent.click(saveButton());

    expect(etlSaveSpy).toHaveBeenCalled();
    const [sentSourceConfig] = etlSaveSpy.mock.calls[0] as [AutocountEtlTaskUpdate['sourceConfig']];
    expect(sentSourceConfig).toHaveProperty('combine');
    expect(sentSourceConfig.combine).toBeNull();
  });
});
