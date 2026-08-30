import { render as rtlRender, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountEtlTask } from '@/types/autocount';
import { TaskEditorView } from './task-editor-view';

/** Container/Toolbar read layout settings - provide the real provider. */
function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

/**
 * S2 review SHOULD-FIX 7 - the Runs tab is gated `autocount.sync.read` on the
 * BACKEND (GET .../etl-task/runs) - a DIFFERENT resource than the page's own
 * `autocount.companies.manage`, so a user can reach this page without being
 * allowed to read the run history. `ResourceForm` is stubbed to a trivial
 * capture of `config.tabs` - the point under test is which tabs the VIEW
 * builds, not the shell's own rendering (covered elsewhere).
 */

const canMock = vi.fn((): boolean => true);
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: canMock, ready: true }),
}));

vi.mock('@/components/platform/resource-form', () => ({
  ResourceForm: ({ config }: { config: { tabs: { id: string }[] } }) => (
    <div data-testid="tabs">{config.tabs.map((t) => t.id).join(',')}</div>
  ),
}));

function task(over: Partial<AutocountEtlTask> = {}): AutocountEtlTask {
  return {
    companyId: 'c1',
    entityType: 'customer',
    etlStatus: 'draft',
    activatedAt: null,
    sourceConfig: {
      connectionId: 'conn-sql-1',
      query: 'SELECT * FROM dbo.Debtor',
      lineQuery: null,
      keyColumns: ['AccNo'],
      watermarkColumn: null,
      comparedColumns: [],
      fromDate: null,
      incrementalMinutes: 5,
      reconcileMode: 'dailyAt',
      reconcileHours: null,
      reconcileAt: '02:00',
    },
    resultColumns: ['AccNo'],
    lastPreviewAt: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    ...over,
  };
}

vi.mock('@/hooks/use-autocount-company', () => ({
  useAutocountCompany: () => ({ detail: null, isLoading: false, notFound: false, reload: vi.fn() }),
}));

vi.mock('@/hooks/use-autocount-etl', () => ({
  useAutocountEtlTask: () => ({
    task: task(),
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

beforeEach(() => {
  canMock.mockReset();
  canMock.mockReturnValue(true);
});

describe('TaskEditorView (S2 review SHOULD-FIX 7 - Runs tab permission gate)', () => {
  it('offers the Runs tab with autocount.sync.read', () => {
    render(<TaskEditorView companyId="c1" entityType="customer" />);
    expect(screen.getByTestId('tabs')).toHaveTextContent('runs');
  });

  it('withholds the Runs tab without autocount.sync.read', () => {
    canMock.mockImplementation((key: string) => key !== 'autocount.sync.read');
    render(<TaskEditorView companyId="c1" entityType="customer" />);
    const tabs = screen.getByTestId('tabs').textContent ?? '';
    expect(tabs.split(',')).not.toContain('runs');
    // Every OTHER tab is unaffected by this gate.
    expect(tabs).toContain('query');
    expect(tabs).toContain('mapping');
    expect(tabs).toContain('activate');
  });
});
