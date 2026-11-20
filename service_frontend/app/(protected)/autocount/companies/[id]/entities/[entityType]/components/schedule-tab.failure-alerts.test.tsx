import { fireEvent, render as rtlRender, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountCompanyDetail, AutocountEtlTask } from '@/types/autocount';
import { TaskEditorView } from './task-editor-view';
import { stubAuthFetch } from './task-editor-view.test-helpers';

stubAuthFetch();

/**
 * Plan 33 (SS-INTEGRATION-ALERT) AC-33-15 - the Schedule tab's "Failure
 * alerts" section: loaded from the task, edited, saved with the schedule,
 * dirty-guarded. RED: written before the section exists. Real TaskEditorView
 * tree, hooks mocked at the boundary; the save payload is asserted as the
 * serialised call so the test does not pin where the service nests the keys.
 */

function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

vi.mock('@/lib/toast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true }),
}));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'UTC',
    formatDate: (v: string) => `FMT<${v}>`,
    formatDateTime: (v: string) => `FMT<${v}>`,
    formatTime: (v: string) => `FMT<${v}>`,
  }),
}));

const pushSpy = vi.fn();
vi.mock('next/navigation', () => ({
  usePathname: () => '/autocount/companies/c1/entities/customer',
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: pushSpy, replace: vi.fn(), prefetch: vi.fn() }),
}));

vi.mock('@/hooks/use-autocount-pull', () => ({
  usePreviewColumnsMap: () => ({ columnsByKey: {}, loadingKeys: {}, errorsByKey: {}, run: vi.fn() }),
  useSetDeliveryMode: () => ({
    saving: false, error: null, fieldErrors: {}, save: vi.fn(), clearError: vi.fn(),
  }),
}));

function configuredTask(over: Partial<AutocountEtlTask> = {}): AutocountEtlTask {
  return {
    companyId: 'c1',
    entityType: 'customer',
    etlStatus: 'active',
    activatedAt: '2026-09-01T00:00:00Z',
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
      incrementalMinutes: 15,
      reconcileMode: 'dailyAt',
      reconcileHours: null,
      reconcileAt: '02:00',
    },
    resultColumns: ['AccNo', 'CompanyName'],
    lastPreviewAt: '2026-09-01T00:00:00Z',
    lastPreviewFailedCount: 0,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
    deliveryMode: 'push',
    alertsEnabled: true,
    alertAfterFailedRuns: 2,
    alertStaleMultiple: 3,
    alertEmails: [],
    openIncident: null,
    ...over,
  };
}

function companyDetail(): AutocountCompanyDetail {
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
      sourceKind: 'db',
      documentPrerequisites: [],
    },
    entities: [],
  };
}

const taskBox = vi.hoisted(() => ({ current: null as unknown }));
const etlSaveSpy = vi.hoisted(() => vi.fn().mockResolvedValue(true));

vi.mock('@/hooks/use-autocount-company', () => ({
  useAutocountCompany: () => ({
    detail: companyDetail(),
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
  useAutocountSqlConnections: () => ({
    connections: [{ id: 'conn-sql-1', name: 'AutoCount DB', dialect: 'postgresql', database: 'AED_2024' }],
    isLoading: false,
    error: null,
  }),
  useAutocountApiConnections: () => ({ connections: [], isLoading: false, error: null }),
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
    view: null, isLoading: false, notFound: false, saveError: null, isSaving: false,
    save: vi.fn(), reload: vi.fn(), testFormula: vi.fn(), simulate: vi.fn(),
  }),
}));

vi.mock('../../../../components/use-runs-list-config', () => ({
  useAutocountRunsListConfig: () => ({}),
}));

function editButton() {
  return screen.getByRole('button', { name: /^Edit$/ });
}

beforeEach(() => {
  etlSaveSpy.mockClear();
  pushSpy.mockClear();
  taskBox.current = configuredTask();
});


function alertsSwitch() {
  return screen.getByRole('switch', { name: /failure alerts/i });
}
function afterRuns() {
  return screen.getByLabelText(/alert after n failed runs in a row/i);
}
function staleMultiple() {
  return screen.getByLabelText(/alert when no clean run for n x the interval/i);
}
function saveButton() {
  return screen.getByRole('button', { name: /^Save/i });
}
function savedPayload(): string {
  return JSON.stringify(etlSaveSpy.mock.calls[0]);
}

async function openSchedule() {
  render(<TaskEditorView companyId="c1" entityType="customer" initialTab="schedule" />);
  fireEvent.click(editButton());
  await screen.findByText('Failure alerts');
}

describe('ScheduleTab Failure alerts (AC-33-15)', () => {
  it('AC-33-15: the section loads the four settings from the task', async () => {
    taskBox.current = configuredTask({
      alertsEnabled: true,
      alertAfterFailedRuns: 4,
      alertStaleMultiple: 6,
      alertEmails: ['ops@vsoft.example', 'it@vsoft.example'],
    });
    await openSchedule();
    expect(alertsSwitch()).toHaveAttribute('aria-checked', 'true');
    expect(afterRuns()).toHaveValue(4);
    expect(staleMultiple()).toHaveValue(6);
    expect(screen.getByText('ops@vsoft.example')).toBeInTheDocument();
    expect(screen.getByText('it@vsoft.example')).toBeInTheDocument();
  });

  it('AC-33-15: the switch reflects alerts off', async () => {
    taskBox.current = configuredTask({ alertsEnabled: false });
    await openSchedule();
    expect(alertsSwitch()).toHaveAttribute('aria-checked', 'false');
  });

  it('AC-33-15: editing a threshold and saving sends it in the save payload', async () => {
    await openSchedule();
    fireEvent.change(afterRuns(), { target: { value: '5' } });
    fireEvent.change(staleMultiple(), { target: { value: '8' } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(etlSaveSpy).toHaveBeenCalled());
    const payload = savedPayload();
    expect(payload).toContain('"alertAfterFailedRuns":5');
    expect(payload).toContain('"alertStaleMultiple":8');
  });

  it('AC-33-15: switching alerts off and saving sends alertsEnabled false', async () => {
    await openSchedule();
    fireEvent.click(alertsSwitch());
    fireEvent.click(saveButton());
    await waitFor(() => expect(etlSaveSpy).toHaveBeenCalled());
    expect(savedPayload()).toContain('"alertsEnabled":false');
  });

  it('AC-33-15: an untouched save still carries the loaded values (never resets them)', async () => {
    taskBox.current = configuredTask({ alertAfterFailedRuns: 7 });
    await openSchedule();
    fireEvent.change(screen.getByTestId('etl-incremental-minutes'), { target: { value: '30' } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(etlSaveSpy).toHaveBeenCalled());
    expect(savedPayload()).toContain('"alertAfterFailedRuns":7');
  });

  it('AC-33-15: editing an alert setting arms the dirty guard on Back', async () => {
    await openSchedule();
    fireEvent.change(afterRuns(), { target: { value: '9' } });
    fireEvent.click(screen.getByRole('link', { name: /back/i }));
    expect(screen.getByText('Discard changes?')).toBeInTheDocument();
  });

  it('AC-33-15: reverting the edit disarms the dirty guard', async () => {
    await openSchedule();
    fireEvent.change(afterRuns(), { target: { value: '9' } });
    fireEvent.change(afterRuns(), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('link', { name: /back/i }));
    expect(screen.queryByText('Discard changes?')).not.toBeInTheDocument();
  });
});
