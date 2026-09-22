import type { ReactNode } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import { mockAutocountService } from '@/services/autocount-service.mock';
import type {
  AutocountCompanyDetail,
  AutocountEtlTask,
  AutocountMappingView,
} from '@/types/autocount';

/**
 * AC-12-27 (fix round) - "Reset to preset" must be reachable for a DOCUMENT
 * entity. A `sql_db` entity's mapping opens on the TASK editor's Mapping tab,
 * never the standalone `/mapping` page, so the action has to live on this
 * surface too, with the SAME gating and the SAME post-apply hydration
 * (`applyView`, never a second `getMapping`).
 *
 * `ResourceForm` is reduced to "render the visible form actions" (the shell's
 * own permission/visibility filtering and its `!editing` dirty guard have
 * their own suite) - what is asserted here is what THIS view puts into
 * `config.actions` and what it does with the applied view.
 */

let canManage = true;
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({
    can: (key: string) => (key === 'autocount.companies.manage' ? canManage : true),
    ready: true,
  }),
}));

vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/components/common/container', () => ({
  Container: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));
vi.mock('react-hook-form', () => ({ useForm: () => ({}) }));
vi.mock('@/components/ui/form', () => ({
  Form: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

const appliedView = vi.hoisted(() => ({ current: null as AutocountMappingView | null }));
vi.mock('../mapping/components/mapping-reset-dialog', () => ({
  MappingResetDialog: ({
    open,
    onApplied,
  }: {
    open: boolean;
    onApplied: (view: AutocountMappingView) => void;
  }) =>
    open ? (
      <div data-testid="reset-dialog-open">
        <button type="button" onClick={() => onApplied(appliedView.current!)}>
          apply-reset
        </button>
      </div>
    ) : null,
}));

vi.mock('@/components/platform/resource-form', () => ({
  ResourceForm: ({ config }: { config: ResourceFormConfig<AutocountEtlTask> }) => (
    <div>
      {config.actions
        .filter((a) => a.surfaces.form && (!a.permission || canManage) && (!a.isVisible || a.isVisible([])))
        .map((a) => (
          <button
            key={a.id}
            type="button"
            onClick={() =>
              (a as { run: (rows: [], runtime: { reload: () => void }) => void }).run([], {
                reload: () => {},
              })
            }
          >
            {typeof a.label === 'function' ? a.label([]) : a.label}
          </button>
        ))}
    </div>
  ),
}));

const taskBox = vi.hoisted(() => ({ current: null as unknown }));
const detailBox = vi.hoisted(() => ({ current: null as unknown }));

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
    save: vi.fn(),
    apply: vi.fn(),
    reload: vi.fn(),
  }),
  useAutocountSqlConnections: () => ({ connections: [], isLoading: false, error: null }),
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
  useHttpPreview: () => ({
    state: { status: 'idle' },
    run: vi.fn().mockResolvedValue(true),
    fieldErrors: {},
    reset: vi.fn(),
  }),
}));

const mappingViewBox = vi.hoisted(() => ({ current: null as AutocountMappingView | null }));
const applyViewSpy = vi.hoisted(() => vi.fn());
const mappingReloadSpy = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-autocount-mapping', () => ({
  useAutocountMappingPresets: () => ({ presets: [], isLoading: false }),
  useAutocountMapping: () => ({
    view: mappingViewBox.current,
    isLoading: false,
    notFound: false,
    saveError: null,
    isSaving: false,
    save: vi.fn(),
    reload: mappingReloadSpy,
    testFormula: vi.fn(),
    simulate: vi.fn(),
    applyView: applyViewSpy,
  }),
}));

vi.mock('@/hooks/use-autocount-pull', () => ({
  usePreviewColumnsMap: () => ({ probe: vi.fn(), columnsByEntity: {}, isLoading: false }),
  useSetDeliveryMode: () => ({ save: vi.fn().mockResolvedValue(true), error: null, isSaving: false }),
}));

vi.mock('../../../../components/use-runs-list-config', () => ({
  useAutocountRunsListConfig: () => ({}),
}));

const { TaskEditorView } = await import('./task-editor-view');

