import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { UseEtlTaskLifecycleResult, UseEtlTaskPreviewResult } from '@/hooks/use-autocount-etl';
import type { AutocountCompany, AutocountEntityConfig, AutocountEtlTask } from '@/types/autocount';
import { ActivateTab } from './activate-tab';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

const canMock = vi.fn((): boolean => true);
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: canMock, ready: true }),
}));

beforeEach(() => {
  canMock.mockReset();
  canMock.mockReturnValue(true);
});

function company(over: Partial<AutocountCompany> = {}): AutocountCompany {
  return {
    id: 'c1',
    connectionId: 'conn-1',
    databaseName: 'AED',
    companyName: 'AED',
    name: 'AED',
    isActive: true,
    sinkImpl: 'sorento',
    sinkConnectionId: 'conn-9',
    sorentoCompanyCode: 'SRT',
    createdAt: null,
    ...over,
  };
}

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
    nextIncrementalAt: null,
    nextReconcileAt: null,
    ...over,
  };
}

function preview(state: UseEtlTaskPreviewResult['state'] = { status: 'idle' }): UseEtlTaskPreviewResult {
  return { state, run: vi.fn().mockResolvedValue(undefined), reset: vi.fn() };
}

function entityConfig(over: Partial<AutocountEntityConfig> = {}): AutocountEntityConfig {
  return {
    id: 'e1',
    entityType: 'product_category',
    syncMode: 'SCHEDULED_REVIEW',
    sourceImpl: 'sql_db',
    recordCap: 200,
    initialLookbackDays: 30,
    enabled: true,
    lastSuccessAt: null,
    lastAttemptAt: null,
    watermarkAt: null,
    consecutiveFailures: 0,
    lastError: null,
    etlStatus: 'active',
    ...over,
  };
}

function lifecycle(over: Partial<UseEtlTaskLifecycleResult> = {}): UseEtlTaskLifecycleResult {
  return {
    busy: null,
    error: null,
    activate: vi.fn().mockResolvedValue(true),
    pause: vi.fn().mockResolvedValue(true),
    resume: vi.fn().mockResolvedValue(true),
    runNow: vi.fn().mockResolvedValue('run-1'),
    clearError: vi.fn(),
    ...over,
  };
}

