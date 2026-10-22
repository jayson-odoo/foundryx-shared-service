import { fireEvent, render as rtlRender, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountCompanyDetail, AutocountEtlTask } from '@/types/autocount';
import { TaskEditorView } from './task-editor-view';
import { stubAuthFetch } from './task-editor-view.test-helpers';

stubAuthFetch();

/**
 * Plan 33 (SS-INTEGRATION-ALERT) AC-33-13 - the incident banner on the
 * integration page. RED: written before the banner exists.
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

vi.mock('@/components/platform/resource-list', () => ({
  ResourceList: () => <div data-testid="runs-list-stub" />,
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


const INCIDENT = {
  openedAt: '2026-08-30T12:00:00Z',
  firstFailureAt: '2026-08-30T11:40:00Z',
  failedRuns: 14,
  lastError: 'AutoCount answered HTTP 502 on page 3.',
  reason: 'consecutive' as const,
};

function banner(): HTMLElement | undefined {
  return screen.queryAllByRole('alert').find((el) => /Failing since/.test(el.textContent ?? ''));
}

describe('TaskEditorView incident banner (AC-33-13)', () => {
  it('AC-33-13: shows the banner under the header while an incident is open', () => {
    taskBox.current = configuredTask({ openIncident: INCIDENT });
    render(<TaskEditorView companyId="c1" entityType="customer" initialTab="schedule" />);
    const el = banner();
    expect(el).toBeDefined();
    expect(el).toHaveTextContent(
      /Failing since .*2026-08-30T11:40:00Z.* - 14 failed runs\. Last error: AutoCount answered HTTP 502 on page 3\./,
    );
  });

  it('AC-33-13: a stale incident with no failed run still reads sensibly (singular run)', () => {
    taskBox.current = configuredTask({
      openIncident: { ...INCIDENT, failedRuns: 1, reason: 'stale' },
    });
    render(<TaskEditorView companyId="c1" entityType="customer" initialTab="schedule" />);
    expect(banner()).toHaveTextContent(/1 failed run\b/);
  });

  it('AC-33-13: "View runs" switches to the Runs tab', async () => {
    taskBox.current = configuredTask({ openIncident: INCIDENT });
    render(<TaskEditorView companyId="c1" entityType="customer" initialTab="schedule" />);
    expect(screen.getByRole('tab', { name: 'Runs' })).toHaveAttribute('aria-selected', 'false');
    fireEvent.click(screen.getByText('View runs'));
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Runs' })).toHaveAttribute('aria-selected', 'true'),
    );
    expect(screen.getByTestId('runs-list-stub')).toBeInTheDocument();
  });

  it('AC-33-13: no banner when there is no open incident', () => {
    taskBox.current = configuredTask({ openIncident: null });
    render(<TaskEditorView companyId="c1" entityType="customer" initialTab="schedule" />);
    expect(banner()).toBeUndefined();
    expect(screen.queryByText('View runs')).not.toBeInTheDocument();
  });

  it('AC-33-13: the banner shows in read mode and survives entering Edit', () => {
    taskBox.current = configuredTask({ openIncident: INCIDENT });
    render(<TaskEditorView companyId="c1" entityType="customer" initialTab="schedule" />);
    fireEvent.click(editButton());
    expect(banner()).toBeDefined();
  });
});
