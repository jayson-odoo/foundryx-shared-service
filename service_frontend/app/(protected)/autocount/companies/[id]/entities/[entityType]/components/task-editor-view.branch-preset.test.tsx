import { fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountCompanyDetail, AutocountEtlTask } from '@/types/autocount';
import { TaskEditorView } from './task-editor-view';
import { stubAuthFetch } from './task-editor-view.test-helpers';

stubAuthFetch();

/**
 * sprint-5/14 section 11 (AC-14-47) - a never-configured `branch` task on an
 * open (http) company opens with its Source tab ALREADY pre-filled from
 * `HTTP_PRESETS.branch` (path `/branchbypage`, key fields `AccNo` + `BranchCode`).
 * Mirrors `task-editor-view.stock-preset.test.tsx`'s hook-mocking pattern. The
 * `product` case is the control: same rig, same assertions, passes today, so
 * the branch case can only go red for the missing preset.
 */
function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true }),
}));

function blankTask(entityType: string): AutocountEtlTask {
  return {
    companyId: 'company-http',
    entityType,
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
    deliveryMode: 'push',
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
      { id: 'conn-api-mocha', name: 'Mocha REST', baseUrl: 'https://hapi.sorento.cc.cd/api/db1', auth: 'none' as const },
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
  detailBox.current = httpCompanyDetail();
});

function keyColumnsBox(): HTMLElement {
  const label = screen.getByText(
    (_, el) => el?.tagName === 'LABEL' && (el.textContent ?? '').startsWith('Key columns'),
  );
  return label.parentElement as HTMLElement;
}

describe('TaskEditorView - a new branch task pre-fills from HTTP_PRESETS.branch (AC-14-47)', () => {
  it('control: a blank product task pre-fills its own path and key column', async () => {
    taskBox.current = blankTask('product');
    render(<TaskEditorView companyId="company-http" entityType="product" />);
    await screen.findByRole('tab', { name: /Source/i });
    expect(screen.getByLabelText('Endpoint path')).toHaveValue('/itembypage');
    fireEvent.click(screen.getByRole('button', { name: /^Edit$/ }));
    expect(keyColumnsBox()).toHaveTextContent('ItemCode');
  });

  it('a blank branch task pre-fills /branchbypage keyed on AccNo and BranchCode', async () => {
    taskBox.current = blankTask('branch');
    render(<TaskEditorView companyId="company-http" entityType="branch" />);
    await screen.findByRole('tab', { name: /Source/i });
    expect(screen.getByLabelText('Endpoint path')).toHaveValue('/branchbypage');
    fireEvent.click(screen.getByRole('button', { name: /^Edit$/ }));
    expect(keyColumnsBox()).toHaveTextContent('AccNo');
    expect(keyColumnsBox()).toHaveTextContent('BranchCode');
  });
});
