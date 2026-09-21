/**
 * Prod hotfix (2026-09-21) - a PULL-mode product task's Activate button must
 * not be blocked by a consumer-side dry-run failure count; PUSH mode is
 * unchanged (control). Mirrors ``test_autocount_pull_activate_gate.py``'s
 * backend RED tests one for one.
 *
 * RED expectation: 5 and 7 fail today (`previewFailedBlocksActivation`
 * blocks on ANY truthy `lastPreviewFailedCount` regardless of delivery mode,
 * and the tab has no warning-banner testid for the pull case yet); 6 passes
 * unmodified (the EXISTING push-mode gate/banner, proving this file is not
 * vacuously red end to end).
 */
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { UseEtlTaskLifecycleResult, UseEtlTaskPreviewResult } from '@/hooks/use-autocount-etl';
import type { AutocountCompany, AutocountEtlTask } from '@/types/autocount';
import { previewFailedBlocksActivation } from '@/lib/autocount-etl';
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

vi.mock('@/lib/toast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

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
    entityType: 'product',
    etlStatus: 'draft',
    activatedAt: null,
    sourceConfig: {
      connectionId: 'conn-sql-1',
      query: 'SELECT * FROM dbo.Item',
      lineQuery: null,
      keyColumns: ['ItemCode'],
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
    resultColumns: ['ItemCode'],
    lastPreviewAt: '2026-09-21T06:21:00Z',
    lastPreviewFailedCount: 4,
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

describe('previewFailedBlocksActivation delivery-mode awareness (prod hotfix 2026-09-21)', () => {
  it('does NOT block a pull-mode task even with a truthy failed count', () => {
    expect(
      previewFailedBlocksActivation(task({ deliveryMode: 'pull', lastPreviewFailedCount: 4 })),
    ).toBe(false);
  });

  it('still blocks a push-mode task with a truthy failed count (control)', () => {
    expect(
      previewFailedBlocksActivation(task({ deliveryMode: 'push', lastPreviewFailedCount: 4 })),
    ).toBe(true);
  });
});

describe('ActivateTab - pull-mode consumer-side failed rows (prod hotfix 2026-09-21)', () => {
  it('enables Activate and shows a WARNING banner naming the consumer review page for a pull-mode task', () => {
    render(
      <ActivateTab
        company={company()}
        task={task({ deliveryMode: 'pull', lastPreviewFailedCount: 4 })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    expect(screen.getByTestId('etl-activate')).toBeEnabled();
    // Never the destructive per-record gate banner - a pull failure is the
    // CONSUMER's dry run, not one Foundryx itself blocks on.
    expect(screen.queryByTestId('etl-preview-failed')).not.toBeInTheDocument();
    const banner = screen.getByTestId('etl-preview-failed-pull-warning');
    expect(banner).toHaveTextContent(
      "4 rows would fail at the consumer. They are listed on the consumer's review page on every pull; the rest are included in the snapshot.",
    );
  });

  it('singularises the warning banner for exactly 1 failed row', () => {
    render(
      <ActivateTab
        company={company()}
        task={task({ deliveryMode: 'pull', lastPreviewFailedCount: 1 })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    const banner = screen.getByTestId('etl-preview-failed-pull-warning');
    expect(banner).toHaveTextContent(
      "1 row would fail at the consumer. They are listed on the consumer's review page on every pull; the rest are included in the snapshot.",
    );
  });

  it('disables Activate and shows the existing red banner for a push-mode task with the same state (control)', () => {
    render(
      <ActivateTab
        company={company()}
        task={task({ deliveryMode: 'push', lastPreviewFailedCount: 4 })}
        configDirty={false}
        preview={preview()}
        lifecycle={lifecycle()}
        onRan={vi.fn()}
      />,
    );
    expect(screen.getByTestId('etl-activate')).toBeDisabled();
    expect(screen.queryByTestId('etl-preview-failed-pull-warning')).not.toBeInTheDocument();
    const banner = screen.getByTestId('etl-preview-failed');
    expect(banner).toHaveTextContent('The last preview reported 4 failed rows');
    expect(banner).toHaveTextContent('Fix the mapping, then re-run preview before activating.');
  });
});
