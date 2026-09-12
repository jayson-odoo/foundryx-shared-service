import { act, fireEvent, render, screen } from '@testing-library/react';
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

const { toastSuccess, toastError } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));
vi.mock('@/lib/toast', () => ({
  toast: { success: toastSuccess, error: toastError, info: vi.fn(), warning: vi.fn() },
}));

// "Re-push all" rides the CORE deferred-actions engine now (review round,
// D2/D13) - `useDeferredAction` is the real hook; only the service
// underneath it is mocked (the same pattern `resource-form.deferred.
// test.tsx` uses for the shell's own deferred gear actions).
const park = vi.fn();
const cancelPark = vi.fn();
const current = vi.fn();
vi.mock('@/services/pending-actions-service', () => ({
  pendingActionsService: {
    park: (...a: unknown[]) => park(...a),
    cancel: (...a: unknown[]) => cancelPark(...a),
    current: (...a: unknown[]) => current(...a),
  },
}));

beforeEach(() => {
  canMock.mockReset();
  canMock.mockReturnValue(true);
  toastSuccess.mockReset();
  toastError.mockReset();
  park.mockReset();
  cancelPark.mockReset();
  current.mockReset();
  current.mockResolvedValue({ pending: null, lastOutcome: null });
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
    sourceKind: 'api',
    documentPrerequisites: [],
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
      docDateColumn: null,
      filterFormula: null,
      incrementalMinutes: 5,
      reconcileMode: 'dailyAt',
      reconcileHours: null,
      reconcileAt: '02:00',
    },
    resultColumns: ['AccNo'],
    lastPreviewAt: null,
    lastPreviewFailedCount: null,
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

  it('blocks Activate but keeps Run preview enabled when the last preview reported failed rows (S5 review SHOULD-FIX 4b)', () => {
    render(
      <ActivateTab
        company={company()}
        task={task({ lastPreviewAt: '2026-08-30T06:21:00Z', lastPreviewFailedCount: 2 })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    // Fixing this MEANS re-running preview after editing the mapping - that
    // button must never be trapped by the same gate it is the fix for.
    expect(screen.getByTestId('etl-run-preview')).toBeEnabled();
    expect(screen.getByTestId('etl-activate')).toBeDisabled();
    expect(screen.getByTestId('etl-preview-failed')).toHaveTextContent('2 failed row');
  });

  it('re-enables Activate once a re-run preview reports zero failed rows', () => {
    render(
      <ActivateTab
        company={company()}
        task={task({ lastPreviewAt: '2026-08-30T06:21:00Z', lastPreviewFailedCount: 0 })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    expect(screen.getByTestId('etl-activate')).toBeEnabled();
    expect(screen.queryByTestId('etl-preview-failed')).not.toBeInTheDocument();
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
      'No active category or unit-of-measure task yet - products may not sync until one runs.',
    );
    // A warning, never a block - Activate stays governed by its OWN gate.
    expect(screen.getByTestId('etl-activate')).toBeEnabled();
  });

  it('still warns with the same fixed copy once only ONE dependency lands', () => {
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
    expect(warning).toHaveTextContent(
      'No active category or unit-of-measure task yet - products may not sync until one runs.',
    );
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

  // ── logging-sink delivery warning (sprint-5/08 review round 5) ────────────

  it('warns, but does NOT block, a logging-sink company', () => {
    render(
      <ActivateTab
        company={company({ sinkImpl: 'logging', sorentoCompanyCode: null })}
        task={task({ lastPreviewAt: '2026-08-30T06:21:00Z' })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    expect(screen.getByTestId('activate-logging-sink-warning')).toHaveTextContent(
      'Runs on this company are logged only - no records are delivered until a Sorento target is set.',
    );
    // Nit (review round 6) - same escape hatch the companyCode prerequisite
    // gives, so the warning is never a dead end.
    expect(screen.getByTestId('activate-logging-sink-warning')).toHaveTextContent(/Open company/);
    expect(
      screen.getByRole('link', { name: 'Open company' }),
    ).toHaveAttribute('href', '/autocount/companies/c1');
    expect(screen.getByTestId('etl-activate')).toBeEnabled();
  });

  it('shows no logging-sink warning for a company pointed at Sorento', () => {
    render(
      <ActivateTab
        company={company({ sinkImpl: 'sorento' })}
        task={task({ lastPreviewAt: '2026-08-30T06:21:00Z' })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('activate-logging-sink-warning')).not.toBeInTheDocument();
  });

  // ── brand consumer-contract gate (sprint-5/08, AC-08-33/AC-08-20 S5) ──────

  it('shows the contract-gate banner for a brand task on a 2.2 consumer, naming the real advertised version', () => {
    render(
      <ActivateTab
        company={company()}
        task={task({
          entityType: 'brand',
          lastPreviewAt: '2026-08-30T06:21:00Z',
          brandContractGate: { version: 2.2, requiredVersion: 2.3 },
        })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    expect(screen.getByTestId('activate-brand-contract-gate')).toHaveTextContent(
      'Consumer contract 2.2 - brands land when 2.3 is deployed',
    );
    // A warning, never a block - the task still activates (falls back to
    // logging for brand until the consumer deploys the entity).
    expect(screen.getByTestId('etl-activate')).toBeEnabled();
  });

  it('hides the banner for a brand task once the consumer contract accepts brands (2.3, gate cleared server-side)', () => {
    render(
      <ActivateTab
        company={company()}
        task={task({
          entityType: 'brand',
          lastPreviewAt: '2026-08-30T06:21:00Z',
          brandContractGate: null,
        })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('activate-brand-contract-gate')).not.toBeInTheDocument();
  });

  it('hides the banner entirely for a non-brand entity', () => {
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
    expect(screen.queryByTestId('activate-brand-contract-gate')).not.toBeInTheDocument();
  });

  // ── "Re-push all" (plan sprint-5/07, AC-07-20..24) ─────────────────────────

  describe('Re-push all', () => {
    const dbEntity = () => entityConfig({ id: 'so', entityType: 'sales_order', sourceImpl: 'sql_db' });

    it('renders for an active database task when the caller can manage companies', () => {
      render(
        <ActivateTab
          company={company()}
          task={task({ entityType: 'sales_order', etlStatus: 'active', lastPreviewAt: '2026-08-30T06:21:00Z' })}
          configDirty={false}
          preview={preview()}
          lifecycle={lifecycle()}
          onRan={vi.fn()}
          entities={[dbEntity()]}
        />,
      );
      expect(screen.getByTestId('etl-repush-all')).toBeInTheDocument();
    });

    it('renders for a paused database task when the caller can manage companies', () => {
      render(
        <ActivateTab
          company={company()}
          task={task({ entityType: 'sales_order', etlStatus: 'paused' })}
          configDirty={false}
          preview={preview()}
          lifecycle={lifecycle()}
          onRan={vi.fn()}
          entities={[dbEntity()]}
        />,
      );
      expect(screen.getByTestId('etl-repush-all')).toBeInTheDocument();
    });

    it('hides for a draft task even when it is a database task and the caller can manage', () => {
      render(
        <ActivateTab
          company={company()}
          task={task({ entityType: 'sales_order', etlStatus: 'draft' })}
          configDirty={false}
          preview={preview()}
          lifecycle={lifecycle()}
          onRan={vi.fn()}
          entities={[dbEntity()]}
        />,
      );
      expect(screen.queryByTestId('etl-repush-all')).not.toBeInTheDocument();
    });

    it('hides for an active task without autocount.companies.manage', () => {
      canMock.mockImplementation((key: string) => key !== 'autocount.companies.manage');
      render(
        <ActivateTab
          company={company()}
          task={task({ entityType: 'sales_order', etlStatus: 'active', lastPreviewAt: '2026-08-30T06:21:00Z' })}
          configDirty={false}
          preview={preview()}
          lifecycle={lifecycle()}
          onRan={vi.fn()}
          entities={[dbEntity()]}
        />,
      );
      expect(screen.queryByTestId('etl-repush-all')).not.toBeInTheDocument();
    });

    it('hides for an active task whose source is the AutoCount API, not a database task', () => {
      render(
        <ActivateTab
          company={company()}
          task={task({ entityType: 'sales_order', etlStatus: 'active', lastPreviewAt: '2026-08-30T06:21:00Z' })}
          configDirty={false}
          preview={preview()}
          lifecycle={lifecycle()}
          onRan={vi.fn()}
          entities={[entityConfig({ id: 'so', entityType: 'sales_order', sourceImpl: 'autocount_read' })]}
        />,
      );
      expect(screen.queryByTestId('etl-repush-all')).not.toBeInTheDocument();
    });

    it('clicking the trigger parks the deferred action with the right key/entity - no dialog', async () => {
      park.mockResolvedValue({
        id: 'pa1', commitAt: new Date(Date.now() + 10_000).toISOString(), windowSeconds: 10,
      });
      render(
        <ActivateTab
          company={company()}
          task={task({ entityType: 'sales_order', etlStatus: 'active' })}
          configDirty={false}
          preview={preview()}
          lifecycle={lifecycle()}
          onRan={vi.fn()}
          entities={[dbEntity()]}
        />,
      );
      expect(screen.queryByTestId('deferred-countdown')).not.toBeInTheDocument();
      await act(async () => {
        fireEvent.click(screen.getByTestId('etl-repush-all'));
      });

      expect(park).toHaveBeenCalledWith('autocount_etl_task.repush', 'autocount_etl_task', 'so', undefined);
      // The countdown REPLACES the trigger button in place - no dialog opened.
      await vi.waitFor(() => expect(screen.getByTestId('deferred-countdown')).toBeInTheDocument());
      expect(screen.queryByTestId('etl-repush-all')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    });

    it('renders the countdown from the parked state (commitAt/windowSeconds)', async () => {
      park.mockResolvedValue({
        id: 'pa1', commitAt: new Date(Date.now() + 7_000).toISOString(), windowSeconds: 7,
      });
      render(
        <ActivateTab
          company={company()}
          task={task({ entityType: 'sales_order', etlStatus: 'active' })}
          configDirty={false}
          preview={preview()}
          lifecycle={lifecycle()}
          onRan={vi.fn()}
          entities={[dbEntity()]}
        />,
      );
      await act(async () => {
        fireEvent.click(screen.getByTestId('etl-repush-all'));
      });
      await vi.waitFor(() => expect(screen.getByRole('timer')).toHaveTextContent('Re-pushing all in 7s'));
    });

    it('Cancel calls cancel() and never toasts - no reload, trigger comes back', async () => {
      park.mockResolvedValue({
        id: 'pa1', commitAt: new Date(Date.now() + 10_000).toISOString(), windowSeconds: 10,
      });
      cancelPark.mockResolvedValue({ id: 'pa1', status: 'cancelled' });
      const onRan = vi.fn();
      const reloadTask = vi.fn();
      render(
        <ActivateTab
          company={company()}
          task={task({ entityType: 'sales_order', etlStatus: 'active' })}
          configDirty={false}
          preview={preview()}
          lifecycle={lifecycle()}
          onRan={onRan}
          entities={[dbEntity()]}
          reloadTask={reloadTask}
        />,
      );
      await act(async () => {
        fireEvent.click(screen.getByTestId('etl-repush-all'));
      });
      await vi.waitFor(() => expect(screen.getByTestId('deferred-countdown')).toBeInTheDocument());

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
      });
      expect(cancelPark).toHaveBeenCalledWith('pa1');
      await vi.waitFor(() => expect(screen.getByTestId('etl-repush-all')).toBeInTheDocument());
      expect(screen.queryByTestId('deferred-countdown')).not.toBeInTheDocument();
      expect(toastSuccess).not.toHaveBeenCalled();
      expect(toastError).not.toHaveBeenCalled();
      expect(onRan).not.toHaveBeenCalled();
      expect(reloadTask).not.toHaveBeenCalled();
    });

    it('onCommitted toasts success (active variant), reloads the Runs tab and the task', async () => {
      vi.useFakeTimers();
      try {
        park.mockResolvedValue({
          id: 'pa1', commitAt: new Date(Date.now() + 10_000).toISOString(), windowSeconds: 10,
        });
        current.mockResolvedValue({
          pending: null,
          lastOutcome: { id: 'pa1', actionKey: 'autocount_etl_task.repush', status: 'committed', errorText: null, endedAt: new Date().toISOString() },
        });
        const onRan = vi.fn();
        const reloadTask = vi.fn();
        render(
          <ActivateTab
            company={company()}
            task={task({ entityType: 'sales_order', etlStatus: 'active' })}
            configDirty={false}
            preview={preview()}
            lifecycle={lifecycle()}
            onRan={onRan}
            entities={[dbEntity()]}
            reloadTask={reloadTask}
          />,
        );
        fireEvent.click(screen.getByTestId('etl-repush-all'));
        await act(async () => {
          await vi.advanceTimersByTimeAsync(11_000);
        });

        expect(toastSuccess).toHaveBeenCalledTimes(1);
        expect(toastSuccess.mock.calls[0][0]).toContain('next scheduler tick');
        expect(onRan).toHaveBeenCalledTimes(1);
        expect(reloadTask).toHaveBeenCalledTimes(1);
        expect(screen.getByTestId('etl-repush-all')).toBeInTheDocument();
      } finally {
        vi.useRealTimers();
      }
    });

    it('a paused task\'s onCommitted toast says nothing moves until resumed, not "next scheduler tick"', async () => {
      vi.useFakeTimers();
      try {
        park.mockResolvedValue({
          id: 'pa1', commitAt: new Date(Date.now() + 10_000).toISOString(), windowSeconds: 10,
        });
        current.mockResolvedValue({
          pending: null,
          lastOutcome: { id: 'pa1', actionKey: 'autocount_etl_task.repush', status: 'committed', errorText: null, endedAt: new Date().toISOString() },
        });
        render(
          <ActivateTab
            company={company()}
            task={task({ entityType: 'sales_order', etlStatus: 'paused' })}
            configDirty={false}
            preview={preview()}
            lifecycle={lifecycle()}
            onRan={vi.fn()}
            entities={[dbEntity()]}
          />,
        );
        fireEvent.click(screen.getByTestId('etl-repush-all'));
        await act(async () => {
          await vi.advanceTimersByTimeAsync(11_000);
        });
        expect(toastSuccess.mock.calls[0][0]).toContain('Nothing moves until the task is resumed.');
      } finally {
        vi.useRealTimers();
      }
    });

    it('onFailed (e.g. a run was in flight at commit time) toasts the error with a link to the Runs tab', async () => {
      vi.useFakeTimers();
      try {
        park.mockResolvedValue({
          id: 'pa1', commitAt: new Date(Date.now() + 10_000).toISOString(), windowSeconds: 10,
        });
        current.mockResolvedValue({
          pending: null,
          lastOutcome: {
            id: 'pa1', actionKey: 'autocount_etl_task.repush', status: 'failed',
            errorText: 'A run for this task is still going. Wait for it to finish.',
            endedAt: new Date().toISOString(),
          },
        });
        const onRan = vi.fn();
        const reloadTask = vi.fn();
        render(
          <ActivateTab
            company={company()}
            task={task({ companyId: 'c1', entityType: 'sales_order', etlStatus: 'active' })}
            configDirty={false}
            preview={preview()}
            lifecycle={lifecycle()}
            onRan={onRan}
            entities={[dbEntity()]}
            reloadTask={reloadTask}
          />,
        );
        fireEvent.click(screen.getByTestId('etl-repush-all'));
        await act(async () => {
          await vi.advanceTimersByTimeAsync(11_000);
        });

        expect(toastError).toHaveBeenCalledTimes(1);
        expect(toastError.mock.calls[0][0]).toBe('A run for this task is still going. Wait for it to finish.');
        // A link to the Runs tab rides `options.action` (the same shape
        // `lib/toast`'s `error()` passes through to sonner).
        expect(toastError.mock.calls[0][1]?.action).toBeTruthy();
        expect(toastError.mock.calls[0][1]?.action?.props?.children).toBe('View run');
        expect(toastSuccess).not.toHaveBeenCalled();
        // A failed commit never reloads - nothing actually changed server-side.
        expect(onRan).not.toHaveBeenCalled();
        expect(reloadTask).not.toHaveBeenCalled();
      } finally {
        vi.useRealTimers();
      }
    });

    it('disables the trigger while a lifecycle action is busy', () => {
      render(
        <ActivateTab
          company={company()}
          task={task({ entityType: 'sales_order', etlStatus: 'active' })}
          configDirty={false}
          preview={preview()}
          lifecycle={lifecycle({ busy: 'activate' })}
          onRan={vi.fn()}
          entities={[dbEntity()]}
        />,
      );
      expect(screen.getByTestId('etl-repush-all')).toBeDisabled();
    });

    it('a cancel that loses the race to the commit toasts onCancelFailed (review round - resource-form.tsx parity)', async () => {
      park.mockResolvedValue({
        id: 'pa1', commitAt: new Date(Date.now() + 10_000).toISOString(), windowSeconds: 10,
      });
      // The cancel request itself fails (arrived at/after the window closed) -
      // `useDeferredAction.cancel()` reconciles by re-reading `current`.
      cancelPark.mockRejectedValue(new Error('too late'));
      current.mockResolvedValue({
        pending: null,
        lastOutcome: {
          id: 'pa1', actionKey: 'autocount_etl_task.repush', status: 'committed',
          errorText: null, endedAt: new Date().toISOString(),
        },
      });
      render(
        <ActivateTab
          company={company()}
          task={task({ entityType: 'sales_order', etlStatus: 'active' })}
          configDirty={false}
          preview={preview()}
          lifecycle={lifecycle()}
          onRan={vi.fn()}
          entities={[dbEntity()]}
        />,
      );
      await act(async () => {
        fireEvent.click(screen.getByTestId('etl-repush-all'));
      });
      await vi.waitFor(() => expect(screen.getByTestId('deferred-countdown')).toBeInTheDocument());

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
      });
      await vi.waitFor(() =>
        expect(toastError).toHaveBeenCalledWith('Could not cancel - the action already ran.'),
      );
    });

    it('disables the trigger while committing (a second park can succeed server-side mid-window)', async () => {
      vi.useFakeTimers();
      try {
        park.mockResolvedValue({
          id: 'pa1', commitAt: new Date(Date.now() + 1_000).toISOString(), windowSeconds: 1,
        });
        current.mockResolvedValue({
          pending: {
            id: 'pa1', actionKey: 'autocount_etl_task.repush', entityType: 'autocount_etl_task',
            entityId: 'so', commitAt: new Date(Date.now() + 1_000).toISOString(), windowSeconds: 1,
            requestedById: null, requestedByName: null, status: 'committing',
          },
          lastOutcome: null,
        });
        render(
          <ActivateTab
            company={company()}
            task={task({ entityType: 'sales_order', etlStatus: 'active' })}
            configDirty={false}
            preview={preview()}
            lifecycle={lifecycle()}
            onRan={vi.fn()}
            entities={[dbEntity()]}
          />,
        );
        await act(async () => {
          fireEvent.click(screen.getByTestId('etl-repush-all'));
        });
        // Past the (1s) window - the poll discovers the row already CLAIMED
        // (another park/commit reached it first), not yet settled.
        await act(async () => {
          await vi.advanceTimersByTimeAsync(2_000);
        });

        expect(screen.queryByTestId('deferred-countdown')).not.toBeInTheDocument();
        expect(screen.getByTestId('etl-repush-all')).toBeDisabled();
      } finally {
        vi.useRealTimers();
      }
    });
  });
});
