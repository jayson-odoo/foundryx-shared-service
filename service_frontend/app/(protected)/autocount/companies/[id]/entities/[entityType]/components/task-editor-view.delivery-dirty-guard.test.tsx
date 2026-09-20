import { fireEvent, render as rtlRender, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountCompanyDetail, AutocountEtlTask } from '@/types/autocount';
import { TaskEditorView } from './task-editor-view';
import { stubAuthFetch } from './task-editor-view.test-helpers';

stubAuthFetch();

/**
 * Browser round 1 defect (AC-10-16): toggling the Schedule tab's Delivery
 * segment (Push -> Pull) without saving, then navigating away via the
 * shell's OWN Back link or a `PageHeader` breadcrumb, silently discarded the
 * edit - the dirty-guard `AlertDialog` never fired. Root cause: `PageHeader`
 * rendered its Back button and every breadcrumb link as bare `next/link`s,
 * bypassing `resource-form.tsx`'s `guard()` (the same one Cancel/RecordNav
 * already used) entirely. Fixed at the SHELL (`resource-form.tsx` +
 * `page-header.tsx`) - this suite renders the REAL `TaskEditorView` tree so
 * the guard's wiring into a real dirty source (delivery mode) is proven,
 * not just the shell in isolation.
 */
function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true }),
}));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'UTC',
    formatDate: (v: string) => v ?? '',
    formatDateTime: (v: string) => v ?? '',
    formatTime: (v: string) => v ?? '',
  }),
}));

const pushSpy = vi.fn();
vi.mock('next/navigation', () => ({
  usePathname: () => '/autocount/companies/c1/entities/customer',
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: pushSpy, prefetch: vi.fn() }),
}));

const setDeliveryModeSave = vi.hoisted(() => vi.fn());

vi.mock('@/hooks/use-autocount-pull', () => ({
  usePreviewColumnsMap: () => ({ columnsByKey: {}, loadingKeys: {}, errorsByKey: {}, run: vi.fn() }),
  useSetDeliveryMode: () => ({
    saving: false,
    error: null,
    fieldErrors: {},
    save: setDeliveryModeSave,
    clearError: vi.fn(),
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
const reloadSpy = vi.hoisted(() => vi.fn());

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
    save: vi.fn().mockResolvedValue(true),
    apply: vi.fn(),
    reload: reloadSpy,
  }),
  useAutocountSqlConnections: () => ({
    connections: [{ id: 'conn-sql-1', name: 'AutoCount DB', dialect: 'postgresql', database: 'AED_2024' }],
    isLoading: false,
    error: null,
  }),
  useAutocountApiConnections: () => ({ connections: [], isLoading: false, error: null }),
  useAutocountSqlSchema: () => ({ schema: null, isLoading: false, error: null, refresh: vi.fn() }),
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
function backLink() {
  return screen.getByRole('link', { name: /back/i });
}

beforeEach(() => {
  pushSpy.mockClear();
  reloadSpy.mockClear();
  setDeliveryModeSave.mockClear();
  setDeliveryModeSave.mockResolvedValue({
    id: 'entity-customer',
    entityType: 'customer',
    syncMode: 'MANUAL',
    sourceImpl: 'sql_db',
    recordCap: 5000,
    initialLookbackDays: 30,
    enabled: true,
    lastSuccessAt: null,
    lastAttemptAt: null,
    watermarkAt: null,
    consecutiveFailures: 0,
    lastError: null,
    etlStatus: 'active',
    deliveryMode: 'pull',
  });
  taskBox.current = configuredTask();
});

describe('TaskEditorView Schedule tab - the delivery toggle arms the SHELL dirty guard (AC-10-16, browser round 1)', () => {
  it('toggling Push -> Pull without saving, then clicking Back, shows "Discard changes?" (defect repro)', async () => {
    render(<TaskEditorView companyId="c1" entityType="customer" initialTab="schedule" />);
    fireEvent.click(editButton());
    fireEvent.click(await screen.findByTestId('etl-delivery-pull'));

    fireEvent.click(backLink());
    expect(screen.getByText('Discard changes?')).toBeInTheDocument();
    // Navigation is DEFERRED behind the dialog - never fired eagerly.
    expect(pushSpy).not.toHaveBeenCalled();
  });

  it('"Keep editing" stays on the page with the toggle still on Pull', async () => {
    render(<TaskEditorView companyId="c1" entityType="customer" initialTab="schedule" />);
    fireEvent.click(editButton());
    fireEvent.click(await screen.findByTestId('etl-delivery-pull'));
    fireEvent.click(backLink());
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
    await waitFor(() => expect(screen.queryByText('Discard changes?')).not.toBeInTheDocument());
    expect(screen.getByTestId('etl-delivery-pull')).toHaveAttribute('data-state', 'on');
  });

  it('discarding navigates via the guarded push (router.push, not a bare Link click)', async () => {
    render(<TaskEditorView companyId="c1" entityType="customer" initialTab="schedule" />);
    fireEvent.click(editButton());
    fireEvent.click(await screen.findByTestId('etl-delivery-pull'));
    fireEvent.click(backLink());
    fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }));
    expect(pushSpy).toHaveBeenCalledWith('/autocount/companies/c1?from=customer');
  });

  it('reverting Pull -> Push (back to the saved value) disarms the guard - no dialog on Back', async () => {
    render(<TaskEditorView companyId="c1" entityType="customer" initialTab="schedule" />);
    fireEvent.click(editButton());
    fireEvent.click(await screen.findByTestId('etl-delivery-pull'));
    fireEvent.click(await screen.findByTestId('etl-delivery-push'));

    // Clean again - Back is a PLAIN Link (never routed through `guard()`),
    // so it never calls the mocked `router.push` either; the pinning
    // assertion is simply that the guard never arms.
    fireEvent.click(backLink());
    expect(screen.queryByText('Discard changes?')).not.toBeInTheDocument();
    expect(pushSpy).not.toHaveBeenCalled();
  });

  it('saving the delivery-mode change disarms the guard (no dialog on the next Back click)', async () => {
    render(<TaskEditorView companyId="c1" entityType="customer" initialTab="schedule" />);
    fireEvent.click(editButton());
    fireEvent.click(await screen.findByTestId('etl-delivery-pull'));

    fireEvent.click(screen.getByRole('button', { name: /^Save/ }));
    await waitFor(() => expect(setDeliveryModeSave).toHaveBeenCalledWith('c1', 'customer', 'pull'));
    await waitFor(() => expect(editButton()).toBeInTheDocument());

    fireEvent.click(backLink());
    expect(screen.queryByText('Discard changes?')).not.toBeInTheDocument();
  });
});