function dbTask(): AutocountEtlTask {
  return {
    companyId: 'company-db',
    entityType: 'sales_order',
    etlStatus: 'draft',
    activatedAt: null,
    sourceConfig: {
      connectionId: 'conn-db',
      query: 'SELECT 1',
      lineQuery: 'SELECT 2',
      keyColumns: ['DocNo'],
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
    resultColumns: ['DocNo'],
    lastPreviewAt: null,
    lastPreviewFailedCount: null,
    lastRunAt: null,
    lastRunError: null,
    lastRunErrorCode: null,
    nextIncrementalAt: null,
    nextReconcileAt: null,
  };
}

function dbCompanyDetail(): AutocountCompanyDetail {
  return {
    company: {
      id: 'company-db',
      connectionId: 'conn-db',
      databaseName: 'AED',
      companyName: 'Acme Sdn Bhd',
      name: 'Acme',
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

function view(overrides: Partial<AutocountMappingView> = {}): AutocountMappingView {
  return {
    entityType: 'sales_order',
    rows: [],
    sorentoFields: [],
    acFields: [],
    lineSorentoFields: [],
    lineAcFields: [],
    hasPreset: false,
    ...overrides,
  };
}

beforeEach(() => {
  canManage = true;
  taskBox.current = dbTask();
  detailBox.current = dbCompanyDetail();
  mappingViewBox.current = view({ hasPreset: true });
  appliedView.current = view({ hasPreset: true });
  applyViewSpy.mockClear();
  mappingReloadSpy.mockClear();
});

describe('TaskEditorView - Reset to preset on the Mapping tab (AC-12-27)', () => {
  it('offers the action when the entity has a preset and the operator may manage', () => {
    render(<TaskEditorView companyId="company-db" entityType="sales_order" initialTab="mapping" />);
    expect(screen.getByText('Reset to preset')).toBeInTheDocument();
  });

  it('hides it when the entity has no preset (foolproof-UI)', () => {
    mappingViewBox.current = view({ hasPreset: false });
    render(<TaskEditorView companyId="company-db" entityType="sales_order" initialTab="mapping" />);
    expect(screen.queryByText('Reset to preset')).not.toBeInTheDocument();
  });

  it('hides it when the mapping has not loaded at all', () => {
    mappingViewBox.current = null;
    render(<TaskEditorView companyId="company-db" entityType="sales_order" initialTab="mapping" />);
    expect(screen.queryByText('Reset to preset')).not.toBeInTheDocument();
  });

  it('hides it without the manage permission even when a preset exists', () => {
    canManage = false;
    render(<TaskEditorView companyId="company-db" entityType="sales_order" initialTab="mapping" />);
    expect(screen.queryByText('Reset to preset')).not.toBeInTheDocument();
  });

  it('a real document fixture (sales_order) carries a preset, so the action is offered', async () => {
    const documentView = await mockAutocountService.getMapping('company-db', 'sales_order');
    expect(documentView.hasPreset).toBe(true);
    mappingViewBox.current = documentView;
    render(<TaskEditorView companyId="company-db" entityType="sales_order" initialTab="mapping" />);
    expect(screen.getByText('Reset to preset')).toBeInTheDocument();
  });

  it('clicking the action opens the reset dialog', () => {
    render(<TaskEditorView companyId="company-db" entityType="sales_order" initialTab="mapping" />);
    fireEvent.click(screen.getByText('Reset to preset'));
    expect(screen.getByTestId('reset-dialog-open')).toBeInTheDocument();
  });

  it('an applied reset hydrates from the returned view - no second getMapping (AC-12-23)', () => {
    const fresh = view({ hasPreset: true, entityType: 'sales_order' });
    appliedView.current = fresh;
    render(<TaskEditorView companyId="company-db" entityType="sales_order" initialTab="mapping" />);
    fireEvent.click(screen.getByText('Reset to preset'));
    fireEvent.click(screen.getByText('apply-reset'));
    expect(applyViewSpy).toHaveBeenCalledWith(fresh);
    expect(mappingReloadSpy).not.toHaveBeenCalled();
  });
});