describe('ActivateTab (plan 22 S2, AC-22-18/19, Appendix A6)', () => {
  it('withholds Activate until a preview passed, then enables it', () => {
    const { rerender } = render(
      <ActivateTab company={company()} task={task()} configDirty={false} preview={preview()} lifecycle={lifecycle()} onRan={vi.fn()} />,
    );
    expect(screen.getByTestId('etl-run-preview')).toBeEnabled();
    // Foolproof-UI (S2 review NIT): the disabled state itself carries the
    // "not yet" signal - no procedural "Preview before activating" caption.
    expect(screen.getByTestId('etl-activate')).toBeDisabled();
    expect(screen.queryByTestId('activate-blocked')).not.toBeInTheDocument();

    rerender(
      <ActivateTab
        company={company()}
        task={task({ lastPreviewAt: '2026-08-30T06:21:00Z' })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    expect(screen.getByTestId('etl-activate')).toBeEnabled();
    expect(screen.getByTestId('etl-preview-passed')).toBeInTheDocument();
  });

  it('withholds both buttons with a stated prerequisite when the company has no Sorento code', () => {
    render(
      <ActivateTab
        company={company({ sorentoCompanyCode: null })}
        task={task({ lastPreviewAt: '2026-08-30T06:21:00Z' })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    expect(screen.getByTestId('activate-prerequisite-companyCode')).toHaveTextContent(/Open company/);
    expect(screen.getByTestId('etl-run-preview')).toBeDisabled();
    expect(screen.getByTestId('etl-activate')).toBeDisabled();
  });

  it('withholds on unsaved edits (a preview of an unsaved query proves nothing)', () => {
    render(
      <ActivateTab company={company()} task={task()} configDirty preview={preview()} lifecycle={lifecycle()} onRan={vi.fn()} />,
    );
    expect(screen.getByTestId('activate-prerequisite-unsaved')).toBeInTheDocument();
    expect(screen.getByTestId('etl-run-preview')).toBeDisabled();
  });

  it('renders a Sorento anchor 422 as a task-level error with its title, not a dry-run failure', () => {
    render(
      <ActivateTab
        company={company()}
        task={task()}
        configDirty={false}
        preview={preview({
          status: 'taskError',
          error: { code: 'COMPANY_ANCHOR_AMBIGUOUS', message: 'Two companies match.' },
        })}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    const alert = screen.getByTestId('etl-task-error');
    expect(alert).toHaveTextContent('Sorento company code is ambiguous');
    expect(alert).toHaveTextContent('Two companies match.');
    expect(screen.queryByTestId('preview-error')).not.toBeInTheDocument();
  });

  it('shows Pause + Run now while active, Resume while paused, and the last run error on the task', async () => {
    const lc = lifecycle();
    const onRan = vi.fn();
    const { rerender } = render(
      <ActivateTab
        company={company()}
        task={task({ etlStatus: 'active', activatedAt: '2026-08-30T06:30:00Z', lastPreviewAt: '2026-08-30T06:21:00Z' })}
        configDirty={false}
        preview={preview()}
        lifecycle={lc}
        onRan={onRan}
      />,
    );
    expect(screen.queryByTestId('etl-activate')).not.toBeInTheDocument();
    expect(screen.getByTestId('etl-pause')).toBeEnabled();
    fireEvent.click(screen.getByTestId('etl-run-now'));
    await vi.waitFor(() => expect(onRan).toHaveBeenCalled());

    rerender(
      <ActivateTab
        company={company()}
        task={task({
          etlStatus: 'paused',
          lastRunAt: '2026-08-30T06:40:00Z',
          lastRunError: "No Sorento company matches code 'ZZ'.",
          lastRunErrorCode: 'UNKNOWN_COMPANY',
        })}
        configDirty={false}
        preview={preview()}
        lifecycle={lc}
        onRan={onRan}
      />,
    );
    expect(screen.getByTestId('etl-resume')).toBeEnabled();
    expect(screen.getByTestId('task-last-run-error')).toHaveTextContent('Unknown Sorento company');
  });

  it('withholds Run preview and Run now without autocount.sync.run (backend split, S2 review SHOULD-FIX 7)', () => {
    canMock.mockImplementation((key: string) => key !== 'autocount.sync.run');
    const { rerender } = render(
      <ActivateTab
        company={company()}
        task={task({ lastPreviewAt: '2026-08-30T06:21:00Z' })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    // Preview withheld even though every OTHER prerequisite passed.
    expect(screen.getByTestId('etl-run-preview')).toBeDisabled();
    // Activate stays governed by the page's own companies.manage gate - a
    // user who reached this tab already holds it, so it is NOT re-gated here.
    expect(screen.getByTestId('etl-activate')).toBeEnabled();

    rerender(
      <ActivateTab
        company={company()}
        task={task({ etlStatus: 'active', lastPreviewAt: '2026-08-30T06:21:00Z' })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    expect(screen.getByTestId('etl-run-now')).toBeDisabled();
    // Pause is companies.manage, unaffected by the sync.run gate.
    expect(screen.getByTestId('etl-pause')).toBeEnabled();
  });

  // ── plan 22 S4 - product/category/UOM dependency warning (AC-22-23) ───────

  it('warns, but does NOT block, a product task with no active category/UOM task', () => {
    render(
      <ActivateTab
        company={company()}
        task={task({ entityType: 'product', lastPreviewAt: '2026-08-30T06:21:00Z' })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
        entities={[]}
      />,
    );
    expect(screen.getByTestId('activate-dependency-warning')).toHaveTextContent(
      /category and unit of measure/,
    );
    // A warning, never a block - Activate stays governed by its OWN gate.
    expect(screen.getByTestId('etl-activate')).toBeEnabled();
  });

  it('names only the still-missing dependency once one lands', () => {
    render(
      <ActivateTab
        company={company()}
        task={task({ entityType: 'product', lastPreviewAt: '2026-08-30T06:21:00Z' })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
        entities={[entityConfig({ id: 'cat', entityType: 'product_category', etlStatus: 'active' })]}
      />,
    );
    const warning = screen.getByTestId('activate-dependency-warning');
    expect(warning).toHaveTextContent(/unit of measure/);
    expect(warning).not.toHaveTextContent(/category and/);
  });

  it('shows no warning once category and UOM are both active', () => {
    render(
      <ActivateTab
        company={company()}
        task={task({ entityType: 'product', lastPreviewAt: '2026-08-30T06:21:00Z' })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
        entities={[
          entityConfig({ id: 'cat', entityType: 'product_category', etlStatus: 'active' }),
          entityConfig({ id: 'uom', entityType: 'unit_of_measure', etlStatus: 'active' }),
        ]}
      />,
    );
    expect(screen.queryByTestId('activate-dependency-warning')).not.toBeInTheDocument();
  });

  it('shows no dependency warning for a non-product entity', () => {
    render(
      <ActivateTab
        company={company()}
        task={task({ entityType: 'customer', lastPreviewAt: '2026-08-30T06:21:00Z' })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
        entities={[]}
      />,
    );
    expect(screen.queryByTestId('activate-dependency-warning')).not.toBeInTheDocument();
  });
});
